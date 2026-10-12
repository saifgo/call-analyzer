import json
import re
import sqlite3

from .config import live, settings
from .crm import match_key

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
    voice           TEXT,   -- JSON from voice.py: what the recording sounds like (emotion, loudness, pitch)
    voice_at        TEXT,
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
-- Notes people write about a call (several per call). Independent of the AI analysis, so re-analyzing keeps them.
CREATE TABLE IF NOT EXISTS feedback (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    call_id     TEXT NOT NULL,
    author      TEXT NOT NULL,
    body        TEXT NOT NULL,
    score       INTEGER,
    created_at  TEXT NOT NULL,
    updated_at  TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_feedback_call ON feedback(call_id);
CREATE TABLE IF NOT EXISTS users (
    username       TEXT PRIMARY KEY,
    password_hash  TEXT NOT NULL,
    created_at     TEXT NOT NULL,
    role           TEXT NOT NULL DEFAULT 'admin',
    display_name   TEXT,
    crm_member_id  TEXT     -- the CRM (Twenty) workspace member this account is, e.g. to own the leads it adds
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
-- Remote agents: PCs that connect to this server and do the transcription / analysis (see workers.py).
CREATE TABLE IF NOT EXISTS workers (
    id          TEXT PRIMARY KEY,
    name        TEXT NOT NULL,
    token_hash  TEXT NOT NULL UNIQUE,
    enabled     INTEGER NOT NULL DEFAULT 1,
    created_at  TEXT NOT NULL,
    created_by  TEXT,
    last_seen   TEXT,
    info        TEXT   -- JSON the agent reports: host, os, version, capabilities, its own overrides
);
CREATE TABLE IF NOT EXISTS worker_tasks (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    kind           TEXT NOT NULL,      -- transcribe | analyze
    call_id        TEXT NOT NULL,
    status         TEXT NOT NULL DEFAULT 'queued',   -- queued | running | done | failed | cancelled
    worker_id      TEXT,
    worker_name    TEXT,
    attempts       INTEGER NOT NULL DEFAULT 0,
    chain          INTEGER NOT NULL DEFAULT 0,       -- analyze right after the transcript arrives
    origin_pid     INTEGER,            -- the pipeline process waiting for this task
    progress       TEXT,
    error          TEXT,
    created_at     TEXT NOT NULL,
    not_before     TEXT,
    started_at     TEXT,
    lease_expires  TEXT,
    finished_at    TEXT
);
-- One open task per call and step, so running a step twice doesn't process a call twice.
CREATE UNIQUE INDEX IF NOT EXISTS idx_tasks_open ON worker_tasks(kind, call_id) WHERE status IN ('queued', 'running');
CREATE INDEX IF NOT EXISTS idx_tasks_status ON worker_tasks(status, kind);
-- Operations (see operations.py): each time a CRM contact is served to an agent on the call desk, and the
-- callbacks agents schedule (status 'scheduled' until they are due and served).
CREATE TABLE IF NOT EXISTS op_calls (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    opportunity_id   TEXT NOT NULL,
    person_id        TEXT,
    lead             TEXT,      -- JSON: the opportunity and its contact as the CRM had them when served
    source           TEXT NOT NULL,     -- queue | callback | direct (agent's pick) | test (see start_test)
    status           TEXT NOT NULL,     -- scheduled | assigned | in_call | done | released | cancelled
    agent            TEXT,              -- the account serving it
    due_at           TEXT,              -- callbacks: when to call
    assign_to        TEXT,              -- callbacks only this account may take (NULL: anyone)
    scheduled_by     TEXT,
    scheduled_from   INTEGER,           -- the op_call where the callback was booked
    callback_note    TEXT,
    assigned_at      TEXT,
    call_started_at  TEXT,
    call_ended_at    TEXT,
    finished_at      TEXT,
    answers          TEXT,              -- JSON: the data gathered during the call
    outcome          TEXT,
    note             TEXT,
    stage_before     TEXT,
    stage_after      TEXT,
    crm_note_id      TEXT,
    crm_error        TEXT,
    created_at       TEXT NOT NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_op_open ON op_calls(opportunity_id) WHERE status IN ('assigned', 'in_call');
CREATE INDEX IF NOT EXISTS idx_op_status ON op_calls(status, due_at);
CREATE INDEX IF NOT EXISTS idx_op_agent ON op_calls(agent, status);
CREATE INDEX IF NOT EXISTS idx_op_opportunity ON op_calls(opportunity_id);
-- Who is taking calls on the desk right now, and the campaign they work (campaign_id, added later).
CREATE TABLE IF NOT EXISTS op_agents (
    username   TEXT PRIMARY KEY,
    ready      INTEGER NOT NULL DEFAULT 0,
    since      TEXT,
    last_seen  TEXT
);
-- Call desk campaigns (see campaigns.py): which CRM stages make the queue, what agents ask and how calls can end.
CREATE TABLE IF NOT EXISTS op_campaigns (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    name             TEXT NOT NULL,
    description      TEXT,
    stages           TEXT NOT NULL,     -- JSON list: the CRM opportunity stages the queue is made of
    questions        TEXT NOT NULL,     -- JSON (see campaigns.validate_questions)
    outcomes         TEXT NOT NULL,     -- JSON (see campaigns.validate_outcomes)
    max_attempts     INTEGER NOT NULL DEFAULT 0,    -- unanswered calls in a row before giving up (0: no limit)
    retry_minutes    INTEGER NOT NULL DEFAULT 120,  -- when to try again after an unanswered call
    exhausted_stage  TEXT,              -- stage for a contact that never answered max_attempts times
    call_start       TEXT,              -- calling hours, "HH:MM" (NULL: any time)
    call_end         TEXT,
    call_days        TEXT,              -- ISO weekdays the queue is served, e.g. "1,2,3,4,5,6" (NULL: every day)
    active           INTEGER NOT NULL DEFAULT 1,
    position         INTEGER NOT NULL DEFAULT 0,
    created_at       TEXT NOT NULL,
    updated_at       TEXT NOT NULL
);
-- Seconds each agent spent taking calls on the desk, per day (for the KPIs: calls per hour, talk time share).
CREATE TABLE IF NOT EXISTS op_presence (
    username       TEXT NOT NULL,
    day            TEXT NOT NULL,
    ready_seconds  INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (username, day)
);
-- Browser softphone (see softphone.py): the GoVoice SIP extension each account signs in with. password is the
-- SIP password, fetched from GoVoice with the account's GoVoice login (govoice_user / account_password).
-- password, account_password and access_token are encrypted (see vault.py).
CREATE TABLE IF NOT EXISTS softphones (
    username    TEXT PRIMARY KEY,
    extension   TEXT NOT NULL,
    password    TEXT NOT NULL,
    updated_at  TEXT NOT NULL
);
-- Call desk quick actions: WhatsApp templates an agent sends the contact in one click (see whatsapp.py).
CREATE TABLE IF NOT EXISTS wa_actions (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    label            TEXT NOT NULL,     -- the button, e.g. "Price list"
    template         TEXT NOT NULL,
    language         TEXT NOT NULL,
    params           TEXT,              -- JSON: {"body.1": "contact_name" | "agent_name" | "lead_name" | "text:..."}
    header_link      TEXT,              -- the file a document/image/video header sends
    header_filename  TEXT,
    position         INTEGER NOT NULL DEFAULT 0,
    created_at       TEXT NOT NULL
);
-- WhatsApp messages sent from the desk (status: sent | failed).
CREATE TABLE IF NOT EXISTS wa_messages (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    op_id            INTEGER,
    action_id        INTEGER,
    label            TEXT NOT NULL,
    template         TEXT NOT NULL,
    to_number        TEXT NOT NULL,
    status           TEXT NOT NULL,
    wa_message_id    TEXT,
    error            TEXT,
    sent_by          TEXT NOT NULL,
    sent_at          TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_wa_messages_op ON wa_messages(op_id);
"""

# Columns added after the first release; connect() adds them to older databases.
_ADDED_COLUMNS = {"transcribed_by": "TEXT", "analyzed_by": "TEXT", "updated_at": "TEXT", "voice": "TEXT",
                  "voice_at": "TEXT"}
# Accounts that existed before roles keep full access.
_ADDED_USER_COLUMNS = {"role": "TEXT NOT NULL DEFAULT 'admin'", "display_name": "TEXT", "crm_member_id": "TEXT"}
_ADDED_SOFTPHONE_COLUMNS = {"govoice_user": "TEXT", "account_password": "TEXT", "sip_user": "TEXT",
                            "access_token": "TEXT"}
# campaign_id: the campaign the call belongs to (NULL: the first campaign, from before campaigns existed);
# phone: the number dialed; call_id: the GoVoice recording of the call (see operations.link_recordings).
_ADDED_OP_COLUMNS = {"campaign_id": "INTEGER", "phone": "TEXT", "call_id": "TEXT"}
_ADDED_OP_AGENT_COLUMNS = {"campaign_id": "INTEGER"}
# The softphone columns holding credentials, encrypted at rest (see vault.py).
SOFTPHONE_SECRETS = ("password", "account_password", "access_token")

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
    existing_phone = {r[1] for r in conn.execute("PRAGMA table_info(softphones)")}
    missing_phone = {k: v for k, v in _ADDED_SOFTPHONE_COLUMNS.items() if k not in existing_phone}
    for name, kind in missing_phone.items():
        conn.execute(f"ALTER TABLE softphones ADD COLUMN {name} {kind}")
    added_op = _add_columns(conn, "op_calls", _ADDED_OP_COLUMNS) | _add_columns(conn, "op_agents", _ADDED_OP_AGENT_COLUMNS)
    # One desk call per recording.
    conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_op_recording ON op_calls(call_id) WHERE call_id IS NOT NULL")
    if missing or missing_user or missing_phone or added_op:
        conn.commit()
    _encrypt_softphones(conn)


def _add_columns(conn: sqlite3.Connection, table: str, columns: dict[str, str]) -> set[str]:
    existing = {r[1] for r in conn.execute(f"PRAGMA table_info({table})")}
    for name, kind in columns.items():
        if name not in existing:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {name} {kind}")
    return set(columns) - existing


def _encrypt_softphones(conn: sqlite3.Connection) -> None:
    """Encrypt the credentials saved before they were encrypted at rest."""
    plain = " OR ".join(f"({c} != '' AND {c} NOT LIKE 'enc1:%')" for c in SOFTPHONE_SECRETS)
    rows = conn.execute(f"SELECT username, {', '.join(SOFTPHONE_SECRETS)} FROM softphones WHERE {plain}").fetchall()
    if not rows:
        return
    from . import vault
    for row in rows:
        conn.execute(f"UPDATE softphones SET {', '.join(f'{c} = ?' for c in SOFTPHONE_SECRETS)} WHERE username = ?",
                     [vault.encrypt(row[c]) for c in SOFTPHONE_SECRETS] + [row["username"]])
    conn.commit()


def connect() -> sqlite3.Connection:
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(settings.db_path, timeout=30, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")  # the UI reads while pipeline jobs write
    conn.executescript(SCHEMA)
    _migrate(conn)
    conn.executescript(TRIGGERS)
    # SQL skip_listed(caller, called): whether a call involves a number in SKIP_NUMBERS, as saved when connecting.
    keys = skip_keys()

    def skip_listed(*numbers) -> int:
        return int(bool(keys) and any(_number_key(n) in keys for n in numbers))

    conn.create_function("skip_listed", 2, skip_listed, deterministic=True)
    return conn


def _number_key(number: str | None) -> str:
    """Phone numbers compare on their last 8 digits (with or without +216, like the CRM); extensions as they are."""
    digits = re.sub(r"\D", "", number or "")
    return match_key(digits) or digits


def skip_keys() -> set[str]:
    """The numbers in SKIP_NUMBERS (e.g. our own phones, called to test the line): their calls aren't processed."""
    return {key for n in re.split(r"[,;]", live("SKIP_NUMBERS")) if (key := _number_key(n))}


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
        min_duration = 0  # explicitly chosen calls are always processed, even short or skip-listed ones
    else:
        clauses.append("NOT skip_listed(caller, called)")
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


def feedback_by_call(conn, call_ids) -> dict[str, list[dict]]:
    """Human feedback for these calls (oldest first), keyed by call id: author, note and the reviewer's own score."""
    call_ids = list(call_ids)
    by_call: dict[str, list[dict]] = {}
    for start in range(0, len(call_ids), 500):  # stay under SQLite's variable limit
        chunk = call_ids[start:start + 500]
        rows = conn.execute(
            f"""SELECT f.call_id, COALESCE(u.display_name, f.author) AS author, f.body, f.score
                FROM feedback f LEFT JOIN users u ON u.username = f.author
                WHERE f.call_id IN ({','.join('?' * len(chunk))}) ORDER BY f.created_at, f.id""", chunk)
        for row in rows:
            by_call.setdefault(row["call_id"], []).append(
                {"reviewer": row["author"], "note": row["body"], "reviewer_score": row["score"]})
    return by_call
