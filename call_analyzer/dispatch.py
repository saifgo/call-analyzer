"""Where a pipeline step runs: on this host, or as tasks for remote agents (see workers.py).

TRANSCRIBE_RUNS_ON / ANALYZE_RUNS_ON in Settings choose, per step:
- host:  this server does it, as before.
- agent: only agents do it. If none is connected the calls stay queued and are processed whenever one connects;
         the host never takes over.
- auto:  agents while one is online, otherwise the host (also when the last agent drops out mid-run).
"""
import os
import sys
import time

from . import db, workers
from .config import runs_on

POLL_SECONDS = 2
OFFLINE_GRACE = 30  # seconds without any agent online before the step stops waiting for them

_DONE_WORD = {"transcribe": "transcribed", "analyze": "analyzed"}
_FINISHED = ("done", "failed", "cancelled")


def _names(online: list[dict]) -> str:
    return ", ".join(w["name"] for w in online)


def process(kind: str, calls: list, local, *, chain: bool = False):
    """Do `kind` for `calls`. `local(calls)` is the host's own implementation of the step.

    chain: the same pipeline run goes on to analyze these calls, so when a transcript arrives the server queues
    the analysis itself, even if this process has stopped waiting by then."""
    mode = runs_on(kind)
    if mode == "host" or not calls:
        return local(calls)
    conn = db.connect()
    online = workers.online_workers(conn, kind)
    if mode == "auto" and not online:
        print(f"No agent is online for {kind}; doing it on this server.")
        return local(calls)

    pid = os.getpid()
    by_call = {c["id"]: c for c in calls}
    task_ids = workers.enqueue(conn, kind, list(by_call), chain=chain, origin_pid=pid)
    if not online:
        workers.release(conn, pid)
        print(f"No agent is online. {len(task_ids)} calls are queued and will be {_DONE_WORD[kind]} when an agent "
              "connects (Agents page).")
        return
    print(f"{len(task_ids)} calls queued for remote agents ({_names(online)} online).")

    pending, finished, offline_since = set(task_ids), 0, None
    try:
        while pending:
            time.sleep(POLL_SECONDS)
            workers.requeue_expired(conn)
            open_ids = set()
            for task in workers.task_rows(conn, pending):
                call = by_call.get(task["call_id"])
                name = call["filename"] if call else task["call_id"]
                if task["status"] in _FINISHED:
                    finished += 1
                    if task["status"] == "done":
                        print(f"  [{finished}/{len(task_ids)}] {_DONE_WORD[kind]} {name} (agent {task['worker_name']})")
                    else:
                        print(f"  [{finished}/{len(task_ids)}] {task['status'].upper()} {name}: {task['error'] or ''}",
                              file=sys.stderr)
                else:
                    open_ids.add(task["id"])
            pending = open_ids
            if not pending:
                break
            online = workers.online_workers(conn, kind)
            if online:
                offline_since = None
                continue
            offline_since = offline_since or time.time()
            if time.time() - offline_since < OFFLINE_GRACE:
                continue
            if mode == "agent":
                workers.release(conn, pid)
                print(f"All agents went offline. {len(pending)} calls stay queued and will be "
                      f"{_DONE_WORD[kind]} when an agent connects.")
                return
            # auto: take back what the agents didn't finish and do it here.
            rows = workers.task_rows(conn, pending)
            workers.cancel(conn, ids=list(pending))
            remaining = [by_call[r["call_id"]] for r in rows if r["call_id"] in by_call]
            print(f"All agents went offline; doing the remaining {len(remaining)} calls on this server.")
            return local(remaining)
    finally:
        workers.release(conn, pid)
