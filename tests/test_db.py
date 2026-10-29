"""The database layer (db.py): PostgreSQL behind the sqlite3-style interface the app's queries are written against.

    python -m unittest discover tests -v
"""
import os
import tempfile
import threading
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

TMP = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
os.environ["DATA_DIR"] = str(Path(TMP.name) / "data")
os.environ["ENV_FILE"] = str(Path(TMP.name) / ".env")

import pgtest  # noqa: E402,F401  (before call_analyzer: the test database)
from call_analyzer import db, workers  # noqa: E402


class SqlTranslationTests(unittest.TestCase):
    def test_placeholders_and_percent_signs(self):
        query, is_write, returns_id = db._prepare("SELECT * FROM t WHERE a = ? AND b LIKE 'x%' AND c = '?'")
        self.assertEqual(query, "SELECT * FROM t WHERE a = %s AND b LIKE 'x%%' AND c = '?'")
        self.assertEqual((is_write, returns_id), (False, False))
        query, is_write, returns_id = db._prepare("INSERT INTO op_calls (a) VALUES (?)")
        self.assertEqual(query, "INSERT INTO op_calls (a) VALUES (%s) RETURNING id")
        self.assertEqual((is_write, returns_id), (True, True))
        # Tables keyed by something else than an assigned id return nothing.
        self.assertFalse(db._prepare("INSERT INTO users (username) VALUES (?)")[2])

    def test_number_key_is_the_same_in_sql_and_python(self):
        conn = db.connect()
        for number in ("+216 22 602 716", "0021622602716", "22602716", "103", "", None, "abc", "12-34", "1234567"):
            with self.subTest(number=number):
                sql = conn.execute("SELECT number_key(?)", (number,)).fetchone()[0]
                self.assertEqual(sql, db.number_key(number))


class ConnectionTests(unittest.TestCase):
    def setUp(self):
        self.conn = db.connect()
        self.addCleanup(self.conn.close)
        self.conn.execute("DELETE FROM op_settings")
        self.conn.execute("DELETE FROM feedback")
        self.conn.commit()

    def test_rows_read_by_position_and_name(self):
        row = self.conn.execute("SELECT 1 AS one, 'two' AS Two").fetchone()
        self.assertEqual((row[0], row["one"], row["two"], row["Two"]), (1, 1, "two", "two"))
        self.assertEqual(dict(row), {"one": 1, "two": "two"})
        self.assertEqual(list(row), [1, "two"])
        with self.assertRaises(IndexError):
            row["three"]

    def test_lastrowid_and_rowcount(self):
        cur = self.conn.execute("INSERT INTO feedback (call_id, author, body, created_at, updated_at) "
                                "VALUES ('c', 'a', 'b', '', '')")
        self.assertIsInstance(cur.lastrowid, int)
        self.assertEqual(cur.rowcount, 1)
        self.assertEqual(cur.fetchall(), [])
        self.conn.commit()
        self.assertEqual(self.conn.execute("SELECT call_id FROM feedback WHERE id = ?", (cur.lastrowid,)).fetchone()[0],
                         "c")

    def test_averages_come_back_as_numbers_json_can_write(self):
        row = self.conn.execute("SELECT AVG(x), ROUND(AVG(x), 1), SUM(x::bigint) FROM (VALUES (1), (2)) AS t(x)").fetchone()
        self.assertEqual((row[0], row[1], row[2]), (1.5, 1.5, 3))
        self.assertIsInstance(row[2], int)

    def test_writes_are_seen_by_others_once_committed_and_dropped_when_not(self):
        other = db.connect()
        self.addCleanup(other.close)
        self.conn.execute("INSERT INTO op_settings (key, value) VALUES ('k', 'v')")
        self.assertTrue(self.conn.in_transaction)
        self.assertIsNone(other.execute("SELECT value FROM op_settings WHERE key = 'k'").fetchone())
        self.conn.commit()
        self.assertEqual(other.execute("SELECT value FROM op_settings WHERE key = 'k'").fetchone()[0], "v")
        # Closed (or dropped) without commit: rolled back, like sqlite3.
        third = db.connect()
        third.execute("UPDATE op_settings SET value = 'w' WHERE key = 'k'")
        third.close()
        self.assertEqual(other.execute("SELECT value FROM op_settings WHERE key = 'k'").fetchone()[0], "v")

    def test_a_failed_statement_inside_a_savepoint_keeps_the_rest(self):
        self.conn.execute("INSERT INTO op_settings (key, value) VALUES ('a', '1')")
        with self.assertRaises(db.IntegrityError):
            with self.conn.savepoint():
                self.conn.execute("INSERT INTO op_settings (key, value) VALUES ('a', '2')")
        self.conn.execute("INSERT INTO op_settings (key, value) VALUES ('b', '1')")
        self.conn.commit()
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM op_settings").fetchone()[0], 2)

    def test_a_failed_statement_outside_a_savepoint_is_reported_at_commit(self):
        self.conn.execute("INSERT INTO op_settings (key, value) VALUES ('a', '1')")
        with self.assertRaises(db.IntegrityError):
            self.conn.execute("INSERT INTO op_settings (key, value) VALUES ('a', '2')")
        with self.assertRaises(db.Error):
            self.conn.commit()
        self.assertFalse(self.conn.in_transaction)  # usable again

    def test_a_failing_first_write_leaves_the_connection_usable(self):
        self.conn.execute("INSERT INTO op_settings (key, value) VALUES ('a', '1')")
        self.conn.commit()
        with self.assertRaises(db.IntegrityError):
            self.conn.execute("INSERT INTO op_settings (key, value) VALUES ('a', '2')")
        self.assertFalse(self.conn.in_transaction)
        self.assertEqual(self.conn.execute("SELECT value FROM op_settings WHERE key = 'a'").fetchone()[0], "1")


class ForgottenCopyTests(unittest.TestCase):
    def test_refuses_an_empty_database_while_the_sqlite_one_has_data(self):
        conn = db.connect()
        self.addCleanup(conn.close)
        for table in ("users", "calls", "op_calls"):
            conn.execute(f"DELETE FROM {table}")
        conn.commit()
        old = Path(TMP.name) / "old-calls.db"
        with mock.patch.object(db, "settings", SimpleNamespace(db_path=old)):
            db._check_sqlite_was_copied(conn)  # no SQLite file: a new install
            old.write_bytes(b"SQLite format 3")
            with self.assertRaisesRegex(RuntimeError, "db-copy"):
                db._check_sqlite_was_copied(conn)
            conn.execute("INSERT INTO users (username, password_hash, created_at) VALUES ('u', 'x', '')")
            conn.commit()
            db._check_sqlite_was_copied(conn)  # copied: data is there
        conn.execute("DELETE FROM users")
        conn.commit()


class ConcurrentClaimTests(unittest.TestCase):
    def test_agents_claiming_at_once_get_different_tasks(self):
        conn = db.connect()
        self.addCleanup(conn.close)
        conn.execute("DELETE FROM worker_tasks")
        conn.commit()
        workers.enqueue(conn, "transcribe", [f"call-{i}" for i in range(8)])
        got, start = [], threading.Barrier(8)

        def claim(i):
            mine = db.connect()
            start.wait()
            task = workers.claim(mine, {"id": f"w{i}", "name": f"PC-{i}"}, ["transcribe"])
            got.append(task["id"] if task else None)
            mine.close()

        threads = [threading.Thread(target=claim, args=(i,)) for i in range(8)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(30)
        claimed = [g for g in got if g is not None]
        self.assertEqual(len(claimed), len(set(claimed)), "a task was handed to two agents")
        self.assertEqual(len(claimed), 8)


if __name__ == "__main__":
    unittest.main()
