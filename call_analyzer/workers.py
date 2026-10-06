"""Remote agents: the registry and the task queue, stored in the same SQLite database as the calls.

An agent is a PC running `python -m call_analyzer agent run`. It connects out to this server (so it can sit behind
any router), asks for work, does the heavy step (Whisper or Claude) with its own hardware and logins, and sends the
result back. The server never calls the agent.

    pipeline step (transcribe / analyze) --enqueue--> worker_tasks --claim--> agent --result--> calls table

Each step can run on the host, on agents, or on agents with the host as the fallback (TRANSCRIBE_RUNS_ON and
ANALYZE_RUNS_ON in Settings; see dispatch.py). A task is leased to one agent at a time. The agent's heartbeats keep
the lease alive; when they stop, the task goes back to the queue for another agent.
"""
import hashlib
import json
import secrets
from datetime import datetime, timedelta

from . import db

KINDS = ("transcribe", "analyze")
PROTOCOL = 1  # bump when the agent <-> server messages change incompatibly
MIN_PROTOCOL = 1  # older agents are told to update

ONLINE_SECONDS = 45  # an agent that hasn't been heard from for this long is offline (it pings every ~15 s)
LEASE_SECONDS = 120  # a running task goes back to the queue when its agent is silent for this long
MAX_ATTEMPTS = 3
RETRY_DELAY = 15  # seconds, times the number of attempts so far

NAME_MAX = 64


def _now() -> datetime:
    return datetime.now().replace(microsecond=0)


def _ts(moment: datetime | None = None) -> str:
    return (moment or _now()).isoformat()


def _in(seconds: int) -> str:
    return _ts(_now() + timedelta(seconds=seconds))


def _hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


# --- Registry ---------------------------------------------------------------------------------

def _online(last_seen: str | None) -> bool:
    return bool(last_seen) and last_seen >= _ts(_now() - timedelta(seconds=ONLINE_SECONDS))


def _worker(row) -> dict:
    worker = dict(row)
    worker.pop("token_hash", None)
    worker["enabled"] = bool(worker["enabled"])
    worker["info"] = json.loads(worker["info"]) if worker["info"] else {}
    worker["online"] = _online(worker["last_seen"])
    return worker


def can_run(worker: dict, kind: str) -> bool:
    """Whether the agent reported that it is set up for this step (Whisper installed, a Claude login, ...)."""
    return bool(worker["info"].get("capabilities", {}).get(kind, {}).get("ok"))


def create_worker(conn, name: str, created_by: str | None = None) -> tuple[dict, str]:
    """Register an agent. Returns it and its token, which is shown once: only a hash is stored."""
    name = " ".join(name.split())
    if not name or len(name) > NAME_MAX:
        raise ValueError(f"Give the agent a name of 1 to {NAME_MAX} characters")
    if any(w["name"].lower() == name.lower() for w in list_workers(conn)):
        raise ValueError(f"There is already an agent called {name!r}")
    token = "ca_" + secrets.token_urlsafe(32)
    worker_id = secrets.token_hex(4)
    conn.execute("INSERT INTO workers (id, name, token_hash, created_at, created_by) VALUES (?, ?, ?, ?, ?)",
                 (worker_id, name, _hash(token), _ts(), created_by))
    conn.commit()
    return get_worker(conn, worker_id), token


def rotate_token(conn, worker_id: str) -> str:
    """New token for an agent (the old one stops working, so a leaked token can be cut off)."""
    token = "ca_" + secrets.token_urlsafe(32)
    if not conn.execute("UPDATE workers SET token_hash=? WHERE id=?", (_hash(token), worker_id)).rowcount:
        raise KeyError(worker_id)
    conn.commit()
    return token


def authenticate(conn, token: str) -> dict | None:
    if not token:
        return None
    row = conn.execute("SELECT * FROM workers WHERE token_hash=?", (_hash(token),)).fetchone()
    return _worker(row) if row else None


def get_worker(conn, worker_id: str) -> dict | None:
    row = conn.execute("SELECT * FROM workers WHERE id=?", (worker_id,)).fetchone()
    return _worker(row) if row else None


def list_workers(conn) -> list[dict]:
    return [_worker(r) for r in conn.execute("SELECT * FROM workers ORDER BY name COLLATE NOCASE")]


def update_worker(conn, worker_id: str, *, name: str | None = None, enabled: bool | None = None):
    if name is not None:
        name = " ".join(name.split())
        if not name or len(name) > NAME_MAX:
            raise ValueError(f"Give the agent a name of 1 to {NAME_MAX} characters")
        if any(w["name"].lower() == name.lower() and w["id"] != worker_id for w in list_workers(conn)):
            raise ValueError(f"There is already an agent called {name!r}")
        conn.execute("UPDATE workers SET name=? WHERE id=?", (name, worker_id))
    if enabled is not None:
        conn.execute("UPDATE workers SET enabled=? WHERE id=?", (int(enabled), worker_id))
    conn.commit()


def delete_worker(conn, worker_id: str) -> bool:
    """Revoke an agent. What it was working on goes back to the queue."""
    conn.execute("UPDATE worker_tasks SET status='queued', worker_id=NULL, worker_name=NULL, lease_expires=NULL "
                 "WHERE worker_id=? AND status='running'", (worker_id,))
    deleted = conn.execute("DELETE FROM workers WHERE id=?", (worker_id,)).rowcount
    conn.commit()
    return bool(deleted)


def touch(conn, worker_id: str, info: dict | None = None):
    """Record that the agent is alive, and what it says about itself."""
    if info is None:
        conn.execute("UPDATE workers SET last_seen=? WHERE id=?", (_ts(), worker_id))
    else:
        conn.execute("UPDATE workers SET last_seen=?, info=? WHERE id=?",
                     (_ts(), json.dumps(info, ensure_ascii=False), worker_id))
    conn.commit()


def goodbye(conn, worker_id: str):
    """The agent is shutting down: show it offline now, and give what it was working on to the others."""
    conn.execute("UPDATE worker_tasks SET status='queued', worker_id=NULL, worker_name=NULL, lease_expires=NULL, "
                 "progress=NULL, not_before=NULL WHERE worker_id=? AND status='running'", (worker_id,))
    conn.execute("UPDATE workers SET last_seen=NULL WHERE id=?", (worker_id,))
    conn.commit()


def online_workers(conn, kind: str | None = None) -> list[dict]:
    """Enabled agents that are connected right now (and set up for `kind`, if given)."""
    return [w for w in list_workers(conn)
            if w["enabled"] and w["online"] and (kind is None or can_run(w, kind))]


# --- Tasks ------------------------------------------------------------------------------------

def enqueue(conn, kind: str, call_ids: list[str], *, chain: bool = False, origin_pid: int | None = None) -> list[int]:
    """Queue `kind` for these calls and return the task ids. A call that already has an open task for this step
    keeps it (the pipeline just waits for that one)."""
    assert kind in KINDS
    ids = []
    for call_id in call_ids:
        conn.execute("INSERT OR IGNORE INTO worker_tasks (kind, call_id, chain, origin_pid, created_at) "
                     "VALUES (?, ?, ?, ?, ?)", (kind, call_id, int(chain), origin_pid, _ts()))
        task_id = conn.execute("SELECT id FROM worker_tasks WHERE kind=? AND call_id=? "
                               "AND status IN ('queued', 'running')", (kind, call_id)).fetchone()[0]
        conn.execute("UPDATE worker_tasks SET origin_pid=?, chain=chain OR ? WHERE id=? AND status='queued'",
                     (origin_pid, int(chain), task_id))
        ids.append(task_id)
    conn.commit()
    return ids


def _call_error(conn, call_id: str, kind: str, error: str):
    conn.execute("UPDATE calls SET error=? WHERE id=?", (f"{kind}: {error}", call_id))


def requeue_expired(conn):
    """Tasks whose agent stopped sending heartbeats go back to the queue, or fail after too many attempts."""
    rows = conn.execute("SELECT id, kind, call_id, attempts FROM worker_tasks "
                        "WHERE status='running' AND lease_expires < ?", (_ts(),)).fetchall()
    for row in rows:
        if row["attempts"] >= MAX_ATTEMPTS:
            error = "The agent stopped responding"
            conn.execute("UPDATE worker_tasks SET status='failed', error=?, finished_at=?, lease_expires=NULL "
                         "WHERE id=?", (error, _ts(), row["id"]))
            _call_error(conn, row["call_id"], row["kind"], error)
        else:
            conn.execute("UPDATE worker_tasks SET status='queued', worker_id=NULL, worker_name=NULL, "
                         "lease_expires=NULL, progress=NULL, error='The agent stopped responding' WHERE id=?",
                         (row["id"],))
    if rows:
        conn.commit()


def claim(conn, worker: dict, kinds: list[str]):
    """Atomically hand the oldest waiting task of one of `kinds` to this agent (or None)."""
    kinds = [k for k in kinds if k in KINDS]
    if not kinds:
        return None
    requeue_expired(conn)
    now = _ts()
    rows = conn.execute(
        f"""UPDATE worker_tasks SET status='running', worker_id=?, worker_name=?, attempts=attempts+1,
                started_at=?, lease_expires=?, progress=NULL, error=NULL
            WHERE id = (SELECT id FROM worker_tasks WHERE status='queued' AND kind IN ({','.join('?' * len(kinds))})
                        AND (not_before IS NULL OR not_before <= ?) ORDER BY id LIMIT 1)
            RETURNING *""",
        (worker["id"], worker["name"], now, _in(LEASE_SECONDS), *kinds, now)).fetchall()
    conn.commit()
    return rows[0] if rows else None


def get_task(conn, task_id: int):
    return conn.execute("SELECT * FROM worker_tasks WHERE id=?", (task_id,)).fetchone()


def heartbeat(conn, worker_id: str, running: list[int]) -> list[int]:
    """Extend the leases of the tasks the agent is working on. Returns those it should drop because they were
    cancelled or given to someone else."""
    if not running:
        return []
    marks = ",".join("?" * len(running))
    conn.execute(f"UPDATE worker_tasks SET lease_expires=? WHERE worker_id=? AND status='running' "
                 f"AND id IN ({marks})", (_in(LEASE_SECONDS), worker_id, *running))
    conn.commit()
    mine = {r[0] for r in conn.execute(f"SELECT id FROM worker_tasks WHERE worker_id=? AND status='running' "
                                       f"AND id IN ({marks})", (worker_id, *running))}
    return [i for i in running if i not in mine]


def set_progress(conn, task_id: int, text: str):
    conn.execute("UPDATE worker_tasks SET progress=?, lease_expires=? WHERE id=? AND status='running'",
                 (text[:200], _in(LEASE_SECONDS), task_id))
    conn.commit()


def _by(label: str, worker: dict) -> str:
    return f"{label} · agent {worker['name']}"


def complete(conn, task, worker: dict, result: dict):
    """Store an agent's result on the call and close the task. Raises ValueError for a result that doesn't fit."""
    now = _ts()
    label = str(result.get("label") or "").strip() or "agent"
    if task["kind"] == "transcribe":
        transcript = result.get("transcript")
        if not isinstance(transcript, str):
            raise ValueError("The result has no transcript")
        conn.execute("UPDATE calls SET transcript=?, transcribed_at=?, transcribed_by=?, error=NULL WHERE id=?",
                     (transcript, now, _by(label, worker), task["call_id"]))
    else:
        from .analyze import CallAnalysis  # the same model the host validates its own analyses with
        try:
            analysis = CallAnalysis.model_validate(result.get("analysis"))
        except Exception as exc:
            raise ValueError(f"The analysis doesn't match the expected format: {exc}") from exc
        conn.execute("UPDATE calls SET analysis=?, analyzed_at=?, analyzed_by=?, error=NULL WHERE id=?",
                     (analysis.model_dump_json(), now, _by(label, worker), task["call_id"]))
    conn.execute("UPDATE worker_tasks SET status='done', finished_at=?, progress=NULL, error=NULL, "
                 "lease_expires=NULL WHERE id=?", (now, task["id"]))
    if task["kind"] == "transcribe" and task["chain"]:
        from .config import runs_on
        if runs_on("analyze") != "host":  # the host's own analyze step picks the call up otherwise
            enqueue(conn, "analyze", [task["call_id"]], origin_pid=task["origin_pid"])
    conn.commit()


def release_task(conn, task_id: int):
    """Give a task back untouched (the agent stopped before starting it): it doesn't count as an attempt."""
    conn.execute("UPDATE worker_tasks SET status='queued', worker_id=NULL, worker_name=NULL, lease_expires=NULL, "
                 "progress=NULL, attempts=MAX(attempts-1, 0), not_before=NULL WHERE id=? AND status='running'",
                 (task_id,))
    conn.commit()


def fail(conn, task, worker: dict | None, error: str, *, retry: bool = True):
    """An agent couldn't do the task: queue it again after a pause (another agent may succeed), or give up."""
    error = (error or "failed")[:1000]
    if retry and task["attempts"] < MAX_ATTEMPTS:
        conn.execute("UPDATE worker_tasks SET status='queued', worker_id=NULL, worker_name=NULL, lease_expires=NULL, "
                     "progress=NULL, error=?, not_before=? WHERE id=?",
                     (error, _in(RETRY_DELAY * task["attempts"]), task["id"]))
    else:
        conn.execute("UPDATE worker_tasks SET status='failed', error=?, finished_at=?, lease_expires=NULL, "
                     "progress=NULL WHERE id=?", (error, _ts(), task["id"]))
        _call_error(conn, task["call_id"], task["kind"], error)
    conn.commit()


def cancel(conn, *, pid: int | None = None, ids: list[int] | None = None) -> int:
    """Cancel open tasks: those of one pipeline process, specific ones, or (no filter) all of them. A running task
    is dropped by its agent at the next heartbeat."""
    clauses, args = ["status IN ('queued', 'running')"], []
    if pid is not None:
        clauses.append("origin_pid=?")
        args.append(pid)
    if ids is not None:
        if not ids:
            return 0
        clauses.append(f"id IN ({','.join('?' * len(ids))})")
        args += ids
    count = conn.execute(f"UPDATE worker_tasks SET status='cancelled', finished_at=?, lease_expires=NULL "
                         f"WHERE {' AND '.join(clauses)}", (_ts(), *args)).rowcount
    conn.commit()
    return count


def release(conn, pid: int):
    """The pipeline process stops waiting: the tasks it leaves queued stay for the agents but are no longer its own."""
    conn.execute("UPDATE worker_tasks SET origin_pid=NULL WHERE origin_pid=?", (pid,))
    conn.commit()


def task_rows(conn, ids) -> list:
    ids = list(ids)
    if not ids:
        return []
    return conn.execute(f"SELECT * FROM worker_tasks WHERE id IN ({','.join('?' * len(ids))})", ids).fetchall()


def running_for(conn, worker_id: str) -> list[dict]:
    rows = conn.execute("SELECT id, kind, call_id, progress, started_at FROM worker_tasks "
                        "WHERE worker_id=? AND status='running' ORDER BY id", (worker_id,))
    return [dict(r) for r in rows]


def recent_tasks(conn, limit: int = 50) -> list[dict]:
    """Open tasks first, then the latest finished ones, with the call they're about."""
    rows = conn.execute(
        """SELECT t.*, c.filename, c.agent AS extension, c.customer, c.date_call
           FROM worker_tasks t LEFT JOIN calls c ON c.id = t.call_id
           ORDER BY CASE WHEN t.status IN ('queued', 'running') THEN 0 ELSE 1 END, t.id DESC LIMIT ?""", (limit,))
    return [dict(r) for r in rows]


def queue_counts(conn) -> dict:
    counts = {"queued": 0, "running": 0}
    for status, n in conn.execute("SELECT status, COUNT(*) FROM worker_tasks "
                                  "WHERE status IN ('queued', 'running') GROUP BY status"):
        counts[status] = n
    return counts


def worker_stats(conn) -> dict[str, dict]:
    """worker id -> finished task counts, for the agents page."""
    stats: dict[str, dict] = {}
    for worker_id, status, n in conn.execute("SELECT worker_id, status, COUNT(*) FROM worker_tasks "
                                             "WHERE worker_id IS NOT NULL AND status IN ('done', 'failed') "
                                             "GROUP BY worker_id, status"):
        stats.setdefault(worker_id, {"done": 0, "failed": 0})[status] = n
    return stats
