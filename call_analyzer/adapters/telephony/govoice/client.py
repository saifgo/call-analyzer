"""Client for the GoVoice VoIP manager: list recordings and download the mp3 files."""
import re
import threading
from pathlib import Path
from urllib.parse import urlsplit

import requests
import urllib3
from dotenv import dotenv_values
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from .config import ENV_PATH, settings

USER_AGENT = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
              "(KHTML, like Gecko) Chrome/130.0 Safari/537.36")
# Exit code of CLI commands when GoVoice rejects the session, so the UI can offer to log in again.
EXIT_AUTH = 3


class SessionExpired(RuntimeError):
    pass


# --- Cookie storage ---------------------------------------------------------------------------

_env_lock = threading.Lock()


def current_cookie() -> str:
    """GOVOICE_COOKIE as saved right now (settings is read once at start; the cookie can change while running)."""
    saved = dotenv_values(ENV_PATH).get("GOVOICE_COOKIE") if ENV_PATH.is_file() else None
    return (saved or settings.govoice_cookie).strip()


def save_cookie(cookie: str) -> None:
    """Write GOVOICE_COOKIE into .env, keeping every other line untouched."""
    with _env_lock:
        text = ENV_PATH.read_text(encoding="utf-8") if ENV_PATH.exists() else ""
        line = f"GOVOICE_COOKIE={cookie}"
        if re.search(r"(?m)^GOVOICE_COOKIE=.*$", text):
            text = re.sub(r"(?m)^GOVOICE_COOKIE=.*$", lambda _: line, text)
        else:
            text = text.rstrip("\n") + f"\n{line}\n"
        ENV_PATH.parent.mkdir(parents=True, exist_ok=True)
        ENV_PATH.write_text(text, encoding="utf-8")


def cookie_header(jar: requests.cookies.RequestsCookieJar) -> str:
    """Cookie header for GoVoice from a cookie jar (latest value wins if a cookie was set twice)."""
    host = urlsplit(settings.govoice_base_url).hostname or ""
    cookies = {}
    for cookie in jar:
        if not cookie.domain or host.endswith(cookie.domain.lstrip(".")):
            cookies[cookie.name] = cookie.value
    return "; ".join(f"{name}={value}" for name, value in cookies.items())


def new_session(cookie: str = "") -> requests.Session:
    session = requests.Session()
    session.verify = settings.govoice_verify_ssl
    # Retry on network blips (DNS failures, resets) and server hiccups, with backoff 2s, 4s, 8s...
    retry = Retry(total=5, connect=5, read=3, backoff_factor=2, status_forcelist=(502, 503, 504),
                  allowed_methods=None)
    session.mount("https://", HTTPAdapter(max_retries=retry))
    session.mount("http://", HTTPAdapter(max_retries=retry))
    if not settings.govoice_verify_ssl:
        urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
    session.headers["User-Agent"] = USER_AGENT
    # Cookies go in the jar (not a fixed header) so cookies GoVoice rotates are picked up automatically.
    host = urlsplit(settings.govoice_base_url).hostname
    for part in cookie.split(";"):
        name, sep, value = part.strip().partition("=")
        if sep and name:
            session.cookies.set(name, value, domain=host, path="/")
    return session


# --- Client -----------------------------------------------------------------------------------

class GoVoiceClient:
    def __init__(self, cookie: str | None = None):
        cookie = current_cookie() if cookie is None else cookie
        if not cookie:
            raise SessionExpired("Not connected to GoVoice yet: log in to GoVoice from the app")
        self.base = settings.govoice_base_url
        self.session = new_session(cookie)
        self.session.headers["Referer"] = f"{self.base}/govoice/Admin/Enregistrement"
        self._saved_cookie = cookie_header(self.session.cookies)
        self._recordings_dir = settings.govoice_recordings_dir

    def _persist_rotated_cookie(self):
        """GoVoice may hand out a new session cookie; save it so the next run keeps working."""
        latest = cookie_header(self.session.cookies)
        if latest and latest != self._saved_cookie:
            save_cookie(latest)
            self._saved_cookie = latest

    def _list_page(self, page: int, perpage: int) -> dict:
        params = {
            "pagination[page]": page,
            "pagination[perpage]": perpage,
            "sort[sort]": "desc",
            "sort[field]": "date_call",
            "query[plusinfo]": 1,
            "requestIds": "true",
        }
        # The page's datatable sends every parameter twice: as-is and nested under datatable[...].
        form = {}
        for name, value in params.items():
            head, _, rest = name.partition("[")
            form[f"datatable[{head}]" + (f"[{rest}" if rest else "")] = value
            form[name] = value
        resp = self.session.post(
            f"{self.base}/govoice/Global/Enregistrement",
            data=form,
            headers={
                "Accept": "application/json, text/javascript, */*; q=0.01",
                "X-Requested-With": "XMLHttpRequest",
            },
            timeout=60,
        )
        resp.raise_for_status()
        try:
            payload = resp.json()
        except ValueError:
            raise SessionExpired("GoVoice session expired: log in to GoVoice again from the app") from None
        self._persist_rotated_cookie()
        return payload

    def check(self) -> int:
        """Return the number of recordings if the session works; raise SessionExpired otherwise."""
        return int(self._list_page(1, 1).get("meta", {}).get("total") or 0)

    def iter_recordings(self, perpage: int = 100, max_pages: int | None = None, stop_before: str | None = None):
        """Yield recording dicts, newest first. Stops early once dates go below `stop_before`."""
        page = 1
        while True:
            payload = self._list_page(page, perpage)
            rows = payload.get("data") or []
            for row in rows:
                if stop_before and row.get("date_call", "") < stop_before:
                    return
                yield row
            # GoVoice's meta.pages rounds down (176 calls / 100 per page = 1), so derive it from total.
            total = int(payload.get("meta", {}).get("total") or 0)
            pages = -(-total // perpage)
            if not rows or page >= pages or (max_pages and page >= max_pages):
                return
            page += 1

    @property
    def recordings_dir(self) -> str:
        if not self._recordings_dir:
            html = self.session.get(f"{self.base}/govoice/Admin/Enregistrement", timeout=60).text
            match = re.search(r"govoice_enreg_\d+", html)
            if not match:
                raise SessionExpired(
                    "Could not find the recordings folder: the GoVoice session may have expired "
                    "(or set GOVOICE_RECORDINGS_DIR, e.g. govoice_enreg_1759512535)."
                )
            self._recordings_dir = match.group(0)
        return self._recordings_dir

    def download(self, filename: str, dest: Path) -> Path:
        url = f"{self.base}/{self.recordings_dir}/{filename}"
        with self.session.get(url, stream=True, timeout=120) as resp:
            resp.raise_for_status()
            ctype = resp.headers.get("Content-Type", "")
            if "html" in ctype:
                raise SessionExpired("GoVoice session expired (got a web page instead of the recording)")
            dest.parent.mkdir(parents=True, exist_ok=True)
            tmp = dest.with_suffix(dest.suffix + ".part")
            with open(tmp, "wb") as fh:
                for chunk in resp.iter_content(64 * 1024):
                    fh.write(chunk)
            tmp.replace(dest)
        self._persist_rotated_cookie()
        return dest
