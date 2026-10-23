"""Twenty CRM (https://twenty.com), through its REST API."""
import json
import os
import re
import threading
import uuid

import requests

from ...config import saved_env
from .base import CrmAdapter, CrmError

DEFAULT_BASE_URL = "https://crm.tunisolutions.com"
TIMEOUT = 15
LEADS_PAGE = 200  # the most Twenty's REST API returns at once
DEFAULT_STAGES = [("NEW", "New"), ("TO_CALL", "To Call"), ("ATTEMPTED", "Attempted"), ("IN_TALK", "In Talk"),
                  ("WAITING_REPLY", "Waiting Reply"), ("ACCEPTED", "Accepted"), ("ACCOUNT_MADE", "Account Made"),
                  ("INSTALLING", "Installing"), ("ACTIVE", "Active"), ("REJECTED", "Rejected")]


_local = threading.local()


def _http() -> requests.Session:
    """This thread's HTTP session: it keeps the connection to the CRM open between requests, which saves a TLS
    handshake (up to a second) on each one. One per thread, as a Session isn't meant to be shared between them."""
    if getattr(_local, "session", None) is None:
        _local.session = requests.Session()
    return _local.session


def _setting(key: str, default: str = "") -> str:
    """The value as saved in .env right now (so Settings edits apply without a restart), else the environment."""
    return (saved_env().get(key) or os.environ.get(key) or default).strip()


def _full_name(name: dict | None) -> str:
    return " ".join(p for p in ((name or {}).get("firstName"), (name or {}).get("lastName")) if p).strip()


def _blocknote(markdown: str) -> str:
    """Twenty stores rich text as BlockNote JSON: one paragraph per line, "**x**" kept as bold."""
    blocks = []
    for line in markdown.splitlines():
        content = []
        for i, part in enumerate(re.split(r"\*\*", line)):
            if part:
                content.append({"type": "text", "text": part, "styles": {"bold": True} if i % 2 else {}})
        blocks.append({"id": str(uuid.uuid4()), "type": "paragraph", "content": content, "children": [],
                       "props": {"textColor": "default", "backgroundColor": "default", "textAlignment": "left"}})
    return json.dumps(blocks, ensure_ascii=False)


def _note_text(body: dict | None) -> str:
    body = body or {}
    if body.get("markdown"):
        return body["markdown"].strip()
    try:
        blocks = json.loads(body.get("blocknote") or "[]")
    except ValueError:
        return ""
    lines = ["".join(c.get("text", "") for c in b.get("content") or [] if isinstance(c, dict)) for b in blocks]
    return "\n".join(lines).strip()


def _phones(number: str) -> dict:
    """A phone number the way the CRM keeps them: Tunisian ones as 8 digits with +216, others as typed."""
    cleaned = re.sub(r"[^\d+]", "", number)
    if re.fullmatch(r"(\+216|00216|216)?\d{8}", cleaned):
        return {"primaryPhoneNumber": cleaned[-8:], "primaryPhoneCountryCode": "TN", "primaryPhoneCallingCode": "+216",
                "additionalPhones": []}
    return {"primaryPhoneNumber": cleaned, "additionalPhones": []}


class TwentyCrm(CrmAdapter):
    name = "twenty"
    label = "Twenty"
    setting_keys = ("CRM_BASE_URL", "CRM_API_KEY", "CRM_VERIFY_SSL")
    secret_keys = ("CRM_API_KEY",)
    lead_stage = "NEW"
    attempted_stage = "ATTEMPTED"

    # --- HTTP ----------------------------------------------------------------------------------

    def _config(self) -> tuple[str, str, bool]:
        base = _setting("CRM_BASE_URL", DEFAULT_BASE_URL).rstrip("/")
        verify = _setting("CRM_VERIFY_SSL", "true").lower() in ("1", "true", "yes", "on")
        return base, _setting("CRM_API_KEY"), verify

    def is_configured(self) -> bool:
        return bool(self._config()[1])

    def not_configured_message(self) -> str:
        return "add CRM_API_KEY in Settings"

    def _get_json(self, path: str, params: dict) -> dict:
        base, key, verify = self._config()
        try:
            res = _http().get(f"{base}/rest/{path}", params=params, headers={"Authorization": f"Bearer {key}"},
                               timeout=TIMEOUT, verify=verify)
        except requests.RequestException as exc:
            raise CrmError(f"Couldn't reach the CRM at {base}: {exc.__class__.__name__}") from exc
        if res.status_code in (401, 403):
            raise CrmError("The CRM rejected the API key. Check CRM_API_KEY in Settings.")
        if not res.ok:
            raise CrmError(f"The CRM answered {res.status_code} for {path}.")
        return res.json()

    def _get_page(self, path: str, params: dict) -> tuple[list[dict], dict]:
        """One page of records, and Twenty's pageInfo (hasNextPage, endCursor) to fetch the next one."""
        body = self._get_json(path, params)
        return (body.get("data") or {}).get(path) or [], body.get("pageInfo") or {}

    def _get(self, path: str, params: dict) -> list[dict]:
        return self._get_page(path, params)[0]

    def _send(self, method: str, path: str, body: dict) -> dict:
        """Create or update a record; returns it."""
        base, key, verify = self._config()
        try:
            res = _http().request(method, f"{base}/rest/{path}", json=body, timeout=TIMEOUT, verify=verify,
                                   headers={"Authorization": f"Bearer {key}"})
        except requests.RequestException as exc:
            raise CrmError(f"Couldn't reach the CRM at {base}: {exc.__class__.__name__}") from exc
        if res.status_code in (401, 403):
            raise CrmError("The CRM refused the change. Check that CRM_API_KEY may edit records.")
        if not res.ok:
            detail = ""
            try:
                detail = (res.json().get("messages") or [res.json().get("message") or ""])[0]
            except ValueError:
                pass
            raise CrmError(f"The CRM answered {res.status_code} for {path}{f': {detail}' if detail else ''}.")
        data = res.json().get("data") or {}
        return next(iter(data.values()), {}) if isinstance(data, dict) else {}

    # --- Twenty records -> the app's shapes ----------------------------------------------------

    def _person(self, rec: dict, opportunities: list[dict]) -> dict:
        phones = rec.get("phones") or {}
        numbers = [f"{phones.get('primaryPhoneCallingCode') or ''} {phones.get('primaryPhoneNumber') or ''}".strip()]
        numbers += [f"{p.get('callingCode') or ''} {p.get('number') or ''}".strip()
                    for p in phones.get("additionalPhones") or []]
        company = rec.get("company") or {}
        return {
            "id": rec["id"],
            "name": _full_name(rec.get("name")) or "Unnamed contact",
            "email": (rec.get("emails") or {}).get("primaryEmail") or None,
            "phones": [n for n in numbers if n],
            "job_title": rec.get("jobTitle") or None,
            "city": rec.get("city") or None,
            "company": company.get("name") or None,
            "created_at": rec.get("createdAt"),
            "last_contact_at": rec.get("lastContactAt"),
            "url": f"{self._config()[0]}/object/person/{rec['id']}",
            "opportunities": opportunities,
        }

    def _opportunity(self, rec: dict) -> dict:
        amount = rec.get("amount") or {}
        micros = amount.get("amountMicros")
        owner = rec.get("owner") or {}
        return {
            "id": rec["id"],
            "name": rec.get("name") or "Untitled opportunity",
            "stage": rec.get("stage"),
            "amount": micros / 1_000_000 if micros else None,
            "currency": amount.get("currencyCode"),
            "close_date": rec.get("closeDate"),
            "company": (rec.get("company") or {}).get("name") or None,
            "owner": _full_name(owner.get("name")) or None,
            "created_at": rec.get("createdAt"),
            "updated_at": rec.get("updatedAt"),
            "url": f"{self._config()[0]}/object/opportunity/{rec['id']}",
        }

    def _lead(self, rec: dict) -> dict:
        contact = rec.get("pointOfContact")
        if contact:
            contact = self._person(contact, [])
            contact.pop("opportunities")
        return {**self._opportunity(rec), "contact": contact}

    # --- Reading -------------------------------------------------------------------------------

    def find_people(self, key: str) -> list[dict]:
        people = self._get("people", {"filter": f'phones.primaryPhoneNumber[ilike]:"%{key}"', "depth": 1,
                                      "limit": 20, "order_by": "createdAt[DescNullsLast]"})
        by_person: dict[str, list[dict]] = {p["id"]: [] for p in people}
        if by_person:
            ids = ",".join(f'"{i}"' for i in by_person)
            for rec in self._get("opportunities", {"filter": f"pointOfContactId[in]:[{ids}]", "depth": 1,
                                                   "limit": 200, "order_by": "createdAt[DescNullsLast]"}):
                by_person.get(rec.get("pointOfContactId"), []).append(self._opportunity(rec))
        return [self._person(p, by_person[p["id"]]) for p in people]

    def list_opportunities(self, stage: str, oldest_first: bool, limit: int | None,
                           after: str | None = None) -> tuple[list[dict], str | None]:
        records, cursor = [], after
        while limit is None or len(records) < limit:
            size = LEADS_PAGE if limit is None else min(LEADS_PAGE, limit - len(records))
            params = {"filter": f"stage[eq]:{stage}", "depth": 1, "limit": size,
                      "order_by": f"createdAt[{'AscNullsLast' if oldest_first else 'DescNullsLast'}]"}
            if cursor:
                params["starting_after"] = cursor
            page, info = self._get_page("opportunities", params)
            records += page
            cursor = info.get("endCursor") if info.get("hasNextPage") and page else None
            if not cursor:
                break
        return [self._lead(rec) for rec in records], cursor

    def get_opportunity(self, opportunity_id: str) -> dict:
        body = self._get_json(f"opportunities/{opportunity_id}", {"depth": 1})
        rec = next(iter((body.get("data") or {}).values()), None)
        if not rec:
            raise CrmError("That opportunity isn't in the CRM anymore.")
        return self._lead(rec)

    def stages(self) -> list[dict]:
        """The stage field's options as set up in the CRM; the usual ones if its metadata can't be read."""
        stages = [{"value": v, "label": label} for v, label in DEFAULT_STAGES]
        if not self.is_configured():
            return stages
        base, key, verify = self._config()
        try:
            res = _http().get(f"{base}/rest/metadata/objects", params={"limit": 200}, timeout=TIMEOUT,
                               headers={"Authorization": f"Bearer {key}"}, verify=verify)
            objects = res.json().get("data") or [] if res.ok else []
            opportunity = next((o for o in objects if o.get("nameSingular") == "opportunity"), {})
            field = next((f for f in opportunity.get("fields") or [] if f.get("name") == "stage"), {})
            options = sorted(field.get("options") or [], key=lambda o: o.get("position") or 0)
            if options:
                stages = [{"value": o["value"], "label": o.get("label") or o["value"]} for o in options]
        except (requests.RequestException, ValueError, KeyError):
            pass
        return stages

    def notes(self, opportunity_id: str | None, person_id: str | None, limit: int) -> list[dict]:
        targets = [f"{field}[eq]:{value}" for field, value in
                   (("targetOpportunityId", opportunity_id), ("targetPersonId", person_id)) if value]
        if not targets:
            return []
        filt = targets[0] if len(targets) == 1 else f"or({','.join(targets)})"
        seen, found = set(), []
        for t in self._get("noteTargets", {"filter": filt, "depth": 1, "limit": 60,
                                           "order_by": "createdAt[DescNullsLast]"}):
            note = t.get("note") or {}
            if not note.get("id") or note["id"] in seen or note.get("deletedAt"):
                continue
            seen.add(note["id"])
            text = _note_text(note.get("bodyV2"))
            if text or note.get("title"):
                found.append({"id": note["id"], "title": note.get("title") or "", "text": text,
                              "created_at": note.get("createdAt"),
                              "author": (note.get("createdBy") or {}).get("name")})
        found.sort(key=lambda n: n["created_at"] or "", reverse=True)
        return found[:limit]

    def members(self) -> list[dict]:
        members = [{"id": m["id"], "name": _full_name(m.get("name")) or m.get("userEmail") or m["id"],
                    "email": m.get("userEmail") or None}
                   for m in self._get("workspaceMembers", {"limit": 200})]
        members.sort(key=lambda m: m["name"].lower())
        return members

    # --- Writing -------------------------------------------------------------------------------

    def update_opportunity(self, opportunity_id: str, fields: dict) -> None:
        self._send("PATCH", f"opportunities/{opportunity_id}", fields)

    def update_person(self, person_id: str, fields: dict) -> None:
        self._send("PATCH", f"people/{person_id}", fields)

    def add_note(self, title: str, markdown: str, opportunity_id: str | None, person_id: str | None) -> str:
        note = self._send("POST", "notes", {"title": title,
                                            "bodyV2": {"markdown": markdown, "blocknote": _blocknote(markdown)}})
        for field, target in (("targetOpportunityId", opportunity_id), ("targetPersonId", person_id)):
            if target:
                self._send("POST", "noteTargets", {"noteId": note["id"], field: target})
        return note["id"]

    def create_person(self, name: str, phone: str, city: str, email: str) -> dict:
        """The full name goes in firstName, like the CRM's other sources."""
        body = {"name": {"firstName": name, "lastName": ""}, "phones": _phones(phone)}
        if city:
            body["city"] = city
        if email:
            body["emails"] = {"primaryEmail": email, "additionalEmails": []}
        return self._send("POST", "people", body)

    def create_opportunity(self, name: str, person_id: str, stage: str, owner_id: str | None) -> dict:
        body = {"name": name, "stage": stage, "pointOfContactId": person_id}
        if owner_id:
            body["ownerId"] = owner_id
        return self._send("POST", "opportunities", body)
