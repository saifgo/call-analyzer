"""GoVoice (https://govoice.tn): recordings from its VoIP manager, SIP sign-ins for the softphone.

    client.py  the recordings list and the mp3 files, with the session cookie saved as GOVOICE_COOKIE
    login.py   GoVoice's login page served through the app, to capture that cookie
    sip.py     an agent's SIP sign-in, fetched with their GoVoice account
"""
import re
from pathlib import Path

from ....config import live, settings
from ..base import TelephonyAdapter
from .client import GoVoiceClient, current_cookie
from .sip import fetch_sip_login


class GoVoiceTelephony(TelephonyAdapter):
    name = "govoice"
    label = "GoVoice"
    setting_keys = ("GOVOICE_BASE_URL", "GOVOICE_COOKIE", "GOVOICE_RECORDINGS_DIR", "GOVOICE_VERIFY_SSL")
    secret_keys = ("GOVOICE_COOKIE",)
    login_url = "/govoice-login/"

    def __init__(self):
        self._client: tuple[str, GoVoiceClient] | None = None  # (the cookie it was made with, client)

    def _connect(self) -> GoVoiceClient:
        """A client on the cookie saved right now; a new one when the cookie changed (signed in again, or rotated
        by GoVoice). Raises SessionExpired when there's none."""
        cookie = current_cookie()
        if self._client is None or self._client[0] != cookie:
            self._client = (cookie, GoVoiceClient(cookie))
        return self._client[1]

    # --- Recordings ----------------------------------------------------------------------------

    def check(self) -> int:
        # A client of its own: the web app checks from several threads.
        return GoVoiceClient(current_cookie()).check()

    def iter_recordings(self, stop_before: str | None = None):
        for row in self._connect().iter_recordings(perpage=100, stop_before=stop_before):
            yield {"id": row["id"], "type": row.get("type"), "caller": row.get("caller"), "called": row.get("called"),
                   "date_call": row.get("date_call"), "duration": int(row.get("duree") or 0),
                   "size_kb": int(row.get("size") or 0), "filename": row.get("filename"), "raw": row}

    def download(self, filename: str, dest: Path) -> Path:
        return self._connect().download(filename, dest)

    def recording_url(self, filename: str) -> str | None:
        folder = live("GOVOICE_RECORDINGS_DIR", settings.govoice_recordings_dir).strip("/")
        base = live("GOVOICE_BASE_URL", settings.govoice_base_url).rstrip("/")
        return f"{base}/{folder}/{filename}" if folder and filename else None

    def diagnostics(self) -> list[str]:
        return [f"recordings folder: {self._connect().recordings_dir}"]

    # --- Session and web app -------------------------------------------------------------------

    def has_session(self) -> bool:
        return bool(current_cookie())

    def routers(self) -> list:
        from .login import router
        return [router]

    # --- Softphone -----------------------------------------------------------------------------

    def softphone_defaults(self) -> dict:
        # SIP usernames are <tenant>_<extension>; the recordings folder (govoice_enreg_<tenant>) names the tenant.
        match = re.search(r"_(\d+)$", live("GOVOICE_RECORDINGS_DIR"))
        return {"ws_url": "wss://otn.govoice.tn:8089/ws", "domain": "otn.govoice.tn",
                "prefix": f"{match.group(1)}_" if match else ""}

    def sip_login(self, account_user: str, account_password: str) -> dict:
        return fetch_sip_login(account_user, account_password)
