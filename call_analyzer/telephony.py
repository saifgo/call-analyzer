"""The phone system, whichever one is connected: where recordings come from and the softphone signs in.

The work is done by the adapter chosen with TELEPHONY_PROVIDER (adapters/telephony/, GoVoice by default); this
module adds what is the same for every phone system: the connection status the UI shows, and keeping the login
alive. See adapters/telephony/base.py to connect another phone system.
"""
import threading
from datetime import datetime

from .adapters import Registry
from .adapters.telephony.base import (DATE_FORMAT, SessionExpired, SipLoginError,  # noqa: F401  (part of the API)
                                      TelephonyAdapter)

BUILTIN = {"govoice": ".telephony.govoice:GoVoiceTelephony"}
registry: Registry[TelephonyAdapter] = Registry("phone system", "TELEPHONY_PROVIDER", "govoice", BUILTIN)

# Exit code of CLI commands when the phone system rejects the session, so the UI can offer to log in again.
EXIT_AUTH = 3
KEEPALIVE_SECONDS = 10 * 60  # GoVoice sessions expire after 2 hours without activity

_status = {"connected": None, "total": None, "message": "Not checked yet", "checked_at": None}


def adapter() -> TelephonyAdapter:
    return registry.get()


def use(phone_system: TelephonyAdapter | None) -> None:
    """Talk to this adapter instead of the one in Settings until use(None), e.g. a fake in the tests."""
    registry.use(phone_system)


def label() -> str:
    return adapter().label


def record_status(connected: bool | None, total: int | None = None, message: str | None = None) -> dict:
    if message is None:
        message = f"Connected · {total} recordings" if connected else "Not connected"
    _status.update(connected=connected, total=total, message=message,
                   checked_at=datetime.now().isoformat(timespec="seconds"))
    return status()


def status() -> dict:
    """The last connection check, with what the UI needs to ask for a login."""
    phone_system = adapter()
    return {**_status, "provider": phone_system.name, "label": phone_system.label,
            "login_url": phone_system.login_url}


def check_connection() -> dict:
    """Test the saved login against the phone system (a check also keeps it alive)."""
    phone_system = adapter()
    if not phone_system.has_session():
        return record_status(False, message=f"Not connected to {phone_system.label} yet")
    try:
        return record_status(True, phone_system.check())
    except SessionExpired:
        return record_status(False, message=f"{phone_system.label} session expired")
    except Exception as exc:  # network problems: not an auth issue, don't ask to log in again
        return record_status(None, message=f"Can't reach {phone_system.label}: {exc}")


def keepalive_loop(stop: threading.Event):
    """Use the session regularly so the phone system doesn't expire it while the app is running."""
    while not stop.wait(KEEPALIVE_SECONDS):
        if adapter().has_session():
            check_connection()


def iter_recordings(stop_before: str | None = None):
    """The recordings, newest first (see base.Recording). Raises SessionExpired."""
    return adapter().iter_recordings(stop_before=stop_before)


def download(filename: str, dest):
    return adapter().download(filename, dest)


def recording_url(filename: str | None) -> str | None:
    return adapter().recording_url(filename) if filename else None
