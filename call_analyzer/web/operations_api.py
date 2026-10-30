"""HTTP API for the Operations call desk (see operations.py).

Agents and admins work the desk (/api/operations/desk, next, call...) and see their own KPIs; only admins see the
team board, everyone's KPIs and the outcome / AI score insights, edit campaigns, and can give a contact back to the
queue or retry writing a call to the CRM (see AGENT_ALLOWED in server.py).
"""
from datetime import date, datetime, timedelta

from fastapi import APIRouter, HTTPException, Request
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel

from .. import alerts, breaks, campaigns, db, desk_stats, floor, idle, inbound, operations
from ..campaigns import CampaignError
from ..floor import FloorError
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
    """The agent's desk, polled every few seconds: whether they're ready (or why they paused), the contact they
    hold, their callbacks, today's figures against their targets, and the prompt to call when they've been idle too
    long (see idle.py), where they stand toward their next earned break (see breaks.py), and the missed calls
    waiting to be called back (see inbound.py)."""
    user = request.state.user
    conn = db.connect()
    try:
        operations.release_stale(conn)
        ready = operations.heartbeat(conn, user)
        missed = inbound.missed(conn)
        row = operations.current(conn, user)
        names = operations.account_names(conn)
        campaign = operations.agent_campaign(conn, user)
        today = operations.today(conn, user)
        idle_prompt = idle.check(conn, user)
        return {"ready": ready, "idle_prompt": idle_prompt,
                "current": operations.to_dict(row, names) if row else None,
                "campaign_id": campaign["id"], "today": today, "goals": operations.goals(conn, user, today),
                "pause": None if ready else floor.pause_state(conn, user), "pause_reasons": floor.reasons(conn),
                "shift": floor.shift_state(conn, user), "clock_out_at": floor.clock_out_at(conn, datetime.now())
                .isoformat(timespec="seconds"),
                "earned_break": breaks.state(conn, user), "missed": missed,
                "callbacks": operations.my_callbacks(conn, user), "queue": operations.queue_counts(conn, campaign)}
    finally:
        conn.close()


# --- Incoming calls (see inbound.py): the agent's softphone says when one rings, is answered and ends ---------------

class RingBody(BaseModel):
    number: str
    name: str = ""


@router.post("/api/inbound")
async def inbound_ring(body: RingBody, request: Request):
    """A call rings the agent's softphone: logged, and who's calling."""
    try:
        return await run_in_threadpool(inbound.ring, request.state.user, body.number, body.name)
    except OperationError as exc:
        _fail(exc)


@router.post("/api/inbound/busy")
def inbound_busy(body: RingBody, request: Request):
    """A call was turned away because the agent was on another one (a missed call)."""
    try:
        return inbound.busy(request.state.user, body.number, body.name)
    except OperationError as exc:
        _fail(exc)


@router.post("/api/inbound/{inbound_id}/answer")
async def inbound_answer(inbound_id: int, request: Request):
    """The agent picked up: the desk call opened for the caller."""
    try:
        return {"current": await run_in_threadpool(inbound.answer, request.state.user, inbound_id)}
    except OperationError as exc:
        _fail(exc)


class InboundEndBody(BaseModel):
    answered: bool
    declined: bool = False  # the agent turned it down
    elsewhere: bool = False  # another phone picked it up


@router.post("/api/inbound/{inbound_id}/end")
def inbound_end(inbound_id: int, body: InboundEndBody, request: Request):
    try:
        inbound.end(request.state.user, inbound_id, answered=body.answered, declined=body.declined,
                    elsewhere=body.elsewhere)
    except OperationError as exc:
        _fail(exc)
    return {"ok": True}


@router.post("/api/operations/missed/{key}/take")
async def take_missed(key: str, request: Request):
    """The agent calls this missed call back now."""
    try:
        return {"current": await run_in_threadpool(inbound.take, request.state.user, key)}
    except OperationError as exc:
        _fail(exc)


@router.post("/api/operations/missed/{key}/dismiss")
def dismiss_missed(key: str, request: Request):
    """Nobody needs to call this number back (spam, dealt with elsewhere)."""
    try:
        inbound.dismiss(request.state.user, key)
    except OperationError as exc:
        _fail(exc)
    return {"ok": True}


class LinkBody(BaseModel):
    opportunity_id: str | None = None  # one of the caller's opportunities
    person_id: str | None = None  # their CRM contact: a new opportunity for them
    name: str = ""  # else a new contact
    city: str = ""
    email: str = ""


@router.post("/api/operations/{op_id}/link")
async def link_call(op_id: int, body: LinkBody, request: Request):
    """Link a call that came in to the caller's CRM contact or opportunity (adding them when they aren't in it)."""
    try:
        return await run_in_threadpool(lambda: operations.link(
            op_id, request.state.user, opportunity_id=body.opportunity_id, person_id=body.person_id, name=body.name,
            city=body.city, email=body.email))
    except OperationError as exc:
        _fail(exc)


@router.post("/api/operations/idle-prompt/{prompt_id}/seen")
def idle_prompt_seen(prompt_id: int, request: Request):
    """The agent dismissed the prompt to call (it's still logged; it comes back if they stay idle)."""
    idle.acknowledge(db.connect(), request.state.user, prompt_id)
    return {"ok": True}


@router.post("/api/operations/earned-break")
def take_earned_break(request: Request):
    """The agent takes the break they earned by closing enough calls: they pause for it."""
    conn = db.connect()
    try:
        breaks.take(conn, request.state.user)
    except FloorError as exc:
        conn.rollback()
        raise HTTPException(409, str(exc))
    return {"ok": True}


@router.post("/api/operations/clock-in")
def clock_in(request: Request):
    """The agent starts their shift."""
    operations.clock_in(db.connect(), request.state.user)
    return {"ok": True}


@router.post("/api/operations/clock-out")
def clock_out(request: Request):
    """The agent ends their shift: they stop taking calls and the pause they're on ends."""
    try:
        operations.clock_out(db.connect(), request.state.user)
    except OperationError as exc:
        _fail(exc)
    return {"ok": True}


@router.post("/api/operations/agents/{username}/clock-out")
def clock_out_agent(username: str):
    """An admin clocks an agent out (from the team board), e.g. one who left without doing it."""
    try:
        operations.clock_out(db.connect(), username, by="admin")
    except OperationError as exc:
        _fail(exc)
    return {"ok": True}


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
    reason_id: int | None = None  # why the agent pauses (see floor.py)


@router.post("/api/operations/ready")
def set_ready(body: ReadyBody, request: Request):
    try:
        operations.set_ready(db.connect(), request.state.user, body.ready, body.reason_id)
    except OperationError as exc:
        _fail(exc)
    return {"ok": True, "ready": body.ready}


@router.post("/api/operations/next")
async def next_contact(request: Request):
    """Serve the agent their next contact (or the one they already hold). Only while they're ready."""
    user = request.state.user
    def ready() -> bool:  # in a worker thread: a database write on the event loop would hold up every request
        conn = db.connect()
        return bool(operations.heartbeat(conn, user) or operations.current(conn, user))

    if not await run_in_threadpool(ready):
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


@router.post("/api/operations/callbacks/{op_id}/take")
def take_callback(op_id: int, request: Request):
    """The agent calls this callback now, before it's due."""
    try:
        return {"current": operations.take_callback(request.state.user, op_id)}
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

    def figures():
        conn = db.connect()
        found = desk_stats.kpis(conn, since or None, until or None, username=username, campaign_id=campaign_id)
        found["inbound"] = inbound.stats(conn, found["since"], found["until"], username)
        return found
    return await run_in_threadpool(figures)


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


@router.get("/api/operations/targets")
def get_targets():
    """Daily targets (team and per agent), the workday, the pause reasons, and the accounts to set targets for."""
    conn = db.connect()
    users = [{"username": r[0], "name": r[1] or r[0], "role": r[2]}
             for r in conn.execute("SELECT username, display_name, role FROM users ORDER BY username")]
    return {**floor.targets(conn), "pause_reasons": floor.reasons(conn), "users": users}


class TargetsBody(BaseModel):
    team: dict = {}
    agents: dict = {}
    workday: dict = {}
    pause_reasons: list[dict] | None = None


@router.put("/api/operations/targets")
def save_targets(body: TargetsBody):
    conn = db.connect()
    try:
        if body.pause_reasons is not None:
            floor.save_reasons(conn, body.pause_reasons)
        floor.save_targets(conn, {"team": body.team, "agents": body.agents, "workday": body.workday})
    except FloorError as exc:
        conn.rollback()
        raise HTTPException(400, str(exc))
    return get_targets()


@router.get("/api/operations/board")
def get_board():
    conn = db.connect()
    operations.release_stale(conn)
    today = date.today()
    return {**operations.board(conn), "missed": inbound.missed(conn),
            "inbound_today": inbound.stats(conn, today.isoformat(), (today + timedelta(days=1)).isoformat())["team"]}


@router.get("/api/operations/alerts")
def get_alerts():
    """What needs a supervisor's eye on the desk right now (see alerts.py); every admin page polls it."""
    return {"alerts": alerts.current(db.connect())}


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
