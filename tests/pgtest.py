"""Points the tests at a scratch PostgreSQL database, emptied once per test run. Import it before call_analyzer.

TEST_DATABASE_URL picks the server (default: the one `docker run` below starts). The database name must end in
_test: everything in it is dropped.

    docker run -d --name ca-pg-test -e POSTGRES_PASSWORD=test -p 55432:5432 postgres:17
"""
import os

import psycopg
from psycopg.conninfo import conninfo_to_dict, make_conninfo

URL = os.getenv("TEST_DATABASE_URL", "postgresql://postgres:test@localhost:55432/call_analyzer_test")


def _reset() -> None:
    name = conninfo_to_dict(URL).get("dbname", "")
    if not name.endswith("_test"):
        raise RuntimeError(f"TEST_DATABASE_URL must name a database ending in _test (it is emptied), not {name!r}")
    with psycopg.connect(make_conninfo(URL, dbname="postgres"), autocommit=True) as admin:
        if not admin.execute("SELECT 1 FROM pg_database WHERE datname = %s", [name]).fetchone():
            admin.execute(f'CREATE DATABASE "{name}"')
    with psycopg.connect(URL, autocommit=True) as conn:
        conn.execute("DROP SCHEMA public CASCADE")
        conn.execute("CREATE SCHEMA public")


if os.environ.get("DATABASE_URL") != URL:  # once per run: every test module imports this
    _reset()
    os.environ["DATABASE_URL"] = URL
