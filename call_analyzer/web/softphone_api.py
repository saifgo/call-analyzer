"""HTTP API for the browser softphone (see softphone.py).

Every account reads its own SIP sign-in (/api/softphone); only admins set extensions and GoVoice logins (see AGENT_ALLOWED in server.py).
"""
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from .. import auth, softphone

router = APIRouter()


@router.get("/api/softphone")
def get_own(request: Request):
    account = request.state.account
    return softphone.client_config(account["username"], account["display_name"])


@router.get("/api/softphones")
def list_extensions():
    return softphone.extensions()


class SoftphoneBody(BaseModel):
    extension: str
    govoice_user: str  # the GoVoice account (e.g. user100) whose SIP password is fetched
    account_password: str | None = None  # its GoVoice password; empty: keep the saved one


@router.put("/api/softphones/{username}")
def set_extension(username: str, body: SoftphoneBody):
    if not auth.user_exists(username):
        raise HTTPException(404, "User not found")
    try:
        softphone.save(username, body.extension, body.govoice_user, body.account_password)
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    return {"ok": True}


@router.delete("/api/softphones/{username}")
def remove_extension(username: str):
    softphone.remove(username)
    return {"ok": True}
