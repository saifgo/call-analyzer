"""Look up a call's customer in a Twenty CRM (https://twenty.com) by phone number, via its REST API."""
import os
import re
import threading
import time

import requests
from dotenv import dotenv_values

from .config import ENV_PATH

DEFAULT_BASE_URL = "https://crm.tunisolutions.com"
CACHE_SECONDS = 60
TIMEOUT = 15
# Tunisian numbers are 8 digits once the +216 / 00216 prefix is dropped. Calls and the CRM write them both
# ways, so numbers are compared on their last 8 digits.
MATCH_DIGITS = 8

_cache: dict[str, tuple[float, dict]] = {}
_cache_lock = threading.Lock()


class CrmError(Exception):
    """The CRM couldn't be queried; the message is meant to be shown to the user."""


def _setting(key: str, default: str = "") -> str:
    """The value as saved in .env right now (so Settings edits apply without a restart), else the environment."""
    return (dotenv_values(ENV_PATH).get(key) or os.environ.get(key) or default).strip()


def _config() -> tuple[str, str, bool]:
    base = _setting("CRM_BASE_URL", DEFAULT_BASE_URL).rstrip("/")
    verify = _setting("CRM_VERIFY_SSL", "true").lower() in ("1", "true", "yes", "on")
    return base, _setting("CRM_API_KEY"), verify


def is_configured() -> bool:
    return bool(_config()[1])


def match_key(number: str) -> str | None:
    """The part of a phone number to search the CRM for, or None for extensions and other short numbers."""
    digits = re.sub(r"\D", "", number or "")
    return digits[-MATCH_DIGITS:] if len(digits) >= MATCH_DIGITS else None


def _get(path: str, params: dict) -> list[dict]:
    base, key, verify = _config()
    try:
        res = requests.get(f"{base}/rest/{path}", params=params, headers={"Authorization": f"Bearer {key}"},
                           timeout=TIMEOUT, verify=verify)
    except requests.RequestException as exc:
        raise CrmError(f"Couldn't reach the CRM at {base}: {exc.__class__.__name__}") from exc
    if res.status_code in (401, 403):
        raise CrmError("The CRM rejected the API key. Check CRM_API_KEY in Settings.")
    if not res.ok:
        raise CrmError(f"The CRM answered {res.status_code} for {path}.")
    data = res.json().get("data") or {}
    return data.get(path) or []


def _full_name(name: dict | None) -> str:
    return " ".join(p for p in ((name or {}).get("firstName"), (name or {}).get("lastName")) if p).strip()


def _person(rec: dict, opportunities: list[dict], base: str) -> dict:
    phones = rec.get("phones") or {}
    numbers = [f"{phones.get('primaryPhoneCallingCode') or ''} {phones.get('primaryPhoneNumber') or ''}".strip()]
    numbers += [f"{p.get('callingCode') or ''} {p.get('number') or ''}".strip()
                for p in phones.get("additionalPhones") or []]
    company = rec.get("company") or {}
    return {
        "id": rec["id"],
        "name": _full_name(rec.get("name")) or "Unnamed contact",
        "email": (rec.get("emails") or {}).get("primaryEmail") or None,
        "phones": [n for n in numbers if n],
        "job_title": rec.get("jobTitle") or None,
        "city": rec.get("city") or None,
        "company": company.get("name") or None,
        "created_at": rec.get("createdAt"),
        "last_contact_at": rec.get("lastContactAt"),
        "url": f"{base}/object/person/{rec['id']}",
        "opportunities": opportunities,
    }


def _opportunity(rec: dict, base: str) -> dict:
    amount = rec.get("amount") or {}
    micros = amount.get("amountMicros")
    owner = rec.get("owner") or {}
    return {
        "id": rec["id"],
        "name": rec.get("name") or "Untitled opportunity",
        "stage": rec.get("stage"),
        "amount": micros / 1_000_000 if micros else None,
        "currency": amount.get("currencyCode"),
        "close_date": rec.get("closeDate"),
        "company": (rec.get("company") or {}).get("name") or None,
        "owner": _full_name(owner.get("name")) or None,
        "created_at": rec.get("createdAt"),
        "updated_at": rec.get("updatedAt"),
        "url": f"{base}/object/opportunity/{rec['id']}",
    }


def lookup(number: str) -> dict:
    """Contacts in the CRM whose phone number matches `number`, each with their opportunities.

    Returns {"configured": bool, "number": str, "searched": bool, "people": [...]}; `searched` is False when
    the number is too short to match (an internal extension). Raises CrmError when the CRM can't be queried.
    """
    result = {"configured": is_configured(), "number": number, "searched": False, "people": []}
    key = match_key(number)
    if not result["configured"] or not key:
        return result
    result["searched"] = True

    with _cache_lock:
        cached = _cache.get(key)
    if cached and time.time() - cached[0] < CACHE_SECONDS:
        return {**result, "people": cached[1]["people"]}

    base = _config()[0]
    people = _get("people", {"filter": f'phones.primaryPhoneNumber[ilike]:"%{key}"', "depth": 1, "limit": 20,
                             "order_by": "createdAt[DescNullsLast]"})
    by_person: dict[str, list[dict]] = {p["id"]: [] for p in people}
    if by_person:
        ids = ",".join(f'"{i}"' for i in by_person)
        for rec in _get("opportunities", {"filter": f"pointOfContactId[in]:[{ids}]", "depth": 1, "limit": 200,
                                          "order_by": "createdAt[DescNullsLast]"}):
            by_person.get(rec.get("pointOfContactId"), []).append(_opportunity(rec, base))
    result["people"] = [_person(p, by_person[p["id"]], base) for p in people]

    with _cache_lock:
        _cache[key] = (time.time(), result)
    return result
