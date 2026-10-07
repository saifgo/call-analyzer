"""Voice tone: measurements from the audio, stored on the call, given to the analysis, scored as `voice`.

    python -m unittest discover tests -v
"""
import json
import os
import tempfile
import unittest
from pathlib import Path

import numpy as np

# The settings are read when call_analyzer is imported, so point it at a scratch folder first.
TMP = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
os.environ["DATA_DIR"] = str(Path(TMP.name) / "data")
os.environ["ENV_FILE"] = str(Path(TMP.name) / ".env")

from call_analyzer import analyze, db, voice  # noqa: E402
from call_analyzer.config import settings  # noqa: E402

SR = voice.SAMPLE_RATE
VOICE_TONE = {"score": 6, "agent_tone": "calm_professional", "customer_tone": "frustrated", "evidence": "00:10-00:20 calm",
              "coaching_tip": "smile", "confidence": "medium"}
SALES = {"is_sales_conversation": True, "call_category": "prospecting", "summary": "s", "outcome": "sale",
         "customer_interest": "high", "overall_score": 7,
         "scores": dict(opening=7, discovery=7, pitch=7, objection_handling=7, closing=7, tone_and_listening=7),
         "strengths": [], "mistakes": [], "objections": [], "missed_opportunities": [], "top_coaching_tip": "t",
         "follow_up_action": "f"}


def fake_voice() -> dict:
    windows = [
        {"start": 0.0, "end": 4.0, "db": -20.0, "pitch_st": 3.1, "emotion": {"neutral": 0.8, "angry": 0.2}},
        {"start": 10.0, "end": 14.0, "db": -12.0, "pitch_st": 1.2, "emotion": {"angry": 0.9, "neutral": 0.1}},
    ]
    return {"version": 1, "model": "fake/model", "duration": 30.0, "separated": False,
            "tracks": [{"label": "mixed", "windows": windows, "summary": voice._summary(windows, 30.0, [(0, 4), (10, 14)])}]}


class AcousticsTests(unittest.TestCase):
    def tone(self, freq):
        t = np.arange(SR * 2) / SR
        return (0.3 * np.sin(2 * np.pi * np.cumsum(freq(t)) / SR)).astype(np.float32)

    def test_steady_pitch_is_monotone_and_moving_pitch_is_not(self):
        steady = voice._pitch(self.tone(lambda t: np.full_like(t, 150.0)))
        moving = voice._pitch(self.tone(lambda t: 150 * 2 ** (4 * np.sin(2 * np.pi * 1.5 * t) / 12)))
        self.assertLess(steady, 0.5)
        self.assertGreater(moving, 1.5)

    def test_silence_and_noise_have_no_pitch(self):
        self.assertIsNone(voice._pitch(np.zeros(SR, dtype=np.float32)))
        self.assertIsNone(voice._pitch(np.random.default_rng(1).normal(0, 0.1, SR).astype(np.float32)))

    def test_summary_weighs_emotions_by_time_and_counts_pauses(self):
        windows = fake_voice()["tracks"][0]["windows"]
        summary = voice._summary(windows, 30.0, [(0, 4), (10, 14)])
        self.assertEqual(summary["speech_seconds"], 8.0)
        self.assertEqual(summary["emotion_share"]["angry"], 0.55)
        self.assertEqual(summary["angry_seconds"], 4.0)  # only the second window is clearly angry
        self.assertEqual((summary["long_pauses"], summary["longest_pause_s"]), (1, 6.0))

    def test_labels_of_other_models_are_mapped(self):
        class Clf:
            def __call__(self, audio):
                return [{"label": "ang", "score": 0.6}, {"label": "Anger", "score": 0.1}, {"label": "neu", "score": 0.3}]

        self.assertEqual(voice._emotions(Clf(), np.zeros(SR)), {"angry": 0.7, "neutral": 0.3})


class StoredVoiceTests(unittest.TestCase):
    def setUp(self):
        self.conn = db.connect()
        self.conn.execute("DELETE FROM calls")
        self.audio = Path(TMP.name) / "a.mp3"
        self.audio.write_bytes(b"x")
        self.conn.execute("INSERT INTO calls (id, filename, audio_path) VALUES ('1', 'a.mp3', ?)", (str(self.audio),))
        self.conn.execute("INSERT INTO calls (id, filename) VALUES ('2', 'b.mp3')")  # not downloaded
        self.conn.commit()
        self._analyze_audio = voice.analyze_audio
        self.measured = []
        voice.analyze_audio = lambda path, cfg=None: self.measured.append(path) or fake_voice()

    def tearDown(self):
        voice.analyze_audio = self._analyze_audio

    def calls(self):
        return self.conn.execute("SELECT * FROM calls ORDER BY id").fetchall()

    def test_ensure_measures_downloaded_calls_once(self):
        self.assertEqual(voice.ensure(self.conn, self.calls()), 1)
        row = self.calls()[0]
        self.assertEqual(json.loads(row["voice"])["model"], "fake/model")
        self.assertTrue(row["voice_at"])
        self.assertEqual(voice.ensure(self.conn, self.calls()), 0)  # already done
        self.assertEqual(voice.ensure(self.conn, self.calls(), redo=True), 1)
        self.assertEqual(len(self.measured), 2)

    def test_a_recording_that_cannot_be_read_does_not_stop_the_pipeline(self):
        def broken(path, cfg=None):
            raise RuntimeError("corrupt mp3")

        voice.analyze_audio = broken
        self.assertEqual(voice.ensure(self.conn, self.calls()), 0)
        self.assertIsNone(self.calls()[0]["voice"])

    def test_it_can_be_turned_off(self):
        from dataclasses import replace
        self.assertEqual(voice.ensure(self.conn, self.calls(), cfg=replace(settings, voice_analysis=False)), 0)
        self.assertEqual(self.measured, [])

    def test_of_call_reads_rows_dicts_and_calls_without_voice(self):
        voice.ensure(self.conn, self.calls())
        self.assertEqual(voice.of_call(self.calls()[0])["model"], "fake/model")
        self.assertIsNone(voice.of_call(self.calls()[1]))
        self.assertEqual(voice.of_call({"voice": json.dumps(fake_voice())})["duration"], 30.0)
        self.assertIsNone(voice.of_call({"transcript": "t"}))  # a dict from an older server
        self.assertIsNone(voice.of_call({"voice": None}))

    def test_description_for_the_prompt(self):
        text = voice.describe(fake_voice())
        self.assertIn("fake/model", text)
        self.assertIn("mono recording", text)
        self.assertIn("00:10-00:14", text)
        self.assertIn("angry 0.90", text)
        self.assertIn("1 pauses over 4s", text)


class AnalysisTests(unittest.TestCase):
    def setUp(self):
        self.seen = []
        self._ask, self._labeled = analyze.ask_model, analyze.ask_model_labeled

        def ask(system, prompt, schema=None, cfg=None):
            self.seen.append((system, prompt, schema))
            if schema and "reason" in schema["properties"]:
                return {"reason": "x", "call_kind": "sales"}
            return {**SALES, **({"voice": VOICE_TONE} if "voice" in schema["properties"] else {})}

        analyze.ask_model = ask
        analyze.ask_model_labeled = lambda system, prompt, schema=None, cfg=None: (ask(system, prompt, schema, cfg), "Fake")

    def tearDown(self):
        analyze.ask_model, analyze.ask_model_labeled = self._ask, self._labeled

    CALL = {"id": "1", "agent": "101", "customer": "216", "date_call": "2026-10-01", "duration": 90, "type": "IN",
            "transcript": "[00:00] agent: Allo"}

    def test_a_measured_call_is_scored_on_its_voice(self):
        analysis, _ = analyze.analyze_call({**self.CALL, "voice": json.dumps(fake_voice())})
        system, prompt, schema = self.seen[1]
        self.assertIn("<voice_analysis>", prompt)
        self.assertIn("angry 0.90", prompt)
        self.assertIn("voice_analysis", system)
        self.assertIn("voice", schema["required"])
        self.assertEqual(schema["properties"]["voice"], {"$ref": "#/$defs/VoiceTone"})
        self.assertIn("VoiceTone", schema["$defs"])
        self.assertEqual((analysis.voice.score, analysis.voice.agent_tone), (6, "calm_professional"))

    def test_a_call_without_audio_data_is_analyzed_as_before(self):
        analysis, _ = analyze.analyze_call(self.CALL)
        system, prompt, schema = self.seen[1]
        self.assertNotIn("voice_analysis", prompt + system)
        self.assertNotIn("voice", schema["properties"])
        self.assertNotIn("VoiceTone", schema.get("$defs", {}))
        self.assertIsNone(analysis.voice)

    def test_both_score_cards_can_carry_a_voice_part(self):
        service = {"call_kind": "service", "issue_category": "other", "summary": "s", "resolution_status": "resolved",
                   "customer_sentiment": "satisfied", "overall_score": 8,
                   "scores": dict(greeting=8, understanding=8, solution=8, clarity=8, empathy_and_tone=8, resolution=8),
                   "strengths": [], "mistakes": [], "missed_opportunities": [], "top_coaching_tip": "t",
                   "follow_up_action": "f", "voice": VOICE_TONE}
        self.assertEqual(analyze.parse_analysis(service).voice.confidence, "medium")
        self.assertIsNone(analyze.parse_analysis(SALES).voice)  # analyses from before voice analysis stay valid
        with self.assertRaises(Exception):
            analyze.parse_analysis({**SALES, "voice": {**VOICE_TONE, "agent_tone": "furious"}})


class ExportTests(unittest.TestCase):
    def test_the_call_page_shows_the_voice_part_only_when_there_is_one(self):
        from call_analyzer.web.export import render_call_page
        row = {"id": "1", "type": "IN", "agent": "101", "customer": "216", "date_call": "2026-10-01 10:00:00",
               "duration": 90, "transcript": "[00:00] hi"}
        with_voice = render_call_page({**row, "analysis": json.dumps({**SALES, "voice": VOICE_TONE})}, audio_src=None, links=[])
        self.assertIn("Voice tone", with_voice)
        self.assertIn("Calm professional", with_voice)
        self.assertIn("00:10-00:20 calm", with_voice)
        self.assertNotIn("Voice tone", render_call_page({**row, "analysis": json.dumps(SALES)}, audio_src=None, links=[]))


class CatalogTests(unittest.TestCase):
    def test_the_default_model_is_one_of_the_choices_and_the_list_says_what_is_installed(self):
        from call_analyzer import voice_models
        from call_analyzer.web.server import voice_models_list
        self.assertIn(settings.voice_model, voice_models.VOICE_MODELS)
        served = voice_models.model_dir("superb/wav2vec2-base-superb-er")
        served.mkdir(parents=True, exist_ok=True)
        for name in ("model.onnx", "model.json"):
            (served / name).write_bytes(b"x")
        listing = {m["name"]: m for m in voice_models_list()}
        self.assertEqual(set(listing), set(voice_models.VOICE_MODELS))
        self.assertTrue(listing["superb/wav2vec2-base-superb-er"]["installed"])
        self.assertFalse(listing["Aniemore/wav2vec2-emotion-v1-crosslingual"]["installed"])

    def test_labels_of_the_listed_models_map_to_the_shared_names_and_tension_counts_as_angry(self):
        for label, expected in (("Tension", "tense"), ("Pleased", "happy"), ("Relaxed", "neutral"),
                                ("enthusiasm", "happy"), ("anger", "angry"), ("sadness", "sad")):
            self.assertEqual(voice.CANONICAL[label.lower()], expected)
        windows = [{"start": 0.0, "end": 4.0, "db": -20.0, "emotion": {"tense": 0.7, "neutral": 0.3}}]
        self.assertEqual(voice._summary(windows, 10.0, [(0, 4)])["angry_seconds"], 4.0)


if __name__ == "__main__":
    unittest.main()
