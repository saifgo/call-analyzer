"""The CRM, whichever one is connected: the call desk reads leads from it and writes call results back.

The work is done by the adapter chosen with CRM_PROVIDER (adapters/crm/, Twenty by default); this module adds what
is the same for every CRM: caching, phone matching and the shape of the results. See adapters/crm/base.py to
connect another CRM.
"""
import threading
import time

from .adapters import Registry
from .adapters.crm.base import CrmAdapter, CrmError  # noqa: F401  (CrmError is part of this module's API)
from .phones import MATCH_DIGITS, match_key  # noqa: F401

BUILTIN = {"twenty": ".crm.twenty:TwentyCrm"}
registry: Registry[CrmAdapter] = Registry("CRM", "CRM_PROVIDER", "twenty", BUILTIN)

CACHE_SECONDS = 60
STAGES_CACHE_SECONDS = 600

_lock = threading.Lock()
_cache: dict[tuple[str, str], tuple[float, dict]] = {}  # (adapter, match key) -> (when, lookup result)
_leads_cache: dict[tuple[str, str, bool], tuple[float, list[dict], bool]] = {}  # -> (when, leads, more in the CRM)
_stages_cache: dict[str, tuple[float, list[dict]]] = {}
_members_cache: dict[str, tuple[float, list[dict]]] = {}


def adapter() -> CrmAdapter:
    return registry.get()


def use(crm: CrmAdapter | None) -> None:
    """Talk to this adapter instead of the one in Settings until use(None), e.g. a fake in the tests."""
    registry.use(crm)
    forget()


def forget() -> None:
    """Drop everything cached from the CRM."""
    with _lock:
        for cache in (_cache, _leads_cache, _stages_cache, _members_cache):
            cache.clear()


def is_configured() -> bool:
    return adapter().is_configured()


def not_configured_message() -> str:
    """Why the call desk can't use the CRM yet, for an agent to pass on to an admin."""
    return f"The CRM isn't connected yet: an admin needs to {adapter().not_configured_message()}."


def lead_stage() -> str:
    """The stage of opportunities nobody has worked on yet."""
    return adapter().lead_stage


def lookup(number: str) -> dict:
    """Contacts in the CRM whose phone number matches `number`, each with their opportunities.

    Returns {"configured": bool, "number": str, "searched": bool, "people": [...]}; `searched` is False when
    the number is too short to match (an internal extension). Raises CrmError when the CRM can't be queried.
    """
    crm = adapter()
    result = {"configured": crm.is_configured(), "number": number, "searched": False, "people": []}
    key = match_key(number)
    if not result["configured"] or not key:
        return result
    result["searched"] = True
    with _lock:
        cached = _cache.get((crm.name, key))
    if cached and time.time() - cached[0] < CACHE_SECONDS:
        return {**result, "people": cached[1]["people"]}
    result["people"] = crm.find_people(key)
    with _lock:
        _cache[(crm.name, key)] = (time.time(), result)
    return result


def leads(stage: str | None = None, refresh: bool = False, oldest_first: bool = False) -> dict:
    """Opportunities at `stage` (the lead stage by default; newest first, or oldest first for the call queue), each
    with its point of contact and their phone numbers.

    Returns {"configured": bool, "stage": str, "leads": [...], "truncated": bool}. Cached for CACHE_SECONDS unless
    `refresh`. Raises CrmError when the CRM can't be queried."""
    crm = adapter()
    stage = stage or crm.lead_stage
    result = {"configured": crm.is_configured(), "stage": stage, "leads": [], "truncated": False}
    if not result["configured"]:
        return result
    cache_key = (crm.name, stage, oldest_first)
    with _lock:
        cached = _leads_cache.get(cache_key)
    if cached and not refresh and time.time() - cached[0] < CACHE_SECONDS:
        found, more = cached[1], cached[2]
    else:
        found, more = crm.list_opportunities(stage, oldest_first)
        with _lock:
            _leads_cache[cache_key] = (time.time(), found, more)
    # Callers add to the leads (e.g. their calls), so each gets its own copies.
    result["leads"] = [{**lead, "contact": dict(lead["contact"]) if lead.get("contact") else None} for lead in found]
    result["truncated"] = more
    return result


def forget_leads():
    """Drop the cached lead lists, e.g. after moving an opportunity to another stage."""
    with _lock:
        _leads_cache.clear()


def opportunity_stages() -> list[dict]:
    """The opportunity stages as set up in the CRM ([{value, label}], in pipeline order)."""
    crm = adapter()
    with _lock:
        cached = _stages_cache.get(crm.name)
    if cached and time.time() - cached[0] < STAGES_CACHE_SECONDS:
        return cached[1]
    stages = crm.stages()
    with _lock:
        _stages_cache[crm.name] = (time.time(), stages)
    return stages


def opportunity(opportunity_id: str) -> dict:
    """One opportunity with its point of contact, shaped like a lead (see leads()). Raises CrmError."""
    return adapter().get_opportunity(opportunity_id)


def notes(opportunity_id: str | None, person_id: str | None, limit: int = 20) -> list[dict]:
    """Notes written in the CRM about this opportunity or person, newest first: [{id, title, text, created_at,
    author}]. Raises CrmError."""
    crm = adapter()
    if not (opportunity_id or person_id) or not crm.is_configured():
        return []
    return crm.notes(opportunity_id, person_id, limit)


def workspace_members() -> list[dict]:
    """The CRM's users ([{id, name, email}], by name), to link app accounts to. Raises CrmError."""
    crm = adapter()
    with _lock:
        cached = _members_cache.get(crm.name)
    if cached and time.time() - cached[0] < STAGES_CACHE_SECONDS:
        return cached[1]
    members = crm.members()
    with _lock:
        _members_cache[crm.name] = (time.time(), members)
    return members


def update_opportunity(opportunity_id: str, fields: dict) -> None:
    adapter().update_opportunity(opportunity_id, fields)


def update_person(person_id: str, fields: dict) -> None:
    adapter().update_person(person_id, fields)


def add_note(title: str, markdown: str, opportunity_id: str | None = None, person_id: str | None = None) -> str:
    """Write a note in the CRM, attached to the opportunity and/or the person. Returns the note's id."""
    return adapter().add_note(title, markdown, opportunity_id, person_id)


def create_person(name: str, phone: str, city: str = "", email: str = "") -> dict:
    """Add a contact. Returns the record (at least its id). Raises CrmError."""
    crm = adapter()
    rec = crm.create_person(name, phone, city, email)
    with _lock:
        _cache.pop((crm.name, match_key(phone) or ""), None)
    return rec


def create_opportunity(name: str, person_id: str, stage: str | None = None, owner_id: str | None = None) -> dict:
    """Add an opportunity for a contact (at the lead stage by default), owned by the CRM user `owner_id`. Returns the
    record (at least its id). Raises CrmError."""
    crm = adapter()
    rec = crm.create_opportunity(name, person_id, stage or crm.lead_stage, owner_id)
    with _lock:
        _cache.clear()  # the contact's lookup lists their opportunities
        _leads_cache.clear()
    return rec
