"""Sales and customer service calls are judged separately: own prompt, score card, business.md parts and report.

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

BUSINESS = """# Business context
Intro for everyone.
## What we sell
Recharge vouchers.
## Our ideal call
SALES-ONLY ideal call.
## Customer service
SERVICE-ONLY rules.
## Team
Shared team notes.
"""

CALL = {"id": "1", "agent": "101", "customer": "216", "date_call": "2026-10-01", "duration": 90, "type": "IN",
        "transcript": "[00:00] agent: Allo\n[00:02] customer: my printer does not print"}

SALES = {"is_sales_conversation": True, "call_category": "prospecting", "summary": "s", "outcome": "sale",
         "customer_interest": "high", "overall_score": 7,
         "scores": dict(opening=7, discovery=7, pitch=7, objection_handling=7, closing=7, tone_and_listening=7),
         "strengths": [], "mistakes": [], "objections": [], "missed_opportunities": [], "top_coaching_tip": "t",
         "follow_up_action": "f"}
SERVICE = {"issue_category": "hardware_printer_pda", "summary": "s", "resolution_status": "resolved",
           "customer_sentiment": "satisfied", "overall_score": 8,
           "scores": dict(greeting=8, understanding=8, solution=8, clarity=8, empathy_and_tone=8, resolution=8),
           "strengths": [], "mistakes": [], "missed_opportunities": [], "top_coaching_tip": "t",
           "follow_up_action": "f"}


class KindTests(unittest.TestCase):
    def setUp(self):
        self.calls = []  # (system, schema) of every model call
        self._ask, self._labeled = analyze.ask_model, analyze.ask_model_labeled

    def tearDown(self):
        analyze.ask_model, analyze.ask_model_labeled = self._ask, self._labeled

    def fake_model(self, kind, analysis):
        def ask(system, prompt, schema=None, cfg=None):
            self.calls.append((system, schema))
            if schema and "reason" in schema["properties"]:
                return {"reason": "x", "call_kind": kind}
            return analysis
        analyze.ask_model = ask
        analyze.ask_model_labeled = lambda system, prompt, schema=None, cfg=None: (ask(system, prompt, schema, cfg), "Fake")

    def test_business_md_is_split_by_kind(self):
        sales = analyze.business_for(BUSINESS, "sales")
        service = analyze.business_for(BUSINESS, "service")
        shared = analyze.business_for(BUSINESS, "shared")
        for text in (sales, service, shared):
            self.assertIn("Recharge vouchers", text)
            self.assertIn("Shared team notes", text)
            self.assertIn("Intro for everyone", text)
        self.assertIn("SALES-ONLY", sales)
        self.assertNotIn("SERVICE-ONLY", sales)
        self.assertIn("SERVICE-ONLY", service)
        self.assertNotIn("SALES-ONLY", service)
        self.assertNotIn("SALES-ONLY", shared)
        self.assertNotIn("SERVICE-ONLY", shared)

    def test_service_call_is_judged_as_service(self):
        self.fake_model("service", SERVICE)
        analysis, by = analyze.analyze_call(CALL, business=BUSINESS)
        self.assertEqual((analysis.call_kind, by), ("service", "Fake"))
        self.assertEqual(analysis.scores.resolution, 8)
        system, schema = self.calls[1]
        self.assertIn("customer service", system)
        self.assertIn("SERVICE-ONLY", system)
        self.assertNotIn("SALES-ONLY", system)
        self.assertIn("resolution_status", schema["properties"])
        self.assertNotIn("call_kind", schema["properties"])  # decided by the classification, not the model
        self.assertNotIn("call_kind", schema["required"])

    def test_sales_call_keeps_the_sales_score_card(self):
        self.fake_model("sales", SALES)
        analysis, _ = analyze.analyze_call(CALL, business=BUSINESS)
        self.assertEqual(analysis.call_kind, "sales")
        system, schema = self.calls[1]
        self.assertIn("sales coach", system)
        self.assertIn("SALES-ONLY", system)
        self.assertNotIn("SERVICE-ONLY", system)
        self.assertIn("objections", schema["properties"])
        self.assertNotIn("call_kind", schema["properties"])

    def test_other_calls_are_not_rated(self):
        self.fake_model("other", SALES)
        analysis, by = analyze.analyze_call(CALL, business=BUSINESS)
        self.assertIsInstance(analysis, analyze.OtherAnalysis)
        self.assertEqual((analysis.call_kind, analysis.is_sales_conversation, analysis.summary, by),
                         ("other", False, "x", "Fake"))
        self.assertNotIn("overall_score", analysis.model_dump())
        self.assertEqual(len(self.calls), 1)  # classified only: no score card is asked for

    def test_unknown_kind_is_an_error(self):
        analyze.ask_model_labeled = lambda *a, **k: ({"reason": "x", "call_kind": "banana"}, "Fake")
        with self.assertRaises(RuntimeError):
            analyze.classify_call(CALL, business=BUSINESS)

    def test_parse_and_kind_of(self):
        service = analyze.parse_analysis({**SERVICE, "call_kind": "service"})
        self.assertIsInstance(service, analyze.ServiceAnalysis)
        self.assertIsInstance(analyze.parse_analysis(SALES), analyze.CallAnalysis)  # old analyses have no kind
        self.assertEqual(analyze.kind_of({"call_kind": "service"}), "service")
        self.assertEqual(analyze.kind_of(SALES), "sales")
        self.assertEqual(analyze.kind_of({"is_sales_conversation": False, "call_category": "support"}), "other")
        with self.assertRaises(Exception):
            analyze.parse_analysis({**SERVICE, "call_kind": "service", "scores": SALES["scores"]})
        # An older agent still scores voicemails: the score card is dropped, they are not rated.
        other = analyze.parse_analysis({**SALES, "call_kind": "other", "is_sales_conversation": False})
        self.assertIsInstance(other, analyze.OtherAnalysis)
        self.assertNotIn("overall_score", other.model_dump())

    def test_service_report_has_its_own_sections_and_feedback(self):
        prompts = []
        analyze.ask_model = lambda system, prompt, *a, **k: prompts.append((system, prompt)) or "# r"
        rows = [{"id": "1", "date_call": "2026-10-01", "agent": "101", "type": "IN", "duration": 90,
                 "analysis": json.dumps({**SERVICE, "call_kind": "service"})}]
        analyze.coaching_report("service", rows, {"1": [{"reviewer": "Boss", "note": "good", "reviewer_score": 9}]},
                                kind="service")
        system, prompt = prompts[0]
        self.assertIn("customer service", system)
        self.assertIn("support manager", prompt)
        self.assertIn("Answer playbook", prompt)
        self.assertNotIn("pitch script", prompt)
        self.assertIn("Human review", prompt)


class UnratedCallTests(unittest.TestCase):
    """Voicemails and the like don't count in any score, even those analyzed (and scored) before they stopped being
    rated."""

    def setUp(self):
        self.conn = db.connect()
        for table in ("feedback", "calls"):
            self.conn.execute(f"DELETE FROM {table}")
        rows = [("1", {**SALES, "call_kind": "sales", "overall_score": 8}),
                ("2", {**SALES, "call_kind": "sales", "overall_score": 6}),
                ("3", {**SALES, "call_kind": "other", "is_sales_conversation": False, "overall_score": 1}),
                ("4", {**SALES, "is_sales_conversation": False, "overall_score": 2}),  # from before kinds existed
                ("5", {"call_kind": "other", "is_sales_conversation": False, "summary": "voicemail"}),
                ("6", {**SERVICE, "call_kind": "service"})]
        for call_id, analysis in rows:
            self.conn.execute("INSERT INTO calls (id, type, agent, customer, date_call, duration, analysis) "
                              "VALUES (?, 'OUT', '101', '216', '2026-10-01 10:00:00', 30, ?)",
                              (call_id, json.dumps(analysis)))
        self.conn.commit()

    def test_agent_average_leaves_them_out(self):
        from types import SimpleNamespace

        from call_analyzer.web import server
        request = SimpleNamespace(state=SimpleNamespace(account=None))
        agent = server.stats(request)["agents"][0]
        self.assertEqual((agent["avg_score"], agent["scored"]), (7.0, 2))
        self.assertEqual((agent["service_calls"], agent["service_score"]), (1, 8.0))

    def test_they_have_no_score_in_the_list(self):
        from types import SimpleNamespace

        from call_analyzer.web import server
        request = SimpleNamespace(state=SimpleNamespace(account=None))
        calls = server.list_calls(request, sort="-score")["calls"]
        self.assertEqual([(c["id"], c["score"]) for c in calls][:3], [("1", 8), ("6", 8), ("2", 6)])
        self.assertEqual({c["id"]: c["score"] for c in calls if c["kind"] == "other"},
                         {"3": None, "4": None, "5": None})

    def test_shared_page_shows_no_score_card(self):
        from call_analyzer.web import export
        row = self.conn.execute("SELECT * FROM calls WHERE id = '3'").fetchone()
        page = export.render_call_page(row, audio_src=None, links=[])
        self.assertIn("not rated", page)
        self.assertNotIn("Overall score", page)


class ReportCommandTests(unittest.TestCase):
    def test_cmd_report_writes_a_sales_and_a_service_report(self):
        from argparse import Namespace
        from dataclasses import replace
        from unittest import mock

        from call_analyzer import __main__ as cli
        from call_analyzer.config import settings

        reports = Path(TMP.name) / "reports"  # never write into the real reports folder

        conn = db.connect()
        for table in ("feedback", "calls"):
            conn.execute(f"DELETE FROM {table}")
        rows = [("1", json.dumps({**SALES, "call_kind": "sales"})), ("2", json.dumps({**SERVICE, "call_kind": "service"})),
                ("3", json.dumps({**SALES, "is_sales_conversation": False, "call_kind": "other"})),
                ("4", json.dumps(SALES))]  # written before kinds existed
        for call_id, analysis in rows:
            conn.execute("INSERT INTO calls (id, type, agent, customer, date_call, duration, analysis) "
                         "VALUES (?, 'IN', '101', '216', '2026-10-01 10:00:00', 120, ?)", (call_id, analysis))
        conn.commit()
        asked = []
        original = analyze.ask_model
        analyze.ask_model = lambda system, prompt, *a, **k: asked.append(prompt) or "body"
        try:
            with mock.patch.object(cli, "settings", replace(settings, reports_dir=reports)):
                cli.cmd_report(Namespace(since=None, until=None, agent=None, min_duration=0, limit=None, ids=None,
                                         team_only=True, new_only=False))
        finally:
            analyze.ask_model = original
        names = sorted(p.name.split("-", 2)[2] for p in reports.glob("*.md"))
        self.assertEqual(names, ["service-team.md", "team.md"])
        sales_prompt = next(p for p in asked if "recorded calls" in p)
        service_prompt = next(p for p in asked if "customer service calls" in p)
        self.assertIn('"call_id": "1"', sales_prompt)
        self.assertIn('"call_id": "4"', sales_prompt)
        self.assertNotIn('"call_id": "2"', sales_prompt)
        self.assertNotIn('"call_id": "3"', sales_prompt)  # voicemail and the like are in no report
        self.assertIn('"call_id": "2"', service_prompt)


if __name__ == "__main__":
    unittest.main()
