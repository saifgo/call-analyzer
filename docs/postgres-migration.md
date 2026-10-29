# Moving from SQLite to PostgreSQL

Status: code done on branch `feature/postgres` (phases 1–2); staging and the live switch (phases 3–4) are next.
Written 2026-10-29.

## Why SQLite was used, and why move

SQLite fit the first version: one file in the `data` volume (`data/calls.db`), nothing else to install or
operate, and one container on Coolify. It is reliable: transactions are safe and a crash doesn't corrupt it.
The problems come from how the app is used now:

| Problem today | Where it shows | What PostgreSQL changes |
|---|---|---|
| Only one writer at a time for the whole database | Pipeline jobs, the call desk, worker leases and CRM sync all write. Page loads already stalled behind pipeline writes (see the `_ready` comment in `db.py` and the slow-request watchdog). | Locks are per row, so many writers work at the same time. |
| Bound to one machine and one volume | The app can't run as two containers, and other tools can't read the data safely. | It is a network server: several app instances, BI tools and read-only reports can all connect. |
| Backups mean copying a live file | `docker compose cp` of `calls.db` + `-wal` + `-shm` can catch a half-written state. | `pg_dump` gives a consistent snapshot while the app runs, and Coolify can schedule it. |
| Column types aren't enforced | Any column accepts any value, so bad data goes in without an error. | Types and constraints are enforced on every write. |
| Schema changes are guessed at startup | `_migrate()` reads `PRAGMA table_info` and adds the missing columns. | Numbered migrations, each applied once and recorded. |

The database is small (the local copy is about 2 MB), so moving it takes seconds. The work is in the code.

## What changed in the code

**The database layer (`call_analyzer/db.py`)** keeps the sqlite3 interface the app's ~357 queries are written
against, so most of them didn't change:

- `?` placeholders become `%s`, and a literal `%` becomes `%%` (psycopg reads `%` as a placeholder everywhere).
- Rows read by position and by column name (`row[0]`, `row["agent"]`, `dict(row)`), like `sqlite3.Row`.
- `cursor.lastrowid`: an `INSERT` into a table with an assigned `id` gets `RETURNING id` added.
- sqlite3's transactions: one starts at the first INSERT/UPDATE/DELETE and lasts until `commit()`; reads outside one
  see committed data straight away. If a statement fails inside a transaction, PostgreSQL drops the whole
  transaction, where sqlite3 dropped only that statement. `commit()` then raises instead of losing the writes
  quietly. The one place that catches such an error and goes on (`desk_stats.link_recordings`) uses
  `conn.savepoint()`.
- Connections come from a pool (`DB_POOL_SIZE`, default 20) and go back to it on `close()` or as soon as nothing
  refers to them, so the existing `conn = db.connect()` code doesn't leak connections. If the pool runs out, the
  log says which lines hold the connections.
- Python ints go to PostgreSQL untyped and `numeric` results come back as int/float, so comparisons and JSON output
  behave as they did with SQLite.

**Schema**: `call_analyzer/migrations/0001_initial.sql` has every table and column `_migrate()` used to add, the
indexes, the `calls.updated_at` trigger, and SQL versions of `number_key()` (a test checks it matches Python) and
`skip_listed()` (it reads the SKIP_NUMBERS keys that `db.connect()` sets on the connection). New `NNNN_*.sql` files
are applied in order at startup, under an advisory lock, and recorded in `schema_migrations`.

**SQL rewritten for PostgreSQL**: `json_extract` → `analysis::json ->> 'key'` (`analyze.json_sql`);
`SUM(condition)` → `COUNT(*) FILTER (WHERE ...)`; `INSERT OR IGNORE/REPLACE` → `ON CONFLICT`; scalar
`MAX(a, b)` → `GREATEST`; `COLLATE NOCASE` → `lower()`; the search box's `LIKE` → `ILIKE` (SQLite's `LIKE` ignored
case); `ON CONFLICT ... SET col = col + ...` names the table; descending sorts on `finished_at` say `NULLS LAST`
(SQLite's order).

**Claiming work**:
- `workers.claim` (remote agents taking tasks) was only safe because SQLite allowed one writer at a time. It now uses
  `FOR UPDATE SKIP LOCKED` and re-checks the status, and a test has 8 agents claim at once.
- The call desk's claims (`operations.claim_next`, `inbound.claim`, `start_direct`) were already serialized by
  `operations._claim_lock`, a lock inside the app process, so they're unchanged. That lock only covers one process:
  **run a single app container** until it's replaced by database locks. The unique index `idx_op_open` still stops
  one opportunity from being served twice.

**Safety net**: the app refuses to start on an empty PostgreSQL database while `data/calls.db` still has data, and
says to run `db-copy`. A deploy without the copy can't run with no data and then block the copy.

**Not changed (on purpose)**: times stay ISO text and JSON stays text, as in SQLite: the code compares and slices
them as strings. See phase 5.

## Checks done

- The whole test suite (205 tests) runs against PostgreSQL 17, including the new `tests/test_db.py`.
- `db-copy` on a snapshot of the local `data/calls.db`: 359 rows in 22 tables, counts and checksums match, the
  identity sequences continue after the copied ids, and a second run is refused.
- The app running on that copy: all 45 GET endpoints that have a test value answered without a server error.
- The Docker image built and started with the compose `db` service.

## Switching the live server

### Before the switch day: staging
1. Download a copy of the live database. With the app stopped for a moment, copy `calls.db`, `calls.db-wal` and
   `calls.db-shm` out of the `data` volume together. Or, with the app running, use
   `sqlite3 /app/data/calls.db ".backup /app/data/calls-copy.db"`.
2. Run `python -m call_analyzer db-copy --from calls-copy.db --dry-run` against a scratch database. It lists any
   value that doesn't fit its column. There were none in the local snapshot.
3. Deploy the branch as a second Coolify app with its own `POSTGRES_PASSWORD`, run `db-copy` there, and try the call
   desk with two or more agents at once, the pipeline, remote agents, reports and exports, WhatsApp and inbound
   calls.
4. Turn on scheduled database backups in Coolify and do a test restore (README, "Database").

### Switch (about 15 minutes, outside working hours)
1. Make sure no agent is on a call and no remote agent task is running.
2. **Stop the app.** Nothing may write to `calls.db` from here on.
3. Back up the `data` volume (`calls.db*`, `secret.key`). Nothing below changes them.
4. Set `POSTGRES_PASSWORD` in Coolify (letters and digits) and deploy the new version. The `db` service starts. The
   app refuses to start, because the database is empty and `calls.db` has data. That's expected.
5. Copy: `docker compose run --rm app python -m call_analyzer db-copy --from /app/data/calls.db` (in Coolify, the
   app's terminal works too). It must end with "every table matches".
6. Restart the app. Log in, open calls and reports, have an agent take and close a test contact, check a remote agent
   picks up a task and an inbound call shows up.
7. Reopen to agents. Watch the logs for errors and for "database pool exhausted" that day.

`data/secret.key` must stay in the `data` volume: the softphone passwords are copied encrypted with it.

### Rollback
- **Before step 7:** redeploy the previous version. It reads the untouched `calls.db`, so nothing is lost.
- **After step 7:** what agents did since exists only in PostgreSQL. Fix forward if at all possible. Keep the SQLite
  backup for at least a month.

## Later (optional)
- Replace `operations._claim_lock` with database locks (`FOR UPDATE SKIP LOCKED`, or an advisory lock), so more
  than one app container can run.
- Change time columns to `timestamptz` and JSON columns to `jsonb` (with a GIN index if reports need it).
- Add foreign keys (`op_calls.campaign_id`, `feedback.call_id`, ...) after removing orphan rows.
- Once the live switch is done and the backup is old enough: remove `db_copy.py` and the empty-database check.
