"""HTTP API for the Operations call desk (see operations.py).

Agents and admins work the desk (/api/operations/desk, next, call...) and see their own KPIs; only admins see the
team board, everyone's KPIs and the outcome / AI score insights, edit campaigns, and can give a contact back to the
queue or retry writing a call to the CRM (see AGENT_ALLOWED in server.py).
"""
from fastapi import APIRouter, HTTPException, Request
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel

from .. import campaigns, db, desk_stats, operations
from ..campaigns import CampaignError
from ..operations import OperationError

router = APIRouter()


def _fail(exc: OperationError):
    raise HTTPException(exc.status, str(exc))


def _is_admin(request: Request) -> bool:
    return request.state.account["role"] == "admin"


@router.get("/api/operations/config")
def get_config():
    return operations.config()


@router.get("/api/operations/desk")
def get_desk(request: Request):
    """The agent's desk, polled every few seconds: whether they're ready, the contact they hold, their callbacks."""
    user = request.state.user
    conn = db.connect()
    operations.release_stale(conn)
    ready = operations.heartbeat(conn, user)
    row = operations.current(conn, user)
    names = operations.account_names(conn)
    campaign = operations.agent_campaign(conn, user)
    return {"ready": ready, "current": operations.to_dict(row, names) if row else None,
            "campaign_id": campaign["id"], "today": operations.today(conn, user),
            "callbacks": operations.my_callbacks(conn, user), "queue": operations.queue_counts(conn, campaign)}


class CampaignChoice(BaseModel):
    campaign_id: int


@router.post("/api/operations/campaign")
def choose_campaign(body: CampaignChoice, request: Request):
    """The campaign the agent works: its queue, questions and outcomes. A contact they hold stays theirs."""
    try:
        campaign = operations.set_campaign(db.connect(), request.state.user, body.campaign_id)
    except OperationError as exc:
        _fail(exc)
    return {"ok": True, "campaign_id": campaign["id"]}


class ReadyBody(BaseModel):
    ready: bool


@router.post("/api/operations/ready")
def set_ready(body: ReadyBody, request: Request):
    operations.set_ready(db.connect(), request.state.user, body.ready)
    return {"ok": True, "ready": body.ready}


@router.post("/api/operations/next")
async def next_contact(request: Request):
    """Serve the agent their next contact (or the one they already hold). Only while they're ready."""
    user = request.state.user
    conn = db.connect()
    if not operations.heartbeat(conn, user) and not operations.current(conn, user):
        raise HTTPException(409, "You're paused: start taking calls first")
    op, reason = await run_in_threadpool(operations.claim_next, user)
    return {"current": op, "reason": reason}


@router.get("/api/operations/lookup")
async def lookup(phone: str):
    """The CRM's contacts with this number, to call one of them or add a new one."""
    try:
        return await run_in_threadpool(operations.lookup, phone)
    except OperationError as exc:
        _fail(exc)


class LeadBody(BaseModel):
    name: str
    phone: str = ""
    city: str = ""
    email: str = ""
    person_id: str | None = None
    call: bool = True


@router.post("/api/operations/leads")
async def create_lead(body: LeadBody, request: Request):
    """Add a contact (or a new opportunity for one) to the CRM, then call them now or leave them in the queue."""
    try:
        opportunity_id = await run_in_threadpool(
            operations.create_lead, request.state.user, phone=body.phone, name=body.name, city=body.city, email=body.email,
            person_id=body.person_id)
        current = (await run_in_threadpool(operations.start_direct, request.state.user, opportunity_id)
                   if body.call else None)
    except OperationError as exc:
        _fail(exc)
    return {"opportunity_id": opportunity_id, "current": current}


class DirectBody(BaseModel):
    opportunity_id: str


@router.post("/api/operations/direct")
async def start_direct(body: DirectBody, request: Request):
    """Call a CRM opportunity of the agent's choosing, outside the queue."""
    try:
        return {"current": await run_in_threadpool(operations.start_direct, request.state.user, body.opportunity_id)}
    except OperationError as exc:
        _fail(exc)


class TestBody(BaseModel):
    phone: str
    name: str = ""


@router.post("/api/operations/test")
def start_test(body: TestBody, request: Request):
    """Serve the agent a made-up contact to try the desk with; nothing about it is written to the CRM."""
    try:
        return {"current": operations.start_test(request.state.user, body.phone, body.name)}
    except OperationError as exc:
        _fail(exc)


@router.get("/api/operations/{op_id}/context")
def get_context(op_id: int, request: Request):
    conn = db.connect()
    try:
        row = operations.get_row(conn, op_id)
    except OperationError as exc:
        _fail(exc)
    if row["agent"] != request.state.user and not _is_admin(request):
        raise HTTPException(404, "Not found")
    return operations.context(conn, row)


class CallBody(BaseModel):
    phone: str | None = None  # the number dialed, when the contact has several


@router.post("/api/operations/{op_id}/call")
def start_call(op_id: int, request: Request, body: CallBody | None = None):
    """The agent dials the contact."""
    try:
        return operations.start_call(op_id, request.state.user, body.phone if body else None)
    except OperationError as exc:
        _fail(exc)


@router.post("/api/operations/{op_id}/give-back")
def give_back(op_id: int, request: Request):
    """The agent won't call the contact they were served: back to the queue, for someone else."""
    try:
        operations.give_back(op_id, request.state.user)
    except OperationError as exc:
        _fail(exc)
    return {"ok": True}


@router.post("/api/operations/{op_id}/end")
def end_call(op_id: int, request: Request):
    try:
        return operations.end_call(op_id, request.state.user)
    except OperationError as exc:
        _fail(exc)


class AnswersBody(BaseModel):
    answers: dict


@router.put("/api/operations/{op_id}/answers")
def save_answers(op_id: int, body: AnswersBody, request: Request):
    try:
        operations.save_answers(op_id, request.state.user, body.answers)
    except OperationError as exc:
        _fail(exc)
    return {"ok": True}


class FinishBody(BaseModel):
    answers: dict = {}
    outcome: str
    note: str = ""
    stage: str | None = None
    callback_at: str | None = None
    callback_note: str = ""
    callback_mine: bool = False


@router.post("/api/operations/{op_id}/finish")
async def finish_call(op_id: int, body: FinishBody, request: Request):
    try:
        return await run_in_threadpool(
            operations.finish, op_id, request.state.user, answers=body.answers, outcome=body.outcome,
            note=body.note, stage=body.stage, callback_at=body.callback_at, callback_note=body.callback_note,
            callback_mine=body.callback_mine)
    except OperationError as exc:
        _fail(exc)


@router.delete("/api/operations/callbacks/{op_id}")
def cancel_callback(op_id: int, request: Request):
    try:
        operations.cancel_callback(db.connect(), op_id, request.state.user, _is_admin(request))
    except OperationError as exc:
        _fail(exc)
    return {"ok": True}


@router.get("/api/operations/kpis")
async def get_kpis(request: Request, since: str = "", until: str = "", campaign_id: int | None = None):
    """Agent KPIs between two days (until exclusive; today by default). Agents only get their own."""
    username = None if _is_admin(request) else request.state.user
    return await run_in_threadpool(lambda: desk_stats.kpis(db.connect(), since or None, until or None,
                                                           username=username, campaign_id=campaign_id))


# --- Admins -----------------------------------------------------------------------------------------

@router.get("/api/operations/insights")
async def get_insights(since: str = "", until: str = "", campaign_id: int | None = None):
    """How desk outcomes line up with the AI's scores of the same recorded calls."""
    return await run_in_threadpool(lambda: desk_stats.insights(db.connect(), since or None, until or None,
                                                               campaign_id=campaign_id))


@router.post("/api/operations/campaigns")
def create_campaign(body: dict):
    try:
        return campaigns.save(db.connect(), None, body)
    except CampaignError as exc:
        raise HTTPException(400, str(exc))


@router.put("/api/operations/campaigns/{campaign_id}")
def update_campaign(campaign_id: int, body: dict):
    try:
        return campaigns.save(db.connect(), campaign_id, body)
    except CampaignError as exc:
        raise HTTPException(400, str(exc))


@router.delete("/api/operations/campaigns/{campaign_id}")
def delete_campaign(campaign_id: int):
    """Deletes a campaign never called from; one with calls is archived (stops being served, history kept)."""
    try:
        return {"result": campaigns.delete(db.connect(), campaign_id)}
    except CampaignError as exc:
        raise HTTPException(400, str(exc))


@router.get("/api/operations/board")
def get_board():
    conn = db.connect()
    operations.release_stale(conn)
    return operations.board(conn)


@router.post("/api/operations/{op_id}/release")
def release(op_id: int):
    try:
        operations.release(db.connect(), op_id)
    except OperationError as exc:
        _fail(exc)
    return {"ok": True}


@router.post("/api/operations/{op_id}/sync")
async def retry_sync(op_id: int):
    conn = db.connect()
    try:
        row = operations.get_row(conn, op_id)
    except OperationError as exc:
        _fail(exc)
    if row["status"] != "done":
        raise HTTPException(400, "Only finished calls are written to the CRM")
    await run_in_threadpool(operations.sync_crm, op_id)
    return operations.to_dict(operations.get_row(conn, op_id), operations.account_names(conn))
