"""Command line: python -m call_analyzer <command> [filters]"""
import argparse
import json
import os
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path

from . import db
from .config import settings


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _filters(args) -> dict:
    ids = [i.strip() for i in args.ids.split(",") if i.strip()] if args.ids else None
    return dict(since=args.since, until=args.until, agent=args.agent,
                min_duration=args.min_duration, limit=args.limit, ids=ids)


def cmd_sync(args):
    from .govoice import GoVoiceClient
    conn = db.connect()
    if args.new_only:
        # Newest first: stop at the first page that holds no new recordings instead of fetching them all.
        fetched = new = page_new = 0
        for i, record in enumerate(GoVoiceClient().iter_recordings(perpage=100, stop_before=args.since), 1):
            added = db.upsert_recordings(conn, [record])
            fetched, new, page_new = fetched + 1, new + added, page_new + added
            if i % 100 == 0:
                if not page_new:
                    break
                page_new = 0
        print(f"Fetched {fetched} recordings from GoVoice, {new} new.")
        return
    records = list(GoVoiceClient().iter_recordings(perpage=100, stop_before=args.since))
    new = db.upsert_recordings(conn, records)
    print(f"Fetched {len(records)} recordings from GoVoice, {new} new.")


def cmd_download(args):
    from .govoice import GoVoiceClient, SessionExpired
    conn = db.connect()
    gv = GoVoiceClient()
    calls = db.select_calls(conn, where="audio_path IS NULL", **_filters(args))
    print(f"Downloading {len(calls)} recordings...")
    for i, call in enumerate(calls, 1):
        dest = settings.audio_dir / call["filename"]
        try:
            if not dest.exists():
                gv.download(call["filename"], dest)
            conn.execute("UPDATE calls SET audio_path=?, error=NULL WHERE id=?", (str(dest), call["id"]))
            print(f"  [{i}/{len(calls)}] {call['filename']}")
        except SessionExpired:
            raise
        except Exception as exc:
            conn.execute("UPDATE calls SET error=? WHERE id=?", (f"download: {exc}", call["id"]))
            print(f"  [{i}/{len(calls)}] FAILED {call['filename']}: {exc}", file=sys.stderr)
        finally:
            conn.commit()


def _parallel(calls, fn, workers, label):
    """Run fn over calls in a thread pool; yield (call, result, error) in the main thread."""
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {pool.submit(fn, call): call for call in calls}
        for done, fut in enumerate(as_completed(futures), 1):
            call = futures[fut]
            try:
                result = fut.result()
            except Exception as exc:
                print(f"  [{done}/{len(calls)}] FAILED {call['filename']}: {exc}", file=sys.stderr)
                yield call, None, exc
            else:
                print(f"  [{done}/{len(calls)}] {label} {call['filename']}")
                yield call, result, None


def cmd_transcribe(args):
    from .transcribe import transcribe, transcriber_label
    conn = db.connect()
    where = "audio_path IS NOT NULL" + ("" if args.redo else " AND transcript IS NULL")
    calls = db.select_calls(conn, where=where, **_filters(args))
    print(f"Transcribing {len(calls)} recordings with {settings.transcribe_provider}...")
    for call, text, exc in _parallel(calls, lambda c: transcribe(Path(c["audio_path"])), args.workers, "transcribed"):
        if exc:
            conn.execute("UPDATE calls SET error=? WHERE id=?", (f"transcribe: {exc}", call["id"]))
        else:
            conn.execute("UPDATE calls SET transcript=?, transcribed_at=?, transcribed_by=?, error=NULL WHERE id=?",
                         (text, _now(), transcriber_label(), call["id"]))
        conn.commit()


def cmd_analyze(args):
    from .analyze import analyze_call
    conn = db.connect()
    where = "transcript IS NOT NULL AND transcript != ''" + ("" if args.redo else " AND analysis IS NULL")
    calls = db.select_calls(conn, where=where, **_filters(args))
    if settings.analysis_backend == "cursor":
        who = f"Cursor ({settings.cursor_model})"
    elif settings.analysis_backend == "auto":
        who = f"Claude ({settings.claude_model}), falling back to Cursor ({settings.cursor_model})"
    else:
        who = f"Claude ({settings.claude_model})"
    print(f"Analyzing {len(calls)} calls with {who}...")
    for call, result, exc in _parallel(calls, analyze_call, args.workers, "analyzed"):
        if exc:
            conn.execute("UPDATE calls SET error=? WHERE id=?", (f"analyze: {exc}", call["id"]))
        else:
            analysis, by = result
            conn.execute("UPDATE calls SET analysis=?, analyzed_at=?, analyzed_by=?, error=NULL WHERE id=?",
                         (analysis.model_dump_json(), _now(), by, call["id"]))
        conn.commit()


def cmd_report(args):
    from .analyze import coaching_report
    conn = db.connect()
    calls = db.select_calls(conn, where="analysis IS NOT NULL", **_filters(args))
    sales_calls = [c for c in calls if json.loads(c["analysis"]).get("is_sales_conversation")]
    if not sales_calls:
        print("No analyzed sales calls match these filters. Run `analyze` first.")
        return

    if args.agent:
        groups = {f"agent-{args.agent}": sales_calls}
    else:
        groups = {"team": sales_calls}
        if not args.team_only:
            for call in sales_calls:
                groups.setdefault(f"agent-{call['agent']}", []).append(call)

    settings.reports_dir.mkdir(exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M")
    for name, group in groups.items():
        title = "the whole sales team" if name == "team" else f"agent extension {name.removeprefix('agent-')}"
        print(f"Writing report for {title} ({len(group)} calls)...")
        text = coaching_report(title, group)
        path = settings.reports_dir / f"{stamp}-{name}.md"
        path.write_text(f"# Coaching report: {title}\n\n{text}\n", encoding="utf-8")
        print(f"  -> {path}")


def cmd_show(args):
    conn = db.connect()
    row = conn.execute("SELECT * FROM calls WHERE id=?", (args.id,)).fetchone()
    if not row:
        sys.exit(f"No call with id {args.id}")
    print(f"{row['date_call']}  {row['type']}  agent {row['agent']} <-> {row['customer']}  {row['duration']}s")
    print(f"\n--- transcript ---\n{row['transcript'] or '(none)'}")
    if row["analysis"]:
        print(f"\n--- feedback ---\n{json.dumps(json.loads(row['analysis']), ensure_ascii=False, indent=2)}")
    if row["error"]:
        print(f"\n--- last error ---\n{row['error']}")


def cmd_stats(args):
    conn = db.connect()

    def count(where: str) -> int:
        return conn.execute(f"SELECT COUNT(*) FROM calls WHERE {where}").fetchone()[0]

    print(f"calls in DB:  {count('1=1')}")
    print(f"downloaded:   {count('audio_path IS NOT NULL')}")
    print(f"transcribed:  {count('transcript IS NOT NULL')}")
    print(f"analyzed:     {count('analysis IS NOT NULL')}")
    print(f"with errors:  {count('error IS NOT NULL')}")
    print("\nagent    calls  analyzed  avg score")
    for row in conn.execute("""SELECT agent, COUNT(*) n, COUNT(analysis) a,
                                      ROUND(AVG(json_extract(analysis, '$.overall_score')), 1) score
                               FROM calls GROUP BY agent ORDER BY n DESC"""):
        score = row["score"] if row["score"] is not None else "-"
        print(f"{row['agent']:<8} {row['n']:>5}  {row['a']:>8}  {score:>9}")


def cmd_check(args):
    """Verify GoVoice cookie, Claude CLI and Whisper setup."""
    import shutil
    import subprocess

    ok = True
    print("GoVoice:")
    try:
        from .govoice import GoVoiceClient
        gv = GoVoiceClient()
        print(f"  OK - logged in, {gv.check()} recordings available")
        print(f"  recordings folder: {gv.recordings_dir}")
    except Exception as exc:
        ok = False
        print(f"  FAILED - {exc}")

    def claude_ready() -> bool:
        print(f"Claude ({settings.claude_backend}):")
        if settings.claude_backend == "subscription":
            exe = shutil.which("claude")
            if exe:
                version = subprocess.run([exe, "--version"], capture_output=True, text=True).stdout.strip()
                print(f"  OK - claude CLI {version}")
                return True
            print("  FAILED - `claude` CLI not found on PATH")
            return False
        if settings.claude_backend == "api":
            if os.getenv("ANTHROPIC_API_KEY"):
                print("  OK - API key set")
                return True
            print("  FAILED - ANTHROPIC_API_KEY is empty")
            return False
        print(f"  FAILED - unknown CLAUDE_BACKEND={settings.claude_backend!r}")
        return False

    def cursor_ready() -> bool:
        print(f"Cursor ({settings.cursor_model}):")
        if not settings.cursor_api_key:
            print("  FAILED - CURSOR_API_KEY is empty")
            return False
        try:
            import cursor_sdk  # noqa: F401
        except ImportError:
            print("  FAILED - cursor-sdk is not installed (pip install cursor-sdk)")
            return False
        print("  OK - API key set")
        return True

    print(f"Analysis ({settings.analysis_backend}):")
    if settings.analysis_backend == "cursor":
        ok = cursor_ready() and ok
    elif settings.analysis_backend == "auto":
        ok = claude_ready() and ok
        ok = cursor_ready() and ok
    elif settings.analysis_backend == "claude":
        ok = claude_ready() and ok
    else:
        ok = False
        print(f"  FAILED - unknown ANALYSIS_BACKEND={settings.analysis_backend!r}")

    print(f"Transcription ({settings.transcribe_provider}):")
    if settings.transcribe_provider == "local":
        try:
            import ctranslate2
            gpus = ctranslate2.get_cuda_device_count()
            from .whisper_models import DIALECT_MODELS, is_installed
            if settings.whisper_model in DIALECT_MODELS and not is_installed(settings.whisper_model):
                print(f"  NOTE - {settings.whisper_model} is not installed yet: it is downloaded and converted "
                      "at the first transcription (or now with `install-model`)")
            print(f"  OK - faster-whisper installed, model {settings.whisper_model}, "
                  f"{'GPU available' if gpus else 'CPU only'}, models in {settings.whisper_model_dir}")
        except Exception as exc:
            ok = False
            print(f"  FAILED - {exc}")
    else:
        key = settings.elevenlabs_api_key if settings.transcribe_provider == "elevenlabs" else settings.openai_api_key
        print("  OK - API key set" if key else "  FAILED - API key is empty")
        ok = ok and bool(key)
    if not ok:
        sys.exit(1)


def cmd_install_model(args):
    """Download + convert a Tunisian/dialect Whisper model now instead of at the first transcription."""
    from .whisper_models import DIALECT_MODELS, install, is_installed

    name = args.name or settings.whisper_model
    if name not in DIALECT_MODELS:
        print("Dialect models (WHISPER_MODEL=<name>):")
        for key, m in DIALECT_MODELS.items():
            print(f"  {key:24} {'installed' if is_installed(key) else 'not installed':14} {m.label}  [{m.repo}]")
        if args.name:
            sys.exit(f"Error: unknown dialect model {name!r}")
        print(f"{name} is a standard Whisper model: it downloads by itself on first use.")
        return
    install(name)


def cmd_ui(args):
    import webbrowser

    import uvicorn

    port = args.port or settings.ui_port
    url = f"http://127.0.0.1:{port}"
    print(f"Call Analyzer UI running at {url}  (Ctrl+C to stop)")
    host = args.host or "127.0.0.1"
    if settings.share_on_lan and not args.host:
        from .web.server import _lan_ip
        host = "0.0.0.0"  # other computers need to log in; only /share/... pages are open to anyone
        print(f"Reachable on your network at http://{_lan_ip()}:{port}")
    if not args.no_browser:
        webbrowser.open(url)
    uvicorn.run("call_analyzer.web.server:app", host=host, port=port, log_level="warning")


def cmd_user(args):
    """Manage the accounts that can sign in to the web interface."""
    from getpass import getpass

    from . import auth
    agents = [a.strip() for a in args.agents.split(",")] if args.agents is not None else None
    if args.action == "list":
        accounts = auth.list_accounts()
        for a in accounts:
            name = f"  ({a['display_name']})" if a["display_name"] else ""
            linked = f"  agents: {', '.join(a['agents'])}" if a["agents"] else ""
            print(f"{a['username']:<20} {a['role']:<6}{name}{linked}")
        if not accounts:
            print("No users yet.")
        return
    if not args.username:
        sys.exit(f"Usage: call_analyzer user {args.action} <username>")
    try:
        if args.action == "delete":
            print("Deleted." if auth.delete_user(args.username) else f"No user {args.username!r}.")
            return
        if args.action == "set":
            auth.update_user(args.username, role=args.role, display_name=args.name, agents=agents)
            print("Updated.")
            return
    except ValueError as exc:
        sys.exit(str(exc))
    exists = auth.user_exists(args.username)
    if args.action == "add" and exists:
        sys.exit(f"User {args.username!r} already exists; use `user passwd` to change the password.")
    if args.action == "passwd" and not exists:
        sys.exit(f"No user {args.username!r}; use `user add` to create it.")
    password = os.getenv("NEW_PASSWORD") or getpass(f"Password for {args.username}: ")
    if not os.getenv("NEW_PASSWORD") and getpass("Repeat password: ") != password:
        sys.exit("Passwords don't match.")
    try:
        if args.action == "add":
            auth.create_user(args.username, password, args.role or "admin", args.name or "", agents or [])
        else:
            auth.set_password(args.username, password)
    except ValueError as exc:
        sys.exit(str(exc))
    print("User created." if args.action == "add" else "Password changed; the user was signed out everywhere.")


def cmd_run(args):
    cmd_sync(args)
    cmd_download(args)
    cmd_transcribe(args)
    cmd_analyze(args)
    cmd_report(args)


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")  # Arabic/French text on Windows consoles
    parser = argparse.ArgumentParser(prog="call_analyzer",
                                     description="Analyze GoVoice sales call recordings with Claude")
    sub = parser.add_subparsers(dest="command", required=True)

    def add(name, fn, help_text):
        p = sub.add_parser(name, help=help_text)
        p.set_defaults(fn=fn)
        p.add_argument("--since", help="Only calls on/after this date, e.g. 2026-09-01")
        p.add_argument("--until", help="Only calls before this date, e.g. 2026-10-01")
        p.add_argument("--agent", help="Only this agent extension, e.g. 102")
        p.add_argument("--min-duration", type=int, default=30,
                       help="Skip calls shorter than N seconds (default 30)")
        p.add_argument("--limit", type=int, help="Process at most N calls")
        p.add_argument("--ids", help="Only these call ids, comma separated (ignores --min-duration)")
        p.add_argument("--workers", type=int, default=4, help="Parallel transcriptions/analyses (default 4)")
        p.add_argument("--redo", action="store_true", help="transcribe/analyze: redo calls that are already done")
        p.add_argument("--team-only", action="store_true", help="report: only the team report")
        p.add_argument("--new-only", action="store_true",
                       help="sync: stop at the first page of recordings that are all known already")

    add("sync", cmd_sync, "Fetch the recordings list from GoVoice into the local DB")
    add("download", cmd_download, "Download mp3 files")
    add("transcribe", cmd_transcribe, "Transcribe downloaded recordings")
    add("analyze", cmd_analyze, "Get per-call feedback from Claude")
    add("report", cmd_report, "Write coaching reports (team + per agent) to reports/")
    add("run", cmd_run, "sync + download + transcribe + analyze + report")
    add("stats", cmd_stats, "Show pipeline progress")
    sub.add_parser("check", help="Check GoVoice cookie, Claude and Whisper setup").set_defaults(fn=cmd_check)
    im = sub.add_parser("install-model", help="Download + convert a Tunisian Derja Whisper model (lists them without a name)")
    im.add_argument("name", nargs="?", help="Default: WHISPER_MODEL")
    im.set_defaults(fn=cmd_install_model)
    ui = sub.add_parser("ui", help="Open the web interface")
    ui.add_argument("--port", type=int, help="Default: UI_PORT from .env (8765)")
    ui.add_argument("--host", help="Address to listen on, e.g. 0.0.0.0 in Docker (default: 127.0.0.1)")
    ui.add_argument("--no-browser", action="store_true")
    ui.set_defaults(fn=cmd_ui)
    user = sub.add_parser("user", help="Manage web interface logins: list | add | set | passwd | delete")
    user.add_argument("action", choices=["list", "add", "set", "passwd", "delete"])
    user.add_argument("username", nargs="?")
    user.add_argument("--role", choices=["admin", "agent"],
                      help="admin: full access (default for add); agent: only sees the calls of --agents")
    user.add_argument("--agents", help="Agent extensions linked to the account, comma separated, e.g. 102,103")
    user.add_argument("--name", help="Display name, e.g. the agent's full name")
    user.set_defaults(fn=cmd_user)
    show = sub.add_parser("show", help="Show transcript + feedback for one call")
    show.add_argument("id")
    show.set_defaults(fn=cmd_show)

    args = parser.parse_args()
    from .govoice import EXIT_AUTH, SessionExpired
    try:
        args.fn(args)
    except SessionExpired as exc:  # the UI recognises this exit code and asks to log in to GoVoice
        print(f"GoVoice login needed: {exc}", file=sys.stderr)
        sys.exit(EXIT_AUTH)
    except RuntimeError as exc:  # config problems
        sys.exit(f"Error: {exc}")


if __name__ == "__main__":
    main()
