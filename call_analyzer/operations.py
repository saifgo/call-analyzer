"""Operations: the call desk. Agents who are ready are served CRM contacts one at a time, call them, fill in what
they learned, and close the call with an outcome, a note, the contact's next stage and maybe a callback.

Each agent works one campaign (see campaigns.py; the first one is the CRM's New contacts). Its queue is the CRM's
opportunities at the campaign's stages that have a phone number, oldest first (first in, first out), whoever owns
them, served during the campaign's calling hours. Callbacks agents booked go in front of it once they are due. A
contact is served to one agent at a time: the next free agent takes the oldest contact nobody holds, so with agents
a1-a3 and contacts c1-c7, a1-c1, a2-c2, a3-c3, then whoever finishes first gets c4, and so on. The campaign also says
what agents ask during the call, how a call can end, and how many unanswered calls in a row end the tries.

Agents can also call a contact of their choosing (start_direct), a sales call outside the queue: they look the number up
in the CRM and call the contact found, or add the contact (create_lead) and call them right away or leave them in the
queue. The call then goes the same way as one from the queue.

Incoming calls (see inbound.py) open a desk call when the agent picks up (source 'inbound'), and the calls nobody
answered are served back to agents before anything else (source 'missed'). Both belong to the incoming calls campaign.
A caller who isn't in the CRM gets a desk-only lead (LOCAL_PREFIX), linked to the CRM during the call if the agent
adds them (link).

Test calls (start_test) serve the agent a made-up contact with a number they choose, to try the desk end to end:
nothing about them is written to the CRM, their callbacks are kept for the agent who made them, and they don't count
in the day's figures.
"""
import json
import re
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from itertools import groupby

from . import campaigns, crm, db, floor

OPEN = ("assigned", "in_call")
# A contact served to an agent whose desk stopped checking in (closed tab, lost connection) goes back to the queue
# after this long, unless the call was started.
STALE_MINUTES = 5
# A contact an agent gave back without calling isn't served to that same agent again for this long.
SKIP_MINUTES = 60
# An agent whose desk hasn't checked in for this long shows as offline on the team board.
OFFLINE_SECONDS = 90
# The opportunity id of a test call (and of the callbacks booked from it) starts with this.
TEST_PREFIX = "test:"
# The opportunity id of a caller who has no opportunity in the CRM: "inbound:<number key>" (see inbound.py). Nothing is
# written to the CRM for them, but a note when they are a CRM contact.
LOCAL_PREFIX = "inbound:"
# Desk time (op_presence) counts the time between two check-ins of a ready agent, when they are at most this far apart.
PRESENCE_GAP_SECONDS = 60

_claim_lock = threading.Lock()

# A finished call is written to the CRM in the background, one at a time and in order, so the agent moves on to the
# next contact straight away instead of waiting for the CRM. Until it's written, the call's crm_error says so; one the
# server stopped before writing is written again when it starts (resume_sync). False: right away (the tests).
SYNC_IN_BACKGROUND = True
PENDING_SYNC = "Not written to the CRM yet"
_sync_pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="crm-sync")
_sync_lock = threading.Lock()  # a retry from the board doesn't run alongside the background write (no double note)


class OperationError(Exception):
    """Something the agent did can't be done; the message is shown to them. `status` is the HTTP status."""

    def __init__(self, message: str, status: int = 400):
        super().__init__(message)
        self.status = status


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def config() -> dict:
    """What the desk needs to draw its forms: every campaign (archived ones too, to read old calls) with its questions
    and outcomes, and `outcomes`, all campaigns' outcomes by value, to label calls whatever their campaign."""
    stages = crm.opportunity_stages()
    known = {s["value"] for s in stages}
    found = []
    for c in campaigns.all_campaigns(db.connect()):
        outcomes = [{**o, "stage": o["stage"] if o["stage"] in known else None} for o in c["outcomes"]]
        found.append({**c, "outcomes": outcomes, "hours": campaigns.hours_label(c)})
    merged: dict[str, dict] = {}
    for c in found:
        for o in c["outcomes"]:
            merged.setdefault(o["value"], o)
    return {"campaigns": found, "outcomes": list(merged.values()), "stages": stages,
            "lead_stage": crm.lead_stage(), "attempted_stage": crm.attempted_stage(),
            "crm_configured": crm.is_configured()}


def outcome_lookup(conn):
    """f(campaign_id, value) -> that outcome of the campaign ({} when unknown); calls from before campaigns
    (campaign_id NULL) belong to the first one."""
    default = campaigns.default_id(conn)
    table = {c["id"]: {o["value"]: o for o in c["outcomes"]} for c in campaigns.all_campaigns(conn)}
    return lambda campaign_id, value: table.get(default if campaign_id is None else campaign_id, {}).get(value, {})


def campaign_of(conn, row) -> dict:
    return campaigns.get(conn, row["campaign_id"])


# --- Records --------------------------------------------------------------------------------------

def account_names(conn) -> dict[str, str]:
    return {r[0]: r[1] or r[0] for r in conn.execute("SELECT username, display_name FROM users")}


def is_test(row) -> bool:
    return row["opportunity_id"].startswith(TEST_PREFIX)


def in_crm(row) -> bool:
    """Whether the call is about an opportunity of the CRM (not a test, nor a caller who isn't in the CRM yet)."""
    return not (is_test(row) or row["opportunity_id"].startswith(LOCAL_PREFIX))


def to_dict(row, names: dict[str, str] | None = None) -> dict:
    item = dict(row)
    item["test"] = is_test(row)
    item["in_crm"] = in_crm(row)
    item["lead"] = json.loads(item["lead"]) if item["lead"] else None
    item["answers"] = json.loads(item["answers"]) if item["answers"] else {}
    if names is not None:
        for key in ("agent", "assign_to", "scheduled_by"):
            item[f"{key}_name"] = names.get(item[key], item[key]) if item[key] else None
    return item


def get_row(conn, op_id: int):
    row = conn.execute("SELECT * FROM op_calls WHERE id = ?", (op_id,)).fetchone()
    if not row:
        raise OperationError("This contact is no longer on the desk", 404)
    return row


def _own_open(conn, op_id: int, username: str):
    row = get_row(conn, op_id)
    if row["agent"] != username or row["status"] not in OPEN:
        raise OperationError("This contact isn't yours anymore (it may have been given back to the queue)", 409)
    return row


def current(conn, username: str):
    return conn.execute("SELECT * FROM op_calls WHERE agent = ? AND status IN ('assigned', 'in_call') "
                        "ORDER BY id LIMIT 1", (username,)).fetchone()


# --- Agents ---------------------------------------------------------------------------------------

def _tick(conn, username: str, now: datetime) -> None:
    """Count the time since the agent's last check-in as desk time, if they were ready (taking calls) meanwhile."""
    row = conn.execute("SELECT ready, last_seen FROM op_agents WHERE username = ?", (username,)).fetchone()
    if not row or not row["ready"] or not row["last_seen"]:
        return
    try:
        gap = (now - datetime.fromisoformat(row["last_seen"])).total_seconds()
    except ValueError:
        return
    if 0 < gap <= PRESENCE_GAP_SECONDS:
        conn.execute("INSERT INTO op_presence (username, day, ready_seconds) VALUES (?, ?, ?) "
                     "ON CONFLICT(username, day) DO UPDATE SET ready_seconds = ready_seconds + excluded.ready_seconds",
                     (username, now.date().isoformat(), round(gap)))


def heartbeat(conn, username: str) -> bool:
    """The agent's desk checked in. Returns whether they are ready to take calls."""
    now = datetime.now().replace(microsecond=0)
    _tick(conn, username, now)
    away = (now - timedelta(seconds=OFFLINE_SECONDS)).isoformat()
    conn.execute("INSERT INTO op_agents (username, ready, last_seen, online_since) VALUES (?, 0, ?, ?) "
                 "ON CONFLICT(username) DO UPDATE SET last_seen = excluded.last_seen, online_since = "
                 "CASE WHEN COALESCE(op_agents.last_seen, '') < ? THEN excluded.online_since "
                 "ELSE op_agents.online_since END", (username, now.isoformat(), now.isoformat(), away))
    floor.touch_pause(conn, username, now)
    floor.touch_shift(conn, username, now, busy=current(conn, username) is not None)
    conn.commit()
    return bool(conn.execute("SELECT ready FROM op_agents WHERE username = ?", (username,)).fetchone()[0])


def agent_campaign(conn, username: str) -> dict:
    """The campaign the agent works: the one they picked while it's active, else the first active one."""
    row = conn.execute("SELECT campaign_id FROM op_agents WHERE username = ?", (username,)).fetchone()
    campaign = campaigns.get(conn, row[0] if row else None)
    return campaign if campaign["active"] and campaign["kind"] == campaigns.OUTBOUND else campaigns.get(conn, None)


def set_campaign(conn, username: str, campaign_id: int) -> dict:
    row = conn.execute("SELECT active, kind FROM op_campaigns WHERE id = ?", (campaign_id,)).fetchone()
    if not row or not row[0]:
        raise OperationError("This campaign isn't running anymore", 404)
    if row[1] == campaigns.INBOUND:
        raise OperationError("Incoming calls come to you by themselves: pick a campaign to call")
    conn.execute("INSERT INTO op_agents (username, ready, campaign_id) VALUES (?, 0, ?) "
                 "ON CONFLICT(username) DO UPDATE SET campaign_id = excluded.campaign_id", (username, campaign_id))
    conn.commit()
    return campaigns.get(conn, campaign_id)


def set_ready(conn, username: str, ready: bool, reason_id: int | None = None) -> None:
    """Start or stop taking calls. Pausing with a reason starts a pause for it (see floor.py); pausing without one
    (e.g. for a test call) keeps the pause the agent is on, if any. Taking calls ends it, and clocks the agent in if
    they weren't; pausing for a reason needs them clocked in."""
    moment = datetime.now().replace(microsecond=0)
    if not ready and reason_id is not None and not floor.open_shift(conn, username):
        raise OperationError("Clock in first", 409)
    _tick(conn, username, moment)
    now = moment.isoformat()
    if not ready and reason_id is None:
        was = conn.execute("SELECT ready, since FROM op_agents WHERE username = ?", (username,)).fetchone()
        if was and not was["ready"] and was["since"]:
            now = was["since"]  # already paused: keep when the pause started
    conn.execute("INSERT INTO op_agents (username, ready, since, last_seen) VALUES (?, ?, ?, ?) "
                 "ON CONFLICT(username) DO UPDATE SET ready = excluded.ready, since = excluded.since, "
                 "last_seen = excluded.last_seen", (username, int(ready), now, moment.isoformat()))
    try:
        if ready:
            floor.clock_in(conn, username, moment)
            floor.end_pause(conn, username, moment)
        elif reason_id is not None:
            floor.start_pause(conn, username, reason_id, moment)
    except floor.FloorError as exc:
        conn.rollback()
        raise OperationError(str(exc), 404) from None
    conn.commit()


def clock_in(conn, username: str) -> None:
    """The agent starts their shift (paused: they start taking calls when they're ready)."""
    floor.clock_in(conn, username, datetime.now().replace(microsecond=0))
    conn.commit()


def clock_out(conn, username: str, by: str = "agent") -> None:
    """The agent ends their shift: they stop taking calls, the pause they're on ends, and a contact they were served
    but haven't called goes back to the queue. Not during a call."""
    with _claim_lock:
        if row := current(conn, username):
            if row["call_started_at"]:
                raise OperationError("Close your call before clocking out", 409)
            release(conn, row["id"])
        moment = datetime.now().replace(microsecond=0)
        _tick(conn, username, moment)
        floor.clock_out(conn, username, moment, by=by)
        conn.commit()


def release(conn, op_id: int) -> None:
    """Give a contact back: a callback is due again for anyone allowed, a queue contact goes back in the queue."""
    row = get_row(conn, op_id)
    if row["status"] not in OPEN:
        raise OperationError("This contact isn't being served")
    if row["source"] == "callback":
        conn.execute("UPDATE op_calls SET status = 'scheduled', agent = NULL, assigned_at = NULL, "
                     "call_started_at = NULL, call_ended_at = NULL WHERE id = ?", (op_id,))
    else:
        conn.execute("UPDATE op_calls SET status = 'released', finished_at = ? WHERE id = ?", (_now(), op_id))
    conn.commit()


def give_back(op_id: int, username: str) -> None:
    """The agent doesn't call the contact they were served: it goes back to the queue (a callback stays due) for
    the others, and isn't served to them again for SKIP_MINUTES."""
    conn = db.connect()
    row = _own_open(conn, op_id, username)
    if row["call_started_at"]:
        raise OperationError("The call was started: close it with an outcome instead")
    release(conn, op_id)
    if row["source"] == "callback":
        # The callback itself is waiting again; this marker only keeps it away from the agent who gave it back.
        now = _now()
        conn.execute("""INSERT INTO op_calls (opportunity_id, person_id, lead, source, status, agent, finished_at,
                                              stage_before, campaign_id, created_at)
                        VALUES (?, ?, ?, 'callback', 'released', ?, ?, ?, ?, ?)""",
                     (row["opportunity_id"], row["person_id"], row["lead"], username, now, row["stage_before"],
                      row["campaign_id"], now))
        conn.commit()


def _skipped(conn, username: str) -> set[str]:
    """Opportunities the agent gave back recently, not to be served to them again yet."""
    since = (datetime.now() - timedelta(minutes=SKIP_MINUTES)).isoformat(timespec="seconds")
    return {r[0] for r in conn.execute("SELECT DISTINCT opportunity_id FROM op_calls WHERE status = 'released' "
                                       "AND agent = ? AND finished_at >= ?", (username, since))}


def release_stale(conn) -> None:
    """Contacts held by agents whose desk went quiet before they started the call go back to the queue."""
    cutoff = (datetime.now() - timedelta(minutes=STALE_MINUTES)).isoformat(timespec="seconds")
    for row in conn.execute("""SELECT o.id FROM op_calls o LEFT JOIN op_agents a ON a.username = o.agent
                               WHERE o.status = 'assigned' AND COALESCE(a.last_seen, '') < ?""", (cutoff,)).fetchall():
        release(conn, row["id"])


# --- The queue ------------------------------------------------------------------------------------

def _callable(lead: dict) -> bool:
    return bool((lead.get("contact") or {}).get("phones"))


def _retries(conn, campaign: dict) -> dict[str, str]:
    """Contacts handled in this campaign that the queue may serve again, with when they were last tried: the latest
    call didn't reach them (and didn't reject them), it's been the campaign's retry time since, and they have tries
    left."""
    lookup = outcome_lookup(conn)
    attempted = crm.attempted_stage()
    cutoff = (datetime.now() - timedelta(minutes=campaign["retry_minutes"])).isoformat(timespec="seconds")
    rows = conn.execute("""SELECT opportunity_id, outcome, campaign_id, finished_at FROM op_calls
                           WHERE status = 'done' AND opportunity_id IN (
                               SELECT opportunity_id FROM op_calls WHERE status = 'done' AND COALESCE(campaign_id, ?) = ?)
                           ORDER BY opportunity_id, finished_at DESC, id DESC""",
                        (campaigns.default_id(conn), campaign["id"])).fetchall()
    ready = {}
    for opp, calls in groupby(rows, key=lambda r: r["opportunity_id"]):
        calls = [(lookup(r["campaign_id"], r["outcome"]), r["finished_at"] or "") for r in calls]
        latest, when = calls[0]
        if latest.get("reached") or latest.get("stage") not in (None, attempted) or when > cutoff:
            continue
        unanswered = next((i for i, (o, _) in enumerate(calls) if o.get("reached")), len(calls))
        if not campaign["max_attempts"] or unanswered < campaign["max_attempts"]:
            ready[opp] = when
    return ready


def _taken(conn, campaign: dict) -> tuple[set[str], dict[str, str]]:
    """Opportunities the campaign's queue must skip (being called, waiting for a callback, or already handled in this
    campaign, unless it's time to try an unreached one again), and those tried again with when they were last
    tried."""
    busy = {r[0] for r in conn.execute(
        "SELECT DISTINCT opportunity_id FROM op_calls WHERE status IN ('assigned', 'in_call', 'scheduled')")}
    handled = {r[0] for r in conn.execute(
        "SELECT DISTINCT opportunity_id FROM op_calls WHERE status = 'done' AND COALESCE(campaign_id, ?) = ?",
        (campaigns.default_id(conn), campaign["id"]))}
    retries = {k: v for k, v in _retries(conn, campaign).items() if k not in busy}
    return busy | (handled - set(retries)), retries


def _campaign_leads(campaign: dict, skip: set[str], wait: bool = True) -> dict:
    """The CRM opportunities the campaign's queue holds, leaving out those in `skip`: stage by stage in pipeline order
    (New before Attempted), oldest first within each, at most a batch of them (crm.batch_size(); None: all). Read
    from the CRM batch by batch, the next one only while the queue isn't full, so contacts it can't serve (e.g.
    Attempted ones out of tries) don't hide the ones after them. `truncated`: the CRM holds more. `wait=False`:
    batches out of date are used as they are (see crm.leads). Raises crm.CrmError."""
    order = {s["value"]: i for i, s in enumerate(crm.opportunity_stages())}
    limit = crm.batch_size()
    leads, truncated = [], False

    def full() -> bool:
        return limit is not None and len(leads) >= limit

    for stage in sorted(campaign["stages"], key=lambda s: order.get(s, len(order))):
        if full():
            truncated = True
            break
        after = None
        for _ in range(crm.MAX_BATCHES):
            data = crm.leads(stage=stage, oldest_first=True, wait=wait, after=after)
            leads += [lead for lead in data["leads"] if lead["id"] not in skip]
            after = data["next"]
            if not after or full():
                break
        truncated = truncated or bool(after)
    return {"leads": leads[:limit], "truncated": truncated or (limit is not None and len(leads) > limit)}


def _queue(leads: list[dict], taken: set[str], retries: dict[str, str]) -> list[dict]:
    """The contacts waiting, in serving order: the campaign's order, except that contacts we already tried go after
    those of their stage we haven't, the least recently tried first."""
    rank = {}
    for lead in leads:
        rank.setdefault(lead.get("stage"), len(rank))
    fresh = [lead for lead in leads if lead["id"] not in taken]
    # sorted() is stable: untried contacts keep their oldest-first order.
    return sorted(fresh, key=lambda lead: (rank[lead.get("stage")], lead["id"] in retries, retries.get(lead["id"], "")))


def queue_counts(conn, campaign: dict) -> dict:
    """How many contacts are waiting in the campaign's queue. `waiting` is None when the CRM can't be read (`error`
    says why). Polled with the desk, so it doesn't wait for the CRM: the count may be up to a fetch behind."""
    now = _now()
    mine = "COALESCE(campaign_id, ?) = ?"
    args = (campaigns.default_id(conn), campaign["id"])
    due = conn.execute(f"SELECT COUNT(*) FROM op_calls WHERE status = 'scheduled' AND due_at <= ? AND {mine}",
                       (now, *args)).fetchone()[0]
    scheduled = conn.execute(f"SELECT COUNT(*) FROM op_calls WHERE status = 'scheduled' AND {mine}", args).fetchone()[0]
    result = {"campaign_id": campaign["id"], "campaign": campaign["name"], "hours": campaigns.hours_label(campaign),
              "open": campaigns.is_open(campaign, datetime.now()), "due_callbacks": due, "scheduled": scheduled,
              "waiting": None, "no_phone": None, "error": None, "truncated": False}
    if not crm.is_configured():
        result["error"] = crm.not_configured_message()
        return result
    try:
        taken, retries = _taken(conn, campaign)
        data = _campaign_leads(campaign, taken, wait=False)
    except crm.CrmError as exc:
        result["error"] = str(exc)
        return result
    fresh = _queue(data["leads"], taken, retries)
    result.update(waiting=sum(map(_callable, fresh)), no_phone=sum(not _callable(lead) for lead in fresh),
                  truncated=data["truncated"])
    return result


def claim_next(username: str) -> tuple[dict | None, str | None]:
    """Serve the agent their next contact: the one they already hold, else a missed call to call back (see
    inbound.claim), else the earliest due callback they may take, else the oldest New opportunity in the CRM nobody
    has. Returns (op_call, None), or (None, why there's none).

    The CRM is read outside _claim_lock, so a slow CRM doesn't hold up the other agents, and from the cached lead
    lists when there are some (refreshed in the background, see crm.leads(wait=False)): what's being called or was
    handled is in our database, so a list a little out of date can't serve a contact twice."""
    conn = db.connect()
    try:
        with _claim_lock:
            served, reason, campaign = _claim_local(conn, username)
        if served or reason or campaign is None:
            return served, reason
        try:
            leads = _campaign_leads(campaign, _taken(conn, campaign)[0] | _skipped(conn, username), wait=False)["leads"]
        except crm.CrmError as exc:
            return None, str(exc)
        with _claim_lock:
            # Again under the lock: another agent may have taken one of these contacts (or this agent another one)
            # while the CRM was being read.
            if row := current(conn, username):
                return to_dict(row, account_names(conn)), None
            taken, retries = _taken(conn, campaign)
            skip = taken | _skipped(conn, username)
            lead = next((lead for lead in _queue(leads, skip, retries) if _callable(lead)), None)
            if not lead:
                return None, None
            now = _now()
            cur = conn.execute("""INSERT INTO op_calls (opportunity_id, person_id, lead, source, status, agent,
                                                        assigned_at, stage_before, campaign_id, created_at)
                                  VALUES (?, ?, ?, 'queue', 'assigned', ?, ?, ?, ?, ?)""",
                               (lead["id"], (lead["contact"] or {}).get("id"), json.dumps(lead, ensure_ascii=False),
                                username, now, lead.get("stage"), campaign["id"], now))
            conn.commit()
            return to_dict(get_row(conn, cur.lastrowid), account_names(conn)), None
    finally:
        conn.close()


def _claim_local(conn, username: str) -> tuple[dict | None, str | None, dict | None]:
    """What claim_next serves without the CRM: the contact the agent holds, a missed call, a due callback. Returns
    (op_call, None, None), (None, why there's none, None), or (None, None, the campaign) to serve from its queue."""
    from . import inbound
    if row := current(conn, username):
        return to_dict(row, account_names(conn)), None, None
    if op := inbound.claim(conn, username):
        return op, None, None
    campaign = agent_campaign(conn, username)
    now = _now()
    skipped = _skipped(conn, username)
    # Their own callbacks (kept for them or booked by them, whatever the campaign), the campaign's callbacks for
    # anyone, and for anyone too the incoming calls' callbacks (nobody works that campaign) and those of a campaign
    # that isn't running anymore (nobody works it either).
    default = campaigns.default_id(conn)
    row = next((r for r in conn.execute("""
        SELECT * FROM op_calls WHERE status = 'scheduled' AND due_at <= ?
          AND (assign_to = ? OR (assign_to IS NULL AND (
                scheduled_by = ? OR COALESCE(campaign_id, ?) = ? OR campaign_id = ?
                OR COALESCE(campaign_id, ?) NOT IN (SELECT id FROM op_campaigns WHERE active = 1))))
          AND opportunity_id NOT IN (SELECT opportunity_id FROM op_calls WHERE status IN ('assigned', 'in_call'))
        ORDER BY due_at, id""", (now, username, username, default, campaign["id"], campaigns.inbound_id(conn),
                                 default))
                if r["opportunity_id"] not in skipped), None)
    if row:
        conn.execute("UPDATE op_calls SET status = 'assigned', agent = ?, assigned_at = ? WHERE id = ?",
                     (username, now, row["id"]))
        conn.commit()
        return to_dict(get_row(conn, row["id"]), account_names(conn)), None, None
    if not campaigns.is_open(campaign, datetime.now()):
        return None, (f"{campaign['name']} is only called {campaigns.hours_label(campaign)}. "
                      "Callbacks that come due are still served."), None
    if not crm.is_configured():
        return None, crm.not_configured_message(), None
    return None, None, campaign


def lookup(phone: str) -> dict:
    """The CRM's contacts with this number, each with their opportunities (see crm.lookup)."""
    if not crm.match_key(phone):
        raise OperationError("Enter the full phone number (8 digits)")
    if not crm.is_configured():
        raise OperationError(crm.not_configured_message())
    try:
        return crm.lookup(phone)
    except crm.CrmError as exc:
        raise OperationError(str(exc), 502)


def create_lead(username: str, *, phone: str = "", name: str = "", city: str = "", email: str = "",
                person_id: str | None = None) -> str:
    """Add a New opportunity to the CRM, for an existing contact (`person_id`) or a new one made from the details,
    owned by the agent's CRM user when their account is linked to one. Being New, it's in the queue too. Returns the
    opportunity id."""
    name = " ".join(name.split())[:100]
    if not name:
        raise OperationError("Enter the contact's name")
    if not crm.is_configured():
        raise OperationError(crm.not_configured_message())
    try:
        if not person_id:
            if not crm.match_key(phone):
                raise OperationError("Enter the full phone number (8 digits)")
            if crm.lookup(phone)["people"]:
                raise OperationError("This number is already in the CRM: search it again to call that contact", 409)
            person_id = crm.create_person(name, " ".join(phone.split())[:40], " ".join(city.split())[:200],
                                          email.strip()[:200])["id"]
        return crm.create_opportunity(f"{name} Call Desk Lead", person_id, owner_id=crm.member_id(username))["id"]
    except crm.CrmError as exc:
        raise OperationError(str(exc), 502)


def start_direct(username: str, opportunity_id: str) -> dict:
    """Serve the agent the CRM opportunity they chose to call. A contact they hold but haven't called yet goes back
    to the queue; one they're on the phone with must be closed first."""
    try:
        lead = crm.opportunity(opportunity_id)
    except crm.CrmError as exc:
        raise OperationError(str(exc), 502)
    if not _callable(lead):
        raise OperationError("This contact has no phone number in the CRM")
    with _claim_lock:
        conn = db.connect()
        names = account_names(conn)
        if row := current(conn, username):
            if row["opportunity_id"] == opportunity_id:
                return to_dict(row, names)
            if row["status"] != "assigned":
                raise OperationError("Close the call you're on before starting another one", 409)
            release(conn, row["id"])
        held = conn.execute("SELECT agent FROM op_calls WHERE opportunity_id = ? AND status IN ('assigned', 'in_call')",
                            (opportunity_id,)).fetchone()
        if held:
            raise OperationError(f"{names.get(held[0], held[0])} is already calling this contact", 409)
        now = _now()
        cur = conn.execute("""INSERT INTO op_calls (opportunity_id, person_id, lead, source, status, agent, assigned_at,
                                                    stage_before, campaign_id, created_at)
                              VALUES (?, ?, ?, 'direct', 'assigned', ?, ?, ?, ?, ?)""",
                           (lead["id"], (lead["contact"] or {}).get("id"), json.dumps(lead, ensure_ascii=False),
                            username, now, lead.get("stage"), agent_campaign(conn, username)["id"], now))
        conn.commit()
        return to_dict(get_row(conn, cur.lastrowid), names)


def link(op_id: int, username: str, *, opportunity_id: str | None = None, person_id: str | None = None,
         name: str = "", city: str = "", email: str = "") -> dict:
    """Link a call that came in (or calls back a missed one) to the CRM: to one of the caller's opportunities, to a new
    opportunity for their CRM contact (`person_id`), or to a new contact made from the details. The call then goes on
    about that opportunity. Returns the op_call."""
    conn = db.connect()
    row = _own_open(conn, op_id, username)
    if row["source"] not in ("inbound", "missed"):
        raise OperationError("Only calls that came in can be linked to another contact")
    if not opportunity_id:
        lead = json.loads(row["lead"]) if row["lead"] else {}
        phone = row["phone"] or next(iter((lead.get("contact") or {}).get("phones") or []), "")
        opportunity_id = create_lead(username, phone=phone, name=name or (lead.get("contact") or {}).get("name") or "",
                                     city=city, email=email, person_id=person_id)
    try:
        lead = crm.opportunity(opportunity_id)
    except crm.CrmError as exc:
        raise OperationError(str(exc), 502)
    with _claim_lock:
        conn = db.connect()
        names = account_names(conn)
        held = conn.execute("SELECT * FROM op_calls WHERE opportunity_id = ? AND status IN ('assigned', 'in_call') "
                            "AND id != ?", (opportunity_id, op_id)).fetchone()
        if held and held["status"] == "assigned":
            release(conn, held["id"])  # served to someone who hasn't called yet: this agent is on the phone with them
        elif held:
            raise OperationError(f"{names.get(held['agent'], held['agent'])} is on a call with this contact", 409)
        conn.execute("UPDATE op_calls SET opportunity_id = ?, person_id = ?, lead = ?, stage_before = ? WHERE id = ?",
                     (opportunity_id, (lead.get("contact") or {}).get("id"), json.dumps(lead, ensure_ascii=False),
                      lead.get("stage"), op_id))
        conn.commit()
        return to_dict(get_row(conn, op_id), names)


def start_test(username: str, phone: str, name: str = "") -> dict:
    """Serve the agent a made-up contact to call on `phone`, and pause them so the queue doesn't serve them a real
    one after it. Only when they aren't holding a contact already."""
    phone = " ".join(phone.split())[:40]
    if len(re.sub(r"\D", "", phone)) < 3:
        raise OperationError("Enter the number to call for the test")
    with _claim_lock:
        conn = db.connect()
        if current(conn, username):
            raise OperationError("Finish or give back the contact you're serving before starting a test call", 409)
        set_ready(conn, username, False)
        now = _now()
        test_id = f"{TEST_PREFIX}{uuid.uuid4().hex[:12]}"
        contact = {"id": None, "name": name.strip()[:100] or "Test contact", "email": None, "phones": [phone],
                   "job_title": None, "city": None, "company": None, "created_at": None, "last_contact_at": None,
                   "url": None}
        lead = {"id": test_id, "name": "Test call (not in the CRM)", "stage": crm.lead_stage(), "amount": None,
                "currency": None, "close_date": None, "company": None, "owner": None, "created_at": None,
                "updated_at": None, "url": None, "contact": contact}
        cur = conn.execute("""INSERT INTO op_calls (opportunity_id, lead, source, status, agent, assigned_at,
                                                    stage_before, campaign_id, created_at)
                              VALUES (?, ?, 'test', 'assigned', ?, ?, ?, ?, ?)""",
                           (test_id, json.dumps(lead, ensure_ascii=False), username, now, lead["stage"],
                            agent_campaign(conn, username)["id"], now))
        conn.commit()
        return to_dict(get_row(conn, cur.lastrowid), account_names(conn))


# --- During and after the call ----------------------------------------------------------------------

def clean_answers(answers: dict, campaign: dict) -> dict:
    """Keep the campaign's questions only, with values of the right type; drop empty ones."""
    questions = campaigns.questions_by_key(campaign)
    clean = {}
    for key, value in (answers or {}).items():
        q = questions.get(key)
        if not q or value is None or value == "" or value == []:
            continue
        kind = q["type"]
        options = {o[0] for o in q.get("options", [])}
        if kind == "number":
            try:
                value = float(value)
            except (TypeError, ValueError):
                continue
            value = int(value) if value.is_integer() else value
        elif kind == "boolean":
            value = bool(value)
        elif kind == "select":
            if value not in options:
                continue
        elif kind == "multi":
            value = [v for v in value if v in options] if isinstance(value, list) else []
            if not value:
                continue
        else:
            value = str(value).strip()[:2000]
            if not value:
                continue
        clean[key] = value
    return clean


def start_call(op_id: int, username: str, phone: str | None = None) -> dict:
    """The agent dials the contact, on `phone` (one of theirs; the first one when not said)."""
    conn = db.connect()
    row = _own_open(conn, op_id, username)
    phones = ((json.loads(row["lead"]) if row["lead"] else {}).get("contact") or {}).get("phones") or []
    phone = " ".join((phone or "").split())[:40] or (phones[0] if phones else None)
    conn.execute("UPDATE op_calls SET status = 'in_call', call_started_at = COALESCE(call_started_at, ?), "
                 "phone = COALESCE(phone, ?) WHERE id = ?", (_now(), phone, op_id))
    conn.commit()
    return to_dict(get_row(conn, op_id), account_names(conn))


def end_call(op_id: int, username: str) -> dict:
    """The conversation is over; the agent is now writing it up."""
    conn = db.connect()
    _own_open(conn, op_id, username)
    now = _now()
    conn.execute("UPDATE op_calls SET status = 'in_call', call_started_at = COALESCE(call_started_at, ?), "
                 "call_ended_at = COALESCE(call_ended_at, ?) WHERE id = ?", (now, now, op_id))
    conn.commit()
    return to_dict(get_row(conn, op_id), account_names(conn))


def save_answers(op_id: int, username: str, answers: dict) -> None:
    conn = db.connect()
    row = _own_open(conn, op_id, username)
    conn.execute("UPDATE op_calls SET answers = ? WHERE id = ?",
                 (json.dumps(clean_answers(answers, campaign_of(conn, row)), ensure_ascii=False), op_id))
    conn.commit()


def _parse_due(value: str) -> str:
    try:
        due = datetime.fromisoformat(value.strip().replace(" ", "T"))
    except ValueError:
        raise OperationError("Pick a valid date and time for the callback")
    if due.tzinfo:
        due = due.astimezone().replace(tzinfo=None)
    if due < datetime.now() - timedelta(minutes=1):
        raise OperationError("The callback must be in the future")
    return due.isoformat(timespec="seconds")


def attempts(conn, row) -> int:
    """Unanswered calls in a row to the contact before this one: the latest closed calls back to the last one where
    the agent spoke with them."""
    lookup = outcome_lookup(conn)
    count = 0
    for r in conn.execute("SELECT outcome, campaign_id FROM op_calls WHERE opportunity_id = ? AND status = 'done' "
                          "AND id != ? ORDER BY finished_at DESC, id DESC", (row["opportunity_id"], row["id"])):
        if lookup(r["campaign_id"], r["outcome"]).get("reached"):
            break
        count += 1
    return count


def finish(op_id: int, username: str, *, answers: dict, outcome: str, note: str, stage: str | None,
           callback_at: str | None = None, callback_note: str = "", callback_mine: bool = False) -> dict:
    """Close the call, book the callback if any, then write it all to the CRM. Returns the finished op_call, with
    `crm_error` set when the CRM couldn't be updated (the call is saved anyway), and `attempts_exhausted` when this
    was the campaign's last try at an unanswered contact: then no callback is booked, and the contact moves to the
    campaign's stage for those, if it has one."""
    known_stages = {s["value"] for s in crm.opportunity_stages()}
    if stage and stage not in known_stages:
        raise OperationError("Unknown stage")
    due = _parse_due(callback_at) if callback_at else None
    conn = db.connect()
    row = _own_open(conn, op_id, username)
    if not in_crm(row) and not is_test(row):
        stage = None  # a caller with no opportunity in the CRM has no stage to move
    campaign = campaign_of(conn, row)
    chosen = campaigns.outcome(campaign, outcome)
    if not chosen:
        raise OperationError("Choose how the call went")
    # A call from a queue that didn't get hold of a New contact (and didn't reject them): they're Attempted now, at
    # the end of the New leads queue.
    attempted = crm.attempted_stage()
    if (campaign["kind"] == campaigns.OUTBOUND and (in_crm(row) or is_test(row)) and not chosen["reached"]
            and not stage and chosen.get("stage") in (None, attempted) and attempted in known_stages and (row["stage_before"] or crm.lead_stage()) == crm.lead_stage()):
        stage = attempted
    exhausted = False
    if not chosen["reached"] and campaign["max_attempts"] and attempts(conn, row) + 1 >= campaign["max_attempts"]:
        exhausted, due = True, None
        if campaign["exhausted_stage"] in known_stages:
            stage = campaign["exhausted_stage"]
    callback_mine = callback_mine or is_test(row)  # a test callback never goes to another agent
    now = _now()
    conn.execute("""UPDATE op_calls SET status = 'done', call_started_at = COALESCE(call_started_at, ?),
                        call_ended_at = COALESCE(call_ended_at, ?), finished_at = ?, answers = ?, outcome = ?,
                        note = ?, stage_after = ? WHERE id = ?""",
                 (now, now, now, json.dumps(clean_answers(answers, campaign), ensure_ascii=False), outcome,
                  note.strip()[:4000] or None, stage or None, op_id))
    if chosen["reached"] or due:
        # The contact was dealt with (or booked again): the callbacks still waiting for them are done with.
        conn.execute("UPDATE op_calls SET status = 'cancelled', finished_at = ? WHERE opportunity_id = ? "
                     "AND status = 'scheduled'", (now, row["opportunity_id"]))
    if due:
        lead = json.loads(row["lead"]) if row["lead"] else {}
        if stage:
            lead["stage"] = stage
        conn.execute("""INSERT INTO op_calls (opportunity_id, person_id, lead, source, status, due_at, assign_to,
                                              scheduled_by, scheduled_from, callback_note, stage_before, campaign_id,
                                              created_at)
                        VALUES (?, ?, ?, 'callback', 'scheduled', ?, ?, ?, ?, ?, ?, ?, ?)""",
                     (row["opportunity_id"], row["person_id"], json.dumps(lead, ensure_ascii=False), due,
                      username if callback_mine else None, username, op_id, callback_note.strip()[:1000] or None,
                      stage or row["stage_before"], campaign["id"], now))
    pending = SYNC_IN_BACKGROUND and _needs_sync(row)
    if pending:
        conn.execute("UPDATE op_calls SET crm_error = ? WHERE id = ?", (PENDING_SYNC, op_id))
    conn.commit()
    if pending:
        _sync_pool.submit(_sync_logged, op_id)
    else:
        sync_crm(op_id)
    done = to_dict(get_row(conn, op_id), account_names(conn))
    conn.close()
    if pending:
        done["crm_error"] = None  # nothing went wrong: it's on its way
    return {**done, "crm_pending": pending, "attempts_exhausted": exhausted}


def cancel_callback(conn, op_id: int, username: str, is_admin: bool) -> None:
    row = get_row(conn, op_id)
    if row["status"] != "scheduled":
        raise OperationError("This callback isn't waiting anymore")
    if not is_admin and username not in (row["scheduled_by"], row["assign_to"]):
        raise OperationError("Only the agent who booked this callback, or an admin, can cancel it", 403)
    conn.execute("UPDATE op_calls SET status = 'cancelled', finished_at = ? WHERE id = ?", (_now(), op_id))
    conn.commit()


def take_callback(username: str, op_id: int) -> dict:
    """The agent calls one of their callbacks now, before it's due (from "My callbacks"). A contact they hold but
    haven't called yet goes back to the queue; one they're on the phone with must be closed first."""
    with _claim_lock:
        conn = db.connect()
        row = get_row(conn, op_id)
        names = account_names(conn)
        if row["source"] != "callback":
            raise OperationError("Not found", 404)
        if (mine := current(conn, username)) and mine["id"] == op_id:
            return to_dict(mine, names)
        if row["status"] != "scheduled":
            raise OperationError("This callback isn't waiting anymore", 409)
        if username not in (row["scheduled_by"], row["assign_to"]):
            raise OperationError("This callback is kept for someone else", 403)
        if mine:
            if mine["status"] != "assigned":
                raise OperationError("Close the call you're on before starting another one", 409)
            release(conn, mine["id"])
        held = conn.execute("SELECT agent FROM op_calls WHERE opportunity_id = ? AND status IN ('assigned', 'in_call')",
                            (row["opportunity_id"],)).fetchone()
        if held:
            raise OperationError(f"{names.get(held[0], held[0])} is already calling this contact", 409)
        conn.execute("UPDATE op_calls SET status = 'assigned', agent = ?, assigned_at = ? WHERE id = ?",
                     (username, _now(), op_id))
        conn.commit()
        return to_dict(get_row(conn, op_id), names)


# --- Writing back to the CRM ----------------------------------------------------------------------

def _fmt_answer(q: dict, value) -> str:
    labels = dict((o[0], o[1]) for o in q.get("options", []))
    if q["type"] == "boolean":
        return "Yes" if value else "No"
    if q["type"] == "multi":
        return ", ".join(labels.get(v, v) for v in value)
    if q["type"] == "select":
        return labels.get(value, value)
    if q["type"] == "number":
        return f"{value:g} {q['unit']}" if q.get("unit") else f"{value:g}"
    return str(value)


def _fmt_when(value: str | None) -> str:
    try:
        return datetime.fromisoformat(value).strftime("%d/%m/%Y %H:%M")
    except (TypeError, ValueError):
        return value or ""


def note_markdown(conn, row, names: dict[str, str]) -> str:
    stages = {s["value"]: s["label"] for s in crm.opportunity_stages()}
    campaign = campaign_of(conn, row)
    outcome = campaigns.outcome(campaign, row["outcome"]).get("label", row["outcome"])
    lines = [f"**Call result: {outcome}**"]
    meta = [f"Agent: {names.get(row['agent'], row['agent'])}", f"Campaign: {campaign['name']}",
            _fmt_when(row["call_started_at"])]
    try:
        seconds = int((datetime.fromisoformat(row["call_ended_at"]) -
                       datetime.fromisoformat(row["call_started_at"])).total_seconds())
        meta.append(f"{seconds // 60}:{seconds % 60:02d} on the call")
    except (TypeError, ValueError):
        pass
    lines.append(" · ".join(m for m in meta if m))
    if row["stage_after"] and row["stage_after"] != row["stage_before"]:
        lines.append(f"Stage: {stages.get(row['stage_before'], row['stage_before'] or '?')} → "
                     f"{stages.get(row['stage_after'], row['stage_after'])}")
    callback = conn.execute("SELECT * FROM op_calls WHERE scheduled_from = ? AND source = 'callback'",
                            (row["id"],)).fetchone()
    if callback:
        who = f" ({names.get(callback['assign_to'], callback['assign_to'])} only)" if callback["assign_to"] else ""
        lines.append(f"Callback: {_fmt_when(callback['due_at'])}{who}"
                     + (f": {callback['callback_note']}" if callback["callback_note"] else ""))
    sent = [r[0] for r in conn.execute("SELECT DISTINCT label FROM wa_messages WHERE op_id = ? AND status = 'sent'",
                                       (row["id"],))]
    if sent:
        lines.append(f"Sent on WhatsApp: {', '.join(sent)}")
    if row["note"]:
        lines += ["", row["note"]]
    answers = json.loads(row["answers"]) if row["answers"] else {}
    if answers:
        lines += ["", "**Data gathered**"]
        lines += [f"{q['label']}: {_fmt_answer(q, answers[q['key']])}" for q in campaign["questions"]
                  if q["key"] in answers]
    return "\n".join(lines)


def _needs_sync(row) -> bool:
    return not is_test(row) and bool(in_crm(row) or row["person_id"]) and crm.is_configured()


def _sync_logged(op_id: int) -> None:
    try:
        sync_crm(op_id)
    except Exception as exc:  # crm_error still says it wasn't written; the board offers to retry
        print(f"[crm] writing call {op_id} to the CRM failed: {exc!r}", flush=True)


def resume_sync() -> None:
    """Write the finished calls the server stopped before writing to the CRM (see SYNC_IN_BACKGROUND)."""
    conn = db.connect()
    try:
        ids = [r[0] for r in conn.execute("SELECT id FROM op_calls WHERE status = 'done' AND crm_error = ? ORDER BY id",
                                          (PENDING_SYNC,))]
    finally:
        conn.close()
    for op_id in ids:
        _sync_pool.submit(_sync_logged, op_id)


def sync_crm(op_id: int) -> None:
    """Move the opportunity to its new stage, copy answers to the contact's fields, and attach a note with everything.
    Each step that fails is noted in crm_error; running it again skips the note if it was already written."""
    with _sync_lock:
        _sync_crm(op_id)


def _sync_crm(op_id: int) -> None:
    conn = db.connect()
    row = get_row(conn, op_id)
    if is_test(row) or not (in_crm(row) or row["person_id"]):
        return  # nothing in the CRM to write to
    if not crm.is_configured():
        conn.execute("UPDATE op_calls SET crm_error = ? WHERE id = ?", ("The CRM isn't connected", op_id))
        conn.commit()
        return
    names = account_names(conn)
    errors = []
    opportunity_id = row["opportunity_id"] if in_crm(row) else None  # else: a note for the contact only
    if opportunity_id and row["stage_after"] and row["stage_after"] != row["stage_before"]:
        try:
            crm.update_opportunity(row["opportunity_id"], {"stage": row["stage_after"]})
        except crm.CrmError as exc:
            errors.append(f"Stage not changed: {exc}")
    answers = json.loads(row["answers"]) if row["answers"] else {}
    campaign = campaign_of(conn, row)
    person = {q["crm"].split(".", 1)[1]: answers[q["key"]] for q in campaign["questions"]
              if q.get("crm", "").startswith("person.") and q["key"] in answers}
    if person and row["person_id"]:
        try:
            crm.update_person(row["person_id"], person)
        except crm.CrmError as exc:
            errors.append(f"Contact not updated: {exc}")
    note_id = row["crm_note_id"]
    if not note_id:
        outcome = campaigns.outcome(campaign, row["outcome"]).get("label", row["outcome"])
        try:
            note_id = crm.add_note(f"Call · {outcome}", note_markdown(conn, row, names), opportunity_id,
                                   row["person_id"])
        except crm.CrmError as exc:
            errors.append(f"Note not written: {exc}")
    conn.execute("UPDATE op_calls SET crm_note_id = ?, crm_error = ? WHERE id = ?",
                 (note_id, " ".join(errors) or None, op_id))
    conn.commit()
    crm.forget_leads()


# --- What the agent sees about the contact ------------------------------------------------------------

def context(conn, row) -> dict:
    """Everything known about the contact being served: earlier desk calls (and the latest answers, to start the
    form from), the CRM's notes, and our recorded calls with their numbers."""
    names = account_names(conn)
    history = [to_dict(r, names) for r in conn.execute(
        "SELECT * FROM op_calls WHERE opportunity_id = ? AND status = 'done' AND id != ? ORDER BY finished_at DESC",
        (row["opportunity_id"], row["id"]))]
    previous_answers = next((h["answers"] for h in history if h["answers"]), {})
    callback_from = None
    if row["scheduled_from"]:
        found = conn.execute("SELECT * FROM op_calls WHERE id = ?", (row["scheduled_from"],)).fetchone()
        callback_from = to_dict(found, names) if found else None

    lead = json.loads(row["lead"]) if row["lead"] else {}
    keys = {crm.match_key(p) for p in (lead.get("contact") or {}).get("phones", [])} - {None}
    recorded = []
    for key in keys:
        for r in conn.execute("SELECT id, date_call, duration, agent, type, analysis FROM calls WHERE customer LIKE ? "
                              "ORDER BY date_call DESC LIMIT 10", (f"%{key}",)):
            analysis = json.loads(r["analysis"]) if r["analysis"] else {}
            recorded.append({"id": r["id"], "date_call": r["date_call"], "duration": r["duration"],
                             "agent": r["agent"], "type": r["type"], "summary": analysis.get("summary"),
                             "outcome": analysis.get("outcome") or analysis.get("resolution_status")})
    recorded.sort(key=lambda c: c["date_call"] or "", reverse=True)

    notes, notes_error = [], None
    if not is_test(row) and (in_crm(row) or row["person_id"]):
        try:
            notes = crm.notes(row["opportunity_id"] if in_crm(row) else None, row["person_id"])
        except crm.CrmError as exc:
            notes_error = str(exc)

    # A call that came in (or calls back one we missed): when it rang, and the CRM's contacts with the number, to
    # link the call to the right one.
    from . import inbound
    rang = inbound.of_op(conn, row)
    people, people_error = None, None
    if row["source"] in ("inbound", "missed") and crm.is_configured():
        number = row["phone"] or next(iter((lead.get("contact") or {}).get("phones") or []), "")
        if crm.match_key(number):
            try:
                people = crm.lookup(number)["people"]
            except crm.CrmError as exc:
                people_error = str(exc)

    # The campaign's rules for an unanswered call: is this the last try, and when to try again.
    campaign = campaign_of(conn, row)
    tries = attempts(conn, row)
    last_try = bool(campaign["max_attempts"]) and tries + 1 >= campaign["max_attempts"]
    retry_at = None
    if campaign["retry_minutes"] and not last_try:
        retry_at = campaigns.next_open(campaign, datetime.now() + timedelta(minutes=campaign["retry_minutes"]))
        retry_at = retry_at.replace(second=0, microsecond=0).isoformat(timespec="seconds")
    return {"history": history, "previous_answers": previous_answers, "callback_from": callback_from,
            "recorded_calls": recorded[:10], "notes": notes, "notes_error": notes_error,
            "attempts": tries, "max_attempts": campaign["max_attempts"], "last_try": last_try, "retry_at": retry_at,
            "inbound": rang, "crm_people": people, "crm_people_error": people_error}


def today(conn, username: str) -> dict:
    start = datetime.now().strftime("%Y-%m-%dT00:00:00")
    rows = conn.execute("SELECT outcome, campaign_id, call_started_at, call_ended_at FROM op_calls "
                        "WHERE agent = ? AND status = 'done' AND finished_at >= ? AND opportunity_id NOT LIKE ?",
                        (username, start, f"{TEST_PREFIX}%")).fetchall()
    talk = 0
    for r in rows:
        try:
            talk += int((datetime.fromisoformat(r["call_ended_at"]) -
                         datetime.fromisoformat(r["call_started_at"])).total_seconds())
        except (TypeError, ValueError):
            pass
    lookup = outcome_lookup(conn)
    found = [lookup(r["campaign_id"], r["outcome"]) for r in rows]
    day = start[:10]
    desk = conn.execute("SELECT ready_seconds FROM op_presence WHERE username = ? AND day = ?",
                        (username, day)).fetchone()
    tomorrow = (datetime.fromisoformat(start) + timedelta(days=1)).date().isoformat()
    paused = floor.pause_totals(conn, day, tomorrow, username).get(username, {})
    return {"done": len(rows), "reached": sum(bool(o.get("reached")) for o in found),
            "success": sum(bool(o.get("success")) for o in found), "talk_seconds": talk,
            "desk_seconds": desk[0] if desk else 0, "pause_seconds": paused.get("pause_seconds", 0),
            "pauses": paused.get("pauses", 0)}


def goals(conn, username: str, done: dict) -> dict:
    """The agent's targets for today and how far along they are (see floor.progress)."""
    day_pace = floor.pace(conn)
    return {"pace": day_pace, "workday": floor.workday(conn),
            "progress": floor.progress(done, floor.resolved(conn, username), day_pace)}


def my_callbacks(conn, username: str) -> list[dict]:
    names = account_names(conn)
    return [to_dict(r, names) for r in conn.execute(
        "SELECT * FROM op_calls WHERE status = 'scheduled' AND (assign_to = ? OR scheduled_by = ?) "
        "ORDER BY due_at LIMIT 50", (username, username))]


def board(conn) -> dict:
    """The team view: who is on the desk and doing what, the queue, callbacks and the latest results."""
    names = account_names(conn)
    now = datetime.now()
    online_after = (now - timedelta(seconds=OFFLINE_SECONDS)).isoformat(timespec="seconds")
    start = now.strftime("%Y-%m-%dT00:00:00")
    real = f"opportunity_id NOT LIKE '{TEST_PREFIX}%'"
    lookup = outcome_lookup(conn)
    done_today: dict[str, dict] = {}
    for r in conn.execute(f"SELECT agent, outcome, campaign_id FROM op_calls WHERE status = 'done' AND finished_at >= ? "
                          f"AND {real}", (start,)):
        o = lookup(r["campaign_id"], r["outcome"])
        d = done_today.setdefault(r["agent"], {"done": 0, "reached": 0, "success": 0})
        d["done"] += 1
        d["reached"] += bool(o.get("reached"))
        d["success"] += bool(o.get("success"))
    day = start[:10]
    tomorrow = (now + timedelta(days=1)).date().isoformat()
    desk_today = dict(conn.execute("SELECT username, ready_seconds FROM op_presence WHERE day = ?", (day,)).fetchall())
    pauses_today = floor.pause_totals(conn, day, tomorrow)
    table = floor.targets(conn)
    day_pace = floor.pace(conn, now)
    team_done = {"done": 0, "reached": 0, "success": 0, "desk_seconds": 0}
    team_goal = {m: 0 for m in floor.METRICS}
    holding = {r["agent"]: to_dict(r, names) for r in
               conn.execute("SELECT * FROM op_calls WHERE status IN ('assigned', 'in_call')")}
    campaign_names = {c["id"]: c["name"] for c in campaigns.all_campaigns(conn)}
    default = campaigns.default_id(conn)
    agents = []
    for a in conn.execute("SELECT * FROM op_agents ORDER BY username"):
        online = (a["last_seen"] or "") >= online_after
        op = holding.get(a["username"])
        clocked_in = bool(a["shift_id"])
        state = ("on_call" if op and op["status"] == "in_call" and not op["call_ended_at"] else
                 "wrap_up" if op and op["call_ended_at"] else
                 "serving" if op else
                 "offline" if not online else
                 "ready" if a["ready"] else "paused" if clocked_in else "clocked_out")
        user = a["username"]
        today_done = {**done_today.get(user, {"done": 0, "reached": 0, "success": 0}),
                      "desk_seconds": desk_today.get(user, 0),
                      "pause_seconds": pauses_today.get(user, {}).get("pause_seconds", 0)}
        goal = floor.resolved(conn, user, table)
        # The team's target counts the agents who came to the desk today.
        if (a["last_seen"] or "") >= start:
            for m in floor.METRICS:
                team_goal[m] += goal[m]
            for k in team_done:
                team_done[k] += today_done[k]
        state_since = (op["call_ended_at"] if state == "wrap_up" else
                       op["call_started_at"] if state == "on_call" else
                       op["assigned_at"] if state == "serving" else
                       a["last_seen"] if state == "offline" else a["since"])
        agents.append({"username": user, "name": names.get(user, user),
                       "state": state, "ready": bool(a["ready"]), "online": online, "since": a["since"],
                       "state_since": state_since, "last_seen": a["last_seen"], "current": op,
                       "done_today": today_done["done"], "today": today_done,
                       "pause": floor.pause_state(conn, user, now.replace(microsecond=0)) if not a["ready"] else None,
                       "shift": floor.shift_state(conn, user, now.replace(microsecond=0)),
                       "progress": floor.progress(today_done, goal, day_pace),
                       "campaign": campaign_names.get(a["campaign_id"] or default)})
    callbacks = [to_dict(r, names) for r in conn.execute(
        "SELECT * FROM op_calls WHERE status = 'scheduled' ORDER BY due_at LIMIT 100")]
    recent = [to_dict(r, names) for r in conn.execute(
        "SELECT * FROM op_calls WHERE status = 'done' ORDER BY finished_at DESC LIMIT 50")]
    outcomes = dict(conn.execute(f"SELECT outcome, COUNT(*) FROM op_calls WHERE status = 'done' AND finished_at >= ? "
                                 f"AND {real} GROUP BY outcome", (start,)).fetchall())
    queues = [queue_counts(conn, c)
              for c in campaigns.all_campaigns(conn, active_only=True, kind=campaigns.OUTBOUND)]
    waiting = [q["waiting"] for q in queues if q["waiting"] is not None]
    no_phone = [q["no_phone"] for q in queues if q["no_phone"] is not None]
    total = {"due_callbacks": sum(q["due_callbacks"] for q in queues),
             "scheduled": sum(q["scheduled"] for q in queues),
             "waiting": sum(waiting) if waiting else None, "no_phone": sum(no_phone) if no_phone else None,
             "error": next((q["error"] for q in queues if q["error"]), None),
             "truncated": any(q["truncated"] for q in queues)}
    return {"agents": agents, "queue": total, "queues": queues, "callbacks": callbacks, "recent": recent,
            "outcomes_today": outcomes, "pace": day_pace, "workday": floor.workday(conn),
            "team_progress": floor.progress(team_done, team_goal, day_pace)}

