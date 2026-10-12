"""HTTP API for WhatsApp quick actions (see whatsapp.py): admins set them up from the account's approved templates;
agents send them to the contact they're serving on the call desk (see AGENT_ALLOWED in server.py)."""
import json
from datetime import datetime

from fastapi import APIRouter, HTTPException, Request
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel

from .. import db, operations, whatsapp
from ..operations import OperationError

router = APIRouter()


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _action(row) -> dict:
    item = dict(row)
    item["params"] = json.loads(item["params"]) if item["params"] else {}
    return item


def _actions(conn) -> list[dict]:
    return [_action(r) for r in conn.execute("SELECT * FROM wa_actions ORDER BY position, id")]


@router.get("/api/whatsapp/actions")
def list_actions():
    """The quick actions, for the desk's buttons and the admin's editor."""
    return {"configured": whatsapp.is_configured(), "actions": _actions(db.connect()),
            "sources": whatsapp.SOURCES}


@router.get("/api/whatsapp/templates")
async def list_templates(refresh: bool = False):
    if not whatsapp.is_configured():
        return {"configured": False, "templates": []}
    try:
        return {"configured": True, "templates": await run_in_threadpool(whatsapp.templates, refresh)}
    except whatsapp.WhatsAppError as exc:
        raise HTTPException(502, str(exc))


class ActionBody(BaseModel):
    label: str
    template: str
    language: str
    params: dict[str, str] = {}
    header_link: str = ""
    header_filename: str = ""


def _clean(body: ActionBody) -> tuple:
    label = " ".join(body.label.split())[:60]
    if not label or not body.template or not body.language:
        raise HTTPException(400, "Give the action a name and pick a template")
    for value in body.params.values():
        if value not in whatsapp.SOURCES and not (value.startswith("text:") and value[5:].strip()):
            raise HTTPException(400, "Fill every variable of the template")
    link = body.header_link.strip()
    if link and not link.startswith("https://"):
        raise HTTPException(400, "The file link must be a public https:// address")
    return (label, body.template, body.language, json.dumps(body.params, ensure_ascii=False), link or None,
            body.header_filename.strip()[:100] or None)


@router.post("/api/whatsapp/actions")
def create_action(body: ActionBody):
    conn = db.connect()
    position = conn.execute("SELECT COALESCE(MAX(position), 0) + 1 FROM wa_actions").fetchone()[0]
    cur = conn.execute("INSERT INTO wa_actions (label, template, language, params, header_link, header_filename, "
                       "position, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)", (*_clean(body), position, _now()))
    conn.commit()
    return _action(conn.execute("SELECT * FROM wa_actions WHERE id = ?", (cur.lastrowid,)).fetchone())


@router.put("/api/whatsapp/actions/{action_id}")
def update_action(action_id: int, body: ActionBody):
    conn = db.connect()
    cur = conn.execute("UPDATE wa_actions SET label = ?, template = ?, language = ?, params = ?, header_link = ?, "
                       "header_filename = ? WHERE id = ?", (*_clean(body), action_id))
    if not cur.rowcount:
        raise HTTPException(404, "Not found")
    conn.commit()
    return _action(conn.execute("SELECT * FROM wa_actions WHERE id = ?", (action_id,)).fetchone())


class OrderBody(BaseModel):
    ids: list[int]


@router.put("/api/whatsapp/actions")
def reorder_actions(body: OrderBody):
    conn = db.connect()
    conn.executemany("UPDATE wa_actions SET position = ? WHERE id = ?", [(i, a) for i, a in enumerate(body.ids)])
    conn.commit()
    return {"actions": _actions(conn)}


@router.delete("/api/whatsapp/actions/{action_id}")
def delete_action(action_id: int):
    conn = db.connect()
    conn.execute("DELETE FROM wa_actions WHERE id = ?", (action_id,))
    conn.commit()
    return {"ok": True}


# --- From the call desk ------------------------------------------------------------------------------

def _messages(conn, op_id: int) -> list[dict]:
    return [dict(r) for r in conn.execute("SELECT * FROM wa_messages WHERE op_id = ? ORDER BY id", (op_id,))]


@router.get("/api/operations/{op_id}/whatsapp")
def sent_messages(op_id: int, request: Request):
    conn = db.connect()
    row = conn.execute("SELECT agent FROM op_calls WHERE id = ?", (op_id,)).fetchone()
    if not row or (row[0] != request.state.user and request.state.account["role"] != "admin"):
        raise HTTPException(404, "Not found")
    return _messages(conn, op_id)


class SendBody(BaseModel):
    action_id: int
    phone: str


def _value(source: str, lead: dict, agent_name: str) -> str:
    if source.startswith("text:"):
        return source[5:]
    return {"contact_name": (lead.get("contact") or {}).get("name") or lead.get("name") or "",
            "agent_name": agent_name, "lead_name": lead.get("name") or ""}.get(source, "")


def send(op_id: int, username: str, action_id: int, phone: str) -> dict:
    """Send a quick action to the contact the agent is serving, and log it (failed ones too)."""
    conn = db.connect()
    try:
        row = operations._own_open(conn, op_id, username)
    except OperationError as exc:
        raise HTTPException(exc.status, str(exc))
    action = conn.execute("SELECT * FROM wa_actions WHERE id = ?", (action_id,)).fetchone()
    if not action:
        raise HTTPException(404, "This quick action was removed")
    lead = json.loads(row["lead"]) if row["lead"] else {}
    if phone not in ((lead.get("contact") or {}).get("phones") or []):
        raise HTTPException(400, "Send it to one of the contact's numbers")
    if not whatsapp.is_configured():
        raise HTTPException(400, "WhatsApp isn't set up yet: an admin needs to fill the WhatsApp settings")
    agent_name = operations.account_names(conn).get(username, username)
    params = json.loads(action["params"]) if action["params"] else {}
    status, wa_id, error = "sent", None, None
    try:
        template = whatsapp.find_template(action["template"], action["language"])
        values = {v: _value(params.get(v, ""), lead, agent_name) for v in template["variables"]}
        wa_id = whatsapp.send_template(phone, template, values, action["header_link"] or "",
                                       action["header_filename"] or "")
    except whatsapp.WhatsAppError as exc:
        status, error = "failed", str(exc)
    conn.execute("INSERT INTO wa_messages (op_id, action_id, label, template, to_number, status, wa_message_id, "
                 "error, sent_by, sent_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                 (op_id, action_id, action["label"], action["template"], phone, status, wa_id, error, username,
                  _now()))
    conn.commit()
    if error:
        raise HTTPException(502, error)
    return {"messages": _messages(conn, op_id)}


@router.post("/api/operations/{op_id}/whatsapp")
async def send_action(op_id: int, body: SendBody, request: Request):
    return await run_in_threadpool(send, op_id, request.state.user, body.action_id, body.phone)
