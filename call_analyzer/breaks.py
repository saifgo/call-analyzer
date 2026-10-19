"""Earned breaks: with DESK_EARNED_BREAK on, an agent who closes DESK_EARNED_BREAK_CALLS calls is offered a break of
DESK_EARNED_BREAK_MINUTES. The calls count from the start of the day, then from their last earned break; an offer
the agent puts off stays until they take it (it doesn't add up). The break is a pause like the others (see floor.py),
logged as "Earned break" with its length as the limit, so it shows on the board and in the KPIs, and turns red when
it runs over.
"""
from datetime import datetime

from . import floor, operations
from .config import live

LABEL = "Earned break"
DEFAULT_CALLS = 20
DEFAULT_MINUTES = 10


def _number(name: str, default: int) -> int:
    try:
        value = int(float(live(name, str(default))))
    except ValueError:
        return default
    return value if value > 0 else default


def rule() -> dict | None:
    """The setting as saved right now: how many calls earn how many minutes (None: off)."""
    if live("DESK_EARNED_BREAK", "false").lower() != "true":
        return None
    return {"calls": _number("DESK_EARNED_BREAK_CALLS", DEFAULT_CALLS),
            "minutes": _number("DESK_EARNED_BREAK_MINUTES", DEFAULT_MINUTES)}


def _last_break(conn, username: str, day: str):
    return conn.execute("SELECT * FROM op_pauses WHERE username = ? AND earned = 1 AND started_at >= ? "
                        "ORDER BY started_at DESC, id DESC LIMIT 1", (username, day)).fetchone()


def state(conn, username: str, now: datetime | None = None) -> dict | None:
    """Where the agent stands: calls closed since their last earned break (or today), how many earn one, its
    length, whether they've earned it, and how many they took today (None: earned breaks are off)."""
    current = rule()
    if not current:
        return None
    day = (now or datetime.now()).strftime("%Y-%m-%dT00:00:00")
    last = _last_break(conn, username, day)
    since = last["started_at"] if last else day
    done = conn.execute("SELECT COUNT(*) FROM op_calls WHERE agent = ? AND status = 'done' AND finished_at >= ? "
                        "AND opportunity_id NOT LIKE ?", (username, since, f"{operations.TEST_PREFIX}%")).fetchone()[0]
    taken = conn.execute("SELECT COUNT(*) FROM op_pauses WHERE username = ? AND earned = 1 AND started_at >= ?",
                         (username, day)).fetchone()[0]
    return {**current, "done": done, "earned": done >= current["calls"], "taken_today": taken}


def take(conn, username: str, now: datetime | None = None) -> None:
    """The agent takes the break they earned: they stop taking calls and go on it (ending the pause they were on)."""
    current = state(conn, username, now)
    if not current:
        raise floor.FloorError("Earned breaks are turned off")
    if not current["earned"]:
        left = current["calls"] - current["done"]
        raise floor.FloorError(f"{left} more call{'s' if left != 1 else ''} to earn your break")
    op = operations.current(conn, username)
    if op and op["status"] == "in_call":
        raise floor.FloorError("Finish your call first")
    operations.set_ready(conn, username, False)
    now = now or datetime.now().replace(microsecond=0)
    floor.end_pause(conn, username, now)
    cur = conn.execute("INSERT INTO op_pauses (username, reason_id, label, limit_minutes, started_at, ended_at, earned) "
                       "VALUES (?, NULL, ?, ?, ?, ?, 1)",
                       (username, LABEL, current["minutes"], now.isoformat(), now.isoformat()))
    conn.execute("UPDATE op_agents SET pause_id = ? WHERE username = ?", (cur.lastrowid, username))
    conn.commit()
