"""HTTP API for remote agents (see workers.py and agent.py).

- /api/worker/...  is what an agent calls. It signs in with its own bearer token instead of a login cookie.
- /api/workers/... is what the admin's Agents page calls (normal admin login, see server.py).
"""
import json
import re
import threading
import time
import zipfile
from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import FileResponse
from pydantic import BaseModel

from .. import db, voice_models, workers
from ..config import live, live_defaults, runs_on, settings
from ..whisper_models import DIALECT_MODELS, is_installed, model_dir

router = APIRouter()

MAX_WAIT = 30  # longest a claim request is held open
MAX_INFO_BYTES = 20_000  # what an agent may report about itself
KEEP_FINISHED_TASKS = 500
AUDIO_KINDS = ("transcribe", "voice")  # the steps that work on the recording itself: the agent downloads it


# --- Agent side ---------------------------------------------------------------------------------

def current_worker(authorization: str = Header("")) -> dict:
    conn = db.connect()
    worker = workers.authenticate(conn, authorization.removeprefix("Bearer ").strip())
    if not worker:
        raise HTTPException(401, "Unknown or revoked agent token")
    return worker


def _clean_info(info) -> dict | None:
    """What an agent says about itself is shown in the UI: accept only a small JSON object."""
    if info is None:
        return None
    if not isinstance(info, dict) or len(json.dumps(info, ensure_ascii=False)) > MAX_INFO_BYTES:
        raise HTTPException(400, "info must be a small JSON object")
    return info


class HelloBody(BaseModel):
    info: dict = {}


@router.post("/api/worker/hello")
def hello(body: HelloBody, worker: dict = Depends(current_worker)):
    info = _clean_info(body.info) or {}
    if int(info.get("protocol") or 0) < workers.MIN_PROTOCOL:
        raise HTTPException(426, "This agent is too old for the server: update Call Analyzer on the agent's PC "
                                 "(git pull), then restart it.")
    conn = db.connect()
    workers.touch(conn, worker["id"], info)
    return {"worker_id": worker["id"], "name": worker["name"], "enabled": worker["enabled"],
            "defaults": live_defaults(), "protocol": workers.PROTOCOL}


@router.get("/api/worker/config")
def worker_config(worker: dict = Depends(current_worker)):
    """What an agent would use: the server's current defaults, and where each step runs."""
    return {"name": worker["name"], "enabled": worker["enabled"], "defaults": live_defaults(),
            "runs_on": {k: runs_on(k) for k in workers.KINDS}}


class HeartbeatBody(BaseModel):
    info: dict | None = None
    running: list[int] = []


@router.post("/api/worker/heartbeat")
def heartbeat(body: HeartbeatBody, worker: dict = Depends(current_worker)):
    conn = db.connect()
    workers.touch(conn, worker["id"], _clean_info(body.info))
    fresh = workers.get_worker(conn, worker["id"])
    return {"cancelled": workers.heartbeat(conn, worker["id"], body.running), "enabled": fresh["enabled"],
            "defaults": live_defaults()}


@router.post("/api/worker/bye")
def bye(worker: dict = Depends(current_worker)):
    workers.goodbye(db.connect(), worker["id"])
    return {"ok": True}


class ClaimBody(BaseModel):
    kinds: list[str]
    wait: int = 20


def _payload(conn, task) -> dict | None:
    """Everything an agent needs for a task, or None after failing a task that can't be done (missing audio...)."""
    call = conn.execute("SELECT id, type, agent, customer, date_call, duration, filename, transcript, audio_path, "
                        "voice FROM calls WHERE id=?", (task["call_id"],)).fetchone()
    problem = None
    if not call:
        problem = "The call no longer exists"
    elif task["kind"] in AUDIO_KINDS and not (call["audio_path"] and Path(call["audio_path"]).exists()):
        problem = "The recording isn't downloaded on the server"
    elif task["kind"] == "analyze" and not call["transcript"]:
        problem = "The call has no transcript"
    if problem:
        workers.fail(conn, task, None, problem, retry=False)
        return None
    payload = {
        "id": task["id"], "kind": task["kind"], "attempt": task["attempts"], "defaults": live_defaults(),
        "call": {k: call[k] for k in ("id", "type", "agent", "customer", "date_call", "duration", "filename")},
    }
    if task["kind"] in AUDIO_KINDS:
        payload["audio_url"] = f"/api/worker/tasks/{task['id']}/audio"
    else:
        payload["call"]["transcript"] = call["transcript"]
        payload["call"]["voice"] = call["voice"]  # from the voice step (voice.py), if it ran
        path = settings.business_context_path
        payload["business"] = path.read_text(encoding="utf-8") if path.exists() else "(no business context provided)"
    return payload


@router.post("/api/worker/claim")
def claim(body: ClaimBody, worker: dict = Depends(current_worker)):
    """Long poll: returns a task as soon as one is waiting for this agent, or {"task": null} after `wait` seconds."""
    deadline = time.time() + min(max(body.wait, 0), MAX_WAIT)
    conn = db.connect()
    try:
        last_touch, was_seen = 0.0, worker["last_seen"] is not None
        while True:
            fresh = workers.get_worker(conn, worker["id"])
            if not fresh:
                raise HTTPException(401, "Unknown or revoked agent token")
            if was_seen and fresh["last_seen"] is None:  # the agent said goodbye while this request was waiting
                return {"task": None, "enabled": fresh["enabled"]}
            if time.time() - last_touch > 10:  # waiting counts as being alive
                workers.touch(conn, worker["id"])
                last_touch = time.time()
            # Only steps this agent says it is set up for (it may have transcription but no Claude login, or a
            # Whisper model still downloading): the rest stays queued for the host or another agent.
            kinds = [k for k in body.kinds if workers.can_run(fresh, k)]
            if fresh["enabled"] and kinds:
                while task := workers.claim(conn, fresh, kinds):
                    if payload := _payload(conn, task):
                        return {"task": payload, "enabled": True}
            if time.time() >= deadline:
                return {"task": None, "enabled": fresh["enabled"]}
            time.sleep(1)
    finally:
        conn.close()


def _owned(conn, task_id: int, worker: dict):
    task = workers.get_task(conn, task_id)
    if not task or task["status"] != "running" or task["worker_id"] != worker["id"]:
        raise HTTPException(409, "This task is no longer yours (it was cancelled or given to another agent)")
    return task


@router.get("/api/worker/tasks/{task_id}/audio")
def task_audio(task_id: int, worker: dict = Depends(current_worker)):
    conn = db.connect()
    task = _owned(conn, task_id, worker)
    call = conn.execute("SELECT audio_path, filename FROM calls WHERE id=?", (task["call_id"],)).fetchone()
    if task["kind"] not in AUDIO_KINDS or not call or not call["audio_path"] or not Path(call["audio_path"]).exists():
        raise HTTPException(404, "No audio for this task")
    return FileResponse(call["audio_path"], media_type="audio/mpeg", filename=call["filename"])


class ProgressBody(BaseModel):
    text: str


@router.post("/api/worker/tasks/{task_id}/progress")
def task_progress(task_id: int, body: ProgressBody, worker: dict = Depends(current_worker)):
    conn = db.connect()
    _owned(conn, task_id, worker)
    workers.set_progress(conn, task_id, body.text)
    return {"ok": True}


class ResultBody(BaseModel):
    transcript: str | None = None
    voice: dict | None = None
    analysis: dict | None = None
    label: str = ""


@router.post("/api/worker/tasks/{task_id}/result")
def task_result(task_id: int, body: ResultBody, worker: dict = Depends(current_worker)):
    conn = db.connect()
    task = _owned(conn, task_id, worker)
    try:
        workers.complete(conn, task, worker, body.model_dump())
    except ValueError as exc:
        workers.fail(conn, task, worker, str(exc))
        raise HTTPException(422, str(exc))
    return {"ok": True}


@router.post("/api/worker/tasks/{task_id}/release")
def task_release(task_id: int, worker: dict = Depends(current_worker)):
    conn = db.connect()
    _owned(conn, task_id, worker)
    workers.release_task(conn, task_id)
    return {"ok": True}


class FailBody(BaseModel):
    error: str
    retry: bool = True


@router.post("/api/worker/tasks/{task_id}/fail")
def task_fail(task_id: int, body: FailBody, worker: dict = Depends(current_worker)):
    conn = db.connect()
    task = _owned(conn, task_id, worker)
    workers.fail(conn, task, worker, body.error, retry=body.retry)
    return {"ok": True}


# --- Whisper models for agents ------------------------------------------------------------------
# The Tunisian Derja models are converted once with torch (a ~1 GB install) on a machine that has it, normally
# this server (Settings, Install now). Agents download the converted result from here instead of converting it
# themselves, which is what lets the installed agent app run without torch.

_pack_lock = threading.Lock()
_packing: dict[str, threading.Thread] = {}


def _pack_path(name: str) -> Path:
    return settings.data_dir / "model-packs" / f"{name}.zip"


def _pack_ready(name: str) -> bool:
    pack = _pack_path(name)
    return pack.exists() and pack.stat().st_mtime >= (model_dir(name) / "model.bin").stat().st_mtime


def _zip_folder(folder: Path, pack: Path):
    pack.parent.mkdir(parents=True, exist_ok=True)
    tmp = pack.with_name(pack.name + ".part")
    try:
        with zipfile.ZipFile(tmp, "w", zipfile.ZIP_STORED) as archive:  # the weights don't compress
            for path in sorted(folder.rglob("*")):
                if path.is_file():
                    archive.write(path, path.relative_to(folder).as_posix())
        tmp.replace(pack)
    except Exception:
        tmp.unlink(missing_ok=True)
        raise


def _build_pack(name: str):
    try:
        _zip_folder(model_dir(name), _pack_path(name))
    except Exception as exc:
        print(f"Packing {name} for agents failed: {exc}")


@router.post("/api/worker/models/{name}/prepare")
def prepare_model(name: str, worker: dict = Depends(current_worker)):
    """Start packing a converted model for download (once; later calls find it ready)."""
    if name not in DIALECT_MODELS or not is_installed(name):
        raise HTTPException(404, f"{name} isn't installed on the server (Settings, Install now)")
    if _pack_ready(name):
        return {"ready": True, "size": _pack_path(name).stat().st_size}
    with _pack_lock:
        thread = _packing.get(name)
        if not thread or not thread.is_alive():
            _packing[name] = threading.Thread(target=_build_pack, args=(name,), daemon=True)
            _packing[name].start()
    return {"ready": False}


@router.get("/api/worker/models/{name}/pack")
def model_pack(name: str, worker: dict = Depends(current_worker)):
    if name not in DIALECT_MODELS or not is_installed(name) or not _pack_ready(name):
        raise HTTPException(404, f"{name} isn't packed yet")
    return FileResponse(_pack_path(name), media_type="application/zip", filename=f"{name}.zip")


# The voice step's emotion model works the same way: converted to ONNX once here (needs torch), downloaded by agents.
# Only the server's own VOICE_MODEL is offered, so an agent can't make the server fetch arbitrary models.

class VoiceModelBody(BaseModel):
    name: str


_voice_errors: dict[str, str] = {}


def _voice_pack_path(name: str) -> Path:
    return settings.data_dir / "model-packs" / f"voice-{name.replace('/', '--')}.zip"


def _voice_pack_ready(name: str) -> bool:
    pack, onnx = _voice_pack_path(name), voice_models.model_dir(name) / "model.onnx"
    return pack.exists() and onnx.exists() and pack.stat().st_mtime >= onnx.stat().st_mtime


def _build_voice_pack(name: str):
    try:
        voice_models.install(name, lambda text: print(f"Voice model: {text}"))  # converts it if this is the first time
        _zip_folder(voice_models.model_dir(name), _voice_pack_path(name))
        _voice_errors.pop(name, None)
    except Exception as exc:
        _voice_errors[name] = str(exc)
        print(f"Preparing the voice model {name} for agents failed: {exc}")


def _served_voice_model(name: str) -> str:
    if name != (live("VOICE_MODEL") or settings.voice_model):
        raise HTTPException(404, "The server only offers the model set as VOICE_MODEL in Settings")
    return name


@router.post("/api/worker/voice-model/prepare")
def prepare_voice_model(body: VoiceModelBody, worker: dict = Depends(current_worker)):
    """Convert (once) and pack the voice model for download; later calls find it ready."""
    name = _served_voice_model(body.name)
    if _voice_pack_ready(name):
        return {"ready": True, "size": _voice_pack_path(name).stat().st_size}
    with _pack_lock:
        thread = _packing.get(f"voice:{name}")
        if not thread or not thread.is_alive():
            if error := _voice_errors.get(name):
                raise HTTPException(404, error)
            _packing[f"voice:{name}"] = threading.Thread(target=_build_voice_pack, args=(name,), daemon=True)
            _packing[f"voice:{name}"].start()
    return {"ready": False}


@router.get("/api/worker/voice-model/pack")
def voice_model_pack(name: str, worker: dict = Depends(current_worker)):
    name = _served_voice_model(name)
    if not _voice_pack_ready(name):
        raise HTTPException(404, "The voice model isn't packed yet")
    return FileResponse(_voice_pack_path(name), media_type="application/zip", filename="voice-model.zip")


# --- Admin side ---------------------------------------------------------------------------------

def _public(worker: dict, running: list[dict], stats: dict) -> dict:
    done = stats.get(worker["id"], {})
    return {
        "id": worker["id"], "name": worker["name"], "enabled": worker["enabled"], "online": worker["online"],
        "last_seen": worker["last_seen"], "created_at": worker["created_at"], "created_by": worker["created_by"],
        "info": worker["info"], "running": running,
        "done": done.get("done", 0), "failed": done.get("failed", 0),
        "ready": {k: workers.can_run(worker, k) for k in workers.KINDS},
    }


INSTALLER_NAME = re.compile(r"^[\w][\w. -]{0,150}\.(exe|msi|zip)$", re.IGNORECASE)
MAX_INSTALLER_BYTES = 4 << 30


def _downloads() -> Path:
    return settings.data_dir / "downloads"


def _installers() -> list[dict]:
    """Agent installers in the data folder (downloads/): what the Agents page offers for download."""
    folder = _downloads()
    if not folder.is_dir():
        return []
    found = []
    for f in sorted(folder.iterdir()):
        if f.is_file() and INSTALLER_NAME.match(f.name):
            version = re.search(r"-(\d+(?:\.\d+)+)\.\w+$", f.name)
            stat = f.stat()
            found.append({
                "name": f.name, "size": stat.st_size,
                "kind": "gpu" if "gpu" in f.name.lower() else "cpu",
                "version": version.group(1) if version else None,
                "modified": datetime.fromtimestamp(stat.st_mtime).replace(microsecond=0).isoformat(),
            })
    return found


@router.get("/api/workers/installers/{name}")
def download_installer(name: str):
    if name not in {i["name"] for i in _installers()}:
        raise HTTPException(404, "No such installer")
    return FileResponse(_downloads() / name, filename=name)


@router.put("/api/workers/installers/{name}")
async def upload_installer(name: str, request: Request):
    """Store an installer sent as the raw request body (streamed to disk: the GPU one is about 1 GB)."""
    if not INSTALLER_NAME.match(name):
        raise HTTPException(400, "The file must be an .exe, .msi or .zip with a plain name")
    _downloads().mkdir(parents=True, exist_ok=True)
    final = _downloads() / name
    tmp = final.with_name(final.name + ".part")
    size = 0
    try:
        with open(tmp, "wb") as fh:
            async for chunk in request.stream():
                size += len(chunk)
                if size > MAX_INSTALLER_BYTES:
                    raise HTTPException(413, "That file is too large")
                await run_in_threadpool(fh.write, chunk)
        if size == 0:
            raise HTTPException(400, "The file is empty")
        tmp.replace(final)
    finally:
        tmp.unlink(missing_ok=True)
    return {"name": name, "size": size}


@router.delete("/api/workers/installers/{name}")
def delete_installer(name: str):
    if name not in {i["name"] for i in _installers()}:
        raise HTTPException(404, "No such installer")
    (_downloads() / name).unlink()
    return {"ok": True}


@router.get("/api/workers")
def list_workers():
    """The Agents page: every agent with its live state, where each step runs, and the size of the queue."""
    conn = db.connect()
    workers.requeue_expired(conn)
    stats = workers.worker_stats(conn)
    return {
        "runs_on": {k: runs_on(k) for k in workers.KINDS},
        "queue": workers.queue_counts(conn),
        "defaults": live_defaults(),
        # For the Add agent dialog: the address agents should use, and where to get the installer.
        "public_url": live("PUBLIC_URL").rstrip("/"),
        "download_url": live("AGENT_DOWNLOAD_URL"),
        "installers": _installers(),
        # Agents that are connected first, then by name.
        "workers": [_public(w, workers.running_for(conn, w["id"]), stats)
                    for w in sorted(workers.list_workers(conn), key=lambda w: (not w["online"], w["name"].lower()))],
    }


class NewWorkerBody(BaseModel):
    name: str


@router.post("/api/workers")
def add_worker(body: NewWorkerBody, request: Request):
    try:
        worker, token = workers.create_worker(db.connect(), body.name, getattr(request.state, "user", None))
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    return {"worker": _public(worker, [], {}), "token": token}


@router.get("/api/workers/tasks")
def list_tasks(limit: int = 50):
    return workers.recent_tasks(db.connect(), max(1, min(limit, 200)))


class CancelBody(BaseModel):
    ids: list[int] | None = None


@router.post("/api/workers/tasks/cancel")
def cancel_tasks(body: CancelBody):
    """Cancel the given tasks, or every waiting and running one."""
    return {"cancelled": workers.cancel(db.connect(), ids=body.ids)}


class WorkerUpdateBody(BaseModel):
    name: str | None = None
    enabled: bool | None = None


@router.patch("/api/workers/{worker_id}")
def update_worker(worker_id: str, body: WorkerUpdateBody):
    conn = db.connect()
    if not workers.get_worker(conn, worker_id):
        raise HTTPException(404, "Agent not found")
    try:
        workers.update_worker(conn, worker_id, name=body.name, enabled=body.enabled)
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    return _public(workers.get_worker(conn, worker_id), workers.running_for(conn, worker_id), {})


@router.post("/api/workers/{worker_id}/token")
def new_token(worker_id: str):
    """Replace the agent's token. The agent has to log in again with the new one."""
    try:
        return {"token": workers.rotate_token(db.connect(), worker_id)}
    except KeyError:
        raise HTTPException(404, "Agent not found")


@router.delete("/api/workers/{worker_id}")
def remove_worker(worker_id: str):
    if not workers.delete_worker(db.connect(), worker_id):
        raise HTTPException(404, "Agent not found")
    return {"ok": True}


# --- Housekeeping -------------------------------------------------------------------------------

def janitor_loop(stop: threading.Event):
    """Puts the tasks of silent agents back in the queue, and trims the task history."""
    while not stop.wait(30):
        try:
            conn = db.connect()
            workers.requeue_expired(conn)
            conn.execute("DELETE FROM worker_tasks WHERE status IN ('done', 'failed', 'cancelled') AND id NOT IN "
                         "(SELECT id FROM worker_tasks WHERE status IN ('done', 'failed', 'cancelled') "
                         "ORDER BY id DESC LIMIT ?)", (KEEP_FINISHED_TASKS,))
            conn.commit()
            conn.close()
        except Exception as exc:  # a locked database must not end the thread
            print(f"Agent housekeeping failed: {exc}")
