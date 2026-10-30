"""Earned breaks (breaks.py): closing enough calls offers the agent a break, logged as a pause.

    python -m unittest discover tests -v
"""
import os
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path

# The settings are read when call_analyzer is imported, so point it at a scratch folder first.
TMP = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
os.environ["DATA_DIR"] = str(Path(TMP.name) / "data")
os.environ["ENV_FILE"] = str(Path(TMP.name) / ".env")

import pgtest  # noqa: E402,F401  (before call_analyzer: the test database)
from call_analyzer import breaks, db, floor  # noqa: E402
from call_analyzer.floor import FloorError  # noqa: E402

SETTINGS = {"DESK_EARNED_BREAK": "true", "DESK_EARNED_BREAK_CALLS": "3", "DESK_EARNED_BREAK_MINUTES": "10"}


class EarnedBreakTests(unittest.TestCase):
    def setUp(self):
        for key, value in SETTINGS.items():
            os.environ[key] = value
            self.addCleanup(os.environ.pop, key, None)
        self.conn = db.connect()
        self.addCleanup(self.conn.close)
        self.addCleanup(self.conn.close)
        for table in ("op_calls", "op_agents", "op_pauses"):
            self.conn.execute(f"DELETE FROM {table}")
        self.conn.execute("INSERT INTO op_agents (username, ready, since, last_seen) VALUES ('a1', 1, ?, ?)",
                          (self.ago(60), self.ago(0)))
        self.conn.commit()

    @staticmethod
    def ago(minutes: float) -> str:
        return (datetime.now().replace(microsecond=0) - timedelta(minutes=minutes)).isoformat()

    def close_calls(self, count: int, opportunity: str = "o", minutes_ago: float = 1) -> None:
        for i in range(count):
            self.conn.execute("INSERT INTO op_calls (opportunity_id, lead, source, status, agent, created_at, "
                              "finished_at) VALUES (?, '{}', 'queue', 'done', 'a1', ?, ?)",
                              (f"{opportunity}{i}", self.ago(90), self.ago(minutes_ago)))
        self.conn.commit()

    def test_off_by_default(self):
        os.environ.pop("DESK_EARNED_BREAK")
        self.assertIsNone(breaks.state(self.conn, "a1"))
        with self.assertRaises(FloorError):
            breaks.take(self.conn, "a1")

    def test_counts_calls_toward_the_break(self):
        self.close_calls(2)
        self.close_calls(1, opportunity="test:")  # test calls don't count
        state = breaks.state(self.conn, "a1")
        self.assertEqual((state["done"], state["calls"], state["minutes"], state["earned"]), (2, 3, 10, False))
        with self.assertRaises(FloorError):
            breaks.take(self.conn, "a1")

    def test_taking_it_pauses_and_starts_the_count_again(self):
        self.close_calls(4)
        self.assertTrue(breaks.state(self.conn, "a1")["earned"])
        breaks.take(self.conn, "a1")
        agent = self.conn.execute("SELECT ready FROM op_agents WHERE username = 'a1'").fetchone()
        self.assertEqual(agent["ready"], 0)
        pause = floor.pause_state(self.conn, "a1")
        self.assertEqual((pause["label"], pause["limit_minutes"], pause["reason_id"]), ("Earned break", 10, None))
        state = breaks.state(self.conn, "a1")
        self.assertEqual((state["done"], state["earned"], state["taken_today"]), (0, False, 1))

    def test_not_during_a_call(self):
        self.close_calls(3, minutes_ago=5)
        self.conn.execute("INSERT INTO op_calls (opportunity_id, lead, source, status, agent, created_at, "
                          "assigned_at, call_started_at) VALUES ('live', '{}', 'queue', 'in_call', 'a1', ?, ?, ?)",
                          (self.ago(3), self.ago(3), self.ago(2)))
        self.conn.commit()
        with self.assertRaises(FloorError):
            breaks.take(self.conn, "a1")


if __name__ == "__main__":
    unittest.main()
