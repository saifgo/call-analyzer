"""Look up a call's customer in a Twenty CRM (https://twenty.com) by phone number, via its REST API."""
import json
import os
import re
import threading
import time
import uuid

import requests
from dotenv import dotenv_values

from .config import ENV_PATH

DEFAULT_BASE_URL = "https://crm.tunisolutions.com"
CACHE_SECONDS = 60
TIMEOUT = 15
# Tunisian numbers are 8 digits once the +216 / 00216 prefix is dropped. Calls and the CRM write them both
# ways, so numbers are compared on their last 8 digits.
MATCH_DIGITS = 8

_cache: dict[str, tuple[float, dict]] = {}
_cache_lock = threading.Lock()


class CrmError(Exception):
    """The CRM couldn't be queried; the message is meant to be shown to the user."""


def _setting(key: str, default: str = "") -> str:
    """The value as saved in .env right now (so Settings edits apply without a restart), else the environment."""
    return (dotenv_values(ENV_PATH).get(key) or os.environ.get(key) or default).strip()


def _config() -> tuple[str, str, bool]:
    base = _setting("CRM_BASE_URL", DEFAULT_BASE_URL).rstrip("/")
    verify = _setting("CRM_VERIFY_SSL", "true").lower() in ("1", "true", "yes", "on")
    return base, _setting("CRM_API_KEY"), verify


def is_configured() -> bool:
    return bool(_config()[1])


def match_key(number: str) -> str | None:
    """The part of a phone number to search the CRM for, or None for extensions and other short numbers."""
    digits = re.sub(r"\D", "", number or "")
    return digits[-MATCH_DIGITS:] if len(digits) >= MATCH_DIGITS else None


def _get(path: str, params: dict) -> list[dict]:
    return _get_page(path, params)[0]


def _get_page(path: str, params: dict) -> tuple[list[dict], dict]:
    """One page of records, and Twenty's pageInfo (hasNextPage, endCursor) to fetch the next one."""
    body = _get_json(path, params)
    return (body.get("data") or {}).get(path) or [], body.get("pageInfo") or {}


def _get_json(path: str, params: dict) -> dict:
    base, key, verify = _config()
    try:
        res = requests.get(f"{base}/rest/{path}", params=params, headers={"Authorization": f"Bearer {key}"},
                           timeout=TIMEOUT, verify=verify)
    except requests.RequestException as exc:
        raise CrmError(f"Couldn't reach the CRM at {base}: {exc.__class__.__name__}") from exc
    if res.status_code in (401, 403):
        raise CrmError("The CRM rejected the API key. Check CRM_API_KEY in Settings.")
    if not res.ok:
        raise CrmError(f"The CRM answered {res.status_code} for {path}.")
    return res.json()


def _full_name(name: dict | None) -> str:
    return " ".join(p for p in ((name or {}).get("firstName"), (name or {}).get("lastName")) if p).strip()


def _person(rec: dict, opportunities: list[dict], base: str) -> dict:
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
        "url": f"{base}/object/person/{rec['id']}",
        "opportunities": opportunities,
    }


def _opportunity(rec: dict, base: str) -> dict:
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
        "url": f"{base}/object/opportunity/{rec['id']}",
    }


def lookup(number: str) -> dict:
    """Contacts in the CRM whose phone number matches `number`, each with their opportunities.

    Returns {"configured": bool, "number": str, "searched": bool, "people": [...]}; `searched` is False when
    the number is too short to match (an internal extension). Raises CrmError when the CRM can't be queried.
    """
    result = {"configured": is_configured(), "number": number, "searched": False, "people": []}
    key = match_key(number)
    if not result["configured"] or not key:
        return result
    result["searched"] = True

    with _cache_lock:
        cached = _cache.get(key)
    if cached and time.time() - cached[0] < CACHE_SECONDS:
        return {**result, "people": cached[1]["people"]}

    base = _config()[0]
    people = _get("people", {"filter": f'phones.primaryPhoneNumber[ilike]:"%{key}"', "depth": 1, "limit": 20,
                             "order_by": "createdAt[DescNullsLast]"})
    by_person: dict[str, list[dict]] = {p["id"]: [] for p in people}
    if by_person:
        ids = ",".join(f'"{i}"' for i in by_person)
        for rec in _get("opportunities", {"filter": f"pointOfContactId[in]:[{ids}]", "depth": 1, "limit": 200,
                                          "order_by": "createdAt[DescNullsLast]"}):
            by_person.get(rec.get("pointOfContactId"), []).append(_opportunity(rec, base))
    result["people"] = [_person(p, by_person[p["id"]], base) for p in people]

    with _cache_lock:
        _cache[key] = (time.time(), result)
    return result


# --- Leads to call --------------------------------------------------------------------------------

LEAD_STAGE = "NEW"  # opportunities nobody has worked on yet
LEADS_PAGE = 200  # the most Twenty's REST API returns at once
MAX_LEADS = 2000

_leads_cache: dict[str, tuple[float, list[dict], bool]] = {}  # stage -> (when, records, more in the CRM)


def _lead(rec: dict, base: str) -> dict:
    contact = rec.get("pointOfContact")
    if contact:
        contact = _person(contact, [], base)
        contact.pop("opportunities")
    return {**_opportunity(rec, base), "contact": contact}


def leads(stage: str = LEAD_STAGE, refresh: bool = False, oldest_first: bool = False) -> dict:
    """Opportunities at `stage` (newest first, or oldest first for the call queue), each with its point of contact
    and their phone numbers.

    Returns {"configured": bool, "stage": str, "leads": [...], "truncated": bool}. Cached for CACHE_SECONDS unless
    `refresh`. Raises CrmError when the CRM can't be queried."""
    result = {"configured": is_configured(), "stage": stage, "leads": [], "truncated": False}
    if not result["configured"]:
        return result
    cache_key = f"{stage}:{'asc' if oldest_first else 'desc'}"
    with _cache_lock:
        cached = _leads_cache.get(cache_key)
    if cached and not refresh and time.time() - cached[0] < CACHE_SECONDS:
        records, more = cached[1], cached[2]
    else:
        records, cursor, more = [], None, False
        while len(records) < MAX_LEADS:
            params = {"filter": f"stage[eq]:{stage}", "depth": 1, "limit": LEADS_PAGE,
                      "order_by": f"createdAt[{'AscNullsLast' if oldest_first else 'DescNullsLast'}]"}
            if cursor:
                params["starting_after"] = cursor
            page, info = _get_page("opportunities", params)
            records += page
            more = bool(info.get("hasNextPage") and info.get("endCursor"))
            if not more:
                break
            cursor = info["endCursor"]
        with _cache_lock:
            _leads_cache[cache_key] = (time.time(), records, more)
    base = _config()[0]
    result["leads"] = [_lead(rec, base) for rec in records]
    result["truncated"] = more
    return result


def forget_leads():
    """Drop the cached lead lists, e.g. after moving an opportunity to another stage."""
    with _cache_lock:
        _leads_cache.clear()


# --- Operations: what the call desk reads and writes back -----------------------------------------

DEFAULT_STAGES = [("NEW", "New"), ("TO_CALL", "To Call"), ("ATTEMPTED", "Attempted"), ("IN_TALK", "In Talk"),
                  ("WAITING_REPLY", "Waiting Reply"), ("ACCEPTED", "Accepted"), ("ACCOUNT_MADE", "Account Made"),
                  ("INSTALLING", "Installing"), ("ACTIVE", "Active"), ("REJECTED", "Rejected")]
STAGES_CACHE_SECONDS = 600
_stages_cache: tuple[float, list[dict]] | None = None


def opportunity_stages() -> list[dict]:
    """The opportunity stages as set up in the CRM ([{value, label}], in pipeline order); the usual ones if the
    CRM's metadata can't be read."""
    global _stages_cache
    if _stages_cache and time.time() - _stages_cache[0] < STAGES_CACHE_SECONDS:
        return _stages_cache[1]
    stages = [{"value": v, "label": label} for v, label in DEFAULT_STAGES]
    if is_configured():
        base, key, verify = _config()
        try:
            res = requests.get(f"{base}/rest/metadata/objects", params={"limit": 200}, timeout=TIMEOUT,
                               headers={"Authorization": f"Bearer {key}"}, verify=verify)
            objects = res.json().get("data") or [] if res.ok else []
            opportunity = next((o for o in objects if o.get("nameSingular") == "opportunity"), {})
            field = next((f for f in opportunity.get("fields") or [] if f.get("name") == "stage"), {})
            options = sorted(field.get("options") or [], key=lambda o: o.get("position") or 0)
            if options:
                stages = [{"value": o["value"], "label": o.get("label") or o["value"]} for o in options]
        except (requests.RequestException, ValueError, KeyError):
            pass
    _stages_cache = (time.time(), stages)
    return stages


def _send(method: str, path: str, body: dict) -> dict:
    """Create or update a record; returns it. Raises CrmError."""
    base, key, verify = _config()
    try:
        res = requests.request(method, f"{base}/rest/{path}", json=body, timeout=TIMEOUT, verify=verify,
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


def update_opportunity(opportunity_id: str, fields: dict) -> None:
    _send("PATCH", f"opportunities/{opportunity_id}", fields)


def update_person(person_id: str, fields: dict) -> None:
    _send("PATCH", f"people/{person_id}", fields)


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


def add_note(title: str, markdown: str, opportunity_id: str | None = None, person_id: str | None = None) -> str:
    """Write a note in the CRM, attached to the opportunity and/or the person. Returns the note's id."""
    note = _send("POST", "notes", {"title": title,
                                   "bodyV2": {"markdown": markdown, "blocknote": _blocknote(markdown)}})
    for field, target in (("targetOpportunityId", opportunity_id), ("targetPersonId", person_id)):
        if target:
            _send("POST", "noteTargets", {"noteId": note["id"], field: target})
    return note["id"]


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


def notes(opportunity_id: str | None, person_id: str | None, limit: int = 20) -> list[dict]:
    """Notes written in the CRM about this opportunity or person, newest first: [{id, title, text, created_at,
    author}]. Raises CrmError."""
    targets = [f"{field}[eq]:{value}" for field, value in
               (("targetOpportunityId", opportunity_id), ("targetPersonId", person_id)) if value]
    if not targets or not is_configured():
        return []
    filt = targets[0] if len(targets) == 1 else f"or({','.join(targets)})"
    seen, found = set(), []
    for t in _get("noteTargets", {"filter": filt, "depth": 1, "limit": 60, "order_by": "createdAt[DescNullsLast]"}):
        note = t.get("note") or {}
        if not note.get("id") or note["id"] in seen or note.get("deletedAt"):
            continue
        seen.add(note["id"])
        text = _note_text(note.get("bodyV2"))
        if text or note.get("title"):
            found.append({"id": note["id"], "title": note.get("title") or "", "text": text,
                          "created_at": note.get("createdAt"), "author": (note.get("createdBy") or {}).get("name")})
    found.sort(key=lambda n: n["created_at"] or "", reverse=True)
    return found[:limit]


def opportunity(opportunity_id: str) -> dict:
    """One opportunity with its point of contact, shaped like a lead (see leads()). Raises CrmError."""
    body = _get_json(f"opportunities/{opportunity_id}", {"depth": 1})
    rec = next(iter((body.get("data") or {}).values()), None)
    if not rec:
        raise CrmError("That opportunity isn't in the CRM anymore.")
    return _lead(rec, _config()[0])


def _phones(number: str) -> dict:
    """A phone number the way the CRM keeps them: Tunisian ones as 8 digits with +216, others as typed."""
    cleaned = re.sub(r"[^\d+]", "", number)
    if re.fullmatch(r"(\+216|00216|216)?\d{8}", cleaned):
        return {"primaryPhoneNumber": cleaned[-8:], "primaryPhoneCountryCode": "TN", "primaryPhoneCallingCode": "+216",
                "additionalPhones": []}
    return {"primaryPhoneNumber": cleaned, "additionalPhones": []}


def create_person(name: str, phone: str, city: str = "", email: str = "") -> dict:
    """Add a contact (the full name in firstName, like the CRM's other sources). Returns the record. Raises CrmError."""
    body = {"name": {"firstName": name, "lastName": ""}, "phones": _phones(phone)}
    if city:
        body["city"] = city
    if email:
        body["emails"] = {"primaryEmail": email, "additionalEmails": []}
    rec = _send("POST", "people", body)
    with _cache_lock:
        _cache.pop(match_key(phone) or "", None)
    return rec


def create_opportunity(name: str, person_id: str, stage: str = LEAD_STAGE, owner_id: str | None = None) -> dict:
    """Add an opportunity for a contact, owned by the workspace member `owner_id`. Returns the record. Raises
    CrmError."""
    body = {"name": name, "stage": stage, "pointOfContactId": person_id}
    if owner_id:
        body["ownerId"] = owner_id
    rec = _send("POST", "opportunities", body)
    with _cache_lock:
        _cache.clear()  # the contact's lookup lists their opportunities
    forget_leads()
    return rec


_members_cache: tuple[float, list[dict]] | None = None


def workspace_members() -> list[dict]:
    """The CRM's users ([{id, name, email}], by name), to link app accounts to. Raises CrmError."""
    global _members_cache
    if _members_cache and time.time() - _members_cache[0] < STAGES_CACHE_SECONDS:
        return _members_cache[1]
    members = [{"id": m["id"], "name": _full_name(m.get("name")) or m.get("userEmail") or m["id"],
                "email": m.get("userEmail") or None}
               for m in _get("workspaceMembers", {"limit": 200})]
    members.sort(key=lambda m: m["name"].lower())
    _members_cache = (time.time(), members)
    return members
