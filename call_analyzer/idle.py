"""Idle prompts: an agent taking calls who stays on the desk without calling anyone for DESK_IDLE_PROMPT_MINUTES is
prompted to call, again every DESK_IDLE_PROMPT_MINUTES while it lasts. Each idle stretch that got a prompt is logged
(op_idle_prompts) so admins can look at them later (Operations > KPIs).

Idle since the latest of: when they started taking calls, when their desk came back online (a closed tab doesn't
count as idle), and their last call (dialed, ended or closed). A call in progress or being closed isn't idle; neither
is a pause. Checked at each check-in of the agent's desk; the stretch ends with how it ended: they called, paused, or
left the desk (their desk stopped checking in).
"""
from datetime import datetime, timedelta

from . import operations
from .config import live

DEFAULT_MINUTES = 5


def minutes() -> float:
    """The setting as saved right now (a bad or negative value: the default; 0: no prompt)."""
    try:
        value = float(live("DESK_IDLE_PROMPT_MINUTES", str(DEFAULT_MINUTES)))
    except ValueError:
        return DEFAULT_MINUTES
    return value if value >= 0 else DEFAULT_MINUTES


def _at(value: str | None) -> datetime | None:
    try:
        return datetime.fromisoformat(value)
    except (TypeError, ValueError):
        return None


def _contact(op) -> str:
    lead = operations.to_dict(op)["lead"] or {}
    return (lead.get("contact") or {}).get("name") or lead.get("name") or "a contact"


def _idle(conn, username: str) -> dict | None:
    """Since when the agent has been idle, what they were doing, and their last call (None: not idle)."""
    a = conn.execute("SELECT * FROM op_agents WHERE username = ?", (username,)).fetchone()
    if not a or not a["ready"]:
        return None
    op = operations.current(conn, username)
    if op and op["status"] == "in_call":
        return None  # on a call, or closing one
    last = _at(conn.execute("SELECT MAX(GREATEST(COALESCE(call_started_at, ''), COALESCE(call_ended_at, ''), "
                            "CASE WHEN status = 'done' THEN COALESCE(finished_at, '') ELSE '' END)) "
                            "FROM op_calls WHERE agent = ?", (username,)).fetchone()[0])
    since = max(filter(None, (_at(a["since"]), _at(a["online_since"]), last)), default=None)
    if not since:
        return None
    return {"since": since, "last_call": last,
            "doing": f"Served {_contact(op)} and didn't dial" if op else "No contact served"}


def _open(conn, username: str):
    return conn.execute("SELECT * FROM op_idle_prompts WHERE username = ? AND closed = 0 ORDER BY id DESC LIMIT 1",
                        (username,)).fetchone()


def to_dict(row) -> dict:
    """`acknowledged`: the agent saw the latest prompt; `outcome` (once closed): called, paused or left."""
    item = dict(row)
    item["closed"] = bool(item["closed"])
    item["idle_seconds"] = max(0, int((_at(row["ended_at"]) - _at(row["idle_since"])).total_seconds()))
    item["acknowledged"] = row["acknowledged"] >= row["prompts"]
    return item


def check(conn, username: str, now: datetime | None = None) -> dict | None:
    """The agent's desk checked in (after operations.heartbeat): prompt them if they've been idle too long, close the
    stretch they were prompted in if it's over. Returns the prompt to show, if any."""
    now = (now or datetime.now()).replace(microsecond=0)
    limit = minutes()
    close_left(conn, now)
    idle = _idle(conn, username)
    row = _open(conn, username)
    if row and (idle is None or idle["since"].isoformat() != row["idle_since"]):
        # Over: a call started (or was closed) since, else they paused (or stopped and took calls again).
        called = conn.execute("SELECT 1 FROM op_calls WHERE agent = ? AND (call_started_at >= ? OR "
                              "(status = 'done' AND finished_at >= ?))",
                              (username, row["idle_since"], row["idle_since"])).fetchone()
        conn.execute("UPDATE op_idle_prompts SET closed = 1, ended_at = ?, outcome = ? WHERE id = ?",
                     (now.isoformat(), "called" if called else "paused", row["id"]))
        row = None
    if row:
        prompts = row["prompts"]
        due = (_at(row["last_prompt_at"]) or now) + timedelta(minutes=limit) if limit else None
        if due and now >= due:
            prompts += 1
            conn.execute("UPDATE op_idle_prompts SET prompts = ?, last_prompt_at = ? WHERE id = ?",
                         (prompts, now.isoformat(), row["id"]))
        conn.execute("UPDATE op_idle_prompts SET ended_at = ?, doing = ? WHERE id = ?",
                     (now.isoformat(), idle["doing"], row["id"]))
    elif idle and limit and now - idle["since"] >= timedelta(minutes=limit):
        conn.execute("INSERT INTO op_idle_prompts (username, idle_since, prompted_at, last_prompt_at, prompts, "
                     "doing, ended_at) VALUES (?, ?, ?, ?, 1, ?, ?)",
                     (username, idle["since"].isoformat(), now.isoformat(), now.isoformat(), idle["doing"],
                      now.isoformat()))
    conn.commit()
    row = _open(conn, username)
    return to_dict(row) if row else None


def acknowledge(conn, username: str, prompt_id: int) -> None:
    """The agent saw the prompt (it shows again at the next one)."""
    conn.execute("UPDATE op_idle_prompts SET acknowledged = prompts WHERE id = ? AND username = ?",
                 (prompt_id, username))
    conn.commit()


def close_left(conn, now: datetime | None = None) -> None:
    """Stretches of agents whose desk stopped checking in end where it last did (the caller commits)."""
    cutoff = ((now or datetime.now()) - timedelta(seconds=operations.OFFLINE_SECONDS)).isoformat(timespec="seconds")
    conn.execute("UPDATE op_idle_prompts SET closed = 1, outcome = 'left' WHERE closed = 0 AND ended_at < ?",
                 (cutoff,))


def history(conn, since: str, until: str, username: str | None = None) -> list[dict]:
    """The idle stretches that got a prompt between two days (until exclusive), latest first."""
    close_left(conn)
    conn.commit()
    names = operations.account_names(conn)
    sql = "SELECT * FROM op_idle_prompts WHERE prompted_at >= ? AND prompted_at < ?"
    args = [since, until]
    if username:
        sql += " AND username = ?"
        args.append(username)
    return [{**to_dict(r), "name": names.get(r["username"], r["username"])}
            for r in conn.execute(sql + " ORDER BY prompted_at DESC, id DESC", args)]
