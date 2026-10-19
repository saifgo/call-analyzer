"""GoVoice login without copying cookies by hand.

The user opens /govoice-login/login: the real GoVoice login page, served through this app. When they sign in,
the login request (login/checkLogin) passes through here, so the session cookies GoVoice sets on it are
captured server-side and saved as GOVOICE_COOKIE. The browser never receives GoVoice's cookies.

/govoice-login/<path> maps to <GOVOICE_BASE_URL>/govoice/<path>, so the page's relative URLs keep working.
"""
import json
import secrets
import threading
import time
from datetime import datetime

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from starlette.concurrency import run_in_threadpool

from ..config import settings
from ..govoice import GoVoiceClient, SessionExpired, cookie_header, current_cookie, new_session, save_cookie

router = APIRouter()
PREFIX = "/govoice-login"
LOGIN_COOKIE = "govoice_login"  # identifies this browser's pending login session
PENDING_TTL = 30 * 60
KEEPALIVE_SECONDS = 10 * 60  # GoVoice sessions expire after 2 hours without activity

_pending: dict[str, tuple[float, object]] = {}  # login id -> (created, requests.Session)
_lock = threading.Lock()
_status = {"connected": None, "total": None, "message": "Not checked yet", "checked_at": None}


# --- Connection status ------------------------------------------------------------------------

def check_connection() -> dict:
    """Test the saved cookie against GoVoice (also saves a rotated cookie)."""
    cookie = current_cookie()
    if not cookie:
        result = {"connected": False, "total": None, "message": "Not connected to GoVoice yet"}
    else:
        try:
            total = GoVoiceClient(cookie).check()
            result = {"connected": True, "total": total, "message": f"Connected · {total} recordings"}
        except SessionExpired:
            result = {"connected": False, "total": None, "message": "GoVoice session expired"}
        except Exception as exc:  # network problems: not an auth issue, don't ask to log in again
            result = {"connected": None, "total": None, "message": f"Can't reach GoVoice: {exc}"}
    _status.update(result, checked_at=datetime.now().isoformat(timespec="seconds"))
    return dict(_status)


@router.get("/api/govoice/status")
def govoice_status(refresh: bool = False):
    if refresh or _status["checked_at"] is None:
        return check_connection()
    return dict(_status)


def keepalive_loop(stop: threading.Event):
    """Use the session regularly so GoVoice doesn't expire it while the app is running."""
    while not stop.wait(KEEPALIVE_SECONDS):
        if current_cookie():
            check_connection()


# --- Login proxy ------------------------------------------------------------------------------

def _session_for(request: Request, fresh: bool):
    now = time.time()
    with _lock:
        for key, (created, _) in list(_pending.items()):
            if now - created > PENDING_TTL:
                del _pending[key]
        login_id = request.cookies.get(LOGIN_COOKIE)
        if fresh or login_id not in _pending:
            login_id = secrets.token_urlsafe(16)
            _pending[login_id] = (now, new_session())
        return login_id, _pending[login_id][1]


def _upstream(path: str) -> str:
    return f"{settings.govoice_base_url}/govoice/{path}"


def _local_location(location: str) -> str:
    """Keep GoVoice redirects inside the proxy."""
    upstream_root = f"{settings.govoice_base_url}/govoice/"
    if location.startswith(upstream_root):
        return f"{PREFIX}/{location[len(upstream_root):]}"
    if location.startswith("/govoice/"):
        return PREFIX + location[len("/govoice"):]
    return location


@router.get(PREFIX)
@router.get(PREFIX + "/")
def login_start():
    return RedirectResponse(f"{PREFIX}/login", status_code=303)


@router.get(PREFIX + "/done", response_class=HTMLResponse)
def login_done():
    return DONE_PAGE


@router.api_route(PREFIX + "/{path:path}", methods=["GET", "POST"])
async def login_proxy(path: str, request: Request):
    # Opening the login page starts a clean GoVoice session.
    login_id, session = _session_for(request, fresh=request.method == "GET" and path == "login")
    body = await request.body()
    headers = {k: v for k, v in request.headers.items()
               if k.lower() in ("accept", "content-type", "x-requested-with", "accept-language")}
    headers["Referer"] = _upstream("login")
    headers["Origin"] = settings.govoice_base_url
    url = _upstream(path) + (f"?{request.url.query}" if request.url.query else "")
    try:
        upstream = await run_in_threadpool(session.request, request.method, url, data=body or None,
                                           headers=headers, allow_redirects=False, timeout=60)
    except Exception as exc:
        raise HTTPException(502, f"Can't reach GoVoice: {exc}")

    content = upstream.content
    content_type = upstream.headers.get("Content-Type", "application/octet-stream")

    if path.rstrip("/") == "login/checkLogin" and request.method == "POST":
        content = await run_in_threadpool(_finish_login, session, content)
        content_type = "application/json"

    if 300 <= upstream.status_code < 400 and "Location" in upstream.headers:
        response = RedirectResponse(_local_location(upstream.headers["Location"]), status_code=303)
    else:
        response = Response(content, status_code=upstream.status_code, media_type=content_type)
    # GoVoice's own cookies stay on the server; the browser only gets the id of its login session.
    response.set_cookie(LOGIN_COOKIE, login_id, httponly=True, samesite="lax", path=PREFIX)
    response.headers["Cache-Control"] = "no-store"
    return response


def _finish_login(session, content: bytes) -> bytes:
    """On a successful sign-in, save the session cookies GoVoice just set and send the tab to /done."""
    try:
        result = json.loads(content)
    except ValueError:
        return content
    if str(result.get("error_login")) == "1":
        return content  # wrong password etc.: GoVoice's page shows its own error message
    cookie = cookie_header(session.cookies)
    try:
        total = GoVoiceClient(cookie).check()
    except Exception as exc:
        result.update(error_login=1, messages=f"Signed in, but the recordings list is not accessible: {exc}")
        return json.dumps(result).encode()
    save_cookie(cookie)
    _status.update(connected=True, total=total, message=f"Connected · {total} recordings",
                   checked_at=datetime.now().isoformat(timespec="seconds"))
    result["redirect_module"] = f"{PREFIX}/done"
    return json.dumps(result).encode()


DONE_PAGE = """<!doctype html>
<html lang="en"><head><meta charset="utf-8"><title>Connected to GoVoice</title>
<style>
  body { margin: 0; min-height: 100vh; display: grid; place-items: center; font: 15px/1.5 "Segoe UI", system-ui, sans-serif;
         background: #f6f7f9; color: #1c2330; }
  .box { background: #fff; border: 1px solid #e3e6eb; border-radius: 12px; padding: 32px 40px; text-align: center; }
  .ok { width: 48px; height: 48px; border-radius: 50%; background: #e3f4ea; color: #1f8a4c; font-size: 26px;
        display: grid; place-items: center; margin: 0 auto 12px; }
  h1 { font-size: 18px; margin: 0 0 4px; }
  p { color: #6b7484; margin: 0; }
</style></head>
<body><div class="box"><div class="ok">✓</div><h1>Connected to GoVoice</h1>
<p>Call Analyzer saved your session. You can close this tab.</p></div>
<script>
  try { window.opener && window.opener.postMessage({ type: "govoice-connected" }, location.origin); } catch (e) {}
  setTimeout(() => window.close(), 1500);
</script></body></html>"""
