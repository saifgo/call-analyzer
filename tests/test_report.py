"""The coaching report includes the human feedback written about the calls.

    python -m unittest discover tests -v
"""
import json
import os
import tempfile
import unittest
from pathlib import Path

# The settings are read when call_analyzer is imported, so point it at a scratch folder first.
TMP = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
os.environ["DATA_DIR"] = str(Path(TMP.name) / "data")
os.environ["ENV_FILE"] = str(Path(TMP.name) / ".env")

from call_analyzer import analyze, db  # noqa: E402


class ReportFeedbackTests(unittest.TestCase):
    def setUp(self):
        self.conn = db.connect()
        for table in ("feedback", "users", "calls"):
            self.conn.execute(f"DELETE FROM {table}")
        for call_id in ("1", "2"):
            self.conn.execute("INSERT INTO calls (id, type, agent, customer, date_call, duration, analysis) "
                              "VALUES (?, 'OUT', '101', '216', '2026-10-01 10:00:00', 120, ?)",
                              (call_id, json.dumps({"is_sales_conversation": True, "overall_score": 4})))
        self.conn.commit()
        self.prompts = []
        self._ask = analyze.ask_model
        analyze.ask_model = lambda system, prompt, *a, **k: self.prompts.append(prompt) or "# report"

    def tearDown(self):
        analyze.ask_model = self._ask

    def add_feedback(self, call_id, author, body, score=None):
        self.conn.execute("INSERT INTO feedback (call_id, author, body, score, created_at, updated_at) "
                          "VALUES (?, ?, ?, ?, '2026-10-02T09:00:00', '2026-10-02T09:00:00')",
                          (call_id, author, body, score))
        self.conn.commit()

    def report(self):
        calls = db.select_calls(self.conn, where="analysis IS NOT NULL")
        feedback = db.feedback_by_call(self.conn, [c["id"] for c in calls])
        return analyze.coaching_report("the team", calls, feedback)

    def test_feedback_is_sent_with_the_calls_and_outweighs_the_ai(self):
        self.conn.execute("INSERT INTO users (username, password_hash, role, display_name, created_at) "
                          "VALUES ('boss', 'x', 'admin', 'The Boss', '2026-10-01')")
        self.add_feedback("1", "boss", "Great rapport, the AI was too harsh", 9)
        self.assertEqual(self.report(), "# report")
        prompt = self.prompts[0]
        self.assertIn("Great rapport, the AI was too harsh", prompt)
        self.assertIn('"reviewer": "The Boss"', prompt)
        self.assertIn('"reviewer_score": 9', prompt)
        self.assertIn("outweigh the AI analysis", prompt)
        self.assertIn("Human review", prompt)
        self.assertEqual(prompt.count('"human_feedback"'), 1)  # only the reviewed call carries it

    def test_report_without_feedback_is_unchanged(self):
        self.report()
        prompt = self.prompts[0]
        self.assertNotIn("human_feedback", prompt)
        self.assertNotIn("Human review", prompt)


if __name__ == "__main__":
    unittest.main()
