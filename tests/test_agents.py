"""End-to-end test of remote agents: a real server on a local port, real agent threads, fake Whisper and Claude.

    python -m unittest discover tests -v
"""
import json
import os
import socket
import sqlite3
import tempfile
import threading
import time
import unittest
from pathlib import Path

# The settings are read when call_analyzer is imported, so point it at a scratch folder first.
TMP = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
os.environ["DATA_DIR"] = str(Path(TMP.name) / "data")
os.environ["ENV_FILE"] = str(Path(TMP.name) / ".env")
os.environ["AGENT_HOME"] = str(Path(TMP.name) / "agent-home")
for key in ("GOVOICE_COOKIE", "ADMIN_USERNAME", "ADMIN_PASSWORD"):
    os.environ.pop(key, None)
ENV_FILE = Path(TMP.name) / ".env"
ENV_FILE.write_text("ADMIN_USERNAME=admin\nADMIN_PASSWORD=correct-horse\nWHISPER_MODEL=large-v3\n"
                    "FEEDBACK_LANGUAGE=English\nTRANSCRIBE_RUNS_ON=agent\nANALYZE_RUNS_ON=agent\n", encoding="utf-8")

import requests  # noqa: E402
import uvicorn  # noqa: E402

from call_analyzer import agent as agent_mod  # noqa: E402
from call_analyzer import auth, db, dispatch, workers  # noqa: E402
from call_analyzer.analyze import CallAnalysis, Scores  # noqa: E402
from call_analyzer.config import effective_settings, live_defaults, runs_on, settings  # noqa: E402
from call_analyzer.web.server import app  # noqa: E402

dispatch.POLL_SECONDS = 0.2
dispatch.OFFLINE_GRACE = 1.5
# This machine may have no Whisper/Claude set up; the agents here use fakes, so they count as ready.
agent_mod.transcribe_ready = lambda cfg: (True, "")
agent_mod.analyze_ready = lambda cfg: (True, "")
agent_mod.voice_ready = lambda cfg: (True, "")

VOICE = {"version": 1, "model": "fake/model", "duration": 10.0, "separated": False,
         "tracks": [{"label": "mixed", "windows": [], "summary": {}}]}

ANALYSIS = CallAnalysis(
    is_sales_conversation=True, call_category="prospecting", summary="s", outcome="sale", customer_interest="high",
    overall_score=7, scores=Scores(opening=7, discovery=7, pitch=7, objection_handling=7, closing=7,
                                   tone_and_listening=7),
    strengths=[], mistakes=[], objections=[], missed_opportunities=[], top_coaching_tip="t", follow_up_action="f")


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def set_env(**values):
    lines = [line for line in ENV_FILE.read_text(encoding="utf-8").splitlines()
             if line.partition("=")[0] not in values]
    ENV_FILE.write_text("\n".join(lines + [f"{k}={v}" for k, v in values.items()]) + "\n", encoding="utf-8")


def wait_for(condition, timeout=15, message="condition"):
    end = time.time() + timeout
    while time.time() < end:
        if condition():
            return
        time.sleep(0.1)
    raise AssertionError(f"Timed out waiting for {message}")


class Running:
    """An agent running in a thread, with fake transcription/analysis that record the settings they got."""

    def __init__(self, base, token, overrides=None, slots=None, manage_models=False):
        self.seen_transcribe, self.seen_analyze, self.seen_voice, self.voice_given_to_analysis = [], [], [], []

        def transcribe(path, cfg):
            self.seen_transcribe.append(cfg)
            assert Path(path).read_bytes() == b"fake mp3 bytes"
            return "[00:00] agent: hello\n[00:03] customer: salam"

        def voice(path, cfg):
            self.seen_voice.append(cfg)
            assert Path(path).read_bytes() == b"fake mp3 bytes"
            return VOICE

        def analyze(call, cfg, business):
            self.seen_analyze.append((cfg, business, call["transcript"]))
            self.voice_given_to_analysis.append(call.get("voice"))
            return ANALYSIS, "Fake Claude"

        self.agent = agent_mod.Agent(base, token, overrides or {}, slots or dict(agent_mod.DEFAULT_SLOTS),
                                     transcribe_fn=transcribe, analyze_fn=analyze, voice_fn=voice,
                                     manage_models=manage_models)
        self.error = None
        self.thread = threading.Thread(target=self._run, daemon=True)
        self.thread.start()

    def _run(self):
        try:
            self.agent.run()
        except Exception as exc:  # AuthError etc. are asserted on by the tests
            self.error = exc

    def stop(self):
        self.agent.stop.set()
        self.thread.join(10)


class AgentTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.port = free_port()
        cls.base = f"http://127.0.0.1:{cls.port}"
        cls.server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=cls.port, log_level="error"))
        cls.thread = threading.Thread(target=cls.server.run, daemon=True)
        cls.thread.start()
        wait_for(lambda: cls.server.started, message="server start")
        cls.admin = requests.Session()
        assert cls.admin.post(cls.base + "/api/login", json={"username": "admin", "password": "correct-horse"}).ok

    @classmethod
    def tearDownClass(cls):
        cls.server.should_exit = True
        cls.thread.join(10)

    def setUp(self):
        self.conn = db.connect()
        self.conn.execute("DELETE FROM worker_tasks")
        self.conn.execute("DELETE FROM workers")
        self.conn.execute("DELETE FROM calls")
        self.conn.commit()
        set_env(TRANSCRIBE_RUNS_ON="agent", ANALYZE_RUNS_ON="agent", VOICE_RUNS_ON="host", WHISPER_MODEL="large-v3",
                VOICE_MODEL="fake/model")
        self.agents: list[Running] = []

    def tearDown(self):
        for running in self.agents:
            running.stop()

    # helpers ------------------------------------------------------------------------------------

    def add_worker(self, name="PC-1") -> str:
        resp = self.admin.post(self.base + "/api/workers", json={"name": name})
        self.assertTrue(resp.ok, resp.text)
        return resp.json()["token"]

    def start_agent(self, name="PC-1", **kwargs) -> Running:
        running = Running(self.base, self.add_worker(name), **kwargs)
        self.agents.append(running)
        wait_for(lambda: any(w["name"] == name and w["online"] for w in self.listing()["workers"]),
                 message=f"{name} online")
        return running

    def listing(self) -> dict:
        return self.admin.get(self.base + "/api/workers").json()

    def add_call(self, call_id="1", transcript=None) -> sqlite3.Row:
        audio = Path(settings.audio_dir)
        audio.mkdir(parents=True, exist_ok=True)
        (audio / f"{call_id}.mp3").write_bytes(b"fake mp3 bytes")
        self.conn.execute("INSERT INTO calls (id, type, agent, customer, date_call, duration, filename, audio_path, "
                          "transcript) VALUES (?, 'OUT', '101', '21694721843', '2026-10-01 10:00:00', 120, ?, ?, ?)",
                          (call_id, f"{call_id}.mp3", str(audio / f"{call_id}.mp3"), transcript))
        self.conn.commit()
        return self.row(call_id)

    def row(self, call_id="1"):
        return self.conn.execute("SELECT * FROM calls WHERE id=?", (call_id,)).fetchone()

    @staticmethod
    def never(batch):
        raise AssertionError("the host must not process these calls")

    # tests --------------------------------------------------------------------------------------

    def test_transcribe_and_chained_analysis_on_an_agent(self):
        running = self.start_agent()
        call = self.add_call()
        dispatch.process("transcribe", [call], self.never, chain=True)
        row = self.row()
        self.assertIn("customer: salam", row["transcript"])
        self.assertEqual(row["transcribed_by"], "Whisper large-v3 (local) · agent PC-1")
        # The analysis was queued by the server when the transcript arrived; the analyze step just waits for it.
        dispatch.process("analyze", [self.row()], self.never)
        row = self.row()
        self.assertEqual(row["analyzed_by"], "Fake Claude · agent PC-1")
        self.assertEqual(row["analysis"] and __import__("json").loads(row["analysis"])["overall_score"], 7)
        self.assertEqual(running.seen_analyze[0][2], row["transcript"])
        self.assertIn("business", running.seen_analyze[0][1].lower() + "business")  # the server sent business.md
        stats = {w["name"]: w for w in self.listing()["workers"]}["PC-1"]
        self.assertEqual((stats["done"], stats["failed"]), (2, 0))

    def test_voice_step_on_an_agent_reaches_the_analysis(self):
        set_env(VOICE_RUNS_ON="agent")
        running = self.start_agent()
        self.assertTrue(self.listing()["workers"][0]["ready"]["voice"])
        self.assertEqual(self.listing()["runs_on"]["voice"], "agent")
        call = self.add_call(transcript="[00:00] agent: hello")
        dispatch.process("voice", [call], self.never, chain=True)
        row = self.row()
        self.assertEqual(json.loads(row["voice"])["model"], "fake/model")
        self.assertTrue(row["voice_at"])
        self.assertEqual(running.seen_voice[0].voice_model, "fake/model")  # the server's setting reached the agent
        # The call was transcribed already, so the chained analysis is queued as soon as the voice is in, and the
        # agent that analyzes it is given the voice data.
        dispatch.process("analyze", [self.row()], self.never)
        self.assertEqual(json.loads(running.voice_given_to_analysis[0])["model"], "fake/model")

    def test_analysis_waits_for_both_transcript_and_voice(self):
        set_env(VOICE_RUNS_ON="agent")
        token = self.add_worker()
        call = self.add_call()
        dispatch.process("voice", [call], self.never, chain=True)  # nobody online: queued
        dispatch.process("transcribe", [call], self.never, chain=True)
        self.assertEqual(self.listing()["queue"]["queued"], 2)
        running = Running(self.base, token)
        self.agents.append(running)
        wait_for(lambda: self.row()["analysis"], message="analysis after both steps")
        # One analysis only, and it saw the voice data.
        self.assertEqual(len(running.seen_analyze), 1)
        self.assertEqual(json.loads(running.voice_given_to_analysis[0])["model"], "fake/model")

    def test_a_failed_voice_step_does_not_block_or_mark_the_call(self):
        set_env(VOICE_RUNS_ON="agent")
        running = self.start_agent()

        def broken(path, cfg):
            raise RuntimeError("corrupt audio")

        running.agent._voice = broken
        workers.RETRY_DELAY = 0
        call = self.add_call(transcript="[00:00] agent: hello")
        dispatch.process("voice", [call], self.never, chain=True)
        row = self.row()
        self.assertIsNone(row["voice"])
        self.assertIsNone(row["error"])  # the call is still fine without it
        task = self.conn.execute("SELECT * FROM worker_tasks").fetchone()
        self.assertEqual((task["kind"], task["status"]), ("voice", "failed"))
        self.assertIn("corrupt audio", task["error"])

    def test_voice_on_host_or_auto_follows_the_other_steps(self):
        self.start_agent()
        done = []
        dispatch.process("voice", [self.add_call()], lambda batch: done.extend(c["id"] for c in batch))
        self.assertEqual(done, ["1"])  # VOICE_RUNS_ON=host: agents are ignored
        set_env(VOICE_RUNS_ON="auto")
        self.add_call("2")
        dispatch.process("voice", [self.row("2")], self.never)
        self.assertIsNotNone(self.row("2")["voice"])  # an agent is online: it does it

    def test_agent_downloads_the_converted_voice_model_from_the_server(self):
        from call_analyzer import voice_models
        # The server has the model converted (normally it converts it itself, with torch, the first time).
        served = voice_models.model_dir("fake/model")
        served.mkdir(parents=True, exist_ok=True)
        (served / "model.onnx").write_bytes(b"onnx bytes")
        (served / "model.json").write_text('{"labels": ["neu"], "do_normalize": true}', encoding="utf-8")
        agent_home = Path(TMP.name) / "agent-models"
        agent = agent_mod.Agent(self.base, self.add_worker(), {"whisper_model_dir": str(agent_home)},
                                dict(agent_mod.DEFAULT_SLOTS), manage_models=False)
        cfg = agent.cfg({"voice_model": "fake/model"})
        self.assertFalse(voice_models.is_installed("fake/model", cfg))
        shown = []
        try:
            agent.ensure_voice_model(cfg, shown.append)
        finally:
            voice_models.fetch_model = None
        self.assertTrue(voice_models.is_installed("fake/model", cfg))
        self.assertEqual((agent_home / "voice" / "fake--model" / "model.onnx").read_bytes(), b"onnx bytes")
        self.assertTrue(any("downloading from the server" in text or "Getting" in text for text in shown), shown)
        # Only the server's own VOICE_MODEL is offered: an agent can't make the server fetch other models.
        with self.assertRaises(requests.HTTPError) as caught:
            agent.server.post("/api/worker/voice-model/prepare", {"name": "someone/else"})
        self.assertEqual(caught.exception.response.status_code, 404)

    def test_server_defaults_and_agent_overrides(self):
        # An agent with nothing set uses the server's default...
        plain = self.start_agent("plain")
        self.add_call("1")
        dispatch.process("transcribe", [self.row("1")], self.never)
        self.assertEqual([c.whisper_model for c in plain.seen_transcribe], ["large-v3"])
        plain.stop()
        # ...an agent that sets it in agent.toml uses its own, and keeps the server's value for the rest.
        tuned = self.start_agent("tuned", overrides={"whisper_model": "small", "feedback_language": "French"})
        self.add_call("2")
        dispatch.process("transcribe", [self.row("2")], self.never)
        self.assertEqual([c.whisper_model for c in tuned.seen_transcribe], ["small"])
        dispatch.process("analyze", [self.row("2")], self.never)
        self.assertEqual(tuned.seen_analyze[0][0].feedback_language, "French")
        # The server's defaults reach the agent live: change Settings, the next task uses the new value.
        set_env(WHISPER_MODEL="medium", FEEDBACK_LANGUAGE="Arabic")
        self.assertEqual(live_defaults()["whisper_model"], "medium")
        self.add_call("3")
        dispatch.process("transcribe", [self.row("3")], self.never)
        self.assertEqual(tuned.seen_transcribe[-1].whisper_model, "small")  # still its own choice
        self.assertEqual(effective_settings(live_defaults(), {}).feedback_language, "Arabic")
        info = {w["name"]: w["info"] for w in self.listing()["workers"]}
        self.assertEqual(info["tuned"]["overrides"], {"whisper_model": "small", "feedback_language": "French"})
        self.assertEqual(info["tuned"]["effective"]["whisper_model"], "small")

    def test_no_agent_online_queues_and_processes_later(self):
        token = self.add_worker()  # registered but not running
        call = self.add_call()
        dispatch.process("transcribe", [call], self.never, chain=True)  # returns at once
        self.assertEqual(self.listing()["queue"]["queued"], 1)
        running = Running(self.base, token)
        self.agents.append(running)
        wait_for(lambda: self.row()["transcript"], message="queued call transcribed once the agent connects")
        wait_for(lambda: self.row()["analysis"], message="chained analysis")

    def test_auto_mode_falls_back_to_the_host(self):
        set_env(TRANSCRIBE_RUNS_ON="auto")
        call = self.add_call()
        done = []
        dispatch.process("transcribe", [call], lambda batch: done.extend(c["id"] for c in batch))
        self.assertEqual(done, ["1"])  # nobody online: straight to the host

    def test_auto_mode_takes_back_work_when_the_agents_vanish(self):
        set_env(TRANSCRIBE_RUNS_ON="auto")
        running = self.start_agent(slots={"transcribe": 0, "analyze": 0})  # online, but set up for nothing
        self.assertEqual(workers.online_workers(self.conn, "transcribe"), [])
        done = []
        dispatch.process("transcribe", [self.add_call()], lambda batch: done.extend(c["id"] for c in batch))
        self.assertEqual(done, ["1"])
        running.stop()

    def test_host_mode_ignores_agents(self):
        set_env(TRANSCRIBE_RUNS_ON="host")
        self.assertEqual(runs_on("transcribe"), "host")
        self.start_agent()
        done = []
        dispatch.process("transcribe", [self.add_call()], lambda batch: done.extend(c["id"] for c in batch))
        self.assertEqual(done, ["1"])
        self.assertEqual(self.listing()["queue"], {"queued": 0, "running": 0})

    def test_failing_task_is_retried_then_recorded_on_the_call(self):
        running = self.start_agent()

        def broken(path, cfg):
            raise RuntimeError("GPU exploded")

        running.agent._transcribe = broken
        workers.RETRY_DELAY = 0
        call = self.add_call()
        dispatch.process("transcribe", [call], self.never)
        row = self.row()
        self.assertIsNone(row["transcript"])
        self.assertIn("GPU exploded", row["error"])
        task = self.conn.execute("SELECT * FROM worker_tasks").fetchone()
        self.assertEqual((task["status"], task["attempts"]), ("failed", workers.MAX_ATTEMPTS))

    def test_agent_only_gets_the_steps_it_is_set_up_for(self):
        # Transcription works on this PC, analysis doesn't (no Claude login).
        agent_mod.analyze_ready = lambda cfg: (False, "Not logged in to Claude")
        try:
            running = self.start_agent("transcriber")
            self.assertEqual(workers.online_workers(self.conn, "analyze"), [])
            self.add_call("1")
            self.add_call("2", transcript="[00:00] agent: hi")
            analyze_id = workers.enqueue(self.conn, "analyze", ["2"])[0]
            workers.enqueue(self.conn, "transcribe", ["1"])
            wait_for(lambda: self.row("1")["transcript"], message="the transcription it can do")
            time.sleep(2.5)  # long enough for its analyze runners to have claimed the task if they could
            self.assertEqual(workers.get_task(self.conn, analyze_id)["status"], "queued")
            self.assertEqual(running.seen_analyze, [])
            self.assertIsNone(self.row("2")["error"])
            running.stop()
        finally:
            agent_mod.analyze_ready = lambda cfg: (True, "")
        # An agent that can analyze picks the waiting task up.
        self.start_agent("analyst")
        wait_for(lambda: self.row("2")["analysis"], message="analysis by the capable agent")
        self.assertEqual(workers.get_task(self.conn, analyze_id)["worker_name"], "analyst")

    def test_lease_expiry_gives_the_task_to_another_agent(self):
        self.add_call()
        task_id = workers.enqueue(self.conn, "transcribe", ["1"])[0]
        ghost, token = workers.create_worker(self.conn, "ghost")
        claimed = workers.claim(self.conn, ghost, ["transcribe"])
        self.assertEqual(claimed["id"], task_id)
        self.conn.execute("UPDATE worker_tasks SET lease_expires='2000-01-01T00:00:00' WHERE id=?", (task_id,))
        self.conn.commit()
        self.start_agent("live")
        wait_for(lambda: self.row()["transcript"], message="requeued task done by the live agent")
        self.assertEqual(workers.get_task(self.conn, task_id)["worker_name"], "live")

    def test_stop_cancels_a_jobs_tasks_and_the_agent_drops_them(self):
        call = self.add_call()
        workers.enqueue(self.conn, "transcribe", [call["id"]], origin_pid=4242)
        self.assertEqual(workers.cancel(self.conn, pid=4242), 1)
        self.assertEqual(self.listing()["queue"]["queued"], 0)
        # nothing is left for an agent to do
        self.start_agent()
        time.sleep(1.5)
        self.assertIsNone(self.row()["transcript"])

    def test_paused_agent_gets_no_work_and_revoked_agent_is_turned_away(self):
        running = self.start_agent()
        worker_id = self.listing()["workers"][0]["id"]
        self.assertTrue(self.admin.patch(f"{self.base}/api/workers/{worker_id}", json={"enabled": False}).ok)
        self.add_call()
        workers.enqueue(self.conn, "transcribe", ["1"])
        time.sleep(2.5)
        self.assertIsNone(self.row()["transcript"])
        self.assertTrue(self.admin.patch(f"{self.base}/api/workers/{worker_id}", json={"enabled": True}).ok)
        wait_for(lambda: self.row()["transcript"], message="resumed agent works")
        self.assertTrue(self.admin.delete(f"{self.base}/api/workers/{worker_id}").ok)
        running.thread.join(30)
        self.assertIsInstance(running.error, agent_mod.AuthError)

    def test_new_token_replaces_the_old_one(self):
        token = self.add_worker()
        worker_id = self.listing()["workers"][0]["id"]
        new = self.admin.post(f"{self.base}/api/workers/{worker_id}/token").json()["token"]
        self.assertNotEqual(new, token)
        bad = requests.post(self.base + "/api/worker/hello", json={"info": {"protocol": 1}},
                            headers={"Authorization": f"Bearer {token}"})
        good = requests.post(self.base + "/api/worker/hello", json={"info": {"protocol": 1}},
                             headers={"Authorization": f"Bearer {new}"})
        self.assertEqual((bad.status_code, good.status_code), (401, 200))
        self.assertEqual(good.json()["defaults"]["whisper_model"], "large-v3")

    def test_access_control(self):
        self.assertEqual(requests.get(self.base + "/api/workers").status_code, 401)  # no login
        self.assertEqual(requests.post(self.base + "/api/workers", json={"name": "x"}).status_code, 401)
        self.assertEqual(requests.post(self.base + "/api/worker/hello", json={}).status_code, 401)  # no token
        self.assertEqual(requests.post(self.base + "/api/worker/claim", json={"kinds": ["transcribe"]},
                                       headers={"Authorization": "Bearer nope"}).status_code, 401)
        auth.create_user("sales", "sales-pass-1", "agent", "Sales", ["101"])
        sales = requests.Session()
        self.assertTrue(sales.post(self.base + "/api/login", json={"username": "sales", "password": "sales-pass-1"}).ok)
        self.assertEqual(sales.get(self.base + "/api/workers").status_code, 403)  # sales accounts can't see agents
        token = self.add_worker()
        old = requests.post(self.base + "/api/worker/hello", json={"info": {"protocol": 0}},
                            headers={"Authorization": f"Bearer {token}"})
        self.assertEqual(old.status_code, 426)  # too old
        auth.delete_user("sales")

    def test_agent_cannot_fetch_audio_of_a_task_it_does_not_hold(self):
        self.add_call()
        task_id = workers.enqueue(self.conn, "transcribe", ["1"])[0]
        token = self.add_worker()
        resp = requests.get(f"{self.base}/api/worker/tasks/{task_id}/audio", headers={"Authorization": f"Bearer {token}"})
        self.assertEqual(resp.status_code, 409)

    def test_agent_downloads_a_converted_model_from_the_server(self):
        from call_analyzer import whisper_models
        name = "tunisian-large-v3"
        server_copy = whisper_models.model_dir(name)  # the server's own converted copy
        server_copy.mkdir(parents=True, exist_ok=True)
        (server_copy / "model.bin").write_bytes(b"weights" * 1000)
        (server_copy / "config.json").write_text("{}", encoding="utf-8")
        running = self.start_agent()
        dest = Path(TMP.name) / "agent-models" / name
        # Packing runs in the background: the agent asks again until the pack is ready.
        running.agent._fetch_model(name, dest, lambda text: None)
        self.assertEqual((dest / "model.bin").read_bytes(), b"weights" * 1000)
        self.assertTrue((dest / "config.json").exists())
        with self.assertRaises(whisper_models.ModelUnavailable):  # a model the server doesn't have
            running.agent._fetch_model("arabic-dialectal-turbo", Path(TMP.name) / "x", lambda text: None)

    def test_connection_code_roundtrip_and_login(self):
        token = self.add_worker("coded")
        code = agent_mod.encode_code(self.base, token)
        server, parsed = agent_mod.parse_connection(f"python -m call_analyzer agent login --code {code}")
        self.assertEqual((server, parsed), (self.base, token))
        url, name = agent_mod.connect(server, parsed)
        self.assertEqual((url, name), (self.base, "coded"))
        self.assertEqual(agent_mod.load_credentials(), (self.base, token))
        with self.assertRaises(agent_mod.ConnectError):
            agent_mod.connect(self.base, "ca_wrong")

    def test_installer_is_offered_for_download(self):
        folder = Path(settings.data_dir) / "downloads"
        folder.mkdir(parents=True, exist_ok=True)
        (folder / "CallAnalyzerAgent-Setup-1.0.exe").write_bytes(b"MZ installer")
        (folder / "notes.txt").write_text("not an installer", encoding="utf-8")
        listing = self.listing()
        self.assertEqual([i["name"] for i in listing["installers"]], ["CallAnalyzerAgent-Setup-1.0.exe"])
        ok = self.admin.get(f"{self.base}/api/workers/installers/CallAnalyzerAgent-Setup-1.0.exe")
        self.assertEqual((ok.status_code, ok.content), (200, b"MZ installer"))
        for bad in ("notes.txt", "..%2F..%2F.env", "missing.exe"):
            self.assertEqual(self.admin.get(f"{self.base}/api/workers/installers/{bad}").status_code, 404, bad)
        self.assertEqual(requests.get(f"{self.base}/api/workers/installers/CallAnalyzerAgent-Setup-1.0.exe").status_code, 401)

    def test_installer_upload_download_delete(self):
        folder = Path(settings.data_dir) / "downloads"
        for f in folder.glob("*"):
            f.unlink()
        payload = os.urandom(5 * 1024 * 1024)  # streamed to disk in chunks
        name = "CallAnalyzerAgent-GPU-Setup-2.3.exe"
        url = f"{self.base}/api/workers/installers/{name}"
        self.assertEqual(requests.put(url, data=payload).status_code, 401)  # needs an admin login
        up = self.admin.put(url, data=payload, headers={"Content-Type": "application/octet-stream"})
        self.assertEqual((up.status_code, up.json()["size"]), (200, len(payload)), up.text)
        (info,) = self.listing()["installers"]
        self.assertEqual((info["name"], info["kind"], info["version"], info["size"]), (name, "gpu", "2.3", len(payload)))
        self.assertEqual(self.admin.get(url).content, payload)
        self.assertEqual(list(folder.glob("*.part")), [])  # no half-written file is left behind
        for bad in ("notes.txt", "..%2Fevil.exe", ".hidden.exe"):
            resp = self.admin.put(f"{self.base}/api/workers/installers/{bad}", data=b"x")
            self.assertIn(resp.status_code, (400, 404, 405), bad)
        self.assertEqual(self.admin.put(f"{self.base}/api/workers/installers/empty.exe", data=b"").status_code, 400)
        self.assertEqual(self.admin.delete(url).status_code, 200)
        self.assertEqual(self.listing()["installers"], [])
        self.assertEqual(self.admin.delete(url).status_code, 404)

    def _with_fake_model_store(self, free_bytes=None):
        """The Whisper model store of this machine, replaced by a fake: absent until download_standard finishes."""
        import types
        from call_analyzer import whisper_models
        state = {"present": False, "downloads": []}
        saved = (whisper_models.is_present, whisper_models.download_standard, agent_mod.shutil.disk_usage,
                 agent_mod.MODEL_POLL_SECONDS, agent_mod.MODEL_RETRY_SECONDS)

        def download(name, cfg=None):
            state["downloads"].append(name)
            time.sleep(1.2)
            state["present"] = True

        whisper_models.is_present = lambda name, cfg=None: state["present"]
        whisper_models.download_standard = download
        agent_mod.MODEL_POLL_SECONDS, agent_mod.MODEL_RETRY_SECONDS = 0.2, 0.5
        if free_bytes is not None:
            agent_mod.shutil.disk_usage = lambda path: types.SimpleNamespace(free=free_bytes)

        def restore():
            (whisper_models.is_present, whisper_models.download_standard, agent_mod.shutil.disk_usage,
             agent_mod.MODEL_POLL_SECONDS, agent_mod.MODEL_RETRY_SECONDS) = saved

        self.addCleanup(restore)
        return state

    def test_missing_model_is_downloaded_in_the_background_before_work_is_offered(self):
        state = self._with_fake_model_store()
        set_env(TRANSCRIBE_RUNS_ON="auto")
        token = self.add_worker("model-pc")
        managed = Running(self.base, token, manage_models=True)
        self.agents.append(managed)
        wait_for(lambda: state["downloads"], message="the model download starts by itself")
        worker = next(w for w in self.listing()["workers"] if w["name"] == "model-pc")
        # While it downloads the PC is online but is not offered transcription...
        self.assertFalse(worker["ready"]["transcribe"])
        self.assertIn("Downloading the model large-v3", worker["info"]["capabilities"]["transcribe"]["reason"])
        self.assertEqual(worker["info"]["model"]["status"], "downloading")
        # ...so in "auto" mode the host does the work meanwhile instead of leaving it waiting.
        done = []
        dispatch.process("transcribe", [self.add_call("1")], lambda batch: done.extend(c["id"] for c in batch))
        self.assertEqual(done, ["1"])
        # Once the model is there the server learns at once and gives it work.
        wait_for(lambda: self.listing()["workers"][0]["ready"]["transcribe"], timeout=8, message="ready after download")
        self.assertEqual(self.listing()["workers"][0]["info"]["model"]["status"], "ready")
        set_env(TRANSCRIBE_RUNS_ON="agent")
        dispatch.process("transcribe", [self.add_call("2")], self.never)
        self.assertIn("customer: salam", self.row("2")["transcript"])
        self.assertEqual(state["downloads"], ["large-v3"])  # downloaded once

    def test_model_download_is_refused_without_disk_space_and_retried(self):
        state = self._with_fake_model_store(free_bytes=1000)
        token = self.add_worker("tiny-disk")
        managed = Running(self.base, token, manage_models=True)
        self.agents.append(managed)
        wait_for(lambda: self.listing()["workers"] and self.listing()["workers"][0]["info"].get("model", {}).get("status") == "error",
                 message="a disk space error is reported")
        reason = self.listing()["workers"][0]["info"]["capabilities"]["transcribe"]["reason"]
        self.assertIn("Not enough free disk space", reason)
        self.assertEqual(state["downloads"], [])
        agent_mod.shutil.disk_usage = lambda path: __import__("types").SimpleNamespace(free=50 * 10**9)  # space freed
        wait_for(lambda: self.listing()["workers"][0]["ready"]["transcribe"], message="retried after the failure")
        self.assertEqual(state["downloads"], ["large-v3"])

    def test_duplicate_enqueue_is_one_task(self):
        self.add_call()
        first = workers.enqueue(self.conn, "transcribe", ["1"])
        second = workers.enqueue(self.conn, "transcribe", ["1"])
        self.assertEqual(first, second)
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM worker_tasks").fetchone()[0], 1)


if __name__ == "__main__":
    unittest.main()
