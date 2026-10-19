"""Call desk figures: which GoVoice recording each desk call is (link_recordings), the agents' KPIs (kpis), and how the
outcomes agents pick line up with the AI's scores of the same calls (insights).

A desk call is matched to the recording of the same number, made from the agent's extension (their softphone or the
extensions linked to their account), that starts closest to when the call was started on the desk, within
LINK_SLACK_MINUTES of the call. RECORDING_CLOCK_OFFSET_MINUTES corrects a GoVoice clock that runs ahead (or behind,
negative) of this server's, e.g. 60 when the server runs on UTC and GoVoice on Tunisian time.
"""
import json
import sqlite3
from datetime import date, datetime, timedelta

from . import campaigns, crm, floor, idle, operations
from .analyze import kind_of
from .adapters.telephony.base import DATE_FORMAT
from .config import live

LINK_SLACK_MINUTES = 3
LINK_LOOKBACK_DAYS = 30
_RECORDING_TIME = DATE_FORMAT  # how recordings write date_call
REAL = f"opportunity_id NOT LIKE '{operations.TEST_PREFIX}%'"
# AI score bands, to compare how often calls in each band end in a win.
SCORE_BANDS = [("1-4", 1, 4), ("5-6", 5, 6), ("7-8", 7, 8), ("9-10", 9, 10)]


def _clock_offset() -> timedelta:
    try:
        return timedelta(minutes=float(live("RECORDING_CLOCK_OFFSET_MINUTES", "0")))
    except ValueError:
        return timedelta()


def _extensions(conn) -> dict[str, set[str]]:
    """username -> the GoVoice extensions their calls are made from."""
    found: dict[str, set[str]] = {}
    for username, ext in conn.execute("SELECT username, extension FROM softphones UNION "
                                      "SELECT username, agent FROM user_agents"):
        found.setdefault(username, set()).add(ext)
    return found


def _phone_keys(row) -> set[str]:
    lead = json.loads(row["lead"]) if row["lead"] else {}
    numbers = [row["phone"], *((lead.get("contact") or {}).get("phones") or [])]
    return {key for n in numbers if n and (key := crm.match_key(n))}


def link_recordings(conn) -> int:
    """Link the desk calls of the last LINK_LOOKBACK_DAYS that have no recording yet to theirs, once GoVoice has it.
    Returns how many were linked."""
    since = (datetime.now() - timedelta(days=LINK_LOOKBACK_DAYS)).isoformat(timespec="seconds")
    rows = conn.execute(f"""SELECT id, agent, phone, lead, call_started_at, call_ended_at FROM op_calls
                            WHERE status = 'done' AND call_id IS NULL AND call_started_at IS NOT NULL
                              AND finished_at >= ? AND {REAL} ORDER BY call_started_at""", (since,)).fetchall()
    if not rows:
        return 0
    claimed = {r[0] for r in conn.execute("SELECT call_id FROM op_calls WHERE call_id IS NOT NULL")}
    extensions = _extensions(conn)
    offset, slack = _clock_offset(), timedelta(minutes=LINK_SLACK_MINUTES)
    linked = 0
    for row in rows:
        keys = _phone_keys(row)
        try:
            start = datetime.fromisoformat(row["call_started_at"]) + offset
            end = datetime.fromisoformat(row["call_ended_at"] or row["call_started_at"]) + offset
        except ValueError:
            continue
        if not keys:
            continue
        mine = extensions.get(row["agent"])
        best = None
        for rec in conn.execute("SELECT id, agent, customer, date_call FROM calls WHERE date_call BETWEEN ? AND ?",
                                ((start - slack).strftime(_RECORDING_TIME), (end + slack).strftime(_RECORDING_TIME))):
            if rec["id"] in claimed or crm.match_key(rec["customer"] or "") not in keys:
                continue
            if mine and rec["agent"] not in mine:
                continue
            try:
                gap = abs((datetime.strptime(rec["date_call"], _RECORDING_TIME) - start).total_seconds())
            except (TypeError, ValueError):
                continue
            if best is None or gap < best[0]:
                best = (gap, rec["id"])
        if best:
            try:
                conn.execute("UPDATE op_calls SET call_id = ? WHERE id = ? AND call_id IS NULL", (best[1], row["id"]))
            except sqlite3.IntegrityError:  # linked meanwhile by another request
                continue
            claimed.add(best[1])
            linked += 1
    conn.commit()
    return linked


def desk_call_for_recording(conn, call_id: str) -> dict | None:
    """The desk call a recording was linked to, with its outcome and campaign, for the call's page."""
    row = conn.execute("SELECT * FROM op_calls WHERE call_id = ?", (call_id,)).fetchone()
    if not row:
        return None
    campaign = operations.campaign_of(conn, row)
    o = campaigns.outcome(campaign, row["outcome"])
    names = operations.account_names(conn)
    return {"id": row["id"], "outcome": row["outcome"], "outcome_label": o.get("label") or row["outcome"],
            "reached": bool(o.get("reached")), "success": bool(o.get("success")), "campaign": campaign["name"],
            "agent_name": names.get(row["agent"], row["agent"]), "finished_at": row["finished_at"],
            "note": row["note"], "stage_before": row["stage_before"], "stage_after": row["stage_after"],
            "lead_url": (json.loads(row["lead"]) if row["lead"] else {}).get("url")}


# --- Shared ------------------------------------------------------------------------------------------

def _range(since: str | None, until: str | None) -> tuple[str, str]:
    """ISO days, `until` exclusive; today when not given."""
    today = date.today()
    return since or today.isoformat(), until or (today + timedelta(days=1)).isoformat()


def _seconds(start: str | None, end: str | None) -> int | None:
    try:
        return max(0, int((datetime.fromisoformat(end) - datetime.fromisoformat(start)).total_seconds()))
    except (TypeError, ValueError):
        return None


def _scores(conn, call_ids) -> dict[str, dict]:
    """call id -> the AI's rating of the recording: overall score, score card, kind, its own outcome. Calls that
    aren't rated (voicemail, no answer...) or not analyzed yet are left out."""
    call_ids = [c for c in call_ids if c]
    found = {}
    for i in range(0, len(call_ids), 500):
        chunk = call_ids[i:i + 500]
        for row in conn.execute(f"SELECT id, duration, analysis FROM calls WHERE id IN ({','.join('?' * len(chunk))})",
                                chunk):
            try:
                analysis = json.loads(row["analysis"]) if row["analysis"] else None
            except ValueError:
                analysis = None
            if not analysis or kind_of(analysis) == "other" or analysis.get("overall_score") is None:
                continue
            found[row["id"]] = {"overall": analysis["overall_score"], "scores": analysis.get("scores") or {},
                                "kind": kind_of(analysis), "duration": row["duration"],
                                "ai_outcome": analysis.get("outcome") or analysis.get("resolution_status"),
                                "voice": (analysis.get("voice") or {}).get("score"),
                                "summary": analysis.get("summary"), "tip": analysis.get("top_coaching_tip")}
    return found


def _avg(values) -> float | None:
    values = [v for v in values if isinstance(v, (int, float))]
    return round(sum(values) / len(values), 2) if values else None


def _rate(part: int, whole: int) -> float | None:
    return round(part / whole, 4) if whole else None


def _done_rows(conn, since: str, until: str, *, username: str | None = None, campaign_id: int | None = None):
    sql = (f"SELECT * FROM op_calls WHERE status = 'done' AND {REAL} AND finished_at >= ? AND finished_at < ?")
    args: list = [since, until]
    if username:
        sql += " AND agent = ?"
        args.append(username)
    if campaign_id:
        sql += " AND COALESCE(campaign_id, ?) = ?"
        args += [campaigns.default_id(conn), campaign_id]
    return conn.execute(sql + " ORDER BY finished_at", args).fetchall()


# --- Agent KPIs --------------------------------------------------------------------------------------

def kpis(conn, since: str | None = None, until: str | None = None, username: str | None = None,
         campaign_id: int | None = None) -> dict:
    """Per agent, and for the team: calls closed, reached, wins, the rates between them, talk and wrap-up time, time
    on the desk and calls per hour, callbacks booked, contacts given back, and the AI's average score of their
    recorded calls, time paused (in all, per reason, and pauses over their limit), and the times they were prompted
    to call after staying idle (`idle_prompts`, each one listed, latest first; see idle.py). `days` has the team's
    calls, reached and wins per day."""
    since, until = _range(since, until)
    link_recordings(conn)
    lookup = operations.outcome_lookup(conn)
    names = operations.account_names(conn)
    rows = _done_rows(conn, since, until, username=username, campaign_id=campaign_id)
    scores = _scores(conn, {r["call_id"] for r in rows})

    def blank():
        return {"calls": 0, "reached": 0, "success": 0, "talk_seconds": 0, "wrap_seconds": 0, "wrapped": 0,
                "linked": 0, "score_sum": 0.0, "scored": 0, "outcomes": {}, "desk_seconds": 0, "callbacks_booked": 0,
                "given_back": 0, "pause_seconds": 0, "pauses_over": 0, "pause_reasons": {}, "idle_prompts": 0,
                "idle_seconds": 0}

    agents: dict[str, dict] = {}
    days: dict[str, dict] = {}
    for r in rows:
        a = agents.setdefault(r["agent"], blank())
        o = lookup(r["campaign_id"], r["outcome"])
        day = days.setdefault(r["finished_at"][:10], {"calls": 0, "reached": 0, "success": 0})
        for target in (a, day):
            target["calls"] += 1
            target["reached"] += bool(o.get("reached"))
            target["success"] += bool(o.get("success"))
        a["outcomes"][r["outcome"]] = a["outcomes"].get(r["outcome"], 0) + 1
        a["talk_seconds"] += _seconds(r["call_started_at"], r["call_ended_at"]) or 0
        wrap = _seconds(r["call_ended_at"], r["finished_at"])
        if wrap is not None:
            a["wrap_seconds"] += wrap
            a["wrapped"] += 1
        if r["call_id"]:
            a["linked"] += 1
            if s := scores.get(r["call_id"]):
                a["score_sum"] += s["overall"]
                a["scored"] += 1

    agent_sql, agent_args = ("AND username = ?", [username]) if username else ("", [])
    for user, seconds in conn.execute(f"SELECT username, SUM(ready_seconds) FROM op_presence WHERE day >= ? "
                                      f"AND day < ? {agent_sql} GROUP BY username", [since, until, *agent_args]):
        agents.setdefault(user, blank())["desk_seconds"] = seconds or 0
    by_sql, by_args = ("AND scheduled_by = ?", [username]) if username else ("", [])
    for user, n in conn.execute(f"SELECT scheduled_by, COUNT(*) FROM op_calls WHERE source = 'callback' "
                                f"AND scheduled_by IS NOT NULL AND created_at >= ? AND created_at < ? AND {REAL} "
                                f"{by_sql} GROUP BY scheduled_by", [since, until, *by_args]):
        agents.setdefault(user, blank())["callbacks_booked"] = n
    ag_sql, ag_args = ("AND agent = ?", [username]) if username else ("", [])
    for user, n in conn.execute(f"SELECT agent, COUNT(*) FROM op_calls WHERE status = 'released' AND agent IS NOT NULL "
                                f"AND finished_at >= ? AND finished_at < ? AND {REAL} {ag_sql} GROUP BY agent",
                                [since, until, *ag_args]):
        agents.setdefault(user, blank())["given_back"] = n
    for user, t in floor.pause_totals(conn, since, until, username).items():
        a = agents.setdefault(user, blank())
        a["pause_seconds"], a["pauses_over"], a["pause_reasons"] = t["pause_seconds"], t["pauses_over"], t["by_reason"]
    prompts = idle.history(conn, since, until, username)
    for p in prompts:
        a = agents.setdefault(p["username"], blank())
        a["idle_prompts"] += 1
        a["idle_seconds"] += p["idle_seconds"]

    def finish(user: str | None, a: dict) -> dict:
        hours = a["desk_seconds"] / 3600
        return {"username": user, "name": names.get(user, user) if user else "Team", "calls": a["calls"],
                "reached": a["reached"], "success": a["success"], "outcomes": a["outcomes"],
                "contact_rate": _rate(a["reached"], a["calls"]), "conversion_rate": _rate(a["success"], a["reached"]),
                "success_rate": _rate(a["success"], a["calls"]), "talk_seconds": a["talk_seconds"],
                "avg_talk_seconds": round(a["talk_seconds"] / a["calls"]) if a["calls"] else None,
                "avg_wrap_seconds": round(a["wrap_seconds"] / a["wrapped"]) if a["wrapped"] else None,
                "desk_seconds": a["desk_seconds"],
                "calls_per_hour": round(a["calls"] / hours, 2) if hours >= 0.05 else None,
                "success_per_hour": round(a["success"] / hours, 2) if hours >= 0.05 else None,
                "talk_share": _rate(a["talk_seconds"], a["desk_seconds"]) if a["desk_seconds"] else None,
                "callbacks_booked": a["callbacks_booked"], "given_back": a["given_back"], "linked": a["linked"],
                "pause_seconds": a["pause_seconds"], "pauses_over": a["pauses_over"],
                "pause_reasons": a["pause_reasons"], "idle_prompts": a["idle_prompts"], "idle_seconds": a["idle_seconds"],
                "scored": a["scored"], "avg_score": round(a["score_sum"] / a["scored"], 2) if a["scored"] else None}

    team = blank()
    for a in agents.values():
        for key in ("calls", "reached", "success", "talk_seconds", "wrap_seconds", "wrapped", "linked", "score_sum",
                    "scored", "desk_seconds", "callbacks_booked", "given_back", "pause_seconds", "pauses_over", "idle_prompts", "idle_seconds"):
            team[key] += a[key]
        for label, seconds in a["pause_reasons"].items():
            team["pause_reasons"][label] = team["pause_reasons"].get(label, 0) + seconds
        for value, n in a["outcomes"].items():
            team["outcomes"][value] = team["outcomes"].get(value, 0) + n
    listed = sorted((finish(u, a) for u, a in agents.items()), key=lambda k: (-k["success"], -k["calls"], k["name"]))
    return {"since": since, "until": until, "team": finish(None, team), "agents": listed,
            "days": [{"day": d, **v} for d, v in sorted(days.items())], "idle_prompts": prompts}


# --- Outcomes and AI scores --------------------------------------------------------------------------

def insights(conn, since: str | None = None, until: str | None = None, campaign_id: int | None = None) -> dict:
    """How the outcomes agents pick on the desk line up with the AI's rating of the same recorded calls:

    - outcomes: per outcome, how many calls, how many have a rated recording, their average AI score and score card,
      and what the AI itself said the call's outcome was;
    - drivers: each score card criterion's average on won calls against the other calls where the contact was reached,
      biggest gap first (what the wins do better);
    - bands: how often reached calls end in a win per AI score band;
    - agents: per agent, average AI score and win rate;
    - calls: the rated calls themselves, latest first, to open the recordings."""
    since, until = _range(since, until)
    link_recordings(conn)
    lookup = operations.outcome_lookup(conn)
    names = operations.account_names(conn)
    rows = _done_rows(conn, since, until, campaign_id=campaign_id)
    scores = _scores(conn, {r["call_id"] for r in rows})

    outcomes: dict[str, dict] = {}
    won, lost = [], []  # rated calls where the contact was reached: wins, and the others
    agents: dict[str, dict] = {}
    calls = []
    for r in rows:
        o = lookup(r["campaign_id"], r["outcome"])
        s = scores.get(r["call_id"]) if r["call_id"] else None
        item = outcomes.setdefault(r["outcome"], {"outcome": r["outcome"], "label": o.get("label") or r["outcome"],
                                                  "reached": bool(o.get("reached")), "success": bool(o.get("success")),
                                                  "calls": 0, "linked": 0, "rated": [], "talk": [], "ai_outcomes": {}})
        item["calls"] += 1
        item["linked"] += bool(r["call_id"])
        item["talk"].append(_seconds(r["call_started_at"], r["call_ended_at"]))
        a = agents.setdefault(r["agent"], {"calls": 0, "reached": 0, "success": 0, "rated": [], "won_scores": [],
                                           "other_scores": []})
        a["calls"] += 1
        a["reached"] += bool(o.get("reached"))
        a["success"] += bool(o.get("success"))
        if not s:
            continue
        item["rated"].append(s)
        if s["ai_outcome"]:
            item["ai_outcomes"][s["ai_outcome"]] = item["ai_outcomes"].get(s["ai_outcome"], 0) + 1
        a["rated"].append(s["overall"])
        if o.get("reached"):
            (won if o.get("success") else lost).append(s)
            (a["won_scores"] if o.get("success") else a["other_scores"]).append(s["overall"])
        lead = json.loads(r["lead"]) if r["lead"] else {}
        calls.append({"op_id": r["id"], "call_id": r["call_id"], "finished_at": r["finished_at"],
                      "agent_name": names.get(r["agent"], r["agent"]),
                      "contact": (lead.get("contact") or {}).get("name") or lead.get("name"),
                      "outcome": r["outcome"], "outcome_label": o.get("label") or r["outcome"],
                      "success": bool(o.get("success")), "reached": bool(o.get("reached")),
                      "score": s["overall"], "kind": s["kind"], "ai_outcome": s["ai_outcome"], "summary": s["summary"]})

    def criteria(rated: list[dict]) -> dict[str, float | None]:
        keys = sorted({k for s in rated for k in s["scores"]})
        return {k: _avg(s["scores"].get(k) for s in rated) for k in keys}

    outcome_list = []
    for item in outcomes.values():
        rated = item.pop("rated")
        talk = item.pop("talk")
        outcome_list.append({**item, "rated": len(rated), "avg_score": _avg(s["overall"] for s in rated),
                             "avg_voice": _avg(s["voice"] for s in rated), "criteria": criteria(rated),
                             "avg_talk_seconds": _avg(talk), "avg_recording_seconds": _avg(s["duration"] for s in rated)})
    outcome_list.sort(key=lambda x: (not x["success"], not x["reached"], -x["calls"]))

    drivers = []
    won_criteria, lost_criteria = criteria(won), criteria(lost)
    for key in sorted(set(won_criteria) | set(lost_criteria)):
        w, other = won_criteria.get(key), lost_criteria.get(key)
        drivers.append({"criterion": key, "won": w, "other": other,
                        "gap": round(w - other, 2) if w is not None and other is not None else None})
    overall = {"criterion": "overall_score", "won": _avg(s["overall"] for s in won),
               "other": _avg(s["overall"] for s in lost)}
    overall["gap"] = round(overall["won"] - overall["other"], 2) if None not in (overall["won"], overall["other"]) else None
    drivers.sort(key=lambda d: -(d["gap"] if d["gap"] is not None else -99))

    bands = []
    for label, low, high in SCORE_BANDS:
        in_band = [s for s in won if low <= s["overall"] <= high], [s for s in lost if low <= s["overall"] <= high]
        n = len(in_band[0]) + len(in_band[1])
        bands.append({"band": label, "calls": n, "success": len(in_band[0]), "success_rate": _rate(len(in_band[0]), n)})

    agent_list = [{"username": u, "name": names.get(u, u), "calls": a["calls"], "reached": a["reached"],
                   "success": a["success"], "conversion_rate": _rate(a["success"], a["reached"]),
                   "rated": len(a["rated"]), "avg_score": _avg(a["rated"]), "avg_score_won": _avg(a["won_scores"]),
                   "avg_score_other": _avg(a["other_scores"])} for u, a in agents.items()]
    agent_list.sort(key=lambda a: (-(a["avg_score"] or 0), a["name"]))
    calls.sort(key=lambda c: c["finished_at"], reverse=True)
    return {"since": since, "until": until, "total": len(rows), "linked": sum(bool(r["call_id"]) for r in rows),
            "rated": sum(1 for r in rows if r["call_id"] in scores), "won_rated": len(won), "other_rated": len(lost),
            "overall": overall, "outcomes": outcome_list, "drivers": drivers, "bands": bands, "agents": agent_list,
            "calls": calls[:200]}
