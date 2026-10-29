"""Running the sales floor: each agent's daily targets, and the reasons they pause the desk for.

Targets: admins set a team default for calls closed, contacts reached, wins and hours on the desk, and can override
any of them per agent (op_targets: the row '*' is the team, a NULL column of an agent's row takes the team's value,
0 means no target). The workday (op_settings workday_start / workday_end) gives the pace: how far along the day is,
so an agent sees whether they are ahead of or behind where they should be by now.

Pauses: an agent who stops taking calls says why (break, lunch, training…). Each reason may have a time limit; the
desk, the team board and the wallboard show a pause that runs over it. Every pause is logged (op_pauses) with the
reason's label and limit as they were, so the KPIs can add up pause time per reason. A pause lasts until the agent
takes calls again or picks another reason; while the agent's desk is open its end is moved forward at each
check-in, and a pause left open overnight ends at the last check-in of its day.

Shifts: an agent clocks in to start their day and clocks out to end it (op_shifts). They take calls and pause only
while clocked in, so the breaks they take are bounded by the shift: clocking out ends the pause they're on. A shift
nobody clocked out of ends on its own AUTO_CLOCK_OUT_MINUTES after the workday ends (at the last check-in before that,
when the desk was closed earlier), with the pause it was on, so a break left open after work doesn't keep counting.
"""
from datetime import datetime, timedelta

METRICS = ("calls", "reached", "wins", "desk_minutes")
# A shift still open this long after the workday ends is clocked out on its own.
AUTO_CLOCK_OUT_MINUTES = 60
TEAM = "*"
DEFAULT_WORKDAY = ("09:00", "17:00")
# Created the first time the desk runs; admins edit them on Operations > Targets.
DEFAULT_REASONS = [("Break", 15), ("Lunch", 60), ("Training", 60), ("Meeting", 30), ("Admin work", 20),
                   ("Technical problem", 15)]


class FloorError(Exception):
    """Invalid targets or pause reasons; the message is shown to the admin."""


def _now() -> datetime:
    return datetime.now().replace(microsecond=0)


def _setting(conn, key: str, default: str | None = None) -> str | None:
    row = conn.execute("SELECT value FROM op_settings WHERE key = ?", (key,)).fetchone()
    return row[0] if row else default


def _set_setting(conn, key: str, value: str) -> None:
    conn.execute("INSERT INTO op_settings (key, value) VALUES (?, ?) "
                 "ON CONFLICT(key) DO UPDATE SET value = excluded.value", (key, value))


# --- Targets ----------------------------------------------------------------------------------------

def workday(conn) -> dict:
    return {"start": _setting(conn, "workday_start", DEFAULT_WORKDAY[0]),
            "end": _setting(conn, "workday_end", DEFAULT_WORKDAY[1])}


def _minutes(hhmm: str) -> int:
    hours, minutes = hhmm.split(":")
    return int(hours) * 60 + int(minutes)


def pace(conn, now: datetime | None = None) -> float:
    """How much of the workday is behind us, from 0 (not started) to 1 (over)."""
    now = now or datetime.now()
    day = workday(conn)
    start, end = _minutes(day["start"]), _minutes(day["end"])
    current = now.hour * 60 + now.minute + now.second / 60
    if end <= start:
        return 1.0
    return round(min(1.0, max(0.0, (current - start) / (end - start))), 4)


def _row_targets(row) -> dict:
    return {m: (row[m] if row is not None else None) for m in METRICS}


def targets(conn) -> dict:
    """The team's targets, each agent's overrides (None: the team's), and the workday."""
    rows = {r["username"]: r for r in conn.execute("SELECT * FROM op_targets")}
    team = {m: v or 0 for m, v in _row_targets(rows.get(TEAM)).items()}
    agents = {u: _row_targets(r) for u, r in rows.items() if u != TEAM}
    return {"team": team, "agents": agents, "workday": workday(conn)}


def resolved(conn, username: str, table: dict | None = None) -> dict:
    """The agent's targets for the day: their own where set, else the team's. 0: no target."""
    table = table or targets(conn)
    own = table["agents"].get(username, {})
    return {m: own[m] if own.get(m) is not None else table["team"][m] for m in METRICS}


def _target_value(value, label: str) -> int | None:
    if value is None or value == "":
        return None
    try:
        number = int(value)
    except (TypeError, ValueError):
        raise FloorError(f"{label}: enter a whole number") from None
    if not 0 <= number <= 10_000:
        raise FloorError(f"{label}: enter a number between 0 and 10000")
    return number


def _check_time(value, label: str) -> str:
    text = str(value or "").strip()
    try:
        datetime.strptime(text, "%H:%M")
    except ValueError:
        raise FloorError(f"{label}: enter a time like 09:00") from None
    return text


def save_targets(conn, body: dict) -> dict:
    """Replace the targets: body = {"team": {...}, "agents": {username: {...}}, "workday": {"start", "end"}}."""
    team = {m: _target_value((body.get("team") or {}).get(m), f"Team {m.replace('_', ' ')}") or 0 for m in METRICS}
    known = {r[0] for r in conn.execute("SELECT username FROM users")}
    agents = {}
    for username, values in (body.get("agents") or {}).items():
        if username not in known:
            continue
        row = {m: _target_value((values or {}).get(m), f"{username}: {m.replace('_', ' ')}") for m in METRICS}
        if any(v is not None for v in row.values()):
            agents[username] = row
    day = body.get("workday") or {}
    start, end = _check_time(day.get("start"), "Workday start"), _check_time(day.get("end"), "Workday end")
    if _minutes(end) <= _minutes(start):
        raise FloorError("The workday must end after it starts")
    conn.execute("DELETE FROM op_targets")
    columns = ", ".join(METRICS)
    marks = ", ".join("?" for _ in METRICS)
    for username, row in [(TEAM, team), *agents.items()]:
        conn.execute(f"INSERT INTO op_targets (username, {columns}) VALUES (?, {marks})",
                     (username, *[row[m] for m in METRICS]))
    _set_setting(conn, "workday_start", start)
    _set_setting(conn, "workday_end", end)
    conn.commit()
    return targets(conn)


# --- Pause reasons -----------------------------------------------------------------------------------

def _seed_reasons(conn) -> None:
    if _setting(conn, "pause_reasons_seeded"):
        return
    if not conn.execute("SELECT 1 FROM op_pause_reasons LIMIT 1").fetchone():
        for position, (label, limit) in enumerate(DEFAULT_REASONS):
            conn.execute("INSERT INTO op_pause_reasons (label, limit_minutes, position, active) VALUES (?, ?, ?, 1)",
                         (label, limit, position))
    _set_setting(conn, "pause_reasons_seeded", "1")
    conn.commit()


def reasons(conn) -> list[dict]:
    """The reasons agents can pause for, in order. limit_minutes 0: no limit."""
    _seed_reasons(conn)
    return [dict(r) for r in conn.execute("SELECT id, label, limit_minutes FROM op_pause_reasons WHERE active = 1 "
                                          "ORDER BY position, id")]


def save_reasons(conn, items: list[dict]) -> list[dict]:
    """Replace the list: items with an id update that reason, without one add a reason; reasons left out are retired
    (the pauses already taken keep their label)."""
    _seed_reasons(conn)
    cleaned, seen = [], set()
    for item in items:
        label = " ".join(str(item.get("label") or "").split())[:40]
        if not label:
            raise FloorError("Every pause reason needs a name")
        if label.lower() in seen:
            raise FloorError(f"“{label}” is in the list twice")
        seen.add(label.lower())
        limit = _target_value(item.get("limit_minutes"), f"{label}: time limit") or 0
        if limit > 600:
            raise FloorError(f"{label}: the time limit can't be over 600 minutes")
        cleaned.append((item.get("id"), label, limit))
    if not cleaned:
        raise FloorError("Keep at least one pause reason")
    kept = set()
    for position, (reason_id, label, limit) in enumerate(cleaned):
        if reason_id and conn.execute("SELECT 1 FROM op_pause_reasons WHERE id = ?", (reason_id,)).fetchone():
            conn.execute("UPDATE op_pause_reasons SET label = ?, limit_minutes = ?, position = ?, active = 1 "
                         "WHERE id = ?", (label, limit, position, reason_id))
            kept.add(int(reason_id))
        else:
            cur = conn.execute("INSERT INTO op_pause_reasons (label, limit_minutes, position, active) "
                               "VALUES (?, ?, ?, 1)", (label, limit, position))
            kept.add(cur.lastrowid)
    conn.execute(f"UPDATE op_pause_reasons SET active = 0 WHERE id NOT IN ({','.join('?' * len(kept))})", list(kept))
    conn.commit()
    return reasons(conn)


# --- Pauses ------------------------------------------------------------------------------------------

def _open_pause(conn, username: str):
    return conn.execute("SELECT p.* FROM op_agents a JOIN op_pauses p ON p.id = a.pause_id "
                        "WHERE a.username = ? AND p.closed = 0", (username,)).fetchone()


def end_pause(conn, username: str, now: datetime | None = None) -> None:
    """Close the agent's pause, if they are on one (the caller commits)."""
    row = _open_pause(conn, username)
    if row:
        conn.execute("UPDATE op_pauses SET ended_at = ?, closed = 1 WHERE id = ?",
                     ((now or _now()).isoformat(), row["id"]))
    conn.execute("UPDATE op_agents SET pause_id = NULL WHERE username = ?", (username,))


def start_pause(conn, username: str, reason_id: int, now: datetime | None = None) -> None:
    """The agent pauses for this reason (ending the pause they were on). The caller commits; op_agents must have the
    agent's row."""
    reason = conn.execute("SELECT * FROM op_pause_reasons WHERE id = ? AND active = 1", (reason_id,)).fetchone()
    if not reason:
        raise FloorError("This pause reason doesn't exist anymore: pick another one")
    now = now or _now()
    end_pause(conn, username, now)
    cur = conn.execute("INSERT INTO op_pauses (username, reason_id, label, limit_minutes, started_at, ended_at) "
                       "VALUES (?, ?, ?, ?, ?, ?)", (username, reason["id"], reason["label"], reason["limit_minutes"],
                                                     now.isoformat(), now.isoformat()))
    conn.execute("UPDATE op_agents SET pause_id = ? WHERE username = ?", (cur.lastrowid, username))


def touch_pause(conn, username: str, now: datetime) -> None:
    """The agent's desk checked in: their pause lasts until now. One from an earlier day ends where it was (the
    caller commits)."""
    row = _open_pause(conn, username)
    if not row:
        return
    if row["started_at"][:10] != now.date().isoformat():
        conn.execute("UPDATE op_pauses SET closed = 1 WHERE id = ?", (row["id"],))
        conn.execute("UPDATE op_agents SET pause_id = NULL WHERE username = ?", (username,))
    else:
        conn.execute("UPDATE op_pauses SET ended_at = ? WHERE id = ?", (now.isoformat(), row["id"]))


def _seconds(start: str, end: str | None) -> int:
    try:
        return max(0, int((datetime.fromisoformat(end) - datetime.fromisoformat(start)).total_seconds()))
    except (TypeError, ValueError):
        return 0


def pause_state(conn, username: str, now: datetime | None = None) -> dict | None:
    """The pause the agent is on: its reason, limit, start, and whether it runs over the limit."""
    row = _open_pause(conn, username)
    if not row:
        return None
    elapsed = _seconds(row["started_at"], (now or _now()).isoformat())
    limit = row["limit_minutes"] or 0
    return {"id": row["id"], "reason_id": row["reason_id"], "label": row["label"], "limit_minutes": limit,
            "started_at": row["started_at"], "seconds": elapsed, "over": bool(limit) and elapsed > limit * 60}


def pause_totals(conn, since: str, until: str, username: str | None = None) -> dict[str, dict]:
    """Per agent between two days (until exclusive): pause seconds in all, per reason, and how many pauses ran over
    their limit."""
    sql = "SELECT * FROM op_pauses WHERE started_at >= ? AND started_at < ?"
    args = [since, until]
    if username:
        sql += " AND username = ?"
        args.append(username)
    totals: dict[str, dict] = {}
    for row in conn.execute(sql, args):
        seconds = _seconds(row["started_at"], row["ended_at"])
        t = totals.setdefault(row["username"], {"pause_seconds": 0, "pauses": 0, "pauses_over": 0, "by_reason": {}})
        t["pause_seconds"] += seconds
        t["pauses"] += 1
        t["pauses_over"] += bool(row["limit_minutes"]) and seconds > row["limit_minutes"] * 60
        t["by_reason"][row["label"]] = t["by_reason"].get(row["label"], 0) + seconds
    return totals


# --- Shifts ------------------------------------------------------------------------------------------

def open_shift(conn, username: str):
    return conn.execute("SELECT s.* FROM op_agents a JOIN op_shifts s ON s.id = a.shift_id "
                        "WHERE a.username = ? AND s.closed = 0", (username,)).fetchone()


def clock_in(conn, username: str, now: datetime | None = None) -> None:
    """Start the agent's shift, unless they're clocked in already (the caller commits)."""
    if open_shift(conn, username):
        return
    now = now or _now()
    conn.execute("INSERT INTO op_agents (username, ready) VALUES (?, 0) ON CONFLICT(username) DO NOTHING", (username,))
    cur = conn.execute("INSERT INTO op_shifts (username, started_at, ended_at) VALUES (?, ?, ?)",
                       (username, now.isoformat(), now.isoformat()))
    conn.execute("UPDATE op_agents SET shift_id = ? WHERE username = ?", (cur.lastrowid, username))


def clock_out(conn, username: str, now: datetime | None = None, by: str = "agent") -> None:
    """End the agent's shift and the pause they're on; they stop taking calls (the caller commits)."""
    now = now or _now()
    row = open_shift(conn, username)
    end_pause(conn, username, now)
    if row:
        conn.execute("UPDATE op_shifts SET ended_at = ?, closed = 1, ended_by = ? WHERE id = ?",
                     (max(now.isoformat(), row["started_at"]), by, row["id"]))
    conn.execute("UPDATE op_agents SET shift_id = NULL, ready = 0, since = ? WHERE username = ?",
                 (now.isoformat(), username))


def clock_out_at(conn, now: datetime) -> datetime:
    """When a shift still open at `now` is clocked out on its own: AUTO_CLOCK_OUT_MINUTES after today's workday."""
    end = datetime.combine(now.date(), datetime.strptime(workday(conn)["end"], "%H:%M").time())
    return end + timedelta(minutes=AUTO_CLOCK_OUT_MINUTES)


def touch_shift(conn, username: str, now: datetime, busy: bool = False) -> None:
    """The agent's desk checked in: their shift lasts until now. One from an earlier day ends at its last check-in,
    and one past the workday's clock-out time (see clock_out_at) ends then, unless the agent is `busy` with a
    contact; either way with the pause it was on. The caller commits."""
    row = open_shift(conn, username)
    if not row:
        return
    last = datetime.fromisoformat(row["ended_at"] or row["started_at"])
    if row["started_at"][:10] != now.date().isoformat():
        clock_out(conn, username, last, by="auto")
        return
    cutoff = clock_out_at(conn, now)
    if not busy and now >= cutoff and row["started_at"] < cutoff.isoformat():
        clock_out(conn, username, min(last, cutoff), by="auto")
        return
    conn.execute("UPDATE op_shifts SET ended_at = ? WHERE id = ?", (now.isoformat(), row["id"]))


def shift_state(conn, username: str, now: datetime | None = None) -> dict | None:
    """The agent's shift today: when they clocked in (and out, once they have), how long it lasted, and the time they
    spent paused during it. The open one, else the latest of the day; None: they haven't clocked in today."""
    now = now or _now()
    row = open_shift(conn, username) or conn.execute(
        "SELECT * FROM op_shifts WHERE username = ? AND started_at >= ? ORDER BY started_at DESC, id DESC LIMIT 1",
        (username, now.date().isoformat())).fetchone()
    if not row:
        return None
    end = now.isoformat() if not row["closed"] else row["ended_at"]
    paused = 0
    for p in conn.execute("SELECT started_at, ended_at, closed FROM op_pauses WHERE username = ? AND started_at >= ? "
                          "AND started_at <= ?", (username, row["started_at"], end)):
        paused += _seconds(p["started_at"], min(p["ended_at"] or end, end) if p["closed"] else end)
    return {"id": row["id"], "open": not row["closed"], "started_at": row["started_at"],
            "ended_at": row["ended_at"] if row["closed"] else None, "ended_by": row["ended_by"],
            "seconds": _seconds(row["started_at"], end), "pause_seconds": paused}


def shift_totals(conn, since: str, until: str, username: str | None = None) -> dict[str, dict]:
    """Per agent between two days (until exclusive): seconds clocked in, and the number of shifts."""
    sql = "SELECT username, started_at, ended_at FROM op_shifts WHERE started_at >= ? AND started_at < ?"
    args = [since, until]
    if username:
        sql += " AND username = ?"
        args.append(username)
    totals: dict[str, dict] = {}
    for row in conn.execute(sql, args):
        t = totals.setdefault(row["username"], {"shift_seconds": 0, "shifts": 0})
        t["shift_seconds"] += _seconds(row["started_at"], row["ended_at"])
        t["shifts"] += 1
    return totals


# --- Progress ----------------------------------------------------------------------------------------

def progress(done: dict, goal: dict, day_pace: float) -> list[dict]:
    """Each metric with a target: how far along it is, and how far it should be by now."""
    values = {"calls": done.get("done", 0), "reached": done.get("reached", 0), "wins": done.get("success", 0),
              "desk_minutes": round(done.get("desk_seconds", 0) / 60)}
    return [{"metric": m, "value": values[m], "target": goal[m], "expected": round(goal[m] * day_pace, 1)}
            for m in METRICS if goal[m]]
