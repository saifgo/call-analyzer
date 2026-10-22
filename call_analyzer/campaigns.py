"""Call desk campaigns: each one is a queue (the CRM opportunities at some stages), the questions agents ask on its
calls, the ways those calls can end, and its rules: how many unanswered calls before giving up, when to try again,
and the hours the queue is served. Admins edit them on Operations > Campaigns; agents pick the one they work.

The first campaign is created from DEFAULT_QUESTIONS and DEFAULT_OUTCOMES (what the desk asked before campaigns
existed), and the calls made before then belong to it.

One more campaign, "Incoming calls" (kind inbound, made from INBOUND_QUESTIONS and INBOUND_OUTCOMES), is for the calls
customers make to us and our callbacks of the ones we missed (see inbound.py). It has no queue, no calling hours and
no limit on tries: agents don't pick it, and it can't be deleted. Admins edit its questions and outcomes like the
others'.
"""
import json
import re
from datetime import datetime, timedelta

from . import crm

# What the agent asks during the call. Types: select, multi, number, text, textarea, boolean. `show_if` shows a
# question only when another answer is one of the values. `crm` copies the answer to that field of the contact.
DEFAULT_QUESTIONS = [
    {"key": "business_type", "section": "Who they are", "label": "What kind of business?", "type": "select",
     "options": [["shop", "Shop"], ["salesman", "Salesman / reseller"], ["other", "Other"]]},
    {"key": "shop_type", "section": "Who they are", "label": "What kind of shop?", "type": "select",
     "show_if": {"business_type": ["shop"]},
     "options": [["grocery", "Superette / grocery"], ["gsm", "Phone / GSM shop"], ["kiosk", "Kiosk / tabac"],
                 ["cafe", "Café / publinet"], ["library", "Library / copy shop"], ["drugstore", "Drugstore"],
                 ["other", "Other"]]},
    {"key": "business_other", "section": "Who they are", "label": "What do they do?", "type": "text",
     "show_if": {"business_type": ["other"]}},
    {"key": "shops_count", "section": "Who they are", "label": "How many shops or points of sale?", "type": "number"},
    {"key": "city", "section": "Who they are", "label": "City / area", "type": "text", "crm": "person.city"},

    {"key": "daily_revenue", "section": "Revenue and vouchers", "label": "How much do they make a day?",
     "type": "number", "unit": "DT / day"},
    {"key": "daily_recharges", "section": "Revenue and vouchers", "label": "How much recharge do they sell a day?",
     "type": "number", "unit": "DT / day"},
    {"key": "operators", "section": "Revenue and vouchers", "label": "Operators they sell", "type": "multi",
     "options": [["ooredoo", "Ooredoo"], ["orange", "Orange"], ["tt", "Tunisie Telecom"]]},
    {"key": "voucher_management", "section": "Revenue and vouchers",
     "label": "How do they manage their vouchers today?", "type": "multi",
     "options": [["scratch", "Scratch cards"], ["platform", "Another electronic platform"],
                 ["dealer", "Operator dealer"], ["none", "Doesn't sell recharges yet"], ["other", "Other"]]},
    {"key": "supplier", "section": "Revenue and vouchers", "label": "Who do they buy their vouchers from?",
     "type": "text", "help": "Supplier, wholesaler or platform name"},
    {"key": "price_1dt", "section": "Revenue and vouchers", "label": "Price they pay for a 1 DT voucher",
     "type": "number", "unit": "DT", "step": 0.001, "help": "Our prices: 1.110 to 1.140 depending on the deposit"},
    {"key": "price_5dt", "section": "Revenue and vouchers", "label": "Price they pay for a 5 DT voucher",
     "type": "number", "unit": "DT", "step": 0.001, "help": "Our prices: 5.550 to 5.600 depending on the deposit"},
    {"key": "purchase_amount", "section": "Revenue and vouchers", "label": "How much do they buy each time?",
     "type": "number", "unit": "DT"},
    {"key": "purchase_frequency", "section": "Revenue and vouchers", "label": "How often do they restock?",
     "type": "select", "options": [["daily", "Every day"], ["few_weekly", "A few times a week"],
                                   ["weekly", "Every week"], ["monthly", "Every month or less"]]},
    {"key": "pain_points", "section": "Revenue and vouchers", "label": "Problems with their current supplier",
     "type": "textarea", "help": "Stockouts, price, delays, support…"},

    {"key": "has_pos", "section": "Equipment and payment", "label": "Has a POS terminal", "type": "boolean",
     "crm": "person.havepos"},
    {"key": "equipment", "section": "Equipment and payment", "label": "Equipment in the shop", "type": "multi",
     "options": [["cash_register", "Cash register"], ["printer", "Printer"], ["smartphone", "Smartphone"],
                 ["pc", "Computer"]]},
    {"key": "payment_method", "section": "Equipment and payment", "label": "How they'd top up their balance",
     "type": "select", "options": [["cash", "Cash"], ["deposit", "Bank deposit (versement)"],
                                   ["transfer", "Bank transfer (virement)"]]},
    {"key": "first_deposit", "section": "Equipment and payment", "label": "First deposit they would make",
     "type": "number", "unit": "DT"},
]

# How a call can end. `stage` is the stage suggested for the contact (the agent can pick another); `reached`: the
# agent spoke with them; `success`: a win, what the conversion KPIs count; `callback`: booking a callback is suggested.
DEFAULT_OUTCOMES = [
    {"value": "account_created", "label": "Account created", "stage": "ACCOUNT_MADE", "reached": True,
     "success": True},
    {"value": "visit_booked", "label": "Salesman visit booked", "stage": "ACCEPTED", "reached": True, "success": True},
    {"value": "interested", "label": "Interested", "stage": "IN_TALK", "reached": True},
    {"value": "link_sent", "label": "Sign-up link sent", "stage": "WAITING_REPLY", "reached": True},
    {"value": "callback_requested", "label": "Asked to be called back", "stage": "IN_TALK", "reached": True,
     "callback": True},
    {"value": "not_interested", "label": "Not interested", "stage": "REJECTED", "reached": True},
    {"value": "no_answer", "label": "No answer", "stage": "ATTEMPTED", "callback": True},
    {"value": "busy", "label": "Busy / hung up", "stage": "ATTEMPTED", "callback": True},
    {"value": "unreachable", "label": "Phone off / unreachable", "stage": "ATTEMPTED", "callback": True},
    {"value": "wrong_number", "label": "Wrong number", "stage": "REJECTED"},
]

# Calls customers make to us, and our callbacks when we missed them.
INBOUND_QUESTIONS = [
    {"key": "call_reason", "section": "Why they called", "label": "Why are they calling?", "type": "select",
     "options": [["new_customer", "Wants to become a customer"], ["prices", "Prices / offers"],
                 ["account", "Their account"], ["recharge", "A recharge or voucher problem"],
                 ["payment", "Payment / deposit"], ["salesman", "Wants a salesman visit"], ["other", "Other"]]},
    {"key": "call_reason_other", "section": "Why they called", "label": "What about?", "type": "text",
     "show_if": {"call_reason": ["other"]}},
    {"key": "heard_from", "section": "Why they called", "label": "How did they hear about us?", "type": "select",
     "show_if": {"call_reason": ["new_customer", "prices", "salesman"]},
     "options": [["facebook", "Facebook / Instagram"], ["friend", "A friend or another shop"],
                 ["salesman", "One of our salesmen"], ["search", "Google / the website"], ["other", "Other"]]},
    {"key": "city", "section": "Who they are", "label": "City / area", "type": "text", "crm": "person.city"},
    {"key": "resolved", "section": "Follow-up", "label": "Was their request solved during the call?",
     "type": "boolean"},
    {"key": "follow_up", "section": "Follow-up", "label": "What still has to be done", "type": "textarea",
     "show_if": {"resolved": ["false"]}, "help": "Who does it, and what the customer was promised"},
]

INBOUND_OUTCOMES = [
    {"value": "account_created", "label": "Account created", "stage": "ACCOUNT_MADE", "reached": True,
     "success": True},
    {"value": "visit_booked", "label": "Salesman visit booked", "stage": "ACCEPTED", "reached": True, "success": True},
    {"value": "interested", "label": "Interested", "stage": "IN_TALK", "reached": True},
    {"value": "info_given", "label": "Information given", "reached": True},
    {"value": "support_solved", "label": "Support: solved", "reached": True},
    {"value": "support_open", "label": "Support: to follow up", "reached": True, "callback": True},
    {"value": "complaint", "label": "Complaint", "reached": True, "callback": True},
    {"value": "callback_requested", "label": "Asked to be called back", "reached": True, "callback": True},
    {"value": "not_interested", "label": "Not interested", "stage": "REJECTED", "reached": True},
    {"value": "no_answer", "label": "No answer", "callback": True},
    {"value": "busy", "label": "Busy / hung up", "callback": True},
    {"value": "unreachable", "label": "Phone off / unreachable", "callback": True},
    {"value": "dropped", "label": "Cut off before we could talk", "callback": True},
    {"value": "wrong_number", "label": "Wrong number / spam"},
]
NEW_LEADS_DESCRIPTION = "The CRM's New contacts, oldest first, then the Attempted ones we couldn't reach yet."
_OLD_NEW_LEADS_DESCRIPTION = "The CRM's New contacts, oldest first."
_ATTEMPTED_MIGRATION = "migrated.attempted_in_new_leads"

INBOUND = "inbound"
OUTBOUND = "outbound"

QUESTION_TYPES = ("select", "multi", "number", "text", "textarea", "boolean")
_KEY_RE = re.compile(r"^[a-z][a-z0-9_]{0,39}$")
_STAGE_RE = re.compile(r"^[A-Z][A-Z0-9_]{0,59}$")
_CRM_FIELD_RE = re.compile(r"^person\.[a-zA-Z][a-zA-Z0-9]{0,59}$")
_TIME_RE = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")
MAX_QUESTIONS = 100
MAX_OPTIONS = 50
MAX_OUTCOMES = 30


class CampaignError(ValueError):
    """The campaign can't be saved as it is; the message says what to fix."""


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def slug(text: str, fallback: str) -> str:
    """A key made from a label: "Has a POS?" -> has_a_pos. Labels without latin letters get `fallback`."""
    value = re.sub(r"[^a-z0-9]+", "_", text.lower()).strip("_")[:40].rstrip("_")
    if value and not value[0].isalpha():
        value = f"q_{value}"[:40]
    return value or fallback


def _text(value, limit: int) -> str:
    return " ".join(str(value or "").split())[:limit]


# --- Validation ---------------------------------------------------------------------------------------

# Languages the desk can show a question or outcome in besides the English it's written in (see frontend i18n).
TRANSLATED = ("fr", "ar")


def _translations(raw, fields: dict[str, int], options: list | None = None) -> dict:
    """The optional `tr` of a question or outcome: {"fr": {"label": ..., "options": {value: label}}, "ar": {...}}.
    Unknown languages, fields and choices are dropped; empty texts too."""
    tr = raw.get("tr") if isinstance(raw, dict) else None
    if not isinstance(tr, dict):
        return {}
    values = {o[0] for o in options or []}
    clean = {}
    for lang in TRANSLATED:
        src = tr.get(lang)
        if not isinstance(src, dict):
            continue
        out = {field: text for field, limit in fields.items() if (text := _text(src.get(field), limit))}
        if values and isinstance(src.get("options"), dict):
            opts = {v: text for v, label in src["options"].items() if v in values and (text := _text(label, 120))}
            if opts:
                out["options"] = opts
        if out:
            clean[lang] = out
    return clean


def validate_questions(questions) -> list[dict]:
    if not isinstance(questions, list):
        raise CampaignError("The questions must be a list")
    if len(questions) > MAX_QUESTIONS:
        raise CampaignError(f"At most {MAX_QUESTIONS} questions")
    clean, seen = [], {}
    for i, raw in enumerate(questions, 1):
        if not isinstance(raw, dict):
            raise CampaignError(f"Question {i} is not valid")
        label = _text(raw.get("label"), 200)
        if not label:
            raise CampaignError(f"Question {i} has no text")
        explicit = str(raw.get("key") or "").strip()
        key = explicit or slug(label, f"q{i}")
        if not _KEY_RE.match(key):
            raise CampaignError(f"\"{label}\": the key may only hold lowercase letters, digits and _")
        if key in seen:
            if explicit:  # answers are saved under the key: two questions can't share one
                raise CampaignError(f"Two questions have the key \"{key}\"")
            base, n = key, 2
            while key in seen:
                key, n = f"{base[:36]}_{n}", n + 1
        kind = raw.get("type")
        if kind not in QUESTION_TYPES:
            raise CampaignError(f"\"{label}\": unknown answer type {kind!r}")
        q = {"key": key, "section": _text(raw.get("section"), 80) or "Questions", "label": label, "type": kind}
        if kind in ("select", "multi"):
            options, values = [], set()
            for opt in raw.get("options") or []:
                if isinstance(opt, (list, tuple)) and len(opt) == 2:
                    value, opt_label = str(opt[0]).strip(), _text(opt[1], 120)
                else:
                    opt_label = _text(opt, 120)
                    value = ""
                if not opt_label:
                    continue
                value = value or slug(opt_label, f"o{len(options) + 1}")
                if not _KEY_RE.match(value):
                    value = slug(value, f"o{len(options) + 1}")
                while value in values:
                    value = f"{value[:36]}_{len(options) + 1}"
                values.add(value)
                options.append([value, opt_label])
            if not options:
                raise CampaignError(f"\"{label}\": add at least one choice")
            if len(options) > MAX_OPTIONS:
                raise CampaignError(f"\"{label}\": at most {MAX_OPTIONS} choices")
            q["options"] = options
        for field, limit in (("help", 300), ("unit", 30)):
            if value := _text(raw.get(field), limit):
                q[field] = value
        if kind == "number" and raw.get("step") not in (None, ""):
            try:
                step = float(raw["step"])
            except (TypeError, ValueError):
                raise CampaignError(f"\"{label}\": the step must be a number")
            if step <= 0:
                raise CampaignError(f"\"{label}\": the step must be above 0")
            q["step"] = step
        if crm_field := str(raw.get("crm") or "").strip():
            if not _CRM_FIELD_RE.match(crm_field):
                raise CampaignError(f"\"{label}\": the CRM field is written person.<field name>, e.g. person.city")
            q["crm"] = crm_field
        if tr := _translations(raw, {"label": 200, "section": 80, "help": 300, "unit": 30}, q.get("options")):
            q["tr"] = tr
        if show_if := raw.get("show_if"):
            if not isinstance(show_if, dict):
                raise CampaignError(f"\"{label}\": the condition is not valid")
            cond = {}
            for other, values in show_if.items():
                parent = seen.get(other)
                if not parent:
                    raise CampaignError(f"\"{label}\" is shown depending on a question that isn't above it")
                if parent["type"] == "boolean":
                    allowed = {"true", "false"}  # how the desk compares a yes/no answer (String(true))
                else:
                    allowed = {o[0] for o in parent.get("options", [])}
                    if parent["type"] not in ("select", "multi"):
                        raise CampaignError(f"\"{label}\" can only depend on a choice or yes/no question")
                values = [str(v) for v in values or [] if str(v) in allowed]
                if not values:
                    raise CampaignError(f"\"{label}\": pick the answers that show it")
                cond[other] = values
            if cond:
                q["show_if"] = cond
        seen[key] = q
        clean.append(q)
    return clean


def validate_outcomes(outcomes) -> list[dict]:
    if not isinstance(outcomes, list) or not outcomes:
        raise CampaignError("Add at least one way a call can end")
    if len(outcomes) > MAX_OUTCOMES:
        raise CampaignError(f"At most {MAX_OUTCOMES} outcomes")
    clean, seen = [], set()
    for i, raw in enumerate(outcomes, 1):
        if not isinstance(raw, dict):
            raise CampaignError(f"Outcome {i} is not valid")
        label = _text(raw.get("label"), 80)
        if not label:
            raise CampaignError(f"Outcome {i} has no name")
        value = str(raw.get("value") or "").strip() or slug(label, f"outcome_{i}")
        if not _KEY_RE.match(value):
            raise CampaignError(f"\"{label}\": the key may only hold lowercase letters, digits and _")
        if value in seen:
            raise CampaignError(f"Two outcomes have the key \"{value}\"")
        seen.add(value)
        stage = str(raw.get("stage") or "").strip() or None
        if stage and not _STAGE_RE.match(stage):
            raise CampaignError(f"\"{label}\": unknown stage {stage!r}")
        reached = bool(raw.get("reached"))
        o = {"value": value, "label": label, "stage": stage, "reached": reached,
             "success": bool(raw.get("success")) and reached, "callback": bool(raw.get("callback"))}
        if tr := _translations(raw, {"label": 80}):
            o["tr"] = tr
        clean.append(o)
    return clean


def _clock(value) -> str | None:
    value = str(value or "").strip()
    if not value:
        return None
    if not _TIME_RE.match(value):
        raise CampaignError("Write calling hours as HH:MM, e.g. 09:00")
    return value


def validate(data: dict, kind: str = OUTBOUND) -> dict:
    """The campaign fields to save, checked and cleaned. The incoming calls campaign only keeps its name, description,
    questions and outcomes. Raises CampaignError."""
    name = _text(data.get("name"), 80)
    if not name:
        raise CampaignError("Give the campaign a name")
    if kind == INBOUND:
        return {"name": name, "description": _text(data.get("description"), 500) or None, "stages": [],
                "questions": validate_questions(data.get("questions") or []),
                "outcomes": validate_outcomes(data.get("outcomes")), "max_attempts": 0, "retry_minutes": 0,
                "exhausted_stage": None, "call_start": None, "call_end": None, "call_days": None, "active": True}
    stages = [s for s in (str(v).strip() for v in data.get("stages") or []) if s]
    if not stages:
        raise CampaignError("Pick at least one CRM stage for the queue")
    if any(not _STAGE_RE.match(s) for s in stages):
        raise CampaignError("Unknown CRM stage")
    try:
        max_attempts = int(data.get("max_attempts") or 0)
        retry_minutes = int(data.get("retry_minutes") if data.get("retry_minutes") not in (None, "") else 120)
    except (TypeError, ValueError):
        raise CampaignError("Attempts and retry delay are whole numbers")
    if not 0 <= max_attempts <= 50:
        raise CampaignError("Attempts: between 0 (no limit) and 50")
    if not 0 <= retry_minutes <= 60 * 24 * 30:
        raise CampaignError("The retry delay is at most 30 days")
    start, end = _clock(data.get("call_start")), _clock(data.get("call_end"))
    if bool(start) != bool(end):
        raise CampaignError("Set both the start and the end of the calling hours, or neither")
    if start and start >= end:
        raise CampaignError("The calling hours must end after they start")
    days = sorted({int(d) for d in data.get("call_days") or [] if str(d).isdigit() and 1 <= int(d) <= 7})
    exhausted = str(data.get("exhausted_stage") or "").strip() or None
    if exhausted and not _STAGE_RE.match(exhausted):
        raise CampaignError("Unknown CRM stage for contacts that never answer")
    return {"name": name, "description": _text(data.get("description"), 500) or None,
            "stages": stages, "questions": validate_questions(data.get("questions") or []),
            "outcomes": validate_outcomes(data.get("outcomes")), "max_attempts": max_attempts,
            "retry_minutes": retry_minutes, "exhausted_stage": exhausted, "call_start": start, "call_end": end,
            "call_days": days if days and len(days) < 7 else None, "active": bool(data.get("active", True))}


# --- Records ------------------------------------------------------------------------------------------

def to_dict(row) -> dict:
    item = dict(row)
    item["stages"] = json.loads(item["stages"])
    item["questions"] = json.loads(item["questions"])
    item["outcomes"] = json.loads(item["outcomes"])
    item["call_days"] = [int(d) for d in item["call_days"].split(",")] if item["call_days"] else None
    item["active"] = bool(item["active"])
    item["kind"] = item.get("kind") or OUTBOUND
    return item


def ensure_default(conn) -> None:
    """The first campaign, from the questions and outcomes the desk had before campaigns existed; the calls made
    before then are put in it. And the incoming calls campaign."""
    ensure_inbound(conn)
    if conn.execute("SELECT 1 FROM op_campaigns WHERE kind = ? LIMIT 1", (OUTBOUND,)).fetchone():
        _add_attempted(conn)
        return
    now = _now()
    cur = conn.execute("""INSERT INTO op_campaigns (name, description, stages, questions, outcomes, max_attempts,
                                              retry_minutes, position, created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, 0, 120, 0, ?, ?)""",
                 ("New leads", NEW_LEADS_DESCRIPTION, json.dumps([crm.lead_stage(), crm.attempted_stage()]),
                  json.dumps(validate_questions(DEFAULT_QUESTIONS), ensure_ascii=False),
                  json.dumps(validate_outcomes(DEFAULT_OUTCOMES), ensure_ascii=False),
                  now, now))
    conn.execute("UPDATE op_calls SET campaign_id = ? WHERE campaign_id IS NULL", (cur.lastrowid,))
    conn.execute("INSERT OR REPLACE INTO op_settings (key, value) VALUES (?, '1')", (_ATTEMPTED_MIGRATION,))
    conn.commit()


def _add_attempted(conn) -> None:
    """Once: the New leads campaigns made before Attempted contacts were queued also call those, after the New ones.
    An admin who takes the stage out again keeps it out."""
    if conn.execute("SELECT 1 FROM op_settings WHERE key = ?", (_ATTEMPTED_MIGRATION,)).fetchone():
        return
    lead, attempted = crm.lead_stage(), crm.attempted_stage()
    for row in conn.execute("SELECT id, stages, description FROM op_campaigns WHERE kind = ?", (OUTBOUND,)).fetchall():
        if json.loads(row["stages"]) == [lead]:
            description = NEW_LEADS_DESCRIPTION if row["description"] == _OLD_NEW_LEADS_DESCRIPTION else row["description"]
            conn.execute("UPDATE op_campaigns SET stages = ?, description = ? WHERE id = ?",
                         (json.dumps([lead, attempted]), description, row["id"]))
    conn.execute("INSERT OR REPLACE INTO op_settings (key, value) VALUES (?, '1')", (_ATTEMPTED_MIGRATION,))
    conn.commit()


def ensure_inbound(conn) -> None:
    if conn.execute("SELECT 1 FROM op_campaigns WHERE kind = ? LIMIT 1", (INBOUND,)).fetchone():
        return
    now = _now()
    conn.execute("""INSERT INTO op_campaigns (name, description, stages, questions, outcomes, max_attempts,
                                              retry_minutes, position, kind, created_at, updated_at)
                    VALUES (?, ?, '[]', ?, ?, 0, 0, -1, ?, ?, ?)""",
                 ("Incoming calls", "Calls customers make to us, and our callbacks when we missed them.",
                  json.dumps(validate_questions(INBOUND_QUESTIONS), ensure_ascii=False),
                  json.dumps(validate_outcomes(INBOUND_OUTCOMES), ensure_ascii=False), INBOUND, now, now))
    conn.commit()


def all_campaigns(conn, active_only: bool = False, kind: str | None = None) -> list[dict]:
    """Every campaign (the incoming calls one first), or only the active ones, or only those of a `kind`."""
    ensure_default(conn)
    clauses, args = [], []
    if active_only:
        clauses.append("active = 1")
    if kind:
        clauses.append("kind = ?")
        args.append(kind)
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    return [to_dict(r) for r in conn.execute(f"SELECT * FROM op_campaigns {where} ORDER BY position, id", args)]


def default_id(conn) -> int:
    """The first outbound campaign (active ones first)."""
    ensure_default(conn)
    row = conn.execute("SELECT id FROM op_campaigns WHERE kind = ? ORDER BY active DESC, position, id LIMIT 1",
                       (OUTBOUND,)).fetchone()
    return row[0]


def inbound_id(conn) -> int:
    """The incoming calls campaign."""
    ensure_default(conn)
    return conn.execute("SELECT id FROM op_campaigns WHERE kind = ?", (INBOUND,)).fetchone()[0]


def get(conn, campaign_id: int | None) -> dict:
    """The campaign, or the first active one when it's None or was deleted."""
    ensure_default(conn)
    row = None
    if campaign_id is not None:
        row = conn.execute("SELECT * FROM op_campaigns WHERE id = ?", (campaign_id,)).fetchone()
    if row is None:
        row = conn.execute("SELECT * FROM op_campaigns WHERE id = ?", (default_id(conn),)).fetchone()
    return to_dict(row)


def save(conn, campaign_id: int | None, data: dict) -> dict:
    """Add an (outbound) campaign, or change one; a campaign's kind never changes."""
    kind = OUTBOUND
    if campaign_id is not None:
        row = conn.execute("SELECT kind FROM op_campaigns WHERE id = ?", (campaign_id,)).fetchone()
        if not row:
            raise CampaignError("This campaign doesn't exist anymore")
        kind = row[0] or OUTBOUND
    fields = validate(data, kind)
    values = {**fields, "stages": json.dumps(fields["stages"]),
              "questions": json.dumps(fields["questions"], ensure_ascii=False),
              "outcomes": json.dumps(fields["outcomes"], ensure_ascii=False),
              "call_days": ",".join(map(str, fields["call_days"])) if fields["call_days"] else None,
              "active": int(fields["active"]), "updated_at": _now()}
    if campaign_id is None:
        position = conn.execute("SELECT COALESCE(MAX(position), 0) + 1 FROM op_campaigns").fetchone()[0]
        cols = list(values) + ["position", "created_at"]
        cur = conn.execute(f"INSERT INTO op_campaigns ({', '.join(cols)}) VALUES ({', '.join('?' * len(cols))})",
                           list(values.values()) + [position, values["updated_at"]])
        campaign_id = cur.lastrowid
    else:
        if not fields["active"] and not conn.execute(
                "SELECT 1 FROM op_campaigns WHERE active = 1 AND kind = ? AND id != ?",
                (OUTBOUND, campaign_id)).fetchone():
            raise CampaignError("Keep at least one campaign active")
        conn.execute(f"UPDATE op_campaigns SET {', '.join(f'{k} = ?' for k in values)} WHERE id = ?",
                     list(values.values()) + [campaign_id])
    conn.commit()
    return get(conn, campaign_id)


def delete(conn, campaign_id: int) -> str:
    """Delete a campaign nobody called from yet; one with calls is archived instead (its history stays readable).
    Returns "deleted" or "archived"."""
    row = conn.execute("SELECT kind FROM op_campaigns WHERE id = ?", (campaign_id,)).fetchone()
    if not row:
        raise CampaignError("This campaign doesn't exist anymore")
    if row[0] == INBOUND:
        raise CampaignError("The incoming calls campaign can't be deleted")
    if not conn.execute("SELECT 1 FROM op_campaigns WHERE active = 1 AND kind = ? AND id != ?",
                        (OUTBOUND, campaign_id)).fetchone():
        raise CampaignError("Keep at least one campaign active")
    if conn.execute("SELECT 1 FROM op_calls WHERE campaign_id = ? LIMIT 1", (campaign_id,)).fetchone():
        conn.execute("UPDATE op_campaigns SET active = 0, updated_at = ? WHERE id = ?", (_now(), campaign_id))
        result = "archived"
    else:
        conn.execute("DELETE FROM op_campaigns WHERE id = ?", (campaign_id,))
        result = "deleted"
    conn.execute("UPDATE op_agents SET campaign_id = NULL WHERE campaign_id = ?", (campaign_id,))
    conn.commit()
    return result


# --- Using a campaign ---------------------------------------------------------------------------------

def outcome(campaign: dict, value: str | None) -> dict:
    return next((o for o in campaign["outcomes"] if o["value"] == value), {})


def questions_by_key(campaign: dict) -> dict[str, dict]:
    return {q["key"]: q for q in campaign["questions"]}


def hours_label(campaign: dict) -> str:
    days = campaign.get("call_days")
    names = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
    parts = []
    if days:
        parts.append(", ".join(names[d - 1] for d in days))
    if campaign.get("call_start"):
        parts.append(f"{campaign['call_start']}–{campaign['call_end']}")
    return " ".join(parts) or "any time"


def is_open(campaign: dict, when: datetime) -> bool:
    """Whether the campaign's queue may be called at `when` (its calling days and hours)."""
    days = campaign.get("call_days")
    if days and when.isoweekday() not in days:
        return False
    if campaign.get("call_start"):
        clock = when.strftime("%H:%M")
        return campaign["call_start"] <= clock < campaign["call_end"]
    return True


def next_open(campaign: dict, when: datetime) -> datetime:
    """`when`, or the start of the next calling period after it."""
    if is_open(campaign, when):
        return when
    start = campaign.get("call_start") or "00:00"
    hour, minute = map(int, start.split(":"))
    day = when.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if day <= when:
        day += timedelta(days=1)
    for _ in range(8):
        if is_open(campaign, day):
            return day
        day += timedelta(days=1)
    return when  # no open day at all: shouldn't happen (validate keeps at least one)
