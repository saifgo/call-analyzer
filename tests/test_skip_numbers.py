"""Calls involving a number in SKIP_NUMBERS are left out of the pipeline.

    python -m unittest discover tests -v
"""
import os
import tempfile
import unittest
from pathlib import Path

# The settings are read when call_analyzer is imported, so point it at a scratch folder first.
TMP = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
os.environ["DATA_DIR"] = str(Path(TMP.name) / "data")
os.environ["ENV_FILE"] = str(Path(TMP.name) / ".env")

from call_analyzer import db  # noqa: E402
from call_analyzer.config import ENV_PATH  # noqa: E402


class SkipNumbersTests(unittest.TestCase):
    def setUp(self):
        conn = db.connect()
        conn.execute("DELETE FROM calls")
        for call_id, caller, called in (("1", "101", "+216 22 333 444"), ("2", "0021655666777", "102"),
                                        ("3", "103", "98111222"), ("4", "104", "71000000")):
            conn.execute("INSERT INTO calls (id, caller, called, date_call, duration) "
                         "VALUES (?, ?, ?, '2026-10-01 10:00:00', 60)", (call_id, caller, called))
        conn.commit()
        conn.close()

    def tearDown(self):
        ENV_PATH.unlink(missing_ok=True)

    def selected(self, skip_numbers: str, **filters) -> list[str]:
        ENV_PATH.write_text(f"SKIP_NUMBERS={skip_numbers}\n", encoding="utf-8")
        conn = db.connect()  # reads the setting as saved right now
        try:
            return sorted(r["id"] for r in db.select_calls(conn, **filters))
        finally:
            conn.close()

    def test_empty_list_skips_nothing(self):
        self.assertEqual(self.selected(""), ["1", "2", "3", "4"])

    def test_numbers_match_with_or_without_country_code(self):
        self.assertEqual(self.selected("22333444, +216 55 666 777"), ["3", "4"])

    def test_extension_matches_exactly(self):
        self.assertEqual(self.selected("103"), ["1", "2", "4"])
        self.assertEqual(self.selected("10"), ["1", "2", "3", "4"])

    def test_explicitly_chosen_calls_are_processed(self):
        self.assertEqual(self.selected("22333444", ids=["1"]), ["1"])


if __name__ == "__main__":
    unittest.main()
