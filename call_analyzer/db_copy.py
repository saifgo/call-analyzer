"""Copy a SQLite calls.db (the app's database before PostgreSQL) into the PostgreSQL database, and prove the copy is
exact. `python -m call_analyzer db-copy --from data/calls.db` (see docs/postgres-migration.md).

Stop the app first: nothing may write to calls.db while it's copied. The SQLite file is only read, never changed.
Every value is checked against its PostgreSQL column before anything is written; problems are listed and nothing is
copied. The copy is one transaction: row counts and a checksum of every table are compared on both sides before it
commits, and any difference rolls it all back.
"""
import hashlib
import sqlite3
from dataclasses import dataclass, field
from pathlib import Path

import psycopg

from . import db

_INTEGER_TYPES = {"integer", "bigint", "smallint"}


class CopyError(Exception):
    pass


@dataclass
class TableReport:
    name: str
    rows: int = 0
    copied: int = 0
    checksum: str = ""
    notes: list[str] = field(default_factory=list)


@dataclass
class Problem:
    table: str
    key: str
    column: str
    value: str
    reason: str

    def __str__(self):
        return f"{self.table} [{self.key}] {self.column} = {self.value}: {self.reason}"


def _pg_tables(conn: psycopg.Connection) -> dict[str, dict]:
    """The app's tables in PostgreSQL: columns (name -> type, not null) in order, and primary key."""
    tables: dict[str, dict] = {}
    for table, column, data_type, nullable in conn.execute(
            """SELECT table_name, column_name, data_type, is_nullable FROM information_schema.columns
               WHERE table_schema = current_schema() AND table_name != 'schema_migrations'
               ORDER BY table_name, ordinal_position"""):
        tables.setdefault(table, {"columns": {}, "key": []})["columns"][column] = (data_type, nullable == "NO")
    for table, column in conn.execute(
            """SELECT tc.table_name, kcu.column_name FROM information_schema.table_constraints tc
               JOIN information_schema.key_column_usage kcu
                 ON kcu.constraint_name = tc.constraint_name AND kcu.table_schema = tc.table_schema
               WHERE tc.table_schema = current_schema() AND tc.constraint_type = 'PRIMARY KEY'
               ORDER BY tc.table_name, kcu.ordinal_position"""):
        if table in tables:
            tables[table]["key"].append(column)
    return tables


def _convert(value, data_type: str):
    """A SQLite value as the PostgreSQL column takes it. Raises ValueError when it doesn't fit."""
    if value is None:
        return None
    if data_type in _INTEGER_TYPES:
        if isinstance(value, bool):
            return int(value)
        if isinstance(value, int):
            return value
        if isinstance(value, float) and value.is_integer():
            return int(value)
        if isinstance(value, str) and value.strip().lstrip("-").isdigit():
            return int(value.strip())
        raise ValueError("not a whole number")
    if data_type == "double precision":
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            return float(value)
        if isinstance(value, str):
            try:
                return float(value)
            except ValueError:
                pass
        raise ValueError("not a number")
    if data_type == "text":
        if isinstance(value, bytes):
            value = value.decode("utf-8")  # UnicodeDecodeError is a ValueError
        elif not isinstance(value, str):
            value = str(value)
        if "\x00" in value:
            raise ValueError("contains a NUL character, which PostgreSQL text can't hold")
        return value
    raise ValueError(f"unexpected column type {data_type}")


def _checksum(rows, key: list[int]) -> str:
    """A hash of the rows in primary key order (sorted here: PostgreSQL and SQLite order text differently)."""
    digest = hashlib.sha256()
    for row in sorted(rows, key=lambda r: tuple(r[i] for i in key)):
        digest.update(repr(tuple(row)).encode("utf-8"))
        digest.update(b"\n")
    return digest.hexdigest()


def _sqlite(path: Path) -> sqlite3.Connection:
    if not path.is_file():
        raise CopyError(f"No SQLite database at {path}")
    conn = sqlite3.connect(f"{path.resolve().as_uri()}?mode=ro", uri=True)
    result = conn.execute("PRAGMA integrity_check").fetchone()[0]
    if result != "ok":
        raise CopyError(f"{path} failed SQLite's integrity check: {result}")
    return conn


def copy(sqlite_path: str | Path, url: str | None = None, *, replace: bool = False, dry_run: bool = False,
         log=print) -> list[TableReport]:
    """Copy every table of the SQLite database into PostgreSQL (`url`, default DATABASE_URL). Returns a report per
    table. Raises CopyError, having written nothing, when anything doesn't fit or doesn't match."""
    source = _sqlite(Path(sqlite_path))
    url = url or db.database_url()
    with psycopg.connect(url, autocommit=True) as target:
        db.migrate(target)
        tables = _pg_tables(target)
        source_tables = {r[0] for r in source.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%'")}

        # 1. Read and check everything before writing anything.
        reports: list[TableReport] = []
        data: dict[str, tuple[list[str], list[tuple]]] = {}
        problems: list[Problem] = []
        for extra in sorted(source_tables - set(tables)):
            count = source.execute(f'SELECT COUNT(*) FROM "{extra}"').fetchone()[0]
            if count:
                raise CopyError(f"The SQLite table {extra} ({count} rows) has no PostgreSQL table to go to")
            log(f"  {extra}: empty, and not in the PostgreSQL schema: skipped")
        for name, info in tables.items():
            report = TableReport(name)
            reports.append(report)
            if name not in source_tables:
                report.notes.append("not in the SQLite database")
                data[name] = ([], [])
                continue
            source_columns = [r[1] for r in source.execute(f'PRAGMA table_info("{name}")')]
            lost = [c for c in source_columns if c not in info["columns"]]
            if lost:
                raise CopyError(f"{name}: the SQLite columns {', '.join(lost)} have no PostgreSQL column to go to")
            columns = [c for c in info["columns"] if c in source_columns]
            missing = [c for c in info["columns"] if c not in source_columns]
            if missing:
                report.notes.append(f"not in SQLite, left to their default: {', '.join(missing)}")
            order = ", ".join(f'"{c}"' for c in info["key"]) or "rowid"
            rows = []
            for raw in source.execute(f'SELECT {", ".join(chr(34) + c + chr(34) for c in columns)} '
                                      f'FROM "{name}" ORDER BY {order}'):
                row = []
                for column, value in zip(columns, raw):
                    data_type, not_null = info["columns"][column]
                    try:
                        converted = _convert(value, data_type)
                        if converted is None and not_null:
                            raise ValueError("is empty, and the column requires a value")
                    except ValueError as exc:
                        key = ", ".join(str(raw[columns.index(k)]) for k in info["key"] if k in columns)
                        problems.append(Problem(name, key, column, repr(value)[:80], str(exc)))
                        converted = None
                    row.append(converted)
                rows.append(tuple(row))
            report.rows = len(rows)
            report.checksum = _checksum(rows, [columns.index(k) for k in info["key"] if k in columns])
            data[name] = (columns, rows)
        if problems:
            shown = "\n".join(f"  {p}" for p in problems[:50])
            more = f"\n  ... and {len(problems) - 50} more" if len(problems) > 50 else ""
            raise CopyError(f"{len(problems)} values don't fit their PostgreSQL column; nothing was copied. "
                            f"Fix them in the SQLite database and run again:\n{shown}{more}")
        if dry_run:
            log("Dry run: every value fits. Nothing was written.")
            return reports

        # 2. Write it all in one transaction, and compare before committing.
        with target.transaction():
            filled = [name for name in tables
                      if target.execute(f'SELECT EXISTS (SELECT 1 FROM "{name}")').fetchone()[0]]
            if filled and not replace:
                raise CopyError(f"The PostgreSQL database already has data (in {', '.join(filled)}). "
                                "Nothing was copied; run again with --replace to overwrite it.")
            if filled:
                target.execute(f"TRUNCATE {', '.join(chr(34) + t + chr(34) for t in tables)} RESTART IDENTITY")
            for name, (columns, rows) in data.items():
                if not rows:
                    continue
                with target.cursor() as cur:
                    with cur.copy(f'COPY "{name}" ({", ".join(chr(34) + c + chr(34) for c in columns)}) '
                                  "FROM STDIN") as out:
                        for row in rows:
                            out.write_row(row)
                if "id" in tables[name]["columns"] and target.execute(
                        "SELECT pg_get_serial_sequence(%s, 'id')", [name]).fetchone()[0]:
                    target.execute(f"""SELECT setval(pg_get_serial_sequence(%s, 'id'),
                                                     (SELECT COALESCE(MAX(id), 0) + 1 FROM "{name}"), false)""",
                                   [name])
            for report in reports:
                columns, _ = data[report.name]
                if not columns:
                    continue
                copied = target.execute(f'SELECT {", ".join(chr(34) + c + chr(34) for c in columns)} '
                                        f'FROM "{report.name}"').fetchall()
                report.copied = len(copied)
                key = [columns.index(k) for k in tables[report.name]["key"] if k in columns]
                if report.copied != report.rows or _checksum(copied, key) != report.checksum:
                    raise CopyError(f"{report.name}: the copy doesn't match ({report.rows} rows in SQLite, "
                                    f"{report.copied} in PostgreSQL, or different values). Nothing was copied.")
    return reports
