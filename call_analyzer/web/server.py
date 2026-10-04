"""Local web UI: settings, call browser with editable transcripts, pipeline runner, reports."""
import hmac
import json
import os
import re
import secrets
import signal
import subprocess
import sys
import threading
import time
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path
from urllib.parse import quote, urlsplit

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from .. import auth, db
from ..config import ENV_PATH, ROOT, settings
from . import govoice_login
from .export import audio_data_uri, render_call_page, render_report_page

# Built from frontend/ (npm run build); see frontend/README.md.
STATIC = Path(__file__).parent / "static"
ENV_EXAMPLE_PATH = ROOT / ".env.example"
SECRET_KEYS = {"GOVOICE_COOKIE", "ANTHROPIC_API_KEY", "ELEVENLABS_API_KEY", "OPENAI_API_KEY",
               "CLAUDE_CODE_OAUTH_TOKEN", "CURSOR_API_KEY", "ADMIN_PASSWORD"}


@asynccontextmanager
async def lifespan(app):
    auth.ensure_admin()
    if not auth.list_users():
        print("No user accounts yet. Create one with:  python -m call_analyzer user add <name>")
    stop = threading.Event()
    threading.Thread(target=govoice_login.keepalive_loop, args=(stop,), daemon=True).start()
    yield
    stop.set()


app = FastAPI(title="Call Analyzer", lifespan=lifespan)
app.include_router(govoice_login.router)


# --- Authentication ---------------------------------------------------------------------------

SESSION_COOKIE = "call_analyzer_session"
# Reachable without logging in: the login page and its assets (static/ is only the UI bundle, no data),
# share links (they carry their own secret token) and the health check.
PUBLIC_PATHS = {"/login", "/api/login", "/healthz"}
# Lets the headless browser that renders PDFs open the print page without a login cookie. New on every start.
PRINT_KEY = secrets.token_urlsafe(32)


def _is_public(request: Request) -> bool:
    path = request.url.path
    if path in PUBLIC_PATHS or path.startswith(("/share/", "/static/")):
        return True
    return path.startswith("/export/") and hmac.compare_digest(request.query_params.get("key", ""), PRINT_KEY)


def _cross_site(request: Request) -> bool:
    """Reject state-changing requests sent by another website (on top of the SameSite cookie)."""
    if request.method in ("GET", "HEAD", "OPTIONS"):
        return False
    origin = request.headers.get("origin")
    return bool(origin) and urlsplit(origin).netloc != request.headers.get("host")


# Everything an agent account may do; anything else is refused. The endpoints themselves then limit
# the data to the agent extensions linked to the account (see _scope).
AGENT_ALLOWED = [(method, re.compile(pattern)) for method, pattern in [
    ("GET", r"/"),
    ("GET", r"/api/me"),
    ("PUT", r"/api/me/password"),
    ("POST", r"/api/logout"),
    ("GET", r"/api/stats"),
    ("GET", r"/api/calls"),
    ("GET", r"/api/calls/[^/]+"),
    ("GET", r"/api/calls/[^/]+/(audio|export\.pdf|export\.html)"),
    ("GET", r"/api/reports"),
    ("GET", r"/api/reports/[^/]+"),
    ("GET", r"/api/reports/[^/]+/export\.pdf"),
]]


def _agent_allowed(request: Request) -> bool:
    method = "GET" if request.method == "HEAD" else request.method
    return any(m == method and p.fullmatch(request.url.path) for m, p in AGENT_ALLOWED)


@app.middleware("http")
async def require_login(request: Request, call_next):
    if _cross_site(request):
        return JSONResponse({"detail": "Cross-site request blocked"}, status_code=403)
    if not _is_public(request):
        account = auth.get_user(auth.session_user(request.cookies.get(SESSION_COOKIE)) or "")
        if not account:
            if request.url.path.startswith("/api/"):
                return JSONResponse({"detail": "Not logged in"}, status_code=401)
            target = request.url.path + (f"?{request.url.query}" if request.url.query else "")
            return RedirectResponse(f"/login?next={quote(target)}", status_code=303)
        if account["role"] != "admin" and not _agent_allowed(request):
            if request.url.path.startswith("/api/"):
                return JSONResponse({"detail": "Only admins can do this"}, status_code=403)
            return RedirectResponse("/", status_code=303)
        request.state.user = account["username"]
        request.state.account = account
    return await call_next(request)


def _scope(request: Request) -> list[str] | None:
    """Agent extensions this account may see, or None for all (admins). Print pages have no account: all."""
    account = getattr(request.state, "account", None)
    return None if account is None or account["role"] == "admin" else account["agents"]


def _scope_sql(request: Request, column: str = "agent") -> tuple[str, list[str]]:
    agents = _scope(request)
    if agents is None:
        return "1=1", []
    if not agents:
        return "0", []
    return f"{column} IN ({','.join('?' * len(agents))})", agents


class LoginBody(BaseModel):
    username: str
    password: str


# username -> timestamps of recent failed logins. Keyed by account rather than IP, so it also holds
# behind a reverse proxy and can't be dodged by rotating addresses.
_failed_logins: dict[str, list[float]] = {}
MAX_FAILED_LOGINS, FAILED_LOGIN_WINDOW = 10, 15 * 60


@app.post("/api/login")
def login(body: LoginBody, request: Request):
    username = body.username.strip()
    now = time.time()
    recent = [t for t in _failed_logins.get(username.lower(), []) if now - t < FAILED_LOGIN_WINDOW]
    if len(recent) >= MAX_FAILED_LOGINS:
        raise HTTPException(429, "Too many failed attempts. Try again in a few minutes.")
    if not auth.authenticate(username, body.password):
        _failed_logins[username.lower()] = [*recent, now]
        raise HTTPException(401, "Wrong username or password")
    _failed_logins.pop(username.lower(), None)
    response = JSONResponse({"ok": True, "user": username})
    response.set_cookie(SESSION_COOKIE, auth.create_session(username), max_age=settings.session_days * 86400,
                        httponly=True, samesite="lax",
                        secure=settings.cookie_secure or request.url.scheme == "https")
    return response


@app.post("/api/logout")
def logout(request: Request):
    auth.delete_session(request.cookies.get(SESSION_COOKIE))
    response = JSONResponse({"ok": True})
    response.delete_cookie(SESSION_COOKIE)
    return response


@app.get("/api/me")
def me(request: Request):
    account = request.state.account
    return {"user": account["username"], "role": account["role"], "display_name": account["display_name"],
            "agents": account["agents"]}


class PasswordBody(BaseModel):
    current_password: str
    new_password: str


@app.put("/api/me/password")
def change_own_password(body: PasswordBody, request: Request):
    username = request.state.user
    if not auth.authenticate(username, body.current_password):
        raise HTTPException(400, "Current password is wrong")
    try:
        auth.set_password(username, body.new_password)
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    # set_password signed out every session, this one too: start a fresh one.
    response = JSONResponse({"ok": True})
    response.set_cookie(SESSION_COOKIE, auth.create_session(username), max_age=settings.session_days * 86400,
                        httponly=True, samesite="lax",
                        secure=settings.cookie_secure or request.url.scheme == "https")
    return response


# --- Accounts (admins only, see AGENT_ALLOWED) -----------------------------------------------

class NewUserBody(BaseModel):
    username: str
    password: str
    role: str = "agent"
    display_name: str = ""
    agents: list[str] = []


class UserUpdateBody(BaseModel):
    role: str | None = None
    display_name: str | None = None
    agents: list[str] | None = None
    password: str | None = None


@app.get("/api/users")
def list_accounts():
    return auth.list_accounts()


@app.post("/api/users")
def create_account(body: NewUserBody):
    try:
        auth.create_user(body.username.strip(), body.password, body.role, body.display_name, body.agents)
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    return auth.get_user(body.username.strip())


@app.patch("/api/users/{username}")
def update_account(username: str, body: UserUpdateBody, request: Request):
    if not auth.user_exists(username):
        raise HTTPException(404, "User not found")
    if username == request.state.user and body.role not in (None, "admin"):
        raise HTTPException(400, "You can't remove your own admin access")
    try:
        auth.update_user(username, role=body.role, display_name=body.display_name, agents=body.agents)
        if body.password:
            auth.set_password(username, body.password)
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    return auth.get_user(username)


@app.delete("/api/users/{username}")
def delete_account(username: str, request: Request):
    if username == request.state.user:
        raise HTTPException(400, "You can't delete your own account")
    try:
        if not auth.delete_user(username):
            raise HTTPException(404, "User not found")
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    return {"ok": True}


@app.get("/api/agents")
def list_agents():
    """Agent extensions seen in calls, with which accounts they're linked to (for the account editor)."""
    conn = db.connect()
    linked: dict[str, list[str]] = {}
    for username, agent in conn.execute("SELECT username, agent FROM user_agents ORDER BY username"):
        linked.setdefault(agent, []).append(username)
    counts = dict(conn.execute("SELECT agent, COUNT(*) FROM calls WHERE agent IS NOT NULL AND agent != '' "
                               "GROUP BY agent").fetchall())
    return [{"agent": a, "calls": counts.get(a, 0), "accounts": linked.get(a, [])}
            for a in sorted(set(counts) | set(linked))]


@app.get("/login")
def login_page():
    return FileResponse(STATIC / "index.html")  # the single-page app shows the sign-in form on /login


@app.get("/healthz")
def healthz():
    return {"ok": True}


@app.middleware("http")
async def no_cache(request, call_next):
    """Always revalidate the HTML so UI updates show up without a hard refresh; built assets have hashed names."""
    response = await call_next(request)
    path = request.url.path
    if path.startswith("/static/assets/"):
        response.headers["Cache-Control"] = "public, max-age=31536000, immutable"
    elif path in ("/", "/login") or path.startswith("/static/"):
        response.headers["Cache-Control"] = "no-cache"
    return response


# --- Settings (.env) --------------------------------------------------------------------------

def _parse_env(path: Path) -> dict[str, str]:
    values = {}
    if path.exists():
        for line in path.read_text(encoding="utf-8").splitlines():
            if "=" in line and not line.lstrip().startswith("#"):
                key, _, value = line.partition("=")
                values[key.strip()] = value.strip()
    return values


def _env_schema() -> list[dict]:
    """Fields in .env.example order, with their section and the comment lines above them as help text."""
    fields, section, comments = [], "General", []
    for line in ENV_EXAMPLE_PATH.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if match := re.match(r"#\s*---\s*(.+?)\s*---", stripped):
            section, comments = match.group(1), []
        elif stripped.startswith("#"):
            comments.append(stripped.lstrip("#").strip())
        elif "=" in stripped:
            key, _, default = stripped.partition("=")
            fields.append({"key": key, "section": section, "help": " ".join(comments),
                           "default": default, "secret": key in SECRET_KEYS})
            comments = []
        else:
            comments = []
    return fields


@app.get("/api/settings")
def get_settings():
    values = _parse_env(ENV_PATH)
    # Values not in the file may come from the environment (e.g. Coolify/Docker environment variables).
    return [{**f, "value": values.get(f["key"], os.environ.get(f["key"], ""))} for f in _env_schema()]


@app.get("/api/whisper-models")
def whisper_models():
    """Dialect models that WHISPER_MODEL can be set to, and whether they're converted yet."""
    from ..whisper_models import DIALECT_MODELS, is_installed
    return [{"name": k, "label": m.label, "repo": m.repo, "size_gb": m.size_gb, "installed": is_installed(k)}
            for k, m in DIALECT_MODELS.items()]


@app.put("/api/settings")
def put_settings(updates: dict[str, str]):
    # Start from the environment so values set outside the file (Coolify/Docker) aren't saved as empty.
    current = {f["key"]: os.environ.get(f["key"], "") for f in _env_schema()}
    current.update(_parse_env(ENV_PATH))
    current.update({k: v.replace("\n", " ").strip() for k, v in updates.items()})
    # Rewrite .env following .env.example's layout and comments; keep unknown keys at the end.
    lines, known = [], set()
    for line in ENV_EXAMPLE_PATH.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if "=" in stripped and not stripped.startswith("#"):
            key = stripped.partition("=")[0]
            known.add(key)
            lines.append(f"{key}={current.get(key, '')}")
        else:
            lines.append(line)
    extra = [f"{k}={v}" for k, v in current.items() if k not in known]
    if extra:
        lines += ["", "# --- Other ---", *extra]
    ENV_PATH.parent.mkdir(parents=True, exist_ok=True)
    ENV_PATH.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return {"ok": True}


# --- Business context -------------------------------------------------------------------------

class TextBody(BaseModel):
    text: str


@app.get("/api/business")
def get_business():
    path = settings.business_context_path
    return {"text": path.read_text(encoding="utf-8") if path.exists() else ""}


@app.put("/api/business")
def put_business(body: TextBody):
    settings.business_context_path.parent.mkdir(exist_ok=True)
    settings.business_context_path.write_text(body.text, encoding="utf-8")
    return {"ok": True}


# --- Calls ------------------------------------------------------------------------------------

STATUS_SQL = {
    "new": "audio_path IS NULL",
    "downloaded": "audio_path IS NOT NULL AND transcript IS NULL",
    "transcribed": "transcript IS NOT NULL AND analysis IS NULL",
    "analyzed": "analysis IS NOT NULL",
    "stale": "analysis IS NOT NULL AND transcribed_at > analyzed_at",
    "error": "error IS NOT NULL",
}

# `sort` query values -> ORDER BY expressions. Prefix with "-" for descending.
SORT_SQL = {
    "date": "date_call",
    "agent": "agent",
    "customer": "customer",
    "duration": "duration",
    "score": "json_extract(analysis, '$.overall_score')",
    "updated": "updated_at",
}


def _summary(row) -> dict:
    analysis = json.loads(row["analysis"]) if row["analysis"] else None
    if row["analysis"]:
        status = "stale" if (row["transcribed_at"] or "") > (row["analyzed_at"] or "") else "analyzed"
    elif row["transcript"] is not None:
        status = "transcribed"
    elif row["audio_path"]:
        status = "downloaded"
    else:
        status = "new"
    return {
        "id": row["id"], "type": row["type"], "agent": row["agent"], "customer": row["customer"],
        "date_call": row["date_call"], "duration": row["duration"], "filename": row["filename"],
        "status": status, "error": row["error"],
        "score": analysis.get("overall_score") if analysis else None,
        "outcome": analysis.get("outcome") if analysis else None,
        "interest": analysis.get("customer_interest") if analysis else None,
        "updated_at": row["updated_at"],
    }


@app.get("/api/calls")
def list_calls(request: Request, agent: str = "", status: str = "", q: str = "", since: str = "", until: str = "",
               min_duration: int = 0, sort: str = "-date", limit: int = 200, offset: int = 0):
    scope, scope_args = _scope_sql(request)
    clauses, args = [scope], list(scope_args)
    if agent:
        clauses.append("agent = ?")
        args.append(agent)
    if status in STATUS_SQL:
        clauses.append(STATUS_SQL[status])
    if q:
        clauses.append("(customer LIKE ? OR id = ? OR transcript LIKE ?)")
        args += [f"%{q}%", q, f"%{q}%"]
    if since:
        clauses.append("date_call >= ?")
        args.append(since)
    if until:
        clauses.append("date_call < ?")
        args.append(until)
    if min_duration:
        clauses.append("duration >= ?")
        args.append(min_duration)
    where = " AND ".join(clauses)
    if sort.lstrip("-") not in SORT_SQL:
        sort = "-date"
    desc = sort.startswith("-")
    col = SORT_SQL[sort.lstrip("-")]
    # Unscored/empty values always go last; newest-first breaks ties.
    order = f"{col} IS NULL, {col} {'DESC' if desc else 'ASC'}, date_call DESC"
    conn = db.connect()
    total = conn.execute(f"SELECT COUNT(*) FROM calls WHERE {where}", args).fetchone()[0]
    rows = conn.execute(f"SELECT * FROM calls WHERE {where} ORDER BY {order} LIMIT ? OFFSET ?",
                        [*args, limit, offset]).fetchall()
    agents = [r[0] for r in conn.execute(f"SELECT DISTINCT agent FROM calls WHERE {scope} ORDER BY agent", scope_args)]
    return {"total": total, "calls": [_summary(r) for r in rows], "agents": agents}


def _get_row(call_id: str, request: Request | None = None):
    """The call, or 404. With a request, also 404 when the account may not see this agent's calls."""
    row = db.connect().execute("SELECT * FROM calls WHERE id=?", (call_id,)).fetchone()
    agents = _scope(request) if request else None
    if not row or (agents is not None and row["agent"] not in agents):
        raise HTTPException(404, "Call not found")
    return row


@app.get("/api/calls/{call_id}")
def get_call(call_id: str, request: Request):
    row = _get_row(call_id, request)
    return {
        **_summary(row),
        "transcript": row["transcript"],
        "transcribed_at": row["transcribed_at"],
        "transcribed_by": row["transcribed_by"],
        "analyzed_at": row["analyzed_at"],
        "analyzed_by": row["analyzed_by"],
        "analysis": json.loads(row["analysis"]) if row["analysis"] else None,
        "has_audio": bool(row["audio_path"]) and Path(row["audio_path"]).exists(),
    }


EDITED_SEP = " · "


@app.put("/api/calls/{call_id}/transcript")
def put_transcript(call_id: str, body: TextBody, request: Request):
    row = _get_row(call_id)
    # Keep the model that wrote the transcript and note who corrected it last.
    model = (row["transcribed_by"] or "").split(EDITED_SEP)[0]
    edited = f"edited by {request.state.user}"
    by = f"{model}{EDITED_SEP}{edited}" if model else edited[0].upper() + edited[1:]
    conn = db.connect()
    conn.execute("UPDATE calls SET transcript=?, transcribed_at=?, transcribed_by=? WHERE id=?",
                 (body.text, datetime.now().isoformat(timespec="seconds"), by, call_id))
    conn.commit()
    return {"ok": True}


@app.get("/api/calls/{call_id}/audio")
def get_audio(call_id: str, request: Request):
    row = _get_row(call_id, request)
    if not row["audio_path"] or not Path(row["audio_path"]).exists():
        raise HTTPException(404, "Audio not downloaded yet")
    return FileResponse(row["audio_path"], media_type="audio/mpeg")


@app.get("/api/stats")
def stats(request: Request):
    conn = db.connect()
    scope, scope_args = _scope_sql(request)

    def count(where: str) -> int:
        return conn.execute(f"SELECT COUNT(*) FROM calls WHERE {scope} AND {where}", scope_args).fetchone()[0]

    agents = [dict(r) for r in conn.execute(f"""
        SELECT agent, COUNT(*) calls, COUNT(analysis) analyzed,
               ROUND(AVG(json_extract(analysis, '$.overall_score')), 1) avg_score,
               SUM(json_extract(analysis, '$.outcome') IN ('sale', 'appointment_or_next_step')) wins,
               ROUND(SUM(duration) / 60.0) minutes
        FROM calls WHERE {scope} GROUP BY agent ORDER BY calls DESC""", scope_args)]
    outcomes = [dict(r) for r in conn.execute(f"""
        SELECT json_extract(analysis, '$.outcome') outcome, COUNT(*) n FROM calls
        WHERE {scope} AND analysis IS NOT NULL GROUP BY 1 ORDER BY n DESC""", scope_args)]
    names = {}
    for username, display_name, agent in conn.execute("""
            SELECT u.username, u.display_name, ua.agent FROM user_agents ua JOIN users u USING (username)
            ORDER BY u.role = 'agent' DESC, u.username"""):
        names.setdefault(agent, display_name or username)  # prefer the agent's own account
    for a in agents:
        a["name"] = names.get(a["agent"])
    return {
        "total": count("1=1"),
        "downloaded": count("audio_path IS NOT NULL"),
        "transcribed": count("transcript IS NOT NULL"),
        "analyzed": count("analysis IS NOT NULL"),
        "stale": count(STATUS_SQL["stale"]),
        "errors": count("error IS NOT NULL"),
        "last_call": conn.execute(f"SELECT MAX(date_call) FROM calls WHERE {scope}", scope_args).fetchone()[0],
        "agents": agents,
        "outcomes": outcomes,
    }


# --- Reports ----------------------------------------------------------------------------------

def _report_visible(name: str, request: Request | None) -> bool:
    """Agent accounts only see the per-agent reports of their own extensions (not the team report)."""
    agents = _scope(request) if request else None
    return agents is None or any(name.endswith(f"-agent-{a}.md") for a in agents)


def _report_path(name: str, request: Request | None = None) -> Path:
    if not name.endswith(".md") or "/" in name or "\\" in name or ".." in name or not _report_visible(name, request):
        raise HTTPException(404, "Report not found")
    path = (settings.reports_dir / name).resolve()
    if path.parent != settings.reports_dir.resolve() or not path.is_file():
        raise HTTPException(404, "Report not found")
    return path


def _report_title(text: str, name: str) -> str:
    for line in text.splitlines():
        if line.startswith("# "):
            return line[2:].strip()
    return name.removesuffix(".md")


@app.get("/api/reports")
def list_reports(request: Request):
    if not settings.reports_dir.exists():
        return []
    files = sorted((p for p in settings.reports_dir.glob("*.md") if _report_visible(p.name, request)),
                   key=lambda p: p.stat().st_mtime, reverse=True)
    return [{"name": p.name, "modified": datetime.fromtimestamp(p.stat().st_mtime).isoformat(timespec="minutes")}
            for p in files]


@app.get("/api/reports/{name}")
def get_report(name: str, request: Request):
    path = _report_path(name, request)
    return {"name": name, "text": path.read_text(encoding="utf-8")}


def _report_share_token(name: str) -> str | None:
    found = db.connect().execute("SELECT token FROM report_shares WHERE report_name=?", (name,)).fetchone()
    return found[0] if found else None


@app.get("/api/reports/{name}/share")
def get_report_share(name: str):
    _report_path(name)
    token = _report_share_token(name)
    return {"token": token, "url": f"{_base_url()}/share/report/{token}" if token else None,
            "lan": _shareable()}


@app.post("/api/reports/{name}/share")
def create_report_share(name: str):
    _report_path(name)
    if not _report_share_token(name):
        conn = db.connect()
        conn.execute("INSERT INTO report_shares (token, report_name, created_at) VALUES (?, ?, ?)",
                     (secrets.token_urlsafe(16), name, datetime.now().isoformat(timespec="seconds")))
        conn.commit()
    return get_report_share(name)


@app.delete("/api/reports/{name}/share")
def revoke_report_share(name: str):
    conn = db.connect()
    conn.execute("DELETE FROM report_shares WHERE report_name=?", (name,))
    conn.commit()
    return {"ok": True}


def _report_for_token(token: str) -> tuple[str, str]:
    found = db.connect().execute("SELECT report_name FROM report_shares WHERE token=?", (token,)).fetchone()
    if not found:
        raise HTTPException(404, "This share link does not exist or was revoked")
    path = _report_path(found[0])
    return found[0], path.read_text(encoding="utf-8")


@app.get("/share/report/{token}", response_class=HTMLResponse)
def report_share_page(token: str):
    _name, text = _report_for_token(token)
    return render_report_page(_report_title(text, _name), text)


@app.get("/export/report/{name}/print", response_class=HTMLResponse)
def report_print_view(name: str):
    path = _report_path(name)
    text = path.read_text(encoding="utf-8")
    return render_report_page(_report_title(text, name), text)


@app.get("/api/reports/{name}/export.pdf")
def export_report_pdf(name: str, request: Request):
    path = _report_path(name, request)
    text = path.read_text(encoding="utf-8")
    filename = f"{path.stem}.pdf"
    url = f"/export/report/{quote(name)}/print?key={PRINT_KEY}"
    data = _pdf_bytes(request, url)
    return Response(data, media_type="application/pdf",
                    headers={"Content-Disposition": f'attachment; filename="{filename}"'})


# --- Jobs: run CLI commands in the background and stream their output -------------------------

COMMANDS = {"check", "sync", "download", "transcribe", "analyze", "report", "run", "install-model"}
ARG_FLAGS = {"since": "--since", "until": "--until", "agent": "--agent", "min_duration": "--min-duration",
             "limit": "--limit", "ids": "--ids", "workers": "--workers"}
BOOL_FLAGS = {"redo": "--redo", "team_only": "--team-only"}


class JobRequest(BaseModel):
    commands: list[str]
    args: dict[str, str | int | bool | None] = {}


class JobRunner:
    def __init__(self):
        self.lock = threading.Lock()
        self.process: subprocess.Popen | None = None
        self.lines: list[str] = []
        self.label = ""
        self.started_at = None
        self.finished_at = None
        self.exit_code = None
        self.stopped = False
        self.history: list[dict] = []

    @property
    def running(self) -> bool:
        return self.finished_at is None and self.started_at is not None

    def start(self, commands: list[str], args: dict):
        with self.lock:
            if self.running:
                raise HTTPException(409, "A job is already running")
            cli_args = []
            for name, value in args.items():
                if name in ARG_FLAGS and value not in (None, "", False):
                    cli_args += [ARG_FLAGS[name], str(value)]
                elif name in BOOL_FLAGS and value:
                    cli_args.append(BOOL_FLAGS[name])
            self.lines, self.exit_code, self.stopped = [], None, False
            self.label = " → ".join(commands) + (f"  ({' '.join(cli_args)})" if cli_args else "")
            self.started_at, self.finished_at = datetime.now().isoformat(timespec="seconds"), None
            threading.Thread(target=self._run, args=(commands, cli_args), daemon=True).start()

    def _run(self, commands: list[str], cli_args: list[str]):
        env = {**os.environ, "PYTHONUNBUFFERED": "1", "PYTHONIOENCODING": "utf-8"}
        code = 0
        for command in commands:
            if self.stopped:
                break
            # check and report don't take every filter; argparse accepts them all on pipeline commands.
            argv = [sys.executable, "-m", "call_analyzer", command] + ([] if command == "check" else cli_args)
            self.lines.append(f"$ call_analyzer {command} {' '.join(argv[4:])}".rstrip())
            # Own process group on Linux/macOS so Stop also ends the claude CLI processes it starts.
            self.process = subprocess.Popen(argv, cwd=ROOT, env=env, stdout=subprocess.PIPE,
                                            stderr=subprocess.STDOUT, text=True, encoding="utf-8",
                                            errors="replace", bufsize=1, start_new_session=os.name != "nt")
            for line in self.process.stdout:
                self.lines.append(line.rstrip("\n"))
            code = self.process.wait()
            if code != 0:
                break
        self.exit_code = -1 if self.stopped else code
        self.finished_at = datetime.now().isoformat(timespec="seconds")
        self.lines.append("Stopped." if self.stopped else ("Done." if code == 0 else f"Failed (exit code {code})."))
        self.history.insert(0, {"label": self.label, "started_at": self.started_at,
                                "finished_at": self.finished_at, "exit_code": self.exit_code})
        del self.history[20:]

    def stop(self):
        self.stopped = True
        if self.process and self.process.poll() is None:
            if os.name == "nt":  # kill the whole tree (claude CLI children too)
                subprocess.run(["taskkill", "/F", "/T", "/PID", str(self.process.pid)], capture_output=True)
            else:
                os.killpg(self.process.pid, signal.SIGTERM)

    def state(self, since: int = 0) -> dict:
        return {"running": self.running, "label": self.label, "started_at": self.started_at,
                "finished_at": self.finished_at, "exit_code": self.exit_code,
                "offset": len(self.lines), "lines": self.lines[since:], "history": self.history}


jobs = JobRunner()


@app.post("/api/jobs")
def start_job(req: JobRequest):
    if not req.commands or any(c not in COMMANDS for c in req.commands):
        raise HTTPException(400, f"Commands must be among {sorted(COMMANDS)}")
    jobs.start(req.commands, req.args)
    return jobs.state()


@app.get("/api/jobs")
def job_state(since: int = 0):
    return jobs.state(since)


@app.post("/api/jobs/stop")
def stop_job():
    jobs.stop()
    return {"ok": True}


# --- Export & sharing -------------------------------------------------------------------------

def _lan_ip() -> str:
    import socket
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
            sock.connect(("8.8.8.8", 80))  # no packet is sent; this just picks the outgoing interface
            return sock.getsockname()[0]
    except OSError:
        return "127.0.0.1"


def _base_url() -> str:
    if settings.public_url:
        return settings.public_url
    host = _lan_ip() if settings.share_on_lan else "127.0.0.1"
    return f"http://{host}:{settings.ui_port}"


def _shareable() -> bool:
    """Whether share links work from other computers."""
    return bool(settings.public_url) or settings.share_on_lan


def _govoice_audio_url(row) -> str | None:
    if settings.govoice_recordings_dir and row["filename"]:
        return f"{settings.govoice_base_url}/{settings.govoice_recordings_dir}/{row['filename']}"
    return None


def _share_token(call_id: str) -> str | None:
    found = db.connect().execute("SELECT token FROM shares WHERE call_id=?", (call_id,)).fetchone()
    return found[0] if found else None


def _links(row, include_share: bool) -> list[tuple[str, str]]:
    links = []
    token = _share_token(row["id"])
    if include_share and token and _shareable():
        links.append(("Listen (share link)", f"{_base_url()}/share/{token}/audio"))
    if url := _govoice_audio_url(row):
        links.append(("Open in GoVoice (login required)", url))
    return links


def _filename(row, ext: str) -> str:
    stamp = (row["date_call"] or "").replace(" ", "_").replace(":", "")
    return f"call-{row['id']}-agent{row['agent']}-{stamp}.{ext}"


def _has_audio(row) -> bool:
    return bool(row["audio_path"]) and Path(row["audio_path"]).exists()


@app.get("/api/calls/{call_id}/share")
def get_share(call_id: str):
    token = _share_token(call_id)
    return {"token": token, "url": f"{_base_url()}/share/{token}" if token else None,
            "lan": _shareable()}


@app.post("/api/calls/{call_id}/share")
def create_share(call_id: str):
    import secrets
    _get_row(call_id)
    if not _share_token(call_id):
        conn = db.connect()
        conn.execute("INSERT INTO shares (token, call_id, created_at) VALUES (?, ?, ?)",
                     (secrets.token_urlsafe(16), call_id, datetime.now().isoformat(timespec="seconds")))
        conn.commit()
    return get_share(call_id)


@app.delete("/api/calls/{call_id}/share")
def revoke_share(call_id: str):
    conn = db.connect()
    conn.execute("DELETE FROM shares WHERE call_id=?", (call_id,))
    conn.commit()
    return {"ok": True}


def _row_for_token(token: str):
    found = db.connect().execute("SELECT call_id FROM shares WHERE token=?", (token,)).fetchone()
    if not found:
        raise HTTPException(404, "This share link does not exist or was revoked")
    return _get_row(found[0])


@app.get("/share/{token}", response_class=HTMLResponse)
def share_page(token: str):
    row = _row_for_token(token)
    audio = f"/share/{token}/audio" if _has_audio(row) else None
    return render_call_page(row, audio_src=audio, links=_links(row, include_share=False))


@app.get("/share/{token}/audio")
def share_audio(token: str):
    row = _row_for_token(token)
    if not _has_audio(row):
        raise HTTPException(404, "Audio not available")
    return FileResponse(row["audio_path"], media_type="audio/mpeg", filename=row["filename"])


@app.get("/api/calls/{call_id}/export.html")
def export_html(call_id: str, request: Request):
    """One self-contained file with the audio embedded: opens anywhere, even offline."""
    row = _get_row(call_id, request)
    audio = audio_data_uri(Path(row["audio_path"])) if _has_audio(row) else None
    page = render_call_page(row, audio_src=audio, links=_links(row, include_share=True))
    return Response(page, media_type="text/html; charset=utf-8",
                    headers={"Content-Disposition": f'attachment; filename="{_filename(row, "html")}"'})


@app.get("/export/{call_id}/print", response_class=HTMLResponse)
def print_view(call_id: str):
    row = _get_row(call_id)
    return render_call_page(row, audio_src=None, links=_links(row, include_share=True), for_print=True)


def _find_browser() -> str | None:
    import shutil
    candidates = [
        shutil.which("msedge"), shutil.which("chrome"),
        shutil.which("chromium"), shutil.which("chromium-browser"), shutil.which("google-chrome"),
        r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
        r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
        r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    ]
    return next((c for c in candidates if c and Path(c).exists()), None)


def _pdf_bytes(request: Request, print_path: str) -> bytes:
    """Print a local page to PDF with headless Edge/Chrome (proper Arabic shaping and RTL)."""
    import tempfile
    browser = _find_browser()
    if not browser:
        raise HTTPException(500, "Microsoft Edge, Google Chrome or Chromium is needed to create PDFs")
    port = request.scope["server"][1]  # the port this server is actually listening on
    # Chromium's sandbox doesn't work inside Docker containers, and Docker's /dev/shm is only 64 MB.
    sandbox = [] if os.name == "nt" else ["--no-sandbox", "--disable-dev-shm-usage"]
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp) / "page.pdf"
        subprocess.run(
            [browser, "--headless", "--disable-gpu", "--no-first-run", "--no-pdf-header-footer", *sandbox,
             f"--user-data-dir={tmp}", f"--print-to-pdf={out}",
             f"http://127.0.0.1:{port}{print_path}"],
            capture_output=True, timeout=120,
        )
        if not out.exists():
            raise HTTPException(500, "PDF generation failed")
        return out.read_bytes()


@app.get("/api/calls/{call_id}/export.pdf")
def export_pdf(call_id: str, request: Request):
    row = _get_row(call_id, request)
    data = _pdf_bytes(request, f"/export/{quote(call_id)}/print?key={PRINT_KEY}")
    return Response(data, media_type="application/pdf",
                    headers={"Content-Disposition": f'attachment; filename="{_filename(row, "pdf")}"'})


# --- Frontend ---------------------------------------------------------------------------------

@app.get("/")
def index():
    return FileResponse(STATIC / "index.html")


app.mount("/static", StaticFiles(directory=STATIC), name="static")
