"""The team board's real-time alerts (alerts.py), worked out from desk rows written straight to the database.

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
from call_analyzer import alerts, campaigns, db  # noqa: E402

NOW = datetime(2026, 10, 12, 15, 0, 0)


def ago(minutes: float) -> str:
    return (NOW - timedelta(minutes=minutes)).isoformat()


class AlertTests(unittest.TestCase):
    def setUp(self):
        for key in alerts.DEFAULTS:
            self.addCleanup(os.environ.pop, key, None)
            os.environ.pop(key, None)
        self.conn = db.connect()
        self.addCleanup(self.conn.close)
        self.addCleanup(self.conn.close)
        for table in ("op_calls", "op_agents", "op_campaigns"):
            self.conn.execute(f"DELETE FROM {table}")
        self.conn.commit()
        self.campaign = campaigns.default_id(self.conn)

    def agent(self, user: str, ready: bool = True, since: float = 60, seen: float = 0):
        self.conn.execute("INSERT INTO op_agents (username, ready, since, last_seen) VALUES (?, ?, ?, ?)",
                          (user, int(ready), ago(since), ago(seen)))
        self.conn.commit()

    def call(self, user: str | None, status: str = "done", outcome: str | None = "interested", finished: float = 5,
             opportunity: str = "o1", **fields) -> int:
        row = {"opportunity_id": opportunity, "lead": '{"contact": {"name": "Sami"}}', "source": "queue",
               "status": status, "agent": user, "outcome": outcome if status == "done" else None,
               "finished_at": ago(finished) if status == "done" else None, "campaign_id": self.campaign,
               "created_at": ago(finished), **fields}
        cur = self.conn.execute(f"INSERT INTO op_calls ({', '.join(row)}) VALUES ({', '.join('?' * len(row))})",
                                list(row.values()))
        self.conn.commit()
        return cur.lastrowid

    def kinds(self) -> list[tuple[str, str]]:
        return [(a["kind"], a["level"]) for a in alerts.current(self.conn, NOW)]

    def test_quiet_desk_has_no_alert(self):
        self.agent("a1")
        self.call("a1", finished=2)
        self.assertEqual(self.kinds(), [])

    def test_idle_agent(self):
        self.agent("a1", since=60)
        self.call("a1", finished=12)
        found = alerts.current(self.conn, NOW)
        self.assertEqual([(a["kind"], a["level"], a["agent"]) for a in found], [("idle", "warning", "a1")])
        self.assertIn("since 14:48", found[0]["detail"])
        # Twice the threshold is critical; paused or offline agents aren't idle.
        self.conn.execute("DELETE FROM op_calls")
        self.conn.commit()
        self.agent("a2", ready=False)
        self.agent("a3", seen=10)
        self.assertEqual(self.kinds(), [("idle", "critical")])

    def test_contact_served_but_not_dialed_or_still_closing(self):
        self.agent("a1")
        self.call("a1", status="assigned", assigned_at=ago(11))
        self.agent("a2")
        self.call("a2", status="in_call", opportunity="o2", call_started_at=ago(20), call_ended_at=ago(12))
        details = sorted(a["detail"] for a in alerts.current(self.conn, NOW))
        self.assertTrue(details[0].startswith("Still closing the call with Sami"))
        self.assertTrue(details[1].startswith("Was served Sami and hasn't dialed"))

    def test_long_call(self):
        self.agent("a1")
        self.call("a1", status="in_call", call_started_at=ago(25))
        self.assertEqual(self.kinds(), [("long_call", "warning")])
        os.environ["ALERT_LONG_CALL_MINUTES"] = "0"
        self.assertEqual(self.kinds(), [])

    def test_no_answer_streak(self):
        self.agent("a1", ready=False)
        self.call("a1", outcome="interested", finished=60)
        for i in range(4):
            self.call("a1", outcome="no_answer", finished=50 - i, opportunity=f"n{i}")
        self.assertEqual(self.kinds(), [])
        self.call("a1", outcome="no_answer", finished=1, opportunity="n9")
        self.assertEqual(self.kinds(), [("no_answer_streak", "warning")])
        # Reaching someone ends the streak.
        self.call("a1", outcome="interested", finished=0.5, opportunity="r")
        self.assertEqual(self.kinds(), [])

    def test_test_calls_dont_count(self):
        self.agent("a1", ready=False)
        for i in range(6):
            self.call("a1", outcome="no_answer", finished=10 - i, opportunity=f"test:{i}")
        self.call(None, status="scheduled", opportunity="test:cb", due_at=ago(60))
        self.assertEqual(self.kinds(), [])

    def test_contact_rate_drop(self):
        # The week before: half of 40 calls reached. The last hour: 2 of 10.
        for i in range(40):
            self.call("a1", outcome="interested" if i % 2 else "no_answer", finished=60 * 24 + i, opportunity=f"b{i}")
        for i in range(10):
            self.call(f"x{i}", outcome="interested" if i < 2 else "no_answer", finished=5 + i, opportunity=f"r{i}")
        found = [a for a in alerts.current(self.conn, NOW) if a["kind"] == "contact_rate_drop"]
        self.assertEqual(len(found), 1)
        self.assertEqual(found[0]["level"], "warning")  # 60% lower; critical from 80%
        self.assertIn("20%", found[0]["title"])
        # Too few calls in the window: no alert.
        self.conn.execute("DELETE FROM op_calls WHERE opportunity_id IN ('r0', 'r1')")
        self.conn.commit()
        self.assertFalse([a for a in alerts.current(self.conn, NOW) if a["kind"] == "contact_rate_drop"])

    def test_overdue_callbacks(self):
        self.conn.execute("INSERT INTO users (username, display_name, role, password_hash, created_at) "
                          "VALUES ('alert_a1', 'Amira', 'agent', 'x', ?) ON CONFLICT (username) DO UPDATE "
                          "SET display_name = excluded.display_name, role = excluded.role", (ago(0),))
        self.conn.commit()
        self.addCleanup(lambda: (self.conn.execute("DELETE FROM users WHERE username = 'alert_a1'"),
                                 self.conn.commit()))
        self.call(None, status="scheduled", due_at=ago(10))  # late, but not by enough
        self.call(None, status="scheduled", due_at=ago(20), assign_to="alert_a1", opportunity="o2")
        found = alerts.current(self.conn, NOW)
        self.assertEqual([(a["kind"], a["level"]) for a in found], [("callback_overdue", "warning")])
        self.assertIn("kept for Amira", found[0]["detail"])
        for i in range(3):
            self.call(None, status="scheduled", due_at=ago(40 + i), opportunity=f"c{i}")
        found = alerts.current(self.conn, NOW)
        self.assertEqual([(a["title"], a["level"]) for a in found], [("4 callbacks overdue", "critical")])

    def test_ids_stay_the_same_while_the_cause_lasts(self):
        self.agent("a1")
        self.call("a1", status="in_call", call_started_at=ago(25))
        first = alerts.current(self.conn, NOW)[0]["id"]
        later = alerts.current(self.conn, NOW + timedelta(minutes=5))[0]
        self.assertEqual(later["id"], first)
        self.assertIn("30 min", later["title"])


if __name__ == "__main__":
    unittest.main()
