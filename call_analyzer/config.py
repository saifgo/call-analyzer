import os
import re
import sys
from dataclasses import dataclass, replace
from pathlib import Path

from dotenv import dotenv_values, load_dotenv

FROZEN = bool(getattr(sys, "frozen", False))  # the installed agent (CallAnalyzerAgent.exe), not a source checkout


def agent_home() -> Path:
    """Where an agent keeps its credentials (agent.json), settings (agent.toml), .env, models and log."""
    if os.getenv("AGENT_HOME"):
        return Path(os.environ["AGENT_HOME"])
    if FROZEN and os.name == "nt":
        return Path(os.getenv("LOCALAPPDATA") or Path.home() / "AppData" / "Local") / "CallAnalyzerAgent"
    return Path.home() / ".call-analyzer-agent"


# An installed agent has no project folder: everything it needs lives in its own per-user folder.
ROOT = agent_home() if FROZEN else Path(__file__).resolve().parent.parent
if FROZEN:
    ROOT.mkdir(parents=True, exist_ok=True)
# The settings file. Docker/Coolify set ENV_FILE=/app/data/.env so it lives in the data volume; the other
# settings can then also come from the platform's environment variables until they're saved in Settings.
ENV_PATH = Path(os.getenv("ENV_FILE") or ROOT / ".env")
# override=True: .env is the source of truth. Pipeline jobs launched by the UI inherit the server's
# environment, which still holds the values from when the server started; without override, edits
# saved in Settings would be ignored.
load_dotenv(ENV_PATH, override=True)


# Where calls.db and the audio live. Docker mounts its data volume at /app/data, the default.
DATA_DIR = Path(os.getenv("DATA_DIR") or ROOT / "data")


def _bool(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None or value == "":
        return default
    return value.strip().lower() in ("1", "true", "yes", "on")


def _local_path(name: str) -> str:
    """A path setting, ignoring Windows paths (D:\\models, from a .env copied off a PC) on Linux/Docker."""
    value = os.getenv(name, "")
    return "" if os.name != "nt" and re.match(r"^[A-Za-z]:[\\/]", value) else value


@dataclass(frozen=True)
class Settings:
    govoice_base_url: str = os.getenv("GOVOICE_BASE_URL", "https://otn.govoice.tn:4444").rstrip("/")
    govoice_cookie: str = os.getenv("GOVOICE_COOKIE", "")
    govoice_recordings_dir: str = os.getenv("GOVOICE_RECORDINGS_DIR", "").strip("/")
    govoice_verify_ssl: bool = _bool("GOVOICE_VERIFY_SSL", True)

    # local = free Whisper on this machine; elevenlabs / openai = paid APIs
    transcribe_provider: str = os.getenv("TRANSCRIBE_PROVIDER", "local").lower()
    whisper_model: str = os.getenv("WHISPER_MODEL", "large-v3-turbo")
    # Where Whisper models are downloaded (~1.6 GB for large-v3-turbo)
    whisper_model_dir: str = _local_path("WHISPER_MODEL_DIR") or str(ROOT / "data" / "models")
    whisper_device: str = os.getenv("WHISPER_DEVICE", "auto").lower()
    whisper_language: str = os.getenv("WHISPER_LANGUAGE", "")
    whisper_prompt: str = os.getenv("WHISPER_PROMPT", "")
    elevenlabs_api_key: str = os.getenv("ELEVENLABS_API_KEY", "")
    elevenlabs_model: str = os.getenv("ELEVENLABS_MODEL", "scribe_v1")
    openai_api_key: str = os.getenv("OPENAI_API_KEY", "")
    openai_transcribe_model: str = os.getenv("OPENAI_TRANSCRIBE_MODEL", "gpt-4o-transcribe")

    # claude = Claude only; cursor = Cursor SDK; auto = Claude, then Cursor if Claude is unavailable
    analysis_backend: str = (os.getenv("ANALYSIS_BACKEND") or "claude").lower()
    # subscription = local `claude` CLI with your Claude Pro/Max login; api = ANTHROPIC_API_KEY
    claude_backend: str = os.getenv("CLAUDE_BACKEND", "subscription").lower()
    claude_model: str = os.getenv("CLAUDE_MODEL", "claude-opus-5-5")
    cursor_api_key: str = os.getenv("CURSOR_API_KEY", "")
    cursor_model: str = os.getenv("CURSOR_MODEL") or "composer-2.5"
    feedback_language: str = os.getenv("FEEDBACK_LANGUAGE", "English")

    # Voice analysis: an audio classification model listens to the recording itself (see voice.py).
    voice_analysis: bool = _bool("VOICE_ANALYSIS", True)
    voice_model: str = os.getenv("VOICE_MODEL") or "superb/wav2vec2-base-superb-er"

    # Where transcription and analysis run: host = this server, agent = remote agents only (jobs wait for one to
    # connect), auto = remote agents while one is online, otherwise this server.
    transcribe_runs_on: str = (os.getenv("TRANSCRIBE_RUNS_ON") or "host").lower()
    voice_runs_on: str = (os.getenv("VOICE_RUNS_ON") or "host").lower()
    analyze_runs_on: str = (os.getenv("ANALYZE_RUNS_ON") or "host").lower()

    # Listen on the local network instead of only this machine. Everything except share links needs a login.
    share_on_lan: bool = _bool("SHARE_ON_LAN", False)
    ui_port: int = int(os.getenv("UI_PORT") or 8765)

    # Hosting: the address people use to reach the app (used in share links), e.g. https://calls.example.com
    public_url: str = os.getenv("PUBLIC_URL", "").rstrip("/")
    # Only send the login cookie over HTTPS. Turn on when the app is served over HTTPS.
    cookie_secure: bool = _bool("COOKIE_SECURE", False)
    session_days: int = int(os.getenv("SESSION_DAYS") or 14)
    # Account created at startup if it doesn't exist yet (handy for Docker). More users: `call_analyzer user add`.
    admin_username: str = os.getenv("ADMIN_USERNAME", "").strip()
    admin_password: str = os.getenv("ADMIN_PASSWORD", "")

    data_dir: Path = DATA_DIR
    audio_dir: Path = DATA_DIR / "audio"
    db_path: Path = DATA_DIR / "calls.db"
    reports_dir: Path = ROOT / "reports"
    business_context_path: Path = ROOT / "context" / "business.md"


settings = Settings()


# --- Remote agents ----------------------------------------------------------------------------
# An agent (a PC running `python -m call_analyzer agent run`) takes these settings from the server, and
# uses its own value for any of them (or the local-only ones) that is set in its agent.toml.
# Secrets and folders on the server are never sent: an agent uses its own keys and model folder.

AGENT_SERVER_KEYS = (
    "transcribe_provider", "whisper_model", "whisper_device", "whisper_language", "whisper_prompt",
    "elevenlabs_model", "openai_transcribe_model",
    "voice_model",
    "analysis_backend", "claude_backend", "claude_model", "cursor_model", "feedback_language",
)
# Only ever set on the agent itself (agent.toml or its environment).
AGENT_LOCAL_KEYS = ("whisper_model_dir", "elevenlabs_api_key", "openai_api_key", "cursor_api_key")
AGENT_OVERRIDE_KEYS = AGENT_SERVER_KEYS + AGENT_LOCAL_KEYS
# An empty value is meaningful for these (auto-detect the language, no prompt); for the others it means "not set".
_EMPTY_OK = {"whisper_language", "whisper_prompt"}
_LOWERCASE = {"transcribe_provider", "whisper_device", "analysis_backend", "claude_backend"}


def live(name: str, default: str = "") -> str:
    """A setting as it is saved right now: the .env file (what the Settings page writes) first, then the
    environment. The server process only loads .env at startup, so it reads the file again for anything
    that has to follow Settings changes straight away."""
    saved = dotenv_values(ENV_PATH) if ENV_PATH.exists() else {}
    value = saved.get(name)
    if value is None:
        value = os.environ.get(name, "")
    return value.strip() or default


RUNS_ON = ("host", "agent", "auto")


def runs_on(kind: str) -> str:
    """Where a step runs: host (this server), agent (remote agents only) or auto (agents while one is online)."""
    value = live(f"{kind.upper()}_RUNS_ON", "host").lower()
    return value if value in RUNS_ON else "host"


def live_defaults() -> dict[str, str]:
    """The settings the server hands to its agents, as saved right now."""
    values = {}
    for key in AGENT_SERVER_KEYS:
        value = live(key.upper())
        if value or key in _EMPTY_OK:
            values[key] = value
    return values


def effective_settings(defaults: dict, overrides: dict, base: Settings = settings) -> Settings:
    """Built-in < this machine's environment < the server's defaults < the agent's own overrides."""
    merged: dict[str, str] = {}
    for layer, allowed in ((defaults, AGENT_SERVER_KEYS), (overrides, AGENT_OVERRIDE_KEYS)):
        for key, value in layer.items():
            if key in allowed and value is not None and (str(value) != "" or key in _EMPTY_OK):
                merged[key] = str(value).strip().lower() if key in _LOWERCASE else str(value)
    return replace(base, **merged)
