"""The CRM, whichever one is connected: the call desk reads leads from it and writes call results back.

The work is done by the adapter chosen with CRM_PROVIDER (adapters/crm/): the built-in CRM (internal) unless set
otherwise; this module adds what is the same for every CRM: caching (for CRMs reached over the network), phone
matching and the shape of the results. See adapters/crm/base.py to connect another CRM.
"""
import threading
import time

from .adapters import Registry
from .adapters.crm.base import CrmAdapter, CrmError  # noqa: F401  (CrmError is part of this module's API)
from . import db
from .config import live
from .phones import MATCH_DIGITS, match_key  # noqa: F401

BUILTIN = {"internal": ".crm.internal:InternalCrm", "twenty": ".crm.twenty:TwentyCrm"}


def default_provider() -> str:
    """The CRM used when CRM_PROVIDER isn't set: the built-in one, except for installs that were set up with Twenty
    before there was a choice (CRM_API_KEY filled in), which keep using it."""
    return "twenty" if live("CRM_API_KEY") else "internal"


registry: Registry[CrmAdapter] = Registry("CRM", "CRM_PROVIDER", default_provider, BUILTIN)

CACHE_SECONDS = 60
STAGES_CACHE_SECONDS = 600
KEEP_STALE_SECONDS = 900  # how long an out-of-date batch may still be shown while it's fetched again
DEFAULT_BATCH = 160
MAX_BATCHES = 25  # per stage: how far the call queue reads past contacts it can't serve before giving up

_lock = threading.Lock()
_cache: dict[tuple[str, str], tuple[float, dict]] = {}  # (adapter, match key) -> (when, lookup result)
# (adapter, stage, oldest first, batch size, after) -> (when fetched, out of date, leads, cursor of the next batch)
_leads_cache: dict[tuple, tuple[float, bool, list[dict], str | None]] = {}
_stages_cache: dict[str, tuple[float, list[dict]]] = {}
_members_cache: dict[str, tuple[float, list[dict]]] = {}
_refreshing: set[tuple] = set()  # lead lists being fetched again in the background (see leads(wait=False))
_leads_generation = 0  # bumped by forget_leads(), so a background fetch started before it isn't kept


def adapter() -> CrmAdapter:
    return registry.get()


def use(crm: CrmAdapter | None) -> None:
    """Talk to this adapter instead of the one in Settings until use(None), e.g. a fake in the tests."""
    registry.use(crm)
    forget()


def forget() -> None:
    """Drop everything cached from the CRM."""
    global _leads_generation
    with _lock:
        _leads_generation += 1
        for cache in (_cache, _leads_cache, _stages_cache, _members_cache):
            cache.clear()


def is_local() -> bool:
    """Whether the CRM is the built-in one (its data is in the app's database)."""
    return adapter().local


def member_id(username: str) -> str | None:
    """The CRM user this app account is (who owns the leads it adds), or None."""
    row = db.connect().execute("SELECT crm_member_id FROM users WHERE username = ?", (username,)).fetchone()
    return adapter().member_id(username, row[0] if row else None)


def is_configured() -> bool:
    return adapter().is_configured()


def not_configured_message() -> str:
    """Why the call desk can't use the CRM yet, for an agent to pass on to an admin."""
    return f"The CRM isn't connected yet: an admin needs to {adapter().not_configured_message()}."


def lead_stage() -> str:
    """The stage of opportunities nobody has worked on yet."""
    return adapter().lead_stage


def attempted_stage() -> str:
    """The stage of opportunities we called but couldn't reach."""
    return adapter().attempted_stage


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
    if crm.local:
        return {**result, "people": crm.find_people(key)}
    with _lock:
        cached = _cache.get((crm.name, key))
    if cached and time.time() - cached[0] < CACHE_SECONDS:
        return {**result, "people": cached[1]["people"]}
    result["people"] = crm.find_people(key)
    with _lock:
        _cache[(crm.name, key)] = (time.time(), result)
    return result


def batch_size() -> int | None:
    """How many contacts are read from the CRM at a time (CRM_QUEUE_BATCH in Settings): a lead list never holds more,
    and the call queue loads the next batch only when it has gone through the ones it holds. None (set to 0): no
    limit, every contact at the stage is read at once."""
    try:
        size = int(live("CRM_QUEUE_BATCH", str(DEFAULT_BATCH)))
    except ValueError:
        return DEFAULT_BATCH
    return None if size <= 0 else size


def leads(stage: str | None = None, refresh: bool = False, oldest_first: bool = False, wait: bool = True,
          after: str | None = None) -> dict:
    """One batch (batch_size(); all of them when it's None) of the opportunities at `stage` (the lead stage by
    default; newest first, or oldest first for the call queue), each with its point of contact and their phone
    numbers; `after`: the batch after the one that returned this `next`.

    Returns {"configured": bool, "stage": str, "leads": [...], "truncated": bool, "next": cursor or None}; `next` is
    set when the CRM holds more. Cached for CACHE_SECONDS unless `refresh`. With `wait=False` an out-of-date batch is
    returned as is and fetched again in the background (for figures polled often, like the desk's queue count); only
    a batch never fetched is waited for. Raises CrmError when the CRM can't be queried."""
    crm = adapter()
    stage = stage or crm.lead_stage
    result = {"configured": crm.is_configured(), "stage": stage, "leads": [], "truncated": False, "next": None}
    if not result["configured"]:
        return result
    limit = batch_size()
    cache_key = (crm.name, stage, oldest_first, limit, after)
    with _lock:
        cached = None if crm.local else _leads_cache.get(cache_key)
    if crm.local:
        found, cursor = crm.list_opportunities(stage, oldest_first, limit, after)
    elif cached and not refresh and not cached[1] and time.time() - cached[0] < CACHE_SECONDS:
        found, cursor = cached[2], cached[3]
    elif cached and not refresh and not wait and time.time() - cached[0] < KEEP_STALE_SECONDS:
        found, cursor = cached[2], cached[3]
        _refresh_leads_later(crm, cache_key)
    else:
        with _lock:
            generation = _leads_generation
        found, cursor = crm.list_opportunities(stage, oldest_first, limit, after)
        _keep_leads(cache_key, generation, found, cursor)
    # Callers add to the leads (e.g. their calls), so each gets its own copies.
    result["leads"] = [{**lead, "contact": dict(lead["contact"]) if lead.get("contact") else None} for lead in found]
    result["truncated"], result["next"] = bool(cursor), cursor
    return result


def _keep_leads(cache_key: tuple, generation: int, found: list[dict], cursor: str | None) -> None:
    """Cache a fetched batch, unless forget_leads() ran while it was being fetched (it may miss that change). Batches
    not fetched for a while are dropped (a batch's cursor changes when the ones before it do)."""
    now = time.time()
    with _lock:
        if generation == _leads_generation:
            _leads_cache[cache_key] = (now, False, found, cursor)
        for key in [k for k, v in _leads_cache.items() if now - v[0] > KEEP_STALE_SECONDS]:
            del _leads_cache[key]


def _refresh_leads_later(crm: CrmAdapter, cache_key: tuple) -> None:
    """Fetch a batch again in a background thread, once at a time per batch."""
    _, stage, oldest_first, limit, after = cache_key
    with _lock:
        if cache_key in _refreshing:
            return
        _refreshing.add(cache_key)
        generation = _leads_generation

    def run():
        try:
            _keep_leads(cache_key, generation, *crm.list_opportunities(stage, oldest_first, limit, after))
        except Exception as exc:  # the stale batch stays; the next poll tries again
            print(f"[crm] refreshing the {stage} leads failed: {exc}", flush=True)
        finally:
            with _lock:
                _refreshing.discard(cache_key)

    threading.Thread(target=run, name="crm-leads", daemon=True).start()


def forget_leads():
    """Mark the cached lead batches out of date, e.g. after moving an opportunity to another stage: the next leads()
    fetches them again (leads(wait=False) keeps showing them meanwhile)."""
    global _leads_generation
    with _lock:
        _leads_generation += 1
        for key, (when, _, found, cursor) in list(_leads_cache.items()):
            _leads_cache[key] = (when, True, found, cursor)


def opportunity_stages() -> list[dict]:
    """The opportunity stages as set up in the CRM ([{value, label}], in pipeline order)."""
    crm = adapter()
    if crm.local:
        return crm.stages()
    with _lock:
        cached = _stages_cache.get(crm.name)
    if cached and time.time() - cached[0] < STAGES_CACHE_SECONDS:
        return cached[1]
    if cached:  # they rarely change: keep using them while they're read again in the background
        with _lock:
            busy = ("stages", crm.name) in _refreshing
            _refreshing.add(("stages", crm.name))
        if not busy:
            threading.Thread(target=_refresh_stages, args=(crm,), name="crm-stages", daemon=True).start()
        return cached[1]
    stages = crm.stages()
    with _lock:
        _stages_cache[crm.name] = (time.time(), stages)
    return stages


def _refresh_stages(crm: CrmAdapter) -> None:
    try:
        stages = crm.stages()
        with _lock:
            _stages_cache[crm.name] = (time.time(), stages)
    except Exception as exc:
        print(f"[crm] reading the opportunity stages failed: {exc}", flush=True)
    finally:
        with _lock:
            _refreshing.discard(("stages", crm.name))


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
    if crm.local:
        return crm.members()
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
