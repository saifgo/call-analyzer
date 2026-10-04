import json
import sqlite3

from .config import settings

SCHEMA = """
CREATE TABLE IF NOT EXISTS calls (
    id              TEXT PRIMARY KEY,
    type            TEXT,
    caller          TEXT,
    called          TEXT,
    agent           TEXT,
    customer        TEXT,
    date_call       TEXT,
    duration        INTEGER,
    size_kb         INTEGER,
    filename        TEXT,
    raw             TEXT,
    audio_path      TEXT,
    transcript      TEXT,
    transcribed_at  TEXT,
    transcribed_by  TEXT,
    analysis        TEXT,
    analyzed_at     TEXT,
    analyzed_by     TEXT,
    error           TEXT,
    updated_at      TEXT
);
CREATE INDEX IF NOT EXISTS idx_calls_date ON calls(date_call);
CREATE INDEX IF NOT EXISTS idx_calls_agent ON calls(agent);
CREATE TABLE IF NOT EXISTS shares (
    token       TEXT PRIMARY KEY,
    call_id     TEXT NOT NULL,
    created_at  TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS report_shares (
    token       TEXT PRIMARY KEY,
    report_name TEXT NOT NULL UNIQUE,
    created_at  TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS users (
    username       TEXT PRIMARY KEY,
    password_hash  TEXT NOT NULL,
    created_at     TEXT NOT NULL,
    role           TEXT NOT NULL DEFAULT 'admin',
    display_name   TEXT
);
-- Agent accounts only see calls and reports of the extensions linked here (one account, one or more extensions).
CREATE TABLE IF NOT EXISTS user_agents (
    username  TEXT NOT NULL,
    agent     TEXT NOT NULL,
    PRIMARY KEY (username, agent)
);
CREATE TABLE IF NOT EXISTS sessions (
    token_hash  TEXT PRIMARY KEY,
    username    TEXT NOT NULL,
    created_at  TEXT NOT NULL,
    expires_at  TEXT NOT NULL
);
"""

# Columns added after the first release; connect() adds them to older databases.
_ADDED_COLUMNS = {"transcribed_by": "TEXT", "analyzed_by": "TEXT", "updated_at": "TEXT"}
# Accounts that existed before roles keep full access.
_ADDED_USER_COLUMNS = {"role": "TEXT NOT NULL DEFAULT 'admin'", "display_name": "TEXT"}

_NOW_SQL = "strftime('%Y-%m-%dT%H:%M:%S', 'now', 'localtime')"  # same format as datetime.isoformat()

# Any change to a call row bumps updated_at, whoever writes it (pipeline, web UI, manual SQL).
TRIGGERS = f"""
CREATE TRIGGER IF NOT EXISTS calls_touch_insert AFTER INSERT ON calls FOR EACH ROW WHEN NEW.updated_at IS NULL
BEGIN UPDATE calls SET updated_at = {_NOW_SQL} WHERE id = NEW.id; END;
CREATE TRIGGER IF NOT EXISTS calls_touch_update AFTER UPDATE ON calls FOR EACH ROW
WHEN NEW.updated_at IS OLD.updated_at
BEGIN UPDATE calls SET updated_at = {_NOW_SQL} WHERE id = NEW.id; END;
"""


def _migrate(conn: sqlite3.Connection) -> None:
    existing = {r[1] for r in conn.execute("PRAGMA table_info(calls)")}
    missing = {k: v for k, v in _ADDED_COLUMNS.items() if k not in existing}
    for name, kind in missing.items():
        conn.execute(f"ALTER TABLE calls ADD COLUMN {name} {kind}")
    if "updated_at" in missing:
        # Best guess for existing rows: the latest pipeline step, else when the call happened.
        conn.execute("""UPDATE calls SET updated_at = CASE
            WHEN COALESCE(transcribed_at, '') > COALESCE(analyzed_at, '') THEN transcribed_at
            ELSE COALESCE(analyzed_at, REPLACE(date_call, ' ', 'T')) END""")
    existing_user = {r[1] for r in conn.execute("PRAGMA table_info(users)")}
    missing_user = {k: v for k, v in _ADDED_USER_COLUMNS.items() if k not in existing_user}
    for name, kind in missing_user.items():
        conn.execute(f"ALTER TABLE users ADD COLUMN {name} {kind}")
    if missing or missing_user:
        conn.commit()


def connect() -> sqlite3.Connection:
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(settings.db_path, timeout=30, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")  # the UI reads while pipeline jobs write
    conn.executescript(SCHEMA)
    _migrate(conn)
    conn.executescript(TRIGGERS)
    return conn


def _is_extension(number: str) -> bool:
    return number.isdigit() and len(number) <= 5


def split_parties(rec: dict) -> tuple[str, str]:
    """Return (agent_extension, customer_number) for a GoVoice recording row."""
    caller, called = rec.get("caller", ""), rec.get("called", "")
    if rec.get("type") == "OUT" or (_is_extension(caller) and not _is_extension(called)):
        return caller, called
    return called, caller


def upsert_recordings(conn: sqlite3.Connection, records: list[dict]) -> int:
    new = 0
    for rec in records:
        agent, customer = split_parties(rec)
        cur = conn.execute(
            """INSERT INTO calls (id, type, caller, called, agent, customer, date_call,
                                  duration, size_kb, filename, raw)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(id) DO NOTHING""",
            (
                rec["id"], rec.get("type"), rec.get("caller"), rec.get("called"), agent, customer,
                rec.get("date_call"), int(rec.get("duree") or 0), int(rec.get("size") or 0),
                rec.get("filename"), json.dumps(rec, ensure_ascii=False),
            ),
        )
        new += cur.rowcount
    conn.commit()
    return new


def select_calls(conn, *, where: str = "1=1", params: tuple = (), since=None, until=None,
                 agent=None, min_duration=0, limit=None, ids=None) -> list[sqlite3.Row]:
    clauses, args = [where], list(params)
    if ids:
        clauses.append(f"id IN ({','.join('?' * len(ids))})")
        args.extend(ids)
        min_duration = 0  # explicitly chosen calls are always processed
    if since:
        clauses.append("date_call >= ?")
        args.append(since)
    if until:
        clauses.append("date_call < ?")
        args.append(until)
    if agent:
        clauses.append("agent = ?")
        args.append(agent)
    if min_duration:
        clauses.append("duration >= ?")
        args.append(min_duration)
    sql = f"SELECT * FROM calls WHERE {' AND '.join(clauses)} ORDER BY date_call DESC"
    if limit:
        sql += f" LIMIT {int(limit)}"
    return conn.execute(sql, args).fetchall()
