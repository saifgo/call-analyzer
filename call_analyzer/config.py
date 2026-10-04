import os
import re
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
# override=True: .env is the source of truth. Pipeline jobs launched by the UI inherit the server's
# environment, which still holds the values from when the server started; without override, edits
# saved in Settings would be ignored.
load_dotenv(ROOT / ".env", override=True)


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

    data_dir: Path = ROOT / "data"
    audio_dir: Path = ROOT / "data" / "audio"
    db_path: Path = ROOT / "data" / "calls.db"
    reports_dir: Path = ROOT / "reports"
    business_context_path: Path = ROOT / "context" / "business.md"


settings = Settings()
