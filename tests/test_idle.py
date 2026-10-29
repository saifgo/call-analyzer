"""Idle prompts (idle.py): agents taking calls who don't call anyone are prompted, and each time is logged.

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
from call_analyzer import db, idle  # noqa: E402

NOW = datetime(2026, 10, 12, 15, 0, 0)


def ago(minutes: float) -> str:
    return (NOW - timedelta(minutes=minutes)).isoformat()


class IdleTests(unittest.TestCase):
    def setUp(self):
        os.environ["DESK_IDLE_PROMPT_MINUTES"] = "5"
        self.addCleanup(os.environ.pop, "DESK_IDLE_PROMPT_MINUTES", None)
        self.conn = db.connect()
        self.addCleanup(self.conn.close)
        self.addCleanup(self.conn.close)
        for table in ("op_calls", "op_agents", "op_idle_prompts"):
            self.conn.execute(f"DELETE FROM {table}")
        self.conn.commit()

    def agent(self, ready: bool = True, since: float = 60, online: float = 60):
        self.conn.execute("INSERT INTO op_agents (username, ready, since, last_seen, online_since) "
                          "VALUES ('a1', ?, ?, ?, ?)", (int(ready), ago(since), ago(0), ago(online)))
        self.conn.commit()

    def call(self, status: str = "done", **fields) -> int:
        row = {"opportunity_id": "o1", "lead": '{"contact": {"name": "Sami"}}', "source": "queue", "status": status,
               "agent": "a1", "created_at": ago(60), **fields}
        cur = self.conn.execute(f"INSERT INTO op_calls ({', '.join(row)}) VALUES ({', '.join('?' * len(row))})",
                                list(row.values()))
        self.conn.commit()
        return cur.lastrowid

    def check(self, later: float = 0):
        return idle.check(self.conn, "a1", NOW + timedelta(minutes=later))

    def keep_checking(self, start: int, until: int):
        """The desk checks in every minute (a gap over a minute and a half means the desk was closed)."""
        for minute in range(start, until + 1):
            prompt = self.check(minute)
        return prompt

    def rows(self):
        return self.conn.execute("SELECT * FROM op_idle_prompts ORDER BY id").fetchall()

    def test_no_prompt_before_the_limit(self):
        self.agent(since=4, online=60)
        self.assertIsNone(self.check())
        self.assertEqual(self.rows(), [])

    def test_prompts_after_the_limit_and_logs_it(self):
        self.agent(since=30)
        self.call(finished_at=ago(7), call_started_at=ago(9), call_ended_at=ago(8))
        prompt = self.check()
        self.assertEqual(prompt["idle_since"], ago(7))
        self.assertEqual(prompt["prompts"], 1)
        self.assertFalse(prompt["acknowledged"])
        self.assertEqual(prompt["doing"], "No contact served")

    def test_served_contact_not_dialed(self):
        self.agent(since=30)
        self.call(status="assigned", assigned_at=ago(20))
        self.assertEqual(self.check()["doing"], "Served Sami and didn't dial")

    def test_not_idle_on_a_call_or_paused(self):
        self.agent(since=30)
        op = self.call(status="in_call", call_started_at=ago(20))
        self.assertIsNone(self.check())
        self.conn.execute("DELETE FROM op_calls WHERE id = ?", (op,))
        self.conn.execute("UPDATE op_agents SET ready = 0")
        self.assertIsNone(self.check())

    def test_back_online_counts_from_then(self):
        self.agent(since=120, online=2)
        self.assertIsNone(self.check())

    def test_acknowledged_until_the_next_prompt(self):
        self.agent(since=30)
        prompt = self.check()
        idle.acknowledge(self.conn, "a1", prompt["id"])
        self.assertTrue(self.keep_checking(1, 4)["acknowledged"])
        again = self.check(5)
        self.assertEqual(again["prompts"], 2)
        self.assertFalse(again["acknowledged"])
        self.assertEqual(len(self.rows()), 1)

    def test_ends_when_they_call(self):
        self.agent(since=30)
        self.check()
        self.call(status="in_call", call_started_at=(NOW + timedelta(minutes=1)).isoformat())
        self.assertIsNone(self.check(1))
        row = self.rows()[0]
        self.assertEqual((row["closed"], row["outcome"]), (1, "called"))
        self.assertEqual(idle.to_dict(row)["idle_seconds"], 31 * 60)

    def test_ends_when_they_pause(self):
        self.agent(since=30)
        self.check()
        self.conn.execute("UPDATE op_agents SET ready = 0")
        self.assertIsNone(self.check(1))
        self.assertEqual(self.rows()[0]["outcome"], "paused")

    def test_ends_where_the_desk_stopped_checking_in(self):
        self.agent(since=30)
        self.keep_checking(0, 2)
        # The tab was closed; they come back 20 minutes later and get a fresh start.
        self.conn.execute("UPDATE op_agents SET online_since = ?", ((NOW + timedelta(minutes=22)).isoformat(),))
        self.assertIsNone(self.check(22))
        row = self.rows()[0]
        self.assertEqual((row["outcome"], row["ended_at"]), ("left", (NOW + timedelta(minutes=2)).isoformat()))

    def test_off(self):
        os.environ["DESK_IDLE_PROMPT_MINUTES"] = "0"
        self.agent(since=30)
        self.assertIsNone(self.check())


if __name__ == "__main__":
    unittest.main()
