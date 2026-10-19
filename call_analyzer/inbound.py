"""Incoming calls: what the desk does when a customer calls an agent's browser softphone.

While it rings (ring), the caller is looked up: who they are in the CRM and what the desk did with them last, so the
agent picks up knowing. Answering (answer) opens a desk call for them (source 'inbound', in the incoming calls
campaign, see campaigns.py) that goes like one served from the queue: the agent fills in the questions and closes it
with an outcome, the contact's next stage and maybe a callback. A caller who isn't in the CRM gets a desk call of
their own (opportunity id "inbound:<number>", see operations.LOCAL_PREFIX), which the agent can link to the CRM during
the call (operations.link).

A call nobody answered (missed, declined, or turned away because the agent was on another call) waits on the missed
calls list, one entry per number, until:
- someone calls the number back from the desk: the desk serves missed calls before anything else (source 'missed'),
  first to the agent who knows the contact, to anyone once MISSED_EXCLUSIVE_MINUTES have passed or when that agent
  isn't taking calls;
- the caller gets through to an agent;
- or someone dismisses it (spam, dealt with elsewhere).

When a call rings several agents (a ring group, at once or one after the other), the ones who didn't pick up don't leave
a missed call: a ring is the same call as the rings of the same number less than RING_GROUP_SECONDS before it.
"""
import json
from datetime import datetime, timedelta

from . import campaigns, crm, db, operations
from .operations import OperationError

RING_GROUP_SECONDS = 30
# A missed call is served this long after it rang at the earliest, so a ring group's answer has landed by then.
MISSED_GRACE_SECONDS = 20
# For this long, a missed call is only served to the agent who knows the contact (when they're taking calls).
MISSED_EXCLUSIVE_MINUTES = 5
# A ring the browser never said the end of (closed tab, lost connection) counts as missed after this long.
STUCK_RINGING_MINUTES = 2
MISSED = ("missed", "declined", "busy")


def _now() -> datetime:
    return datetime.now().replace(microsecond=0)


def _iso(when: datetime) -> str:
    return when.isoformat(timespec="seconds")


def _at(value: str | None) -> datetime | None:
    try:
        return datetime.fromisoformat(value)
    except (TypeError, ValueError):
        return None


def _clean_number(number: str) -> str:
    return " ".join(str(number or "").split())[:40]


def _own(conn, inbound_id: int, username: str):
    row = conn.execute("SELECT * FROM op_inbound WHERE id = ?", (inbound_id,)).fetchone()
    if not row or row["agent"] != username:
        raise OperationError("This call isn't on your phone", 404)
    return row


# --- Who is calling -----------------------------------------------------------------------------------

def _people(number: str) -> tuple[list[dict], str | None]:
    """The CRM's contacts with this number, and why they couldn't be looked up (None when they were)."""
    if not crm.match_key(number) or not crm.is_configured():
        return [], None
    try:
        return crm.lookup(number)["people"], None
    except crm.CrmError as exc:
        return [], str(exc)


def _desk_rows(conn, key: str, opportunity_ids: list[str]):
    """The desk's calls with this number or these opportunities, latest first (test calls left out)."""
    marks = ",".join("?" * len(opportunity_ids))
    by_opportunity = f" OR opportunity_id IN ({marks})" if opportunity_ids else ""
    return conn.execute(f"""SELECT * FROM op_calls WHERE opportunity_id NOT LIKE ?
                              AND (number_key(phone) = ?{by_opportunity})
                            ORDER BY COALESCE(finished_at, created_at) DESC, id DESC""",
                        (f"{operations.TEST_PREFIX}%", key, *opportunity_ids)).fetchall()


def _knows(conn, rows) -> str | None:
    """The agent who last spoke with the contact on the desk."""
    lookup = operations.outcome_lookup(conn)
    return next((r["agent"] for r in rows if r["status"] == "done" and r["agent"]
                 and lookup(r["campaign_id"], r["outcome"]).get("reached")), None)


def caller(conn, number: str, people: list[dict] | None = None, crm_error: str | None = None) -> dict:
    """What the agent sees while it rings: the CRM's contacts with the number and their opportunities, the desk's last
    call with them, a callback waiting, the agent who knows them, and their missed calls not dealt with yet."""
    if people is None:
        people, crm_error = _people(number)
    key = db.number_key(number)
    names = operations.account_names(conn)
    rows = _desk_rows(conn, key, [o["id"] for p in people for o in p.get("opportunities", [])])
    last = next((r for r in rows if r["status"] == "done"), None)
    last_call = None
    if last:
        outcome = campaigns.outcome(operations.campaign_of(conn, last), last["outcome"])
        last_call = {"id": last["id"], "outcome": last["outcome"], "outcome_label": outcome.get("label") or last["outcome"],
                     "reached": bool(outcome.get("reached")), "agent_name": names.get(last["agent"], last["agent"]),
                     "finished_at": last["finished_at"], "note": last["note"], "source": last["source"]}
    callback = next((r for r in rows if r["status"] == "scheduled"), None)
    knows = _knows(conn, rows)
    missed = conn.execute(f"SELECT COUNT(*) FROM op_inbound WHERE number_key = ? AND resolved_at IS NULL "
                          f"AND result IN ({','.join('?' * len(MISSED))})", (key, *MISSED)).fetchone()[0]
    return {"number": number, "people": [{k: p.get(k) for k in ("id", "name", "city", "company", "url", "phones")}
                                         | {"opportunities": [{k: o.get(k) for k in ("id", "name", "stage", "owner")}
                                                              for o in p.get("opportunities", [])]}
                                         for p in people],
            "crm_error": crm_error, "last_call": last_call,
            "callback": {"due_at": callback["due_at"], "assign_to_name": names.get(callback["assign_to"])
                         if callback["assign_to"] else None} if callback else None,
            "knows": {"username": knows, "name": names.get(knows, knows)} if knows else None, "missed": missed}


def _local_lead(number: str, contact: dict | None, caller_name: str | None) -> dict:
    """A desk-only lead for a caller with no opportunity in the CRM (operations.LOCAL_PREFIX)."""
    contact = dict(contact) if contact else {
        "id": None, "name": caller_name or None, "email": None, "phones": [number], "job_title": None, "city": None,
        "company": None, "created_at": None, "last_contact_at": None, "url": None}
    contact.pop("opportunities", None)
    return {"id": f"{operations.LOCAL_PREFIX}{db.number_key(number)}",
            "name": "",
            "stage": None, "amount": None, "currency": None, "close_date": None, "company": None, "owner": None,
            "created_at": None, "updated_at": None, "url": None, "contact": contact}


def lead_for(number: str, caller_name: str | None = None, people: list[dict] | None = None) -> dict:
    """The lead a call with this number is about: the contact's latest opportunity in the CRM, else a desk-only lead
    (with the CRM contact when there's one)."""
    if people is None:
        people, _ = _people(number)
    person = people[0] if people else None
    if person and person.get("opportunities"):
        opportunity = max(person["opportunities"], key=lambda o: o.get("updated_at") or o.get("created_at") or "")
        contact = {k: v for k, v in person.items() if k != "opportunities"}
        return {**opportunity, "contact": contact}
    return _local_lead(number, person, caller_name)


# --- The phone rings ------------------------------------------------------------------------------

def ring(username: str, number: str, caller_name: str = "") -> dict:
    """A call rings the agent's softphone: log it, and say who's calling."""
    number = _clean_number(number)
    if not number:
        raise OperationError("No caller number")
    conn = db.connect()
    cur = conn.execute("""INSERT INTO op_inbound (agent, number, number_key, caller_name, rang_at, result)
                          VALUES (?, ?, ?, ?, ?, 'ringing')""",
                       (username, number, db.number_key(number), caller_name.strip()[:100] or None, _iso(_now())))
    conn.commit()
    return {"id": cur.lastrowid, "caller": caller(conn, number)}


def busy(username: str, number: str, caller_name: str = "") -> dict:
    """A call was turned away because the agent was already on one: it's a missed call."""
    number = _clean_number(number)
    if not number:
        raise OperationError("No caller number")
    conn = db.connect()
    now = _iso(_now())
    cur = conn.execute("""INSERT INTO op_inbound (agent, number, number_key, caller_name, rang_at, ended_at, result)
                          VALUES (?, ?, ?, ?, ?, ?, 'busy')""",
                       (username, number, db.number_key(number), caller_name.strip()[:100] or None, now, now))
    conn.commit()
    return {"id": cur.lastrowid}


def answer(username: str, inbound_id: int) -> dict:
    """The agent picked up: open the desk call for the caller (the contact they were served but hadn't called yet goes
    back to the queue). Returns the op_call."""
    conn = db.connect()
    row = _own(conn, inbound_id, username)
    names = operations.account_names(conn)
    if row["op_id"]:
        return operations.to_dict(operations.get_row(conn, row["op_id"]), names)
    people, _ = _people(row["number"])
    lead = lead_for(row["number"], row["caller_name"], people)
    now = _iso(_now())
    with operations._claim_lock:
        conn = db.connect()
        if (mine := operations.current(conn, username)) and mine["status"] == "assigned":
            operations.release(conn, mine["id"])
        held = conn.execute("SELECT * FROM op_calls WHERE opportunity_id = ? AND status IN ('assigned', 'in_call')",
                            (lead["id"],)).fetchone()
        if held and held["status"] == "assigned":
            operations.release(conn, held["id"])  # served to someone who hasn't called yet: the caller is here now
        elif held:
            # Someone is still closing a call with them: this one stays on the desk only.
            lead = _local_lead(row["number"], lead.get("contact"), row["caller_name"])
            lead["id"] = f"{lead['id']}:{inbound_id}"
        cur = conn.execute("""INSERT INTO op_calls (opportunity_id, person_id, lead, source, status, agent, assigned_at,
                                                    call_started_at, phone, stage_before, campaign_id, created_at)
                              VALUES (?, ?, ?, 'inbound', 'in_call', ?, ?, ?, ?, ?, ?, ?)""",
                           (lead["id"], (lead.get("contact") or {}).get("id"), json.dumps(lead, ensure_ascii=False),
                            username, now, now, row["number"], lead.get("stage"), campaigns.inbound_id(conn), now))
        conn.execute("UPDATE op_inbound SET result = 'answered', answered_at = ?, op_id = ? WHERE id = ?",
                     (now, cur.lastrowid, inbound_id))
        conn.commit()
        return operations.to_dict(operations.get_row(conn, cur.lastrowid), names)


def end(username: str, inbound_id: int, *, answered: bool, declined: bool = False, elsewhere: bool = False) -> None:
    """The call is over. Answered: the desk call moves on to closing it. Not answered: a missed call (declined: the
    agent turned it down; elsewhere: another phone picked it up, so not missed)."""
    conn = db.connect()
    row = _own(conn, inbound_id, username)
    now = _iso(_now())
    if row["result"] == "answered" or answered:
        conn.execute("UPDATE op_inbound SET result = 'answered', answered_at = COALESCE(answered_at, ?), "
                     "ended_at = COALESCE(ended_at, ?) WHERE id = ?", (now, now, inbound_id))
        if row["op_id"]:
            conn.execute("UPDATE op_calls SET call_ended_at = COALESCE(call_ended_at, ?) WHERE id = ? "
                         "AND status = 'in_call'", (now, row["op_id"]))
    elif row["result"] == "ringing":
        result = "elsewhere" if elsewhere else "declined" if declined else "missed"
        conn.execute("UPDATE op_inbound SET result = ?, ended_at = ? WHERE id = ?", (result, now, inbound_id))
    conn.commit()


# --- Missed calls ---------------------------------------------------------------------------------

def refresh(conn, now: datetime | None = None) -> None:
    """Settle the missed calls: rings never ended become missed, and missed calls are dealt with once the number was
    called from the desk since, or the caller got through to an agent."""
    now = now or _now()
    stuck = _iso(now - timedelta(minutes=STUCK_RINGING_MINUTES))
    conn.execute("UPDATE op_inbound SET result = 'missed', ended_at = rang_at WHERE result = 'ringing' AND rang_at < ?",
                 (stuck,))
    open_rows = conn.execute(f"SELECT * FROM op_inbound WHERE resolved_at IS NULL AND result IN "
                             f"({','.join('?' * len(MISSED))}) ORDER BY rang_at", MISSED).fetchall()
    for key in {r["number_key"] for r in open_rows}:
        rows = [r for r in open_rows if r["number_key"] == key]
        first = min(_at(r["rang_at"]) or now for r in rows)
        since = _iso(first - timedelta(seconds=RING_GROUP_SECONDS))
        answered = conn.execute("SELECT agent, rang_at, answered_at FROM op_inbound WHERE number_key = ? "
                                "AND result IN ('answered', 'elsewhere') AND rang_at >= ? ORDER BY rang_at",
                                (key, since)).fetchall()
        called = conn.execute("SELECT id, agent, call_started_at FROM op_calls WHERE number_key(phone) = ? "
                              "AND call_started_at >= ? AND source != 'inbound' AND opportunity_id NOT LIKE ? "
                              "ORDER BY call_started_at", (key, rows[0]["rang_at"],
                                                          f"{operations.TEST_PREFIX}%")).fetchall()
        for r in rows:
            rang = _at(r["rang_at"]) or now
            lower = _iso(rang - timedelta(seconds=RING_GROUP_SECONDS))
            got = next((a for a in answered if a["rang_at"] >= lower), None)
            back = next((c for c in called if c["call_started_at"] >= r["rang_at"]), None)
            if got and (not back or (got["answered_at"] or got["rang_at"]) <= back["call_started_at"]):
                conn.execute("UPDATE op_inbound SET resolved_at = ?, resolved_by = ?, resolution = 'got_through' "
                             "WHERE id = ?", (got["answered_at"] or got["rang_at"], got["agent"], r["id"]))
            elif back:
                conn.execute("UPDATE op_inbound SET resolved_at = ?, resolved_by = ?, resolution = 'called_back', "
                             "followup_op_id = ? WHERE id = ?",
                             (back["call_started_at"], back["agent"], back["id"], r["id"]))
    conn.commit()


def _available(conn, username: str, now: datetime) -> bool:
    """Whether the agent is taking calls on the desk right now."""
    row = conn.execute("SELECT ready, last_seen FROM op_agents WHERE username = ?", (username,)).fetchone()
    online_after = _iso(now - timedelta(seconds=operations.OFFLINE_SECONDS))
    return bool(row and row["ready"] and (row["last_seen"] or "") >= online_after)


def missed(conn, now: datetime | None = None) -> list[dict]:
    """The missed calls waiting to be dealt with, one per number, the longest waiting first: when it first and last
    rang, how many times, whose phones rang, the agent it goes to first (`prefer`: who knows the contact, else whose
    phone rang last), who is calling back right now (`serving`), and who gave it back lately (`given_back_by`: it isn't
    served to them again for operations.SKIP_MINUTES, like a contact of the queue)."""
    now = now or _now()
    refresh(conn, now)
    names = operations.account_names(conn)
    rows = conn.execute(f"SELECT * FROM op_inbound WHERE resolved_at IS NULL AND result IN "
                        f"({','.join('?' * len(MISSED))}) ORDER BY rang_at, id", MISSED).fetchall()
    groups: dict[str, list] = {}
    for r in rows:
        groups.setdefault(r["number_key"], []).append(r)
    found = []
    for key, items in groups.items():
        last = items[-1]
        desk = _desk_rows(conn, key, [])
        knows = _knows(conn, desk)
        prefer = knows or last["agent"]
        serving = None
        follow = {r["followup_op_id"] for r in items if r["followup_op_id"]}
        if follow:
            op = conn.execute(f"SELECT * FROM op_calls WHERE id IN ({','.join('?' * len(follow))}) "
                              f"AND status IN ('assigned', 'in_call') LIMIT 1", tuple(follow)).fetchone()
            if op:
                serving = {"op_id": op["id"], "agent": op["agent"], "agent_name": names.get(op["agent"], op["agent"])}
        lead = next((json.loads(d["lead"]) for d in desk if d["lead"]), None) or {}
        contact_name = (lead.get("contact") or {}).get("name") or next(
            (r["caller_name"] for r in reversed(items) if r["caller_name"]), None)
        first = _at(items[0]["rang_at"]) or now
        skip_after = _iso(now - timedelta(minutes=operations.SKIP_MINUTES))
        given_back = sorted({r[0] for r in conn.execute(
            "SELECT agent FROM op_calls WHERE source = 'missed' AND status = 'released' AND number_key(phone) = ? "
            "AND finished_at >= ?", (key, skip_after))})
        found.append({"key": key, "number": last["number"], "contact_name": contact_name,
                      "first_rang_at": items[0]["rang_at"], "last_rang_at": last["rang_at"], "tries": len(items),
                      "waiting_minutes": int((now - first).total_seconds() // 60),
                      "agents": sorted({names.get(r["agent"], r["agent"]) for r in items}),
                      "busy": any(r["result"] == "busy" for r in items),
                      "prefer": prefer, "prefer_name": names.get(prefer, prefer), "knows": bool(knows),
                      "serving": serving, "given_back_by": given_back})
    return found


def _servable(conn, entry: dict, username: str, now: datetime) -> bool:
    if entry["serving"] or username in entry["given_back_by"]:
        return False
    if (_at(entry["last_rang_at"]) or now) > now - timedelta(seconds=MISSED_GRACE_SECONDS):
        return False
    if entry["prefer"] == username:
        return True
    exclusive = (_at(entry["first_rang_at"]) or now) > now - timedelta(minutes=MISSED_EXCLUSIVE_MINUTES)
    held_for_them = entry["prefer"] not in entry["given_back_by"] and _available(conn, entry["prefer"], now)
    return not (exclusive and held_for_them)


def _serve(conn, username: str, entry: dict) -> dict | None:
    """Serve the agent the callback of a missed call (inside operations._claim_lock). None when the contact is
    being called by someone else."""
    names = operations.account_names(conn)
    lead = lead_for(entry["number"], entry["contact_name"])
    if conn.execute("SELECT 1 FROM op_calls WHERE opportunity_id = ? AND status IN ('assigned', 'in_call')",
                    (lead["id"],)).fetchone():
        return None
    now = _iso(_now())
    cur = conn.execute("""INSERT INTO op_calls (opportunity_id, person_id, lead, source, status, agent, assigned_at,
                                                phone, stage_before, campaign_id, created_at)
                          VALUES (?, ?, ?, 'missed', 'assigned', ?, ?, ?, ?, ?, ?)""",
                       (lead["id"], (lead.get("contact") or {}).get("id"), json.dumps(lead, ensure_ascii=False),
                        username, now, entry["number"], lead.get("stage"), campaigns.inbound_id(conn), now))
    conn.execute(f"UPDATE op_inbound SET followup_op_id = ? WHERE number_key = ? AND resolved_at IS NULL "
                 f"AND result IN ({','.join('?' * len(MISSED))})", (cur.lastrowid, entry["key"], *MISSED))
    conn.commit()
    return operations.to_dict(operations.get_row(conn, cur.lastrowid), names)


def claim(conn, username: str) -> dict | None:
    """The missed call to serve the agent next, if any (called by operations.claim_next, inside its lock)."""
    now = _now()
    for entry in missed(conn, now):
        if _servable(conn, entry, username, now) and (op := _serve(conn, username, entry)):
            return op
    return None


def take(username: str, key: str) -> dict:
    """The agent calls this missed call back now (from the list), whoever it would go to first."""
    with operations._claim_lock:
        conn = db.connect()
        entry = next((e for e in missed(conn) if e["key"] == key), None)
        if not entry:
            raise OperationError("This missed call was already dealt with", 404)
        if entry["serving"] and entry["serving"]["agent"] != username:
            raise OperationError(f"{entry['serving']['agent_name']} is already calling them back", 409)
        if mine := operations.current(conn, username):
            if entry["serving"] and mine["id"] == entry["serving"]["op_id"]:
                return operations.to_dict(mine, operations.account_names(conn))
            if mine["status"] != "assigned":
                raise OperationError("Close the call you're on before starting another one", 409)
            operations.release(conn, mine["id"])
        op = _serve(conn, username, entry)
        if not op:
            raise OperationError("Someone is already calling this contact", 409)
        return op


def dismiss(username: str, key: str) -> None:
    """Nobody needs to call this number back (spam, dealt with elsewhere)."""
    conn = db.connect()
    cur = conn.execute(f"UPDATE op_inbound SET resolved_at = ?, resolved_by = ?, resolution = 'dismissed' "
                       f"WHERE number_key = ? AND resolved_at IS NULL AND result IN ({','.join('?' * len(MISSED))})",
                       (_iso(_now()), username, key, *MISSED))
    conn.commit()
    if not cur.rowcount:
        raise OperationError("This missed call was already dealt with", 404)


def of_op(conn, row) -> dict | None:
    """For a desk call opened by an incoming call, or calling back a missed one: when it rang, and how many times."""
    if row["source"] == "inbound":
        found = conn.execute("SELECT * FROM op_inbound WHERE op_id = ?", (row["id"],)).fetchone()
        return {"rang_at": found["rang_at"], "answered_at": found["answered_at"], "tries": 1} if found else None
    if row["source"] == "missed":
        found = conn.execute("SELECT rang_at FROM op_inbound WHERE followup_op_id = ? ORDER BY rang_at",
                             (row["id"],)).fetchall()
        return {"rang_at": found[0]["rang_at"], "answered_at": None, "tries": len(found)} if found else None
    return None


# --- Figures --------------------------------------------------------------------------------------

def _calls(rows) -> list[list]:
    """The rings grouped into calls: a ring less than RING_GROUP_SECONDS after the last one of the same number is the
    same call (a ring group rings several agents)."""
    calls, latest = [], {}  # number key -> (when it last rang, its call)
    for r in sorted(rows, key=lambda r: (r["rang_at"], r["id"])):
        rang = _at(r["rang_at"]) or datetime.min
        before = latest.get(r["number_key"])
        if before and (rang - before[0]).total_seconds() <= RING_GROUP_SECONDS:
            group = before[1]
            group.append(r)
        else:
            group = [r]
            calls.append(group)
        latest[r["number_key"]] = (rang, group)
    return calls


def stats(conn, since: str, until: str, username: str | None = None) -> dict:
    """Incoming calls between two days (`until` exclusive), for the KPIs: per agent, the calls that rang them,
    answered and missed; for the team, the calls (a ring group's rings count once), how many were answered, and of
    the missed ones how many were called back, how fast, how many got through by calling again, were dismissed, or
    are still waiting."""
    refresh(conn)
    names = operations.account_names(conn)
    sql = "SELECT * FROM op_inbound WHERE rang_at >= ? AND rang_at < ? AND result != 'ringing'"
    args: list = [since, until]
    if username:
        sql += " AND agent = ?"
        args.append(username)
    rows = conn.execute(sql, args).fetchall()
    agents: dict[str, dict] = {}
    for r in rows:
        a = agents.setdefault(r["agent"], {"rang": 0, "answered": 0, "missed": 0, "called_back": 0})
        a["rang"] += 1
        a["answered"] += r["result"] == "answered"
        a["missed"] += r["result"] in MISSED
    back_sql = ("SELECT agent, COUNT(*) FROM op_calls WHERE source = 'missed' AND call_started_at >= ? "
                "AND call_started_at < ?" + (" AND agent = ?" if username else "") + " GROUP BY agent")
    for user, n in conn.execute(back_sql, args):
        agents.setdefault(user, {"rang": 0, "answered": 0, "missed": 0, "called_back": 0})["called_back"] = n

    team = {"calls": 0, "answered": 0, "missed": 0, "called_back": 0, "got_through": 0, "dismissed": 0, "waiting": 0}
    waits = []
    for group in _calls(rows):
        team["calls"] += 1
        if any(r["result"] in ("answered", "elsewhere") for r in group):
            team["answered"] += 1
            continue
        team["missed"] += 1
        resolved = [r for r in group if r["resolved_at"]]
        if not resolved:
            team["waiting"] += 1
            continue
        first = min(resolved, key=lambda r: r["resolved_at"])
        team[{"called_back": "called_back", "got_through": "got_through"}.get(first["resolution"], "dismissed")] += 1
        if first["resolution"] == "called_back":
            rang, back = _at(group[0]["rang_at"]), _at(first["resolved_at"])
            if rang and back:
                waits.append(max(0, (back - rang).total_seconds()))
    waits.sort()
    team.update(
        answer_rate=round(team["answered"] / team["calls"], 4) if team["calls"] else None,
        callback_rate=round((team["called_back"] + team["got_through"]) / team["missed"], 4) if team["missed"] else None,
        avg_callback_minutes=round(sum(waits) / len(waits) / 60, 1) if waits else None,
        median_callback_minutes=round(waits[len(waits) // 2] / 60, 1) if waits else None,
        called_back_15min=sum(w <= 15 * 60 for w in waits))
    listed = [{"username": u, "name": names.get(u, u), **a,
               "answer_rate": round(a["answered"] / a["rang"], 4) if a["rang"] else None}
              for u, a in agents.items()]
    listed.sort(key=lambda a: (-a["rang"], a["name"]))
    return {"team": team, "agents": listed}
