"""What a phone system adapter does, and the shape of what it hands back.

The app takes two things from the phone system (PBX / VoIP provider):
  - the call recordings, to transcribe and analyze (sync, download);
  - the SIP sign-in of each agent, for the browser softphone (optional).

To connect another phone system: subclass TelephonyAdapter in adapters/telephony/<name>.py, add it to BUILTIN in
telephony.py (or call telephony.registry.register), then set TELEPHONY_PROVIDER=<name> in Settings.
"""
from pathlib import Path
from typing import Iterator, TypedDict

# How Recording.date_call is written: the phone system's local time.
DATE_FORMAT = "%Y-%m-%d %H:%M:%S"


class SessionExpired(RuntimeError):
    """The phone system refused the saved login: someone has to sign in again (the UI offers to)."""


class SipLoginError(Exception):
    """The phone system didn't give an agent's SIP sign-in. rejected: it refused their login (not a network
    problem), so the saved password shouldn't be sent again."""

    def __init__(self, message: str, rejected: bool = False):
        super().__init__(message)
        self.rejected = rejected


class Recording(TypedDict, total=False):
    id: str  # unique and stable: calls are stored under it
    type: str | None  # "IN" or "OUT" (anything else: guessed from which side is an extension)
    caller: str | None
    called: str | None
    date_call: str  # DATE_FORMAT
    duration: int  # seconds
    size_kb: int
    filename: str  # what download() takes
    raw: dict  # the phone system's own record, kept as is


class SipLogin(TypedDict):
    sip_user: str
    password: str
    access_token: str  # "" when the phone system doesn't use one


class TelephonyAdapter:
    """One phone system. Settings are read when needed so changes saved in Settings apply straight away."""

    name = ""  # what TELEPHONY_PROVIDER is set to
    label = ""  # shown to people, e.g. "GoVoice"
    # Settings this adapter reads (from .env.example). Secret ones are masked on the Settings page.
    setting_keys: tuple[str, ...] = ()
    secret_keys: tuple[str, ...] = ()
    # Where an admin signs in when the saved session is missing or expired (a page the adapter serves through
    # routers()), or None when the adapter logs in by itself (e.g. with an API key).
    login_url: str | None = None

    # --- Recordings ----------------------------------------------------------------------------

    def check(self) -> int:
        """How many recordings there are, if the saved login works. Raises SessionExpired if it doesn't."""
        raise NotImplementedError

    def iter_recordings(self, stop_before: str | None = None) -> Iterator[Recording]:
        """The recordings, newest first, stopping at the first one older than `stop_before` (DATE_FORMAT).
        Raises SessionExpired."""
        raise NotImplementedError

    def download(self, filename: str, dest: Path) -> Path:
        """Save the recording's audio to `dest`. Raises SessionExpired."""
        raise NotImplementedError

    def recording_url(self, filename: str) -> str | None:
        """Where people can open the recording in the phone system's own web app, if anywhere."""
        return None

    def diagnostics(self) -> list[str]:
        """Extra lines for `call_analyzer check` once check() passed."""
        return []

    # --- Session upkeep and the web app --------------------------------------------------------

    def has_session(self) -> bool:
        """Whether a login is saved at all (check() then tells whether it still works). The web app checks it
        regularly while there is one, which also keeps it from expiring."""
        return True

    def routers(self) -> list:
        """FastAPI routers the web app mounts for this adapter (e.g. a login page)."""
        return []

    # --- Softphone -----------------------------------------------------------------------------

    def softphone_defaults(self) -> dict:
        """{"ws_url", "domain", "prefix"}: the WebRTC WebSocket, the SIP domain, and what goes in front of an
        extension to make the SIP username. SOFTPHONE_WS_URL, SOFTPHONE_DOMAIN and SOFTPHONE_USER_PREFIX in
        Settings win over these."""
        return {"ws_url": "", "domain": "", "prefix": ""}

    def sip_login(self, account_user: str, account_password: str) -> SipLogin:
        """The SIP sign-in that goes with an agent's account on the phone system. Raises SipLoginError."""
        raise SipLoginError(f"{self.label or 'This phone system'} can't give SIP sign-ins")
