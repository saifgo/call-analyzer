"""The database: PostgreSQL, at DATABASE_URL.

The code was written against Python's sqlite3 module, and this thin layer keeps that interface so the queries read the
same: `?` placeholders, rows readable by position and by column name, `cursor.lastrowid`, and sqlite3's transactions
(one starts at the first INSERT/UPDATE/DELETE and lasts until commit(); reads outside one see committed data at once).
Connections come from a pool and go back to it when closed or no longer used. See docs/postgres-migration.md.
"""
import atexit
import gc
import json
import logging
import os
import re
import sys
import threading
import weakref
from collections import Counter
from contextlib import contextmanager
from datetime import datetime
from decimal import Decimal
from functools import lru_cache
from pathlib import Path

import psycopg
from psycopg import pq
from psycopg.adapt import Dumper, Loader
from psycopg_pool import ConnectionPool, PoolTimeout

from .config import live, settings
from .phones import match_key

log = logging.getLogger(__name__)

IntegrityError = psycopg.IntegrityError
Error = psycopg.Error

MIGRATIONS_DIR = Path(__file__).with_name("migrations")
_MIGRATION_LOCK = 724_190_001  # pg_advisory lock id: one process at a time applies migrations

# Tables whose id the database assigns: an INSERT into one returns it, for cursor.lastrowid.
_IDENTITY_TABLES = frozenset({
    "feedback", "worker_tasks", "op_calls", "op_campaigns", "op_pause_reasons", "op_pauses", "op_shifts",
    "op_idle_prompts", "wa_actions", "wa_messages", "op_inbound",
})
_INSERT_RE = re.compile(r"^\s*INSERT\s+INTO\s+(\w+)", re.IGNORECASE)
_WRITE_RE = re.compile(r"^\s*(INSERT|UPDATE|DELETE)\b", re.IGNORECASE)

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
-- The floor (see floor.py): daily targets ('*' is the team, NULL columns of an agent take the team's value, 0: none),
-- the reasons agents pause for, each pause taken, and settings such as the workday.
CREATE TABLE IF NOT EXISTS op_targets (
    username      TEXT PRIMARY KEY,
    calls         INTEGER,
    reached       INTEGER,
    wins          INTEGER,
    desk_minutes  INTEGER
);
CREATE TABLE IF NOT EXISTS op_pause_reasons (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    label          TEXT NOT NULL,
    limit_minutes  INTEGER NOT NULL DEFAULT 0,   -- 0: no limit
    position       INTEGER NOT NULL DEFAULT 0,
    active         INTEGER NOT NULL DEFAULT 1
);
CREATE TABLE IF NOT EXISTS op_pauses (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    username       TEXT NOT NULL,
    reason_id      INTEGER,
    label          TEXT NOT NULL,     -- the reason and its limit as they were when the pause started
    limit_minutes  INTEGER NOT NULL DEFAULT 0,
    started_at     TEXT NOT NULL,
    ended_at       TEXT,              -- moved forward at each check-in while the pause lasts
    closed         INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_op_pauses ON op_pauses(username, started_at);
-- Agents' shifts (see floor.py): from when they clock in to when they clock out. A shift nobody clocked out of ends on
-- its own (ended_by 'auto') after the workday, or at its last check-in when the desk was closed.
CREATE TABLE IF NOT EXISTS op_shifts (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    username    TEXT NOT NULL,
    started_at  TEXT NOT NULL,
    ended_at    TEXT,              -- moved forward at each check-in while the shift lasts
    closed      INTEGER NOT NULL DEFAULT 0,
    ended_by    TEXT               -- agent, admin or auto
);
CREATE INDEX IF NOT EXISTS idx_op_shifts ON op_shifts(username, started_at);
-- Agents taking calls who stayed idle long enough to be prompted to call (see idle.py): one row per idle stretch.
CREATE TABLE IF NOT EXISTS op_idle_prompts (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    username        TEXT NOT NULL,
    idle_since      TEXT NOT NULL,
    prompted_at     TEXT NOT NULL,     -- the first prompt
    last_prompt_at  TEXT NOT NULL,
    prompts         INTEGER NOT NULL DEFAULT 1,
    acknowledged    INTEGER NOT NULL DEFAULT 0,   -- how many of them the agent dismissed
    doing           TEXT,              -- served a contact and didn't dial, or no contact served
    ended_at        TEXT NOT NULL,     -- moved forward at each check-in while the stretch lasts
    outcome         TEXT,              -- once closed: called, paused or left (the desk stopped checking in)
    closed          INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_op_idle_prompts ON op_idle_prompts(username, prompted_at);
CREATE TABLE IF NOT EXISTS op_settings (
    key    TEXT PRIMARY KEY,
    value  TEXT
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
-- Calls that rang an agent's browser softphone (see inbound.py): one row per ring. A missed one waits on the desk's
-- missed calls list until someone calls the number back, the caller gets through, or it's dismissed.
CREATE TABLE IF NOT EXISTS op_inbound (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    agent           TEXT NOT NULL,     -- the account whose phone rang
    number          TEXT NOT NULL,     -- the caller, as the phone system gave it
    number_key      TEXT NOT NULL,     -- what numbers are compared on (db.number_key)
    caller_name     TEXT,              -- the name the phone system showed
    rang_at         TEXT NOT NULL,
    answered_at     TEXT,
    ended_at        TEXT,
    result          TEXT NOT NULL,     -- ringing | answered | missed | declined | busy | elsewhere
    op_id           INTEGER,           -- answered: the desk call opened for it
    followup_op_id  INTEGER,           -- missed: the desk call serving the callback
    resolved_at     TEXT,              -- missed: when it was dealt with
    resolved_by     TEXT,
    resolution      TEXT               -- called_back | got_through | dismissed
);
CREATE INDEX IF NOT EXISTS idx_op_inbound_key ON op_inbound(number_key, rang_at);
CREATE INDEX IF NOT EXISTS idx_op_inbound_open ON op_inbound(resolved_at, result);
-- The built-in CRM (adapters/crm/internal.py): contacts, their phone numbers, their opportunities (leads) moving
-- along the stages, and notes. Ids are UUIDs, like an external CRM's, so the call desk treats them the same way.
CREATE TABLE IF NOT EXISTS crm_people (
    id               TEXT PRIMARY KEY,
    name             TEXT NOT NULL,
    email            TEXT,
    job_title        TEXT,
    city             TEXT,
    company          TEXT,
    fields           TEXT,              -- JSON {key: value} of the custom fields (crm_fields)
    source           TEXT,              -- desk | import | api | inbound | twenty | manual
    created_at       TEXT NOT NULL,
    updated_at       TEXT NOT NULL,
    last_contact_at  TEXT
);
CREATE INDEX IF NOT EXISTS idx_crm_people_created ON crm_people(created_at);
CREATE TABLE IF NOT EXISTS crm_phones (
    person_id   TEXT NOT NULL,
    position    INTEGER NOT NULL,      -- 0: the primary number
    number      TEXT NOT NULL,         -- as shown, e.g. "+216 22602716"
    number_key  TEXT NOT NULL,         -- phones.match_key (last 8 digits), else the digits
    PRIMARY KEY (person_id, position)
);
CREATE INDEX IF NOT EXISTS idx_crm_phones_key ON crm_phones(number_key);
CREATE TABLE IF NOT EXISTS crm_opportunities (
    id          TEXT PRIMARY KEY,
    name        TEXT NOT NULL,
    person_id   TEXT,
    stage       TEXT NOT NULL,
    amount      REAL,
    currency    TEXT,
    close_date  TEXT,
    owner       TEXT,                  -- the app account (users.username) that owns it
    created_at  TEXT NOT NULL,
    updated_at  TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_crm_opp_stage ON crm_opportunities(stage, created_at, id);
CREATE INDEX IF NOT EXISTS idx_crm_opp_person ON crm_opportunities(person_id);
CREATE TABLE IF NOT EXISTS crm_notes (
    id              TEXT PRIMARY KEY,
    title           TEXT NOT NULL,
    body            TEXT NOT NULL,     -- markdown: **bold**, one line per paragraph
    opportunity_id  TEXT,
    person_id       TEXT,
    author          TEXT,              -- users.username, or a name when imported
    created_at      TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_crm_notes_opp ON crm_notes(opportunity_id, created_at);
CREATE INDEX IF NOT EXISTS idx_crm_notes_person ON crm_notes(person_id, created_at);
-- The pipeline, in order. Locked stages (New, Attempted) can be renamed but not removed: the call queue uses them.
CREATE TABLE IF NOT EXISTS crm_stages (
    value     TEXT PRIMARY KEY,
    label     TEXT NOT NULL,
    position  INTEGER NOT NULL,
    locked    INTEGER NOT NULL DEFAULT 0
);
-- Custom contact fields admins define; campaign questions copy answers to them (crm: "person.<key>").
CREATE TABLE IF NOT EXISTS crm_fields (
    key       TEXT PRIMARY KEY,
    label     TEXT NOT NULL,
    type      TEXT NOT NULL,           -- text | number | boolean | choice
    options   TEXT,                    -- JSON [[value, label], ...] for choice
    position  INTEGER NOT NULL
);
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
# pause_id: the op_pauses row of the pause the agent is on (see floor.py); online_since: when their desk last came
# online after being offline (see idle.py); shift_id: the op_shifts row of the shift they're clocked in to.
_ADDED_OP_AGENT_COLUMNS = {"campaign_id": "INTEGER", "pause_id": "INTEGER", "online_since": "TEXT",
                           "shift_id": "INTEGER"}
# earned: an earned break (see breaks.py) rather than a pause for one of the reasons.
_ADDED_OP_PAUSE_COLUMNS = {"earned": "INTEGER NOT NULL DEFAULT 0"}
# kind: outbound (a queue of CRM contacts to call) or inbound (the one campaign for calls customers make to us).
_ADDED_CAMPAIGN_COLUMNS = {"kind": "TEXT NOT NULL DEFAULT 'outbound'"}
# The softphone columns holding credentials, encrypted at rest (see vault.py).
SOFTPHONE_SECRETS = ("password", "account_password", "access_token")


def database_url() -> str:
    url = os.getenv("DATABASE_URL", "").strip()
    if not url:
        raise RuntimeError("DATABASE_URL is not set: the PostgreSQL database to use, e.g. "
                           "postgresql://call_analyzer:password@localhost:5432/call_analyzer")
    return url


# --- Types -----------------------------------------------------------------------------------------------------------

class _UntypedIntDumper(Dumper):
    """Python ints go to PostgreSQL untyped, so it reads them as the column they meet: `text_col = 5` works, as it did
    in SQLite, instead of failing on text = integer."""
    oid = 0

    def dump(self, obj):
        return str(int(obj)).encode()


class _NumericLoader(Loader):
    """AVG(), ROUND() and SUM() of big integers return numeric: read it as int when whole, else float (never
    Decimal, which json.dumps can't write), like SQLite did."""

    def load(self, data):
        value = Decimal(bytes(data).decode())
        return int(value) if value == value.to_integral_value() else float(value)


class Row:
    """A result row, like sqlite3.Row: row[0], row["name"], keys(), dict(row)."""
    __slots__ = ("_values", "_names")

    def __init__(self, values, names: dict[str, int]):
        self._values = values
        self._names = names

    def keys(self) -> list[str]:
        return list(self._names)

    def __getitem__(self, key):
        if isinstance(key, str):
            try:
                return self._values[self._names[key]]
            except KeyError:
                # PostgreSQL folds unquoted names to lower case; sqlite3.Row matched names case-insensitively.
                lowered = key.lower()
                for name, index in self._names.items():
                    if name.lower() == lowered:
                        return self._values[index]
                raise IndexError(f"No column named {key!r}") from None
        return self._values[key]

    def __iter__(self):
        return iter(self._values)

    def __len__(self):
        return len(self._values)

    def __eq__(self, other):
        if isinstance(other, Row):
            return self._names == other._names and tuple(self._values) == tuple(other._values)
        return NotImplemented

    def __hash__(self):
        return hash(tuple(self._values))

    def __repr__(self):
        return f"Row({dict(zip(self._names, self._values))})"


def _row_factory(cursor):
    names: dict[str, int] = {}
    for index, column in enumerate(cursor.description or ()):
        names.setdefault(column.name, index)  # the first of two same-named columns, as sqlite3.Row
    return lambda values: Row(values, names)


@lru_cache(maxsize=4096)
def _prepare(sql: str) -> tuple[str, bool, bool]:
    """sqlite3 SQL -> psycopg SQL: `?` -> `%s`, and `%` -> `%%` (psycopg reads `%` as a placeholder everywhere).
    Inside quotes and comments only the `%` changes. Returns (query, is_write, returns_id)."""
    out = []
    i, n = 0, len(sql)
    quote = None
    while i < n:
        ch = sql[i]
        if quote:
            if ch == quote:
                quote = None
            out.append("%%" if ch == "%" else ch)
        elif ch in ("'", '"'):
            quote = ch
            out.append(ch)
        elif ch == "-" and sql.startswith("--", i):
            end = sql.find("\n", i)
            end = n if end < 0 else end
            out.append(sql[i:end].replace("%", "%%"))
            i = end
            continue
        elif ch == "?":
            out.append("%s")
        elif ch == "%":
            out.append("%%")
        else:
            out.append(ch)
        i += 1
    query = "".join(out)
    insert = _INSERT_RE.match(query)
    returns_id = bool(insert and insert.group(1).lower() in _IDENTITY_TABLES and "RETURNING" not in query.upper())
    if returns_id:
        query = query.rstrip().rstrip(";") + " RETURNING id"
    return query, bool(_WRITE_RE.match(query)), returns_id


# --- Connections -----------------------------------------------------------------------------------------------------

class Cursor:
    """What Connection.execute returns, like a sqlite3 cursor: fetchone/fetchall/iteration, rowcount, lastrowid."""

    def __init__(self, conn: "Connection", cur, returns_id: bool):
        self._conn = conn  # the connection stays out of the pool while its results are read
        self._cur = cur
        self.rowcount = cur.rowcount
        self.lastrowid = None
        if returns_id:
            rows = cur.fetchall()
            self.lastrowid = rows[-1][0] if rows else None
            self._has_rows = False
        else:
            self._has_rows = cur.description is not None

    @property
    def description(self):
        return self._cur.description

    def fetchone(self):
        return self._cur.fetchone() if self._has_rows else None

    def fetchall(self):
        return self._cur.fetchall() if self._has_rows else []

    def fetchmany(self, size: int = 1):
        return self._cur.fetchmany(size) if self._has_rows else []

    def __iter__(self):
        return iter(self.fetchall())


class Connection:
    """A pooled PostgreSQL connection with the sqlite3.Connection interface the app uses. Goes back to the pool on
    close(), or when nothing refers to it any more (an open transaction is rolled back first, as sqlite3 did)."""

    def __init__(self, pool: ConnectionPool, raw: psycopg.Connection, taken_at: str):
        self._raw = raw
        self._finalizer = weakref.finalize(self, _give_back, pool, raw)
        _taken[raw] = taken_at

    @property
    def raw(self) -> psycopg.Connection:
        if self._raw is None:
            raise psycopg.InterfaceError("the connection is closed")
        return self._raw

    @property
    def in_transaction(self) -> bool:
        return self.raw.info.transaction_status != pq.TransactionStatus.IDLE

    def _begin_for(self, is_write: bool) -> bool:
        if is_write and not self.in_transaction:
            self.raw.execute("BEGIN")
            return True
        return False

    def execute(self, sql: str, params=()) -> Cursor:
        query, is_write, returns_id = _prepare(sql)
        began = self._begin_for(is_write)
        cur = self.raw.cursor()
        try:
            cur.execute(query, list(params))
        except Exception:
            if began:  # the transaction held only this statement: undo it, so the connection stays usable
                self.raw.execute("ROLLBACK")
            raise
        return Cursor(self, cur, returns_id)

    def executemany(self, sql: str, seq_of_params) -> Cursor:
        query, is_write, _ = _prepare(sql)
        began = self._begin_for(is_write)
        cur = self.raw.cursor()
        try:
            cur.executemany(query, [list(p) for p in seq_of_params])
        except Exception:
            if began:
                self.raw.execute("ROLLBACK")
            raise
        return Cursor(self, cur, False)

    def commit(self) -> None:
        status = self.raw.info.transaction_status
        if status == pq.TransactionStatus.INERROR:
            # A statement failed inside the transaction and PostgreSQL dropped all of it: say so rather than lose the
            # writes quietly (sqlite3 kept the transaction going).
            self.raw.execute("ROLLBACK")
            raise psycopg.errors.InFailedSqlTransaction("a statement failed in this transaction: nothing was saved")
        if status != pq.TransactionStatus.IDLE:
            self.raw.execute("COMMIT")

    def rollback(self) -> None:
        if self.in_transaction:
            self.raw.execute("ROLLBACK")

    @contextmanager
    def savepoint(self):
        """Run some statements so that if one fails, only they are undone and the transaction goes on (what sqlite3
        did for every statement), e.g. a write that may lose a race to a unique index."""
        self._begin_for(True)
        self.raw.execute("SAVEPOINT call_analyzer_sp")
        try:
            yield
        except Exception:
            self.raw.execute("ROLLBACK TO SAVEPOINT call_analyzer_sp")
            raise
        self.raw.execute("RELEASE SAVEPOINT call_analyzer_sp")

    def close(self) -> None:
        if self._raw is not None:
            self._raw = None
            self._finalizer()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        # Like sqlite3: commit or roll back, but stay open.
        if exc_type is None:
            self.commit()
        else:
            self.rollback()
        return False


def _give_back(pool: ConnectionPool, raw: psycopg.Connection) -> None:
    _taken.pop(raw, None)
    try:
        if not raw.closed and raw.info.transaction_status != pq.TransactionStatus.IDLE:
            raw.execute("ROLLBACK")
    except Exception:  # broken connection: the pool replaces it
        pass
    try:
        pool.putconn(raw)
    except Exception:
        pass


_pool: ConnectionPool | None = None
_pool_url = ""
_pool_lock = threading.Lock()
# The skip_keys value each pooled connection was last given (see connect()).
_skip_set: "weakref.WeakKeyDictionary[psycopg.Connection, str]" = weakref.WeakKeyDictionary()
# Where each connection out of the pool was taken (file:line), to tell what holds them when the pool runs out.
_taken: "weakref.WeakKeyDictionary[psycopg.Connection, str]" = weakref.WeakKeyDictionary()


def _session_time_zone(raw: psycopg.Connection) -> None:
    """The database's "now" (calls.updated_at) is the server's local time, like everything else the app writes."""
    tz = os.getenv("TZ", "").strip()
    if tz:
        try:
            raw.execute("SELECT set_config('TimeZone', %s, false)", [tz])
            return
        except psycopg.Error:
            pass  # not a zone PostgreSQL knows: use the offset below
    offset = datetime.now().astimezone().utcoffset()
    minutes = int(offset.total_seconds() // 60) if offset else 0
    sign = "-" if minutes < 0 else "+"
    raw.execute(f"SET TIME ZONE INTERVAL '{sign}{abs(minutes) // 60:02d}:{abs(minutes) % 60:02d}' HOUR TO MINUTE")


def _configure(raw: psycopg.Connection) -> None:
    raw.adapters.register_dumper(int, _UntypedIntDumper)
    raw.adapters.register_dumper(bool, _UntypedIntDumper)  # True/False are stored as 1/0, as in SQLite
    raw.adapters.register_loader("numeric", _NumericLoader)
    _session_time_zone(raw)


def get_pool() -> ConnectionPool:
    global _pool, _pool_url
    url = database_url()
    with _pool_lock:
        if _pool is None or _pool_url != url:
            if _pool is not None:
                _pool.close()
            _pool = ConnectionPool(
                url, min_size=1, max_size=int(os.getenv("DB_POOL_SIZE") or 20), timeout=30, open=True,
                kwargs={"autocommit": True, "row_factory": _row_factory, "application_name": "call-analyzer"},
                configure=_configure, check=ConnectionPool.check_connection, name="call-analyzer")
            _pool_url = url
        return _pool


@atexit.register  # before interpreter shutdown, when the pool's threads can still be joined
def close_pool() -> None:
    global _pool
    with _pool_lock:
        if _pool is not None:
            _pool.close()
            _pool = None


def _getconn(pool: ConnectionPool) -> psycopg.Connection:
    try:
        return pool.getconn()
    except PoolTimeout:
        # Every connection is out: some may only be waiting for the garbage collector (a Connection in a reference
        # cycle). Free those and try once more before giving up.
        holders = Counter(_taken.values()).most_common(5)
        log.warning("database pool exhausted (%s connections, taken at %s); collecting unused ones",
                    pool.max_size, ", ".join(f"{where} x{n}" for where, n in holders))
        gc.collect()
        return pool.getconn()


# --- Schema ----------------------------------------------------------------------------------------------------------

def migrate(raw: psycopg.Connection) -> list[str]:
    """Apply the migrations/*.sql files this database hasn't had yet, in order. Returns the ones applied."""
    applied = []
    with raw.transaction():
        raw.execute("SELECT pg_advisory_xact_lock(%s)", [_MIGRATION_LOCK])
        raw.execute("CREATE TABLE IF NOT EXISTS schema_migrations (version TEXT PRIMARY KEY, applied_at TEXT NOT NULL)")
        done = {row[0] for row in raw.execute("SELECT version FROM schema_migrations")}
        for path in sorted(MIGRATIONS_DIR.glob("*.sql")):
            if path.stem in done:
                continue
            raw.execute(path.read_text(encoding="utf-8"))
            raw.execute("INSERT INTO schema_migrations (version, applied_at) VALUES (%s, %s)",
                        [path.stem, datetime.now().isoformat(timespec="seconds")])
            applied.append(path.stem)
    if applied:
        log.info("database migrations applied: %s", ", ".join(applied))
    return applied


def _encrypt_softphones(conn: Connection) -> None:
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


def _check_sqlite_was_copied(conn: Connection) -> None:
    """Refuse to start on an empty PostgreSQL database while the old SQLite one, with data, is still in the data
    folder: the app would run without its data, and what agents did meanwhile would block the copy."""
    old = settings.db_path
    if not old.is_file() or old.stat().st_size == 0:
        return
    if any(conn.execute(f"SELECT EXISTS (SELECT 1 FROM {table})").fetchone()[0]
           for table in ("users", "calls", "op_calls")):
        return
    raise RuntimeError(
        f"The PostgreSQL database is empty but {old} still holds the data from before PostgreSQL. Copy it first: "
        f"python -m call_analyzer db-copy --from {old}  (see docs/postgres-migration.md). To start empty instead, "
        "move that file out of the data folder.")


# Databases this process has already migrated (and checked for unencrypted secrets).
_ready: set[str] = set()
_ready_lock = threading.Lock()


def connect() -> Connection:
    """A connection from the pool. Commit what you write; it goes back to the pool when closed or dropped."""
    pool = get_pool()
    raw = _getconn(pool)
    caller = sys._getframe(1)
    conn = Connection(pool, raw, f"{Path(caller.f_code.co_filename).name}:{caller.f_lineno}")
    # skip_listed() in SQL reads the SKIP_NUMBERS keys from the connection, as saved right now.
    keys = ",".join(sorted(skip_keys()))
    if _skip_set.get(raw) != keys:
        raw.execute("SELECT set_config('call_analyzer.skip_keys', %s, false)", [keys])
        _skip_set[raw] = keys
    if _pool_url not in _ready:
        with _ready_lock:
            if _pool_url not in _ready:
                migrate(raw)
                _check_sqlite_was_copied(conn)
                _encrypt_softphones(conn)
                _ready.add(_pool_url)
    return conn


def number_key(number: str | None) -> str:
    """Phone numbers compare on their last 8 digits (with or without +216, like the CRM); extensions as they are.
    Also an SQL function: number_key(phone)."""
    digits = re.sub(r"\D", "", number or "")
    return match_key(digits) or digits


def skip_keys() -> set[str]:
    """The numbers in SKIP_NUMBERS (e.g. our own phones, called to test the line): their calls aren't processed."""
    return {key for n in re.split(r"[,;]", live("SKIP_NUMBERS")) if (key := number_key(n))}


def _is_extension(number: str) -> bool:
    return number.isdigit() and len(number) <= 5


def split_parties(rec: dict) -> tuple[str, str]:
    """Return (agent_extension, customer_number) for a recording (see adapters/telephony/base.Recording)."""
    caller, called = rec.get("caller", ""), rec.get("called", "")
    if rec.get("type") == "OUT" or (_is_extension(caller) and not _is_extension(called)):
        return caller, called
    return called, caller


def upsert_recordings(conn: Connection, records: list[dict]) -> int:
    """Add the recordings the phone system listed (adapters/telephony/base.Recording) that aren't in yet."""
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
                rec.get("date_call"), int(rec.get("duration") or 0), int(rec.get("size_kb") or 0),
                rec.get("filename"), json.dumps(rec.get("raw", rec), ensure_ascii=False),
            ),
        )
        new += cur.rowcount
    conn.commit()
    return new


def select_calls(conn, *, where: str = "1=1", params: tuple = (), since=None, until=None,
                 agent=None, min_duration=0, limit=None, ids=None) -> list[Row]:
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
    for start in range(0, len(call_ids), 500):  # keeps each query a sane size
        chunk = call_ids[start:start + 500]
        rows = conn.execute(
            f"""SELECT f.call_id, COALESCE(u.display_name, f.author) AS author, f.body, f.score
                FROM feedback f LEFT JOIN users u ON u.username = f.author
                WHERE f.call_id IN ({','.join('?' * len(chunk))}) ORDER BY f.created_at, f.id""", chunk)
        for row in rows:
            by_call.setdefault(row["call_id"], []).append(
                {"reviewer": row["author"], "note": row["body"], "reviewer_score": row["score"]})
    return by_call
