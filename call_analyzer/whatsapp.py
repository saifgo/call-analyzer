"""Send WhatsApp messages to contacts through the WhatsApp Cloud API (Meta's Graph API).

A business may only start a conversation with an approved message template (free text is allowed only within 24
hours of the customer writing to us), so the call desk's quick actions are templates: an admin picks an approved
template, says what fills its variables (the contact's name, the agent's name, fixed text) and, for a template with
a document/image/video header, which file to send (a public link, e.g. the price list PDF).
"""
import logging
import os
import re
import threading
import time

import requests
from dotenv import dotenv_values

from .config import ENV_PATH

GRAPH_URL = "https://graph.facebook.com"
DEFAULT_API_VERSION = "v23.0"
TIMEOUT = 20
TEMPLATES_CACHE_SECONDS = 300
MEDIA_HEADERS = ("DOCUMENT", "IMAGE", "VIDEO")
# What can fill a template variable; "text:<value>" is a fixed text.
SOURCES = {"contact_name": "Contact's name", "agent_name": "Agent's name", "lead_name": "Opportunity name"}

_templates_cache: tuple[float, list[dict]] | None = None
_cache_lock = threading.Lock()


_resolved_waba: dict[str, str] = {}  # WHATSAPP_BUSINESS_ACCOUNT_ID as set -> the WhatsApp Business Account found

log = logging.getLogger(__name__)


class WhatsAppError(Exception):
    """The Cloud API refused or couldn't be reached; the message is meant to be shown to the user."""

    def __init__(self, message: str, code: int | None = None):
        super().__init__(message)
        self.code = code


def _setting(key: str, default: str = "") -> str:
    """The value as saved in .env right now (so Settings edits apply without a restart), else the environment."""
    return (dotenv_values(ENV_PATH).get(key) or os.environ.get(key) or default).strip()


def _config() -> dict:
    return {"token": _setting("WHATSAPP_TOKEN"), "phone_id": _setting("WHATSAPP_PHONE_NUMBER_ID"),
            "waba_id": _setting("WHATSAPP_BUSINESS_ACCOUNT_ID"),
            "version": _setting("WHATSAPP_API_VERSION", DEFAULT_API_VERSION)}


def is_configured() -> bool:
    c = _config()
    return bool(c["token"] and c["phone_id"] and c["waba_id"])


def _request(method: str, path: str, **kwargs) -> dict:
    c = _config()
    try:
        res = requests.request(method, f"{GRAPH_URL}/{c['version']}/{path}", timeout=TIMEOUT,
                               headers={"Authorization": f"Bearer {c['token']}"}, **kwargs)
    except requests.RequestException as exc:
        raise WhatsAppError(f"Couldn't reach WhatsApp: {exc.__class__.__name__}") from exc
    try:
        body = res.json()
    except ValueError:
        body = {}
    if not res.ok:
        err = body.get("error") or {}
        detail = (err.get("error_data") or {}).get("details") or ""
        message = err.get("message") or f"WhatsApp answered {res.status_code}"
        if err.get("code") == 190:
            message = "WhatsApp rejected the access token (WHATSAPP_TOKEN in Settings): it may have expired"
        raise WhatsAppError(f"{message}{f' ({detail})' if detail and detail not in message else ''}",
                            err.get("code"))
    return body


def _find_waba(c: dict) -> str | None:
    """The WhatsApp Business Account to use when WHATSAPP_BUSINESS_ACCOUNT_ID isn't one (usually it's the Business
    portfolio's ID): the portfolio's WhatsApp accounts, and those the token was granted, the one that has the phone
    number preferred."""
    candidates = []
    for edge in ("owned_whatsapp_business_accounts", "client_whatsapp_business_accounts"):
        try:
            body = _request("GET", f"{c['waba_id']}/{edge}", params={"fields": "id", "limit": 100})
        except WhatsAppError:
            continue
        candidates += [w.get("id") for w in body.get("data") or []]
    try:
        body = _request("GET", "debug_token", params={"input_token": c["token"]})
        for scope in (body.get("data") or {}).get("granular_scopes") or []:
            if str(scope.get("scope", "")).startswith("whatsapp_business"):
                candidates += scope.get("target_ids") or []
    except WhatsAppError:
        pass
    candidates = list(dict.fromkeys(str(w) for w in candidates if w and str(w) != c["waba_id"]))
    for waba in candidates:
        try:
            body = _request("GET", f"{waba}/phone_numbers", params={"fields": "id", "limit": 100})
        except WhatsAppError:
            continue
        if any(str(p.get("id")) == c["phone_id"] for p in body.get("data") or []):
            return waba
    return candidates[0] if len(candidates) == 1 else None


def _templates_page(params: dict) -> dict:
    c = _config()
    waba = _resolved_waba.get(c["waba_id"], c["waba_id"])
    try:
        return _request("GET", f"{waba}/message_templates", params=params)
    except WhatsAppError as exc:
        # (#100) "Tried accessing nonexisting field (message_templates)": the ID isn't a WhatsApp Business Account.
        if exc.code != 100 or waba != c["waba_id"]:
            raise
        found = _find_waba(c)
        if not found:
            raise WhatsAppError(
                f"WHATSAPP_BUSINESS_ACCOUNT_ID ({c['waba_id']}) isn't a WhatsApp Business Account ID: it's probably "
                "the Business portfolio's ID. Put the \"WhatsApp Business Account ID\" shown under the phone number "
                "on the app's WhatsApp > API Setup page (or in Business Settings > Accounts > WhatsApp accounts) in "
                "Settings", 100) from exc
        log.warning("WHATSAPP_BUSINESS_ACCOUNT_ID %s isn't a WhatsApp Business Account; using %s, which has the "
                    "phone number. Set it to %s in Settings.", c["waba_id"], found, found)
        _resolved_waba[c["waba_id"]] = found
        return _request("GET", f"{found}/message_templates", params=params)


def to_wa_number(number: str) -> str | None:
    """The number as the Cloud API wants it (country code and digits, no +): Tunisian 8-digit numbers get 216."""
    digits = re.sub(r"\D", "", number or "")
    if number.strip().startswith("00") or digits.startswith("00"):
        digits = digits.lstrip("0")
    if len(digits) == 8:
        digits = "216" + digits
    return digits if len(digits) >= 10 else None


def _vars(text: str | None) -> list[str]:
    """The template's variables in order of appearance: ["1", "2"] or named ones like ["customer_name"]."""
    seen = []
    for v in re.findall(r"\{\{\s*(\w+)\s*\}\}", text or ""):
        if v not in seen:
            seen.append(v)
    return seen


def _template(rec: dict) -> dict:
    """A template reduced to what the desk needs: its texts, header type, and the variables to fill."""
    header, body, footer, buttons = {}, {}, {}, []
    for comp in rec.get("components") or []:
        kind = comp.get("type")
        if kind == "HEADER":
            header = comp
        elif kind == "BODY":
            body = comp
        elif kind == "FOOTER":
            footer = comp
        elif kind == "BUTTONS":
            buttons = comp.get("buttons") or []
    fmt = header.get("format")
    variables = [f"header.{v}" for v in (_vars(header.get("text")) if fmt == "TEXT" else [])]
    variables += [f"body.{v}" for v in _vars(body.get("text"))]
    variables += [f"button.{i}.{v}" for i, b in enumerate(buttons) if b.get("type") == "URL" for v in _vars(b.get("url"))]
    return {"name": rec["name"], "language": rec.get("language"), "category": rec.get("category"),
            "status": rec.get("status"), "named": rec.get("parameter_format") == "NAMED",
            "header_format": fmt, "header_text": header.get("text") if fmt == "TEXT" else None,
            "body": body.get("text") or "", "footer": footer.get("text"),
            "buttons": [{"type": b.get("type"), "text": b.get("text"), "url": b.get("url")} for b in buttons],
            "variables": variables}


def templates(refresh: bool = False) -> list[dict]:
    """The account's approved templates (see _template). Cached for a few minutes. Raises WhatsAppError."""
    global _templates_cache
    with _cache_lock:
        cached = _templates_cache
    if cached and not refresh and time.time() - cached[0] < TEMPLATES_CACHE_SECONDS:
        return cached[1]
    found, after = [], None
    while True:
        params = {"limit": 100, "status": "APPROVED",
                  "fields": "name,language,status,category,components,parameter_format"}
        if after:
            params["after"] = after
        body = _templates_page(params)
        found += [_template(r) for r in body.get("data") or []]
        after = ((body.get("paging") or {}).get("cursors") or {}).get("after")
        if not after or not (body.get("paging") or {}).get("next") or len(found) >= 1000:
            break
    found.sort(key=lambda t: (t["name"], t["language"] or ""))
    with _cache_lock:
        _templates_cache = (time.time(), found)
    return found


def find_template(name: str, language: str) -> dict:
    for refresh in (False, True):
        for t in templates(refresh=refresh):
            if t["name"] == name and t["language"] == language:
                return t
    raise WhatsAppError(f"The template {name} ({language}) isn't approved on the WhatsApp account anymore")


def send_template(to: str, template: dict, values: dict[str, str], header_link: str = "",
                  header_filename: str = "") -> str:
    """Send `template` to `to`, its variables filled from `values` ({"body.1": "Ali", ...}). Returns the message
    id. Raises WhatsAppError."""
    number = to_wa_number(to)
    if not number:
        raise WhatsAppError(f"{to} isn't a full phone number")
    missing = [v for v in template["variables"] if not str(values.get(v) or "").strip()]
    if missing:
        raise WhatsAppError(f"Nothing to put in {', '.join(missing)}")

    def param(key: str) -> dict:
        p = {"type": "text", "text": str(values[key]).strip()[:1000]}
        if template["named"]:
            p["parameter_name"] = key.rsplit(".", 1)[1]
        return p

    components = []
    fmt = template["header_format"]
    if fmt in MEDIA_HEADERS:
        if not header_link:
            raise WhatsAppError("This template sends a file: set its link in Settings > WhatsApp quick actions")
        media = {"link": header_link}
        if fmt == "DOCUMENT" and header_filename:
            media["filename"] = header_filename
        components.append({"type": "header", "parameters": [{"type": fmt.lower(), fmt.lower(): media}]})
    header_vars = [v for v in template["variables"] if v.startswith("header.")]
    if header_vars:
        components.append({"type": "header", "parameters": [param(v) for v in header_vars]})
    body_vars = [v for v in template["variables"] if v.startswith("body.")]
    if body_vars:
        components.append({"type": "body", "parameters": [param(v) for v in body_vars]})
    for index in sorted({v.split(".")[1] for v in template["variables"] if v.startswith("button.")}, key=int):
        keys = [v for v in template["variables"] if v.startswith(f"button.{index}.")]
        components.append({"type": "button", "sub_type": "url", "index": index,
                           "parameters": [{"type": "text", "text": str(values[k]).strip()} for k in keys]})

    payload = {"messaging_product": "whatsapp", "recipient_type": "individual", "to": number, "type": "template",
               "template": {"name": template["name"], "language": {"code": template["language"]},
                            "components": components}}
    body = _request("POST", f"{_config()['phone_id']}/messages", json=payload)
    messages = body.get("messages") or [{}]
    return messages[0].get("id") or ""
