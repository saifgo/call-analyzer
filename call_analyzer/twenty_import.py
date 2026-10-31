"""Bringing Twenty's records into the built-in CRM (CRM setup > Import from Twenty).

Contacts, opportunities and notes keep their Twenty ids, so the desk's calls about them (op_calls) stay linked once
CRM_PROVIDER is switched to internal. It can run while Twenty is still the CRM in use, and again later to catch up: a
contact or opportunity is only overwritten when it changed in Twenty after it was last imported or edited here (its
updated_at), so changes made here since are kept. Missing pipeline stages and the contacts' custom fields come along;
opportunity owners and note authors are the app accounts linked to their Twenty member (users.crm_member_id). Records
deleted in Twenty aren't removed here.
"""
import json
import threading
from datetime import datetime, timezone

from . import crm
from .adapters.crm.base import CrmError
from .adapters.crm.internal import _KEY_RE, BUILTIN_FIELDS, InternalCrm, _coerce, _db, now
from .adapters.crm.twenty import DEFAULT_STAGES, LEADS_PAGE, TwentyCrm, _full_name, _note_text

# Twenty field types -> the built-in CRM's; any other type is kept as text.
FIELD_TYPES = {"TEXT": "text", "NUMBER": "number", "NUMERIC": "number", "BOOLEAN": "boolean", "SELECT": "choice"}

_lock = threading.Lock()
_state: dict = {"running": False, "step": None, "started_at": None, "finished_at": None, "error": None, "counts": {}}


def status() -> dict:
    """The import running or last run since the app started: {running, step (setup | people | opportunities |
    notes), started_at, finished_at, error, counts: {"people_added": n, ...}}."""
    with _lock:
        return {**_state, "counts": dict(_state["counts"])}


def start(twenty: TwentyCrm | None = None, background: bool = True) -> dict:
    """Start an import (in a background thread unless `background` is False). Raises CrmError when Twenty isn't
    connected or an import is already running."""
    twenty = twenty or TwentyCrm()
    if not twenty.is_configured():
        raise CrmError("Twenty isn't connected: fill in CRM_BASE_URL and CRM_API_KEY in Settings first.")
    with _lock:
        if _state["running"]:
            raise CrmError("An import from Twenty is already running.")
        _state.update(running=True, step="setup", started_at=now(), finished_at=None, error=None, counts={})
    if background:
        threading.Thread(target=_run, args=(twenty,), name="twenty-import", daemon=True).start()
    else:
        _run(twenty)
    return status()


def _run(twenty: TwentyCrm) -> None:
    try:
        run(twenty)
    except Exception as exc:
        if not isinstance(exc, CrmError):
            print(f"[crm] importing from Twenty failed: {exc!r}", flush=True)
        _set(error=str(exc) if isinstance(exc, CrmError) else f"The import stopped: {exc.__class__.__name__}: {exc}")
    finally:
        _set(running=False, step=None, finished_at=now())
        crm.forget()


def _set(**changes) -> None:
    with _lock:
        _state.update(changes)


def _add(key: str, n: int = 1) -> None:
    with _lock:
        _state["counts"][key] = _state["counts"].get(key, 0) + n


def run(twenty: TwentyCrm) -> None:
    """The import itself, a page of records per transaction: what was imported before a failure stays."""
    twenty.wait_when_limited = True
    objects = _objects(twenty)
    with _db() as conn:
        owners = {r["crm_member_id"]: r["username"] for r in
                  conn.execute("SELECT username, crm_member_id FROM users WHERE crm_member_id IS NOT NULL")}
        stage_field = next((f for f in _fields_of(objects, "opportunity") if f.get("name") == "stage"), {})
        stages = {r["value"] for r in conn.execute("SELECT value FROM crm_stages")}
        for value, label in _options(stage_field) or DEFAULT_STAGES:
            _ensure_stage(conn, stages, value, label)
        fields = _import_fields(conn, objects)

    _set(step="people")
    for page in _pages(twenty, "people", {"depth": 1}):
        with _db() as conn:
            _import_people(conn, twenty, page, fields)

    _set(step="opportunities")
    with _db() as conn:
        people = {r["id"] for r in conn.execute("SELECT id FROM crm_people")}
    for page in _pages(twenty, "opportunities", {"depth": 0}):
        with _db() as conn:
            _import_opportunities(conn, page, people, stages, owners)

    _set(step="notes")
    with _db() as conn:
        opportunities = {r["id"] for r in conn.execute("SELECT id FROM crm_opportunities")}
    notes: dict[str, dict] = {}  # a note has a target per record it's about, maybe on different pages
    for page in _pages(twenty, "noteTargets", {"depth": 1}):
        for target in page:
            note = target.get("note") or {}
            if not note.get("id") or note.get("deletedAt") or target.get("deletedAt"):
                continue
            about = notes.setdefault(note["id"], {"note": note, "person": None, "opportunity": None})
            if not about["person"] and target.get("targetPersonId") in people:
                about["person"] = target["targetPersonId"]
            if not about["opportunity"] and target.get("targetOpportunityId") in opportunities:
                about["opportunity"] = target["targetOpportunityId"]
    found = list(notes.values())
    for start_at in range(0, len(found), LEADS_PAGE):
        with _db() as conn:
            _import_notes(conn, found[start_at:start_at + LEADS_PAGE], owners)


# --- Reading Twenty ------------------------------------------------------------------------------------------------

def _pages(twenty: TwentyCrm, path: str, params: dict):
    """Every record at `path`, a page at a time."""
    cursor = None
    while True:
        query = {**params, "limit": LEADS_PAGE, **({"starting_after": cursor} if cursor else {})}
        page, info = twenty._get_page(path, query)
        if page:
            yield page
        cursor = info.get("endCursor") if info.get("hasNextPage") and page else None
        if not cursor:
            return


def _objects(twenty: TwentyCrm) -> list[dict]:
    """Twenty's objects and their fields (the stage options, the people's custom fields)."""
    data = twenty._get_json("metadata/objects", {"limit": 200}).get("data") or []
    return (data.get("objects") or []) if isinstance(data, dict) else data


def _fields_of(objects: list[dict], name: str) -> list[dict]:
    found = next((o for o in objects if o.get("nameSingular") == name), {})
    return [f for f in found.get("fields") or [] if f.get("isActive", True)]


def _options(field: dict) -> list[list[str]]:
    """A select field's options as [value, label] pairs, in order."""
    options = sorted(field.get("options") or [], key=lambda o: o.get("position") or 0)
    return [[o["value"], o.get("label") or o["value"]] for o in options if o.get("value")]


def _stamp(value) -> str | None:
    """A Twenty date in the built-in CRM's format (see internal.now), so the two compare as text."""
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return str(value)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _plain(value):
    """A Twenty field value as the built-in CRM keeps it: composite and multi-value ones as text."""
    if isinstance(value, dict):
        value = [v for v in value.values() if isinstance(v, (str, int, float)) and not isinstance(v, bool)]
    if isinstance(value, list):
        return ", ".join(str(v) for v in value if v not in (None, "")) or None
    return value


# --- Writing the built-in CRM --------------------------------------------------------------------------------------

def _existing(conn, table: str, ids: list[str], columns: str) -> dict:
    if not ids:
        return {}
    return {r["id"]: r for r in conn.execute(f"SELECT id, {columns} FROM {table} WHERE id IN "
                                             f"({','.join('?' * len(ids))})", ids)}


def _ensure_stage(conn, stages: set[str], value: str, label: str | None = None) -> None:
    """Add the stage at the end of the pipeline unless it's there."""
    if not value or value in stages:
        return
    position = conn.execute("SELECT COALESCE(MAX(position), -1) + 1 FROM crm_stages").fetchone()[0]
    conn.execute("INSERT INTO crm_stages (value, label, position, locked) VALUES (?, ?, ?, 0)",
                 (value, label or value.replace("_", " ").title(), position))
    stages.add(value)
    _add("stages")


def _import_fields(conn, objects: list[dict]) -> dict[str, dict]:
    """Add the people's custom Twenty fields that aren't contact fields here yet, and the choices missing from those
    that are. Returns the fields to copy values of: {key: crm_fields row}."""
    defined = {r["key"]: dict(r) for r in conn.execute("SELECT * FROM crm_fields")}
    position = max((f["position"] for f in defined.values()), default=-1)
    imported = {}
    for meta in _fields_of(objects, "person"):
        key = meta.get("name") or ""
        if not meta.get("isCustom") or key in BUILTIN_FIELDS or not _KEY_RE.match(key):
            continue
        kind = FIELD_TYPES.get(meta.get("type"), "text")
        options = _options(meta)
        if kind == "choice" and not options:
            kind = "text"
        field = defined.get(key)
        if not field:
            position += 1
            field = {"key": key, "label": meta.get("label") or key, "type": kind, "position": position,
                     "options": json.dumps(options, ensure_ascii=False) if kind == "choice" else None}
            conn.execute("INSERT INTO crm_fields (key, label, type, options, position) VALUES (?, ?, ?, ?, ?)",
                         (key, field["label"], kind, field["options"], position))
            _add("fields")
        elif field["type"] == "choice" and kind == "choice":
            have = json.loads(field["options"] or "[]")
            if missing := [o for o in options if o[0] not in {h[0] for h in have}]:
                field["options"] = json.dumps(have + missing, ensure_ascii=False)
                conn.execute("UPDATE crm_fields SET options = ? WHERE key = ?", (field["options"], key))
        imported[key] = field
    return imported


def _import_people(conn, twenty: TwentyCrm, page: list[dict], fields: dict[str, dict]) -> None:
    existing = _existing(conn, "crm_people", [r["id"] for r in page], "updated_at, fields")
    for rec in page:
        if rec.get("deletedAt"):
            continue
        updated = _stamp(rec.get("updatedAt")) or now()
        old = existing.get(rec["id"])
        if old and old["updated_at"] >= updated:
            _add("people_unchanged")
            continue
        shown = twenty._person(rec, [])
        custom = json.loads(old["fields"] or "{}") if old else {}
        for key, field in fields.items():
            if key not in rec:
                continue
            try:
                value = _coerce(field, _plain(rec[key]))
            except CrmError:
                _add("values_skipped")
                continue
            if value is None:
                custom.pop(key, None)
            else:
                custom[key] = value
        values = (_full_name(rec.get("name")), shown["email"], shown["job_title"], shown["city"], shown["company"],
                  json.dumps(custom, ensure_ascii=False), updated, _stamp(rec.get("lastContactAt")))
        if old:
            conn.execute("""UPDATE crm_people SET name = ?, email = ?, job_title = ?, city = ?, company = ?, fields = ?,
                            updated_at = ?, last_contact_at = ? WHERE id = ?""", (*values, rec["id"]))
            _add("people_updated")
        else:
            conn.execute("""INSERT INTO crm_people (name, email, job_title, city, company, fields, updated_at,
                            last_contact_at, id, source, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'twenty', ?)""",
                         (*values, rec["id"], _stamp(rec.get("createdAt")) or updated))
            _add("people_added")
        InternalCrm._set_phones(conn, rec["id"], shown["phones"])


def _import_opportunities(conn, page: list[dict], people: set[str], stages: set[str], owners: dict) -> None:
    existing = _existing(conn, "crm_opportunities", [r["id"] for r in page], "updated_at")
    for rec in page:
        if rec.get("deletedAt"):
            continue
        updated = _stamp(rec.get("updatedAt")) or now()
        old = existing.get(rec["id"])
        if old and old["updated_at"] >= updated:
            _add("opportunities_unchanged")
            continue
        stage = rec.get("stage") or InternalCrm.lead_stage
        _ensure_stage(conn, stages, stage)
        amount = rec.get("amount") or {}
        micros = amount.get("amountMicros")
        person = rec.get("pointOfContactId")
        values = (rec.get("name") or "", person if person in people else None, stage,
                  float(micros) / 1_000_000 if micros not in (None, "") else None, amount.get("currencyCode") or None,
                  (rec.get("closeDate") or "")[:10] or None, owners.get(rec.get("ownerId")), updated)
        if old:
            conn.execute("""UPDATE crm_opportunities SET name = ?, person_id = ?, stage = ?, amount = ?, currency = ?,
                            close_date = ?, owner = ?, updated_at = ? WHERE id = ?""", (*values, rec["id"]))
            _add("opportunities_updated")
        else:
            conn.execute("""INSERT INTO crm_opportunities (name, person_id, stage, amount, currency, close_date, owner,
                            updated_at, id, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                         (*values, rec["id"], _stamp(rec.get("createdAt")) or updated))
            _add("opportunities_added")


def _import_notes(conn, found: list[dict], owners: dict) -> None:
    """Notes can't be edited here, so an imported one is simply kept the same as in Twenty."""
    existing = _existing(conn, "crm_notes", [f["note"]["id"] for f in found], "title, body")
    for about in found:
        note = about["note"]
        text = _note_text(note.get("bodyV2"))
        if not (about["person"] or about["opportunity"]) or not (text or note.get("title")):
            _add("notes_skipped")  # about a company only, or empty
            continue
        title = note.get("title") or "Note"
        old = existing.get(note["id"])
        if old and (old["title"], old["body"]) == (title, text):
            _add("notes_unchanged")
            continue
        if old:
            conn.execute("UPDATE crm_notes SET title = ?, body = ? WHERE id = ?", (title, text, note["id"]))
            _add("notes_updated")
            continue
        by = note.get("createdBy") or {}
        conn.execute("""INSERT INTO crm_notes (id, title, body, opportunity_id, person_id, author, created_at)
                        VALUES (?, ?, ?, ?, ?, ?, ?)""",
                     (note["id"], title, text, about["opportunity"], about["person"],
                      owners.get(by.get("workspaceMemberId")) or by.get("name") or None,
                      _stamp(note.get("createdAt")) or now()))
        _add("notes_added")
