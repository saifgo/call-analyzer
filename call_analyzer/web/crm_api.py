"""HTTP API for the built-in CRM's own screens (Contacts, CRM setup): contacts with their numbers, opportunities and
notes, the pipeline's stages and the custom contact fields. Admins only (see AGENT_ALLOWED in server.py), and only
while the built-in CRM is the one in use: an external CRM is edited in its own app.
"""
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from .. import auth, crm, db, twenty_import
from ..adapters.crm.internal import BUILTIN_FIELDS, InternalCrm
from ..adapters.crm.twenty import TwentyCrm

router = APIRouter()


def _local() -> InternalCrm:
    adapter = crm.adapter()
    if not isinstance(adapter, InternalCrm):
        raise HTTPException(409, f"The CRM in use is {adapter.label}: edit its contacts there. These screens are for "
                                 "the built-in CRM (CRM_PROVIDER=internal in Settings).")
    return adapter


def _run(fn, *args):
    try:
        result = fn(*args)
    except crm.CrmError as exc:
        raise HTTPException(400, str(exc))
    crm.forget()
    return result


@router.get("/api/crm/setup")
def get_setup():
    """What the CRM screens need: whether the built-in CRM is in use, its stages (with how many opportunities are at
    each and the campaigns using it), the custom fields and the users opportunities can belong to."""
    adapter = crm.adapter()
    if not isinstance(adapter, InternalCrm):
        return {"local": False, "label": adapter.label, "stages": [], "fields": [], "members": []}
    conn = db.connect()
    try:
        stage_uses, field_uses = adapter.campaign_uses(conn)
    finally:
        conn.close()
    counts = adapter.stage_counts()
    return {
        "local": True, "label": adapter.label,
        "stages": [{**s, "count": counts.get(s["value"], 0), "campaigns": stage_uses.get(s["value"], [])}
                   for s in adapter.stages()],
        "fields": [{**f, "campaigns": field_uses.get(f["key"], [])} for f in adapter.fields()],
        "members": adapter.members(),
    }


# --- Contacts --------------------------------------------------------------------------------------------------------

class ContactBody(BaseModel):
    name: str | None = None
    email: str | None = None
    job_title: str | None = None
    city: str | None = None
    company: str | None = None
    phones: list[str] | None = None
    fields: dict | None = None


def _person_fields(body: ContactBody) -> dict:
    sent = body.model_dump(exclude_unset=True)
    return {**{k: sent[k] for k in BUILTIN_FIELDS if k in sent}, **(sent.get("fields") or {})}


@router.get("/api/crm/contacts")
def list_contacts(q: str = "", stage: str = "", offset: int = 0, limit: int = 50):
    return _local().search_people(q, stage or None, max(1, min(limit, 200)), max(0, offset))


@router.post("/api/crm/contacts")
def create_contact(body: ContactBody):
    adapter = _local()
    return _run(adapter.create_contact, _person_fields(body), body.phones or [])


@router.get("/api/crm/contacts/{person_id}")
def get_contact(person_id: str):
    try:
        return _local().get_person(person_id)
    except crm.CrmError as exc:
        raise HTTPException(404, str(exc))


@router.patch("/api/crm/contacts/{person_id}")
def update_contact(person_id: str, body: ContactBody):
    adapter = _local()
    if fields := _person_fields(body):
        _run(adapter.update_person, person_id, fields)
    if body.phones is not None:
        _run(adapter.set_phones, person_id, body.phones)
    return get_contact(person_id)


@router.delete("/api/crm/contacts/{person_id}")
def delete_contact(person_id: str):
    _run(_local().delete_person, person_id)
    return {"ok": True}


# --- Opportunities and notes -----------------------------------------------------------------------------------------

class OpportunityBody(BaseModel):
    name: str | None = None
    stage: str | None = None
    owner: str | None = None
    amount: float | None = None
    currency: str | None = None
    close_date: str | None = None


def _opportunity_fields(body: OpportunityBody) -> dict:
    fields = body.model_dump(exclude_unset=True)
    if fields.get("owner") and not auth.user_exists(fields["owner"]):
        raise HTTPException(400, f"There is no account {fields['owner']!r} to own the opportunity.")
    for key in ("owner", "currency", "close_date"):
        if key in fields:
            fields[key] = (fields[key] or "").strip() or None
    if "name" in fields:
        fields["name"] = (fields["name"] or "").strip() or "Untitled opportunity"
    return fields


@router.post("/api/crm/contacts/{person_id}/opportunities")
def create_opportunity(person_id: str, body: OpportunityBody):
    adapter = _local()
    fields = _opportunity_fields(body)
    created = _run(adapter.create_opportunity, fields.pop("name", ""), person_id,
                   fields.pop("stage", None) or adapter.lead_stage, fields.pop("owner", None))
    if fields:
        _run(adapter.update_opportunity, created["id"], fields)
    return get_contact(person_id)


@router.patch("/api/crm/opportunities/{opportunity_id}")
def update_opportunity(opportunity_id: str, body: OpportunityBody):
    if fields := _opportunity_fields(body):
        _run(_local().update_opportunity, opportunity_id, fields)
    return {"ok": True}


@router.delete("/api/crm/opportunities/{opportunity_id}")
def delete_opportunity(opportunity_id: str):
    _run(_local().delete_opportunity, opportunity_id)
    return {"ok": True}


class NoteBody(BaseModel):
    text: str
    title: str = ""
    opportunity_id: str | None = None


@router.post("/api/crm/contacts/{person_id}/notes")
def add_note(person_id: str, body: NoteBody, request: Request):
    adapter = _local()
    if not body.text.strip():
        raise HTTPException(400, "The note is empty.")
    _run(adapter.add_note, body.title.strip() or "Note", body.text.strip(), body.opportunity_id or None, person_id,
         request.state.user)
    return get_contact(person_id)


@router.delete("/api/crm/notes/{note_id}")
def delete_note(note_id: str):
    _run(_local().delete_note, note_id)
    return {"ok": True}


# --- Stages and fields -----------------------------------------------------------------------------------------------

class StageBody(BaseModel):
    value: str | None = None
    label: str


class FieldBody(BaseModel):
    key: str | None = None
    label: str
    type: str = "text"
    options: list | None = None


@router.put("/api/crm/stages")
def save_stages(body: list[StageBody]):
    _run(_local().save_stages, [s.model_dump() for s in body])
    return get_setup()


@router.put("/api/crm/fields")
def save_fields(body: list[FieldBody]):
    _run(_local().save_fields, [f.model_dump() for f in body])
    return get_setup()


# --- Import from Twenty (twenty_import.py): works whichever CRM is in use, to copy it over before switching ---------

def _import_status() -> dict:
    twenty = TwentyCrm()
    return {**twenty_import.status(), "configured": twenty.is_configured(), "base_url": twenty._config()[0]}


@router.get("/api/crm/import")
def import_status():
    return _import_status()


@router.post("/api/crm/import")
def start_import():
    try:
        twenty_import.start()
    except crm.CrmError as exc:
        raise HTTPException(409, str(exc))
    return _import_status()
