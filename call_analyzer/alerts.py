"""Real-time alerts for the team board: what a supervisor should look at right now on the call desk.

Worked out afresh from the desk's tables each time the board asks (nothing is stored), so an alert goes away as soon
as what caused it is over. Each rule has a setting (Settings > Call desk); 0 turns it off:

- an agent idle for ALERT_IDLE_MINUTES: taking calls but no call since, served a contact they haven't dialed, or still
  closing a call that ended;
- a call longer than ALERT_LONG_CALL_MINUTES;
- ALERT_NO_ANSWER_STREAK unanswered calls in a row for an agent today (calls where the contact wasn't reached);
- a sudden drop in contact rate: in the last ALERT_CONTACT_RATE_WINDOW_MINUTES a campaign reached its contacts
  ALERT_CONTACT_RATE_DROP_PERCENT less often than over the 7 days before (with ALERT_CONTACT_RATE_MIN_CALLS calls at
  least in the window, and three times that in the 7 days, so a handful of calls doesn't raise it);
- a callback still waiting ALERT_CALLBACK_OVERDUE_MINUTES after it came due;
- a missed incoming call nobody called back within ALERT_MISSED_CALL_MINUTES (see inbound.py).

An alert is a warning, and critical once it is twice past its threshold (or the rate fell twice as far). Test calls
don't count.
"""
from datetime import datetime, timedelta

from . import campaigns, inbound, operations
from .config import live

DEFAULTS = {"ALERT_IDLE_MINUTES": 10, "ALERT_LONG_CALL_MINUTES": 20, "ALERT_NO_ANSWER_STREAK": 5,
            "ALERT_CONTACT_RATE_WINDOW_MINUTES": 60, "ALERT_CONTACT_RATE_MIN_CALLS": 10,
            "ALERT_CONTACT_RATE_DROP_PERCENT": 40, "ALERT_CALLBACK_OVERDUE_MINUTES": 15,
            "ALERT_MISSED_CALL_MINUTES": 10}
BASELINE_DAYS = 7
# More overdue callbacks than this make one alert for all of them.
CALLBACKS_ONE_BY_ONE = 3
REAL = f"opportunity_id NOT LIKE '{operations.TEST_PREFIX}%'"


def thresholds() -> dict[str, float]:
    """The rules' settings as saved right now (a bad or negative value: the default; 0: the rule is off)."""
    found = {}
    for key, default in DEFAULTS.items():
        try:
            value = float(live(key, str(default)))
        except ValueError:
            value = default
        found[key] = value if value >= 0 else default
    return found


def _at(value: str | None) -> datetime | None:
    try:
        return datetime.fromisoformat(value)
    except (TypeError, ValueError):
        return None


def _minutes(since: datetime, now: datetime) -> int:
    return int((now - since).total_seconds() // 60)


def _hm(when: datetime) -> str:
    return when.strftime("%H:%M")


def _level(value: float, threshold: float) -> str:
    return "critical" if value >= 2 * threshold else "warning"


def _contact(op) -> str:
    lead = operations.to_dict(op)["lead"] or {}
    return (lead.get("contact") or {}).get("name") or lead.get("name") or "the contact"


def _alert(kind: str, key: str, level: str, title: str, detail: str, since: datetime, **extra) -> dict:
    """`id` stays the same while the cause lasts (`key` says what it is), so the board can tell new alerts apart."""
    return {"id": f"{kind}:{key}", "kind": kind, "level": level, "title": title,
            "detail": detail, "since": since.isoformat(), "agent": None, "agent_name": None, "op_id": None, **extra}


def _agent_alerts(conn, names: dict[str, str], limits: dict, now: datetime) -> list[dict]:
    """Idle agents and long calls."""
    idle, long_call = limits["ALERT_IDLE_MINUTES"], limits["ALERT_LONG_CALL_MINUTES"]
    online_after = (now - timedelta(seconds=operations.OFFLINE_SECONDS)).isoformat(timespec="seconds")
    holding = {r["agent"]: r for r in conn.execute(
        "SELECT * FROM op_calls WHERE status IN ('assigned', 'in_call') ORDER BY id DESC")}
    last_done = dict(conn.execute("SELECT agent, MAX(finished_at) FROM op_calls WHERE agent IS NOT NULL "
                                  "GROUP BY agent").fetchall())
    found = []
    for a in conn.execute("SELECT * FROM op_agents"):
        user = a["username"]
        who = {"agent": user, "agent_name": names.get(user, user)}
        name = who["agent_name"]
        op = holding.get(user)
        if op and op["status"] == "in_call" and not op["call_ended_at"]:
            started = _at(op["call_started_at"])
            if long_call and started and _minutes(started, now) >= long_call:
                mins = _minutes(started, now)
                found.append(_alert("long_call", str(op["id"]), _level(mins, long_call),
                                    f"{name} has been on a call for {mins} min",
                                    f"With {_contact(op)}, since {_hm(started)}.", started, op_id=op["id"], **who))
            continue
        if not idle:
            continue
        if op and op["call_ended_at"]:
            since, detail = _at(op["call_ended_at"]), f"Still closing the call with {_contact(op)}"
        elif op:
            since, detail = _at(op["assigned_at"]), f"Was served {_contact(op)} and hasn't dialed"
        elif a["ready"] and (a["last_seen"] or "") >= online_after:
            # Taking calls: idle since they started taking calls, or since their last call if later.
            since = max(filter(None, (_at(a["since"]), _at(last_done.get(user)))), default=None)
            detail = "Taking calls but no call"
        else:
            continue  # paused or offline: not on the desk
        if since and _minutes(since, now) >= idle:
            mins = _minutes(since, now)
            found.append(_alert("idle", f"{user}:{since.isoformat()}", _level(mins, idle), f"{name} idle for {mins} min",
                                f"{detail} since {_hm(since)}.", since, op_id=op["id"] if op else None, **who))
    return found


def _streaks(conn, names: dict[str, str], limits: dict, now: datetime) -> list[dict]:
    """Agents whose latest calls today all went unanswered."""
    streak = int(limits["ALERT_NO_ANSWER_STREAK"])
    if not streak:
        return []
    lookup = operations.outcome_lookup(conn)
    start = now.strftime("%Y-%m-%dT00:00:00")
    calls: dict[str, list] = {}
    for r in conn.execute(f"SELECT agent, outcome, campaign_id, finished_at FROM op_calls WHERE status = 'done' "
                          f"AND finished_at >= ? AND {REAL} ORDER BY finished_at DESC NULLS LAST, id DESC", (start,)):
        calls.setdefault(r["agent"], []).append(r)
    found = []
    for user, rows in calls.items():
        run = []
        for r in rows:
            if lookup(r["campaign_id"], r["outcome"]).get("reached"):
                break
            run.append(r)
        if len(run) >= streak:
            since = _at(run[-1]["finished_at"]) or now
            name = names.get(user, user)
            found.append(_alert("no_answer_streak", f"{user}:{since.isoformat()}", _level(len(run), streak),
                                f"{len(run)} unanswered calls in a row for {name}",
                                f"No contact reached since {_hm(since)}: check the numbers, the line or the "
                                "calling hours.", since, agent=user, agent_name=name))
    return found


def _rate_drops(conn, limits: dict, now: datetime) -> list[dict]:
    """Campaigns whose contact rate over the last window fell well below their rate over the week before."""
    window, min_calls, drop = (limits["ALERT_CONTACT_RATE_WINDOW_MINUTES"], int(limits["ALERT_CONTACT_RATE_MIN_CALLS"]),
                               limits["ALERT_CONTACT_RATE_DROP_PERCENT"])
    if not window or not drop:
        return []
    lookup = operations.outcome_lookup(conn)
    default = campaigns.default_id(conn)
    split = now - timedelta(minutes=window)
    since = (split - timedelta(days=BASELINE_DAYS)).isoformat(timespec="seconds")
    counts: dict[int, dict[str, list[int]]] = {}  # campaign -> recent / before -> [calls, reached]
    for r in conn.execute(f"SELECT outcome, campaign_id, finished_at FROM op_calls WHERE status = 'done' "
                          f"AND finished_at >= ? AND {REAL}", (since,)):
        campaign = r["campaign_id"] or default
        part = counts.setdefault(campaign, {"recent": [0, 0], "before": [0, 0]})[
            "recent" if r["finished_at"] >= split.isoformat(timespec="seconds") else "before"]
        part[0] += 1
        part[1] += bool(lookup(campaign, r["outcome"]).get("reached"))
    names = {c["id"]: c["name"] for c in campaigns.all_campaigns(conn)}
    found = []
    for campaign, c in counts.items():
        (calls, reached), (base_calls, base_reached) = c["recent"], c["before"]
        if calls < max(min_calls, 1) or base_calls < 3 * max(min_calls, 1) or not base_reached:
            continue
        rate, base = reached / calls, base_reached / base_calls
        fall = (1 - rate / base) * 100
        if fall >= drop:
            found.append(_alert(
                "contact_rate_drop", str(campaign), _level(fall, drop),
                f"Contact rate down to {rate:.0%} on {names.get(campaign, 'a campaign')}",
                f"{reached} of {calls} contacts reached in the last {int(window)} min, against {base:.0%} over the "
                f"{BASELINE_DAYS} days before.", split, campaign_id=campaign))
    return found


def _overdue_callbacks(conn, names: dict[str, str], limits: dict, now: datetime) -> list[dict]:
    late = limits["ALERT_CALLBACK_OVERDUE_MINUTES"]
    if not late:
        return []
    cutoff = (now - timedelta(minutes=late)).isoformat(timespec="seconds")
    rows = conn.execute(f"SELECT * FROM op_calls WHERE status = 'scheduled' AND due_at <= ? AND {REAL} "
                        f"ORDER BY due_at, id", (cutoff,)).fetchall()
    if len(rows) > CALLBACKS_ONE_BY_ONE:
        oldest = _at(rows[0]["due_at"]) or now
        mins = _minutes(oldest, now)
        return [_alert("callback_overdue", "many", _level(mins, late), f"{len(rows)} callbacks overdue",
                       f"Late by {late:g} min or more; the oldest was due at {oldest:%d/%m %H:%M}.", oldest)]
    found = []
    for r in rows:
        due = _at(r["due_at"]) or now
        mins = _minutes(due, now)
        who = names.get(r["assign_to"], r["assign_to"]) if r["assign_to"] else None
        found.append(_alert("callback_overdue", str(r["id"]), _level(mins, late),
                            f"Callback to {_contact(r)} overdue by {mins} min",
                            f"Was due at {due:%d/%m %H:%M}" + (f", kept for {who}." if who else ", for anyone."),
                            due, op_id=r["id"], agent=r["assign_to"], agent_name=who))
    return found


def _missed_calls(conn, limits: dict, now: datetime) -> list[dict]:
    late = limits["ALERT_MISSED_CALL_MINUTES"]
    if not late:
        return []
    found = []
    for m in inbound.missed(conn, now):
        first = _at(m["first_rang_at"]) or now
        mins = _minutes(first, now)
        if mins < late:
            continue
        who = m["contact_name"] or m["number"]
        tries = f", {m['tries']} tries" if m["tries"] > 1 else ""
        doing = (f" {m['serving']['agent_name']} is calling back now." if m["serving"] else
                 f" It goes to {m['prefer_name']} first." if m["prefer"] else "")
        found.append(_alert("missed_call", m["key"], _level(mins, late), f"Missed call from {who} not called back",
                            f"Rang at {_hm(first)}{tries}, {mins} min ago.{doing}", first,
                            agent=m["prefer"], agent_name=m["prefer_name"]))
    return found


def current(conn, now: datetime | None = None) -> list[dict]:
    """Every alert right now, critical ones first, then the oldest first."""
    now = (now or datetime.now()).replace(microsecond=0)
    names = operations.account_names(conn)
    limits = thresholds()
    found = (_agent_alerts(conn, names, limits, now) + _streaks(conn, names, limits, now)
             + _rate_drops(conn, limits, now) + _overdue_callbacks(conn, names, limits, now)
             + _missed_calls(conn, limits, now))
    return sorted(found, key=lambda a: (a["level"] != "critical", a["since"]))
