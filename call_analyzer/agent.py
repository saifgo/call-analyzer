"""Remote agent: lets a PC do the heavy steps (Whisper, Claude) for a hosted Call Analyzer server.

    python -m call_analyzer agent login --server https://calls.example.com --token ca_...
    python -m call_analyzer agent run

The agent only makes outgoing HTTPS requests, so it works behind any router or firewall. It asks the server for
work (long polling), downloads the audio, transcribes or analyzes it with this PC's GPU and logins, and sends
the result back. See workers.py for the server side.

Settings: the agent takes the server's current defaults (model, language, backend, ...) with every task, and uses
its own value for anything set in agent.toml. API keys and the Claude login always come from this PC.
"""
import base64
import json
import logging
import logging.handlers
import os
import platform
import re
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import time
import tomllib
import zipfile
from importlib.util import find_spec
from pathlib import Path

import requests

from .config import (AGENT_LOCAL_KEYS, AGENT_OVERRIDE_KEYS, AGENT_SERVER_KEYS, FROZEN, ROOT, Settings,
                     agent_home, effective_settings, settings)
from .workers import KINDS, PROTOCOL

VERSION = "1.0"
HEARTBEAT_SECONDS = 15
CLAIM_WAIT = 20  # seconds the server holds a request open waiting for work
DEFAULT_SLOTS = {"transcribe": 1, "analyze": 2}  # tasks of each kind this PC works on at once
SECRET_KEYS = {k for k in AGENT_LOCAL_KEYS if k.endswith("_api_key")}
EXIT_AUTH, EXIT_OUTDATED = 4, 5

log = logging.getLogger("agent")


class ConnectError(Exception):
    """Connecting to the server failed (message is meant for the user)."""


class AuthError(Exception):
    """The server doesn't accept this agent's token (it was revoked or rotated)."""


class OutdatedError(Exception):
    """The server needs a newer agent than this one."""


# --- Agent folder: credentials and local overrides ----------------------------------------------

def home() -> Path:
    return agent_home()


def credentials_path() -> Path:
    return home() / "agent.json"


def overrides_path() -> Path:
    return home() / "agent.toml"


OVERRIDES_TEMPLATE = """\
# Settings of this agent. The server's defaults apply to everything you don't set here.
# Remove the leading # to override a setting on this PC only. Changes apply to the next task.

[tasks]
# How many tasks of each kind this PC works on at once. 0 turns the step off here.
# transcribe = 1
# analyze = 2

[overrides]
# whisper_model = "large-v3-turbo"   # e.g. a lighter model than the server's default, for a weak GPU
# whisper_device = "cpu"             # auto | cuda | cpu
# whisper_language = "fr"
# whisper_model_dir = "D:\\\\models"     # where Whisper models are stored on this PC
# claude_backend = "subscription"    # use this PC's Claude Code login instead of an API key
# claude_model = "claude-opus-5-5"
# analysis_backend = "claude"        # claude | cursor | auto
# feedback_language = "French"
"""


def load_local() -> tuple[dict, dict]:
    """(overrides, slots) from agent.toml. Unknown settings are ignored with a warning."""
    path = overrides_path()
    if not path.exists():
        return {}, dict(DEFAULT_SLOTS)
    try:
        data = tomllib.loads(path.read_text(encoding="utf-8"))
    except (tomllib.TOMLDecodeError, OSError) as exc:
        raise RuntimeError(f"Can't read {path}: {exc}") from exc
    overrides = {}
    for key, value in (data.get("overrides") or {}).items():
        if key in AGENT_OVERRIDE_KEYS:
            overrides[key] = value
        else:
            log.warning("agent.toml: unknown setting %r ignored (known: %s)", key, ", ".join(AGENT_OVERRIDE_KEYS))
    slots = dict(DEFAULT_SLOTS)
    for kind, value in (data.get("tasks") or {}).items():
        if kind in KINDS and isinstance(value, int) and value >= 0:
            slots[kind] = value
    return overrides, slots


def load_credentials() -> tuple[str, str]:
    server, token = os.getenv("AGENT_SERVER", ""), os.getenv("AGENT_TOKEN", "")
    if not (server and token) and credentials_path().exists():
        saved = json.loads(credentials_path().read_text(encoding="utf-8"))
        server, token = server or saved.get("server", ""), token or saved.get("token", "")
    if not (server and token):
        raise RuntimeError("This PC isn't connected to a server yet. Add it on the server's Agents page, then run: "
                           "python -m call_analyzer agent login --server <address> --token <token>")
    return server.rstrip("/"), token


# A connection code is what the server's Agents page gives for a new agent: the server address and the token in
# one string, so installing an agent is a single paste.
CODE_PREFIX = "ca1."


def encode_code(server: str, token: str) -> str:
    raw = json.dumps({"s": server, "t": token}, separators=(",", ":")).encode()
    return CODE_PREFIX + base64.urlsafe_b64encode(raw).decode().rstrip("=")


def parse_connection(text: str) -> tuple[str, str]:
    """Server address and token from what someone pastes: a connection code, or the `agent login` command."""
    text = text.strip()
    if match := re.search(r"ca1\.[A-Za-z0-9_-]+", text):
        raw = match.group(0)[len(CODE_PREFIX):]
        try:
            data = json.loads(base64.urlsafe_b64decode(raw + "=" * (-len(raw) % 4)))
            return data["s"], data["t"]
        except (ValueError, KeyError, TypeError):
            raise ConnectError("That connection code is damaged: copy it again from the Agents page.") from None
    server, token = re.search(r"--server\s+(\S+)", text), re.search(r"--token\s+(\S+)", text)
    if server and token:
        return server.group(1), token.group(1)
    raise ConnectError("Paste the connection code shown on the server's Remote agents page.")


def connect(server: str, token: str) -> tuple[str, str]:
    """Check the token against the server and remember it. Returns (server address, agent name)."""
    url = _normalize_url(server)
    overrides, slots = load_local()
    agent = Agent(url, token.strip(), overrides, slots)
    try:
        agent.hello(retry=False)
    except (AuthError, OutdatedError) as exc:
        raise ConnectError(str(exc)) from None
    except (requests.RequestException, ValueError) as exc:
        raise ConnectError(f"Can't reach {url}: {exc}") from None
    home().mkdir(parents=True, exist_ok=True)
    credentials_path().write_text(json.dumps({"server": url, "token": token.strip()}), encoding="utf-8")
    try:
        credentials_path().chmod(0o600)
    except OSError:
        pass
    if not overrides_path().exists():
        overrides_path().write_text(OVERRIDES_TEMPLATE, encoding="utf-8")
    return url, agent.name


def _mask(overrides: dict) -> dict:
    return {k: ("•••" if k in SECRET_KEYS and v else v) for k, v in overrides.items()}


# --- What this PC can do ------------------------------------------------------------------------

def _gpu() -> bool:
    try:
        import ctranslate2
        return ctranslate2.get_cuda_device_count() > 0
    except Exception:
        return False


def transcribe_ready(cfg: Settings) -> tuple[bool, str]:
    provider = cfg.transcribe_provider
    if provider == "local":
        if find_spec("faster_whisper") is None:
            return False, "faster-whisper isn't installed (pip install -r requirements.txt)"
        from .whisper_models import DIALECT_MODELS, is_installed
        if cfg.whisper_model in DIALECT_MODELS and not is_installed(cfg.whisper_model, cfg) and (
                find_spec("torch") is None or find_spec("transformers") is None):
            return False, f"{cfg.whisper_model} must be converted once, which needs torch (requirements-convert.txt)"
        return True, ""
    if provider == "elevenlabs":
        return bool(cfg.elevenlabs_api_key), "" if cfg.elevenlabs_api_key else "No ELEVENLABS_API_KEY on this PC"
    if provider == "openai":
        return bool(cfg.openai_api_key), "" if cfg.openai_api_key else "No OPENAI_API_KEY on this PC"
    return False, f"Unknown transcribe provider {provider!r}"


def analyze_ready(cfg: Settings) -> tuple[bool, str]:
    if cfg.claude_backend == "subscription":
        claude = shutil.which("claude") is not None
        claude_why = "The `claude` CLI isn't installed or logged in on this PC"
    else:
        claude = bool(os.getenv("ANTHROPIC_API_KEY"))
        claude_why = "No ANTHROPIC_API_KEY on this PC (or set claude_backend = \"subscription\" in agent.toml)"
    cursor = bool(cfg.cursor_api_key) and find_spec("cursor_sdk") is not None
    cursor_why = "No CURSOR_API_KEY (or cursor-sdk) on this PC"
    backend = cfg.analysis_backend
    if backend == "claude":
        return claude, "" if claude else claude_why
    if backend == "cursor":
        return cursor, "" if cursor else cursor_why
    if backend == "auto":
        return claude or cursor, "" if claude or cursor else f"{claude_why}; {cursor_why}"
    return False, f"Unknown analysis backend {backend!r}"


def _capabilities(cfg: Settings, slots: dict) -> dict:
    caps = {}
    for kind, check, detail in (
        ("transcribe", transcribe_ready,
         f"{cfg.whisper_model} ({cfg.whisper_device})" if cfg.transcribe_provider == "local" else cfg.transcribe_provider),
        ("analyze", analyze_ready, cfg.claude_model if cfg.analysis_backend != "cursor" else cfg.cursor_model),
    ):
        ok, reason = check(cfg)
        if slots.get(kind, 0) <= 0:
            ok, reason = False, "Turned off in agent.toml"
        caps[kind] = {"ok": ok, "reason": reason, "detail": detail, "slots": slots.get(kind, 0)}
    return caps


# --- Talking to the server ----------------------------------------------------------------------

class Server:
    def __init__(self, url: str, token: str):
        self.url = url
        self.http = requests.Session()
        self.http.headers.update({"Authorization": f"Bearer {token}", "User-Agent": f"call-analyzer-agent/{VERSION}"})

    def request(self, method: str, path: str, *, timeout=30, **kwargs) -> requests.Response:
        resp = self.http.request(method, self.url + path, timeout=timeout, **kwargs)
        if resp.status_code == 401:
            raise AuthError("The server doesn't accept this agent's token: it was revoked or replaced. "
                            "Get a new one on the Agents page and run `agent login` again.")
        if resp.status_code == 426:
            raise OutdatedError(resp.json().get("detail", "This agent is too old for the server; update it."))
        return resp

    def post(self, path: str, body: dict, *, timeout=30) -> dict:
        resp = self.request("POST", path, json=body, timeout=timeout)
        if resp.status_code == 409:
            return {"conflict": True}
        resp.raise_for_status()
        return resp.json()

    def get(self, path: str, *, timeout=30) -> dict:
        resp = self.request("GET", path, timeout=timeout)
        resp.raise_for_status()
        return resp.json()


# --- The agent ----------------------------------------------------------------------------------

class Agent:
    def __init__(self, url: str, token: str, overrides: dict, slots: dict, *, transcribe_fn=None, analyze_fn=None):
        self.server = Server(url, token)
        self.overrides, self.slots = overrides, slots
        self.defaults: dict = {}
        self.name = ""
        self.enabled = True
        self.stop = threading.Event()
        self.paused = False  # set from the tray: finish the current work, take no more
        self.connected = False  # whether the last request to the server worked
        self.lock = threading.Lock()
        self.running: dict[int, str] = {}  # task id -> kind
        self.cancelled: set[int] = set()
        self.fatal: Exception | None = None
        self._transcribe, self._analyze = transcribe_fn, analyze_fn
        self.gpu = _gpu()

    # settings -----------------------------------------------------------------------------------

    def cfg(self, defaults: dict | None = None) -> Settings:
        return effective_settings(self.defaults if defaults is None else defaults, self.overrides)

    def info(self) -> dict:
        cfg = self.cfg()
        effective = {k: getattr(cfg, k) for k in AGENT_SERVER_KEYS}
        effective["whisper_prompt"] = effective["whisper_prompt"][:80]
        return {
            "hostname": socket.gethostname(), "os": f"{platform.system()} {platform.release()}",
            "version": VERSION, "protocol": PROTOCOL, "gpu": self.gpu, "slots": self.slots,
            "capabilities": _capabilities(cfg, self.slots),
            "overrides": _mask(self.overrides), "effective": effective,
        }

    # connection ---------------------------------------------------------------------------------

    def hello(self, retry: bool = True):
        """Introduce this agent and learn the server's defaults. Retries while the server is unreachable."""
        delay = 2
        while not self.stop.is_set():
            try:
                reply = self.server.post("/api/worker/hello", {"info": self.info()})
            except (requests.RequestException, ValueError) as exc:
                if not retry:
                    raise
                log.warning("Server not reachable (%s); trying again in %ss", exc, delay)
                self.stop.wait(delay)
                delay = min(delay * 2, 30)
                continue
            self._learn(reply)
            return
        raise KeyboardInterrupt

    def _learn(self, reply: dict):
        self.connected = True
        self.name = reply.get("name", self.name)
        self.enabled = reply.get("enabled", True)
        if "defaults" in reply:
            self.defaults = reply["defaults"]

    def heartbeat_loop(self):
        while not self.stop.wait(HEARTBEAT_SECONDS):
            with self.lock:
                running = list(self.running)
            try:
                reply = self.server.post("/api/worker/heartbeat", {"info": self.info(), "running": running})
            except (AuthError, OutdatedError) as exc:
                self._die(exc)
                return
            except (requests.RequestException, ValueError) as exc:
                self.connected = False
                log.warning("Heartbeat failed: %s", exc)
                continue
            self._learn(reply)
            with self.lock:
                self.cancelled.update(reply.get("cancelled", []))

    def _die(self, exc: Exception):
        self.fatal = exc
        self.stop.set()

    # work ---------------------------------------------------------------------------------------

    def runner(self, kind: str):
        delay = 2
        while not self.stop.is_set():
            if not self.enabled or self.paused:  # paused on the server, or from the tray
                self.stop.wait(2)
                continue
            try:
                reply = self.server.post("/api/worker/claim", {"kinds": [kind], "wait": CLAIM_WAIT},
                                         timeout=CLAIM_WAIT + 15)
            except (AuthError, OutdatedError) as exc:
                self._die(exc)
                return
            except (requests.RequestException, ValueError) as exc:
                self.connected = False
                log.warning("Couldn't ask for work (%s); trying again in %ss", exc, delay)
                self.stop.wait(delay)
                delay = min(delay * 2, 30)
                continue
            delay = 2
            self.connected = True
            self.enabled = reply.get("enabled", self.enabled)
            if task := reply.get("task"):
                if self.stop.is_set():  # shutting down: hand it straight back instead of leaving it to time out
                    self._send(f"/api/worker/tasks/{task['id']}/release", {})
                    return
                self.handle(task)

    def handle(self, task: dict):
        task_id, kind = task["id"], task["kind"]
        call_id = task["call"]["id"]
        with self.lock:
            self.running[task_id] = kind
        log.info("Task %s: %s call %s", task_id, kind, call_id)
        started = time.time()
        try:
            self.defaults = task.get("defaults", self.defaults)
            cfg = self.cfg(task.get("defaults"))
            result = self._transcribe_task(task, cfg) if kind == "transcribe" else self._analyze_task(task, cfg)
        except (AuthError, OutdatedError) as exc:
            self._die(exc)
            return
        except Exception as exc:
            log.error("Task %s failed: %s", task_id, exc)
            self._send(f"/api/worker/tasks/{task_id}/fail", {"error": f"{type(exc).__name__}: {exc}"})
        else:
            with self.lock:
                dropped = task_id in self.cancelled
            if dropped:
                log.info("Task %s was cancelled on the server; result dropped", task_id)
            else:
                self._send(f"/api/worker/tasks/{task_id}/result", result)
                log.info("Task %s done in %.0fs", task_id, time.time() - started)
        finally:
            with self.lock:
                self.running.pop(task_id, None)
                self.cancelled.discard(task_id)

    def _send(self, path: str, body: dict):
        """Upload a result; retries for a few minutes if the connection drops."""
        delay = 2
        for attempt in range(7):
            try:
                reply = self.server.post(path, body, timeout=60)
            except (AuthError, OutdatedError) as exc:
                self._die(exc)
                return
            except requests.HTTPError as exc:  # the server understood and refused: retrying won't help
                log.error("The server rejected %s: %s", path, exc.response.text[:300])
                return
            except (requests.RequestException, ValueError) as exc:
                log.warning("Upload failed (%s); retrying in %ss", exc, delay)
                self.stop.wait(delay)
                delay = min(delay * 2, 60)
                continue
            if reply.get("conflict"):
                log.info("The server no longer expects this result (cancelled or given to another agent)")
            return
        log.error("Gave up uploading %s; the server will hand the task to someone else", path)

    def _progress(self, task_id: int, text: str):
        try:
            self.server.post(f"/api/worker/tasks/{task_id}/progress", {"text": text}, timeout=10)
        except Exception:
            pass  # progress text is cosmetic

    def _fetch_model(self, name: str, dest: Path, task_id: int):
        """Download a converted Whisper model from the server (it converts each one once, with torch), so this PC
        doesn't need torch. Shown as the task's progress."""
        from . import whisper_models
        base = f"/api/worker/models/{name}"
        try:
            while True:
                reply = self.server.post(base + "/prepare", {}, timeout=60)
                if reply.get("ready"):
                    break
                self._progress(task_id, f"waiting for the server to pack {name}")
                if self.stop.wait(5):
                    raise RuntimeError("Stopped")
        except requests.HTTPError as exc:
            if exc.response is not None and exc.response.status_code == 404:
                raise whisper_models.ModelUnavailable(exc.response.json().get("detail", f"{name} isn't on the server"))
            raise
        dest.parent.mkdir(parents=True, exist_ok=True)
        pack = dest.with_name(dest.name + ".zip.part")
        done, total, shown = 0, int(reply.get("size") or 0), 0.0
        with self.server.http.get(self.server.url + base + "/pack", stream=True, timeout=(10, 120)) as resp:
            resp.raise_for_status()
            total = int(resp.headers.get("Content-Length") or total)
            with open(pack, "wb") as fh:
                for chunk in resp.iter_content(1 << 20):
                    fh.write(chunk)
                    done += len(chunk)
                    if time.time() - shown > 4:
                        shown = time.time()
                        pct = f" {done * 100 // total}%" if total else ""
                        self._progress(task_id, f"downloading {name} from the server:{pct} ({done / 1e9:.1f} GB)")
        self._progress(task_id, f"unpacking {name}")
        tmp = dest.with_name(dest.name + ".tmp")
        shutil.rmtree(tmp, ignore_errors=True)
        with zipfile.ZipFile(pack) as archive:
            archive.extractall(tmp)
        pack.unlink(missing_ok=True)
        shutil.rmtree(dest, ignore_errors=True)
        tmp.rename(dest)
        log.info("Installed %s in %s", name, dest)

    def _transcribe_task(self, task: dict, cfg: Settings) -> dict:
        from . import whisper_models
        from .transcribe import transcribe, transcriber_label
        transcribe_fn = self._transcribe or transcribe
        whisper_models.fetch_model = lambda name, dest: self._fetch_model(name, dest, task["id"])
        suffix = Path(task["call"].get("filename") or "call.mp3").suffix or ".mp3"
        with tempfile.TemporaryDirectory() as workdir:
            audio = Path(workdir) / f"call{suffix}"
            self._progress(task["id"], "downloading audio")
            with self.server.http.get(self.server.url + task["audio_url"], stream=True, timeout=(10, 120)) as resp:
                if resp.status_code == 401:
                    raise AuthError("Token rejected while downloading audio")
                resp.raise_for_status()
                with open(audio, "wb") as fh:
                    for chunk in resp.iter_content(1 << 16):
                        fh.write(chunk)
            self._progress(task["id"], f"transcribing with {cfg.whisper_model if cfg.transcribe_provider == 'local' else cfg.transcribe_provider}")
            text = transcribe_fn(audio, cfg)
        return {"transcript": text, "label": transcriber_label(cfg)}

    def _analyze_task(self, task: dict, cfg: Settings) -> dict:
        from .analyze import analyze_call
        analyze_fn = self._analyze or analyze_call
        self._progress(task["id"], "analyzing")
        analysis, label = analyze_fn(task["call"], cfg, task.get("business"))
        return {"analysis": analysis.model_dump(), "label": label}

    # lifecycle ----------------------------------------------------------------------------------

    def run(self):
        """Work until stopped. Raises AuthError / OutdatedError when the server turns this agent away."""
        self.hello()
        log.info("Connected to %s as %r", self.server.url, self.name)
        threads = [threading.Thread(target=self.heartbeat_loop, daemon=True, name="heartbeat")]
        for kind in KINDS:
            threads += [threading.Thread(target=self.runner, args=(kind,), daemon=True, name=f"{kind}-{i}")
                        for i in range(self.slots.get(kind, 0))]
        for t in threads:
            t.start()
        try:
            while not self.stop.wait(0.5):
                pass
        except KeyboardInterrupt:
            self.stop.set()
        finally:
            try:  # let the server hand this agent's unfinished tasks to others right away
                self.server.post("/api/worker/bye", {}, timeout=5)
            except Exception:
                pass
        if self.fatal:
            raise self.fatal


# --- Command line -------------------------------------------------------------------------------

def _setup_logging():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s", datefmt="%H:%M:%S",
                        handlers=[logging.StreamHandler()] if sys.stderr else [])
    home().mkdir(parents=True, exist_ok=True)
    handler = logging.handlers.RotatingFileHandler(home() / "agent.log", maxBytes=1_000_000, backupCount=3,
                                                   encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    logging.getLogger().addHandler(handler)
    logging.getLogger().setLevel(logging.INFO)
    for noisy in ("urllib3", "httpx", "httpcore", "huggingface_hub", "filelock"):
        logging.getLogger(noisy).setLevel(logging.WARNING)


def _normalize_url(server: str) -> str:
    server = server.strip().rstrip("/")
    if "://" not in server:
        local = server.startswith(("localhost", "127.", "192.168.", "10."))
        server = ("http://" if local else "https://") + server
    return server


def login(server: str | None, token: str | None, code: str | None = None):
    if code:
        try:
            server, token = parse_connection(code)
        except ConnectError as exc:
            sys.exit(str(exc))
    if not server or not token:
        sys.exit("Usage: agent login --code ca1.…   (or --server https://calls.example.com --token ca_...)\n"
                 "Add this PC on the server's Remote agents page to get the code.")
    try:
        url, name = connect(server, token)
    except ConnectError as exc:
        sys.exit(str(exc))
    print(f"Connected to {url} as agent {name!r}.")
    print(f"Credentials saved in {credentials_path()}")
    print(f"Settings of this agent (optional): {overrides_path()}")
    print("Start it with:  python -m call_analyzer agent run")


def status():
    url, token = load_credentials()
    server = Server(url, token)
    try:
        remote = server.get("/api/worker/config")
    except (AuthError, OutdatedError) as exc:
        sys.exit(str(exc))
    except requests.RequestException as exc:
        sys.exit(f"Can't reach {url}: {exc}")
    overrides, slots = load_local()
    agent = Agent(url, token, overrides, slots)
    agent.defaults = remote["defaults"]
    cfg = agent.cfg()
    print(f"Server:  {url}")
    print(f"Agent:   {remote['name']} ({'enabled' if remote['enabled'] else 'paused on the server'})")
    print(f"Hosts:   transcribe on {remote['runs_on']['transcribe']}, analyze on {remote['runs_on']['analyze']}")
    print("\nSetting                    value                          source")
    for key in AGENT_SERVER_KEYS:
        source = "agent.toml" if key in overrides else ("server" if key in remote["defaults"] else "this PC")
        value = str(getattr(cfg, key))
        value = (value[:28] + "…") if len(value) > 29 else value
        print(f"  {key:<24} {value:<30} {source}")
    print()
    for kind, cap in _capabilities(cfg, slots).items():
        print(f"  {kind:<11} {'ready' if cap['ok'] else 'NOT READY'}  {cap['detail']}"
              f"{'  - ' + cap['reason'] if cap['reason'] else ''}")


def run():
    _setup_logging()
    url, token = load_credentials()
    overrides, slots = load_local()
    agent = Agent(url, token, overrides, slots)
    print(f"Agent running for {url}  (Ctrl+C to stop; logs in {home() / 'agent.log'})", flush=True)
    try:
        agent.run()
    except AuthError as exc:
        log.error("%s", exc)
        sys.exit(EXIT_AUTH)
    except OutdatedError as exc:
        log.error("%s", exc)
        sys.exit(EXIT_OUTDATED)


RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
RUN_NAME = "CallAnalyzerAgent"


def autostart_enabled() -> bool:
    """Whether the installed agent starts when you sign in to Windows (a per-user Run entry)."""
    if os.name != "nt":
        return False
    import winreg
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as key:
            winreg.QueryValueEx(key, RUN_NAME)
        return True
    except OSError:
        return False


def set_autostart(on: bool):
    import winreg
    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE) as key:
        if on:
            winreg.SetValueEx(key, RUN_NAME, 0, winreg.REG_SZ, f'"{sys.executable}" --background')
        else:
            try:
                winreg.DeleteValue(key, RUN_NAME)
            except FileNotFoundError:
                pass


def autostart(off: bool = False):
    """Start the agent whenever you sign in to Windows (no admin rights needed)."""
    if FROZEN:  # the installed app: a Run entry, the same one the tray menu and the installer manage
        set_autostart(not off)
        print("Removed from startup." if off else "The agent will start when you sign in to Windows.")
        return
    if os.name != "nt":
        sys.exit("autostart is for Windows. On Linux/macOS, run `python -m call_analyzer agent run` from systemd "
                 "or launchd.")
    task = "CallAnalyzerAgent"
    if off:
        out = subprocess.run(["schtasks", "/Delete", "/TN", task, "/F"], capture_output=True, text=True)
        print("Removed from startup." if out.returncode == 0 else out.stderr.strip() or out.stdout.strip())
        return
    load_credentials()  # fail early if this PC isn't connected yet
    pythonw = Path(sys.executable).with_name("pythonw.exe")
    exe = pythonw if pythonw.exists() else Path(sys.executable)
    home().mkdir(parents=True, exist_ok=True)
    script = home() / "start-agent.cmd"
    script.write_text(f'@echo off\r\ncd /d "{ROOT}"\r\nstart "" /B "{exe}" -m call_analyzer agent run\r\n',
                      encoding="utf-8")
    out = subprocess.run(["schtasks", "/Create", "/F", "/SC", "ONLOGON", "/TN", task, "/TR", f'"{script}"'],
                         capture_output=True, text=True)
    if out.returncode != 0:
        sys.exit(out.stderr.strip() or out.stdout.strip())
    print(f"The agent will start when you sign in to Windows (task {task!r}, script {script}).")
    print("Remove it with: python -m call_analyzer agent autostart --off")


def main(args):
    if args.action == "login":
        login(args.server, args.token, getattr(args, "code", None))
    elif args.action == "run":
        run()
    elif args.action == "status":
        status()
    else:
        autostart(args.off)
