"""Browser softphone: the phone system's SIP account each user signs in with from the web UI.

The phone system (GoVoice: an Asterisk PBX) has a WebRTC WebSocket (SOFTPHONE_WS_URL). The browser connects to it
directly (frontend/src/lib/softphone.tsx) and registers with the SIP username and password the phone system gives
the account. The server keeps each account's extension and phone system login (e.g. GoVoice's user100 and its My
Account password), has the telephony adapter fetch the SIP sign-in with that login, and hands it to that account's
own browser. The passwords and the access token are encrypted in the database (vault.py).

The database columns keep their GoVoice names (govoice_user): they hold the login of whichever phone system is used.
"""
import re
from datetime import datetime

from . import db, telephony, vault
from .config import live

EXTENSION_RE = re.compile(r"^\d{1,6}$")
# Kept for callers that catch it: the adapters raise telephony.SipLoginError.
FetchError = telephony.SipLoginError


def ice_servers(value: str) -> list[dict]:
    """SOFTPHONE_ICE_SERVERS as RTCIceServer objects. turn:user:password@host:port carries its login."""
    servers = []
    for url in filter(None, (u.strip() for u in value.split(","))):
        scheme, _, rest = url.partition(":")
        if scheme in ("turn", "turns") and "@" in rest:
            login, _, host = rest.rpartition("@")
            username, _, credential = login.partition(":")
            servers.append({"urls": f"{scheme}:{host}", "username": username, "credential": credential})
        else:
            servers.append({"urls": url})
    return servers


def settings() -> dict:
    """Where the browser signs in: SOFTPHONE_* in Settings, else what the phone system's adapter says."""
    defaults = telephony.adapter().softphone_defaults()
    return {"ws_url": live("SOFTPHONE_WS_URL", defaults.get("ws_url", "")),
            "domain": live("SOFTPHONE_DOMAIN", defaults.get("domain", "")),
            "prefix": live("SOFTPHONE_USER_PREFIX") or defaults.get("prefix", ""),
            "ice_servers": ice_servers(live("SOFTPHONE_ICE_SERVERS", "stun:stun.l.google.com:19302"))}


def fetch_sip_login(account_user: str, account_password: str) -> dict:
    """{"sip_user", "password", "access_token"} from the phone system. Raises FetchError."""
    return telephony.adapter().sip_login(account_user, account_password)


def extensions() -> dict[str, dict]:
    """username -> {"extension", "govoice_user"}, for every account that has a softphone."""
    rows = db.connect().execute("SELECT username, extension, govoice_user FROM softphones").fetchall()
    return {r["username"]: {"extension": r["extension"], "govoice_user": r["govoice_user"] or ""} for r in rows}


def save(username: str, extension: str, govoice_user: str, account_password: str | None):
    """Set an account's extension and phone system login, and fetch its SIP password straight away (so a wrong login
    shows up here). account_password None keeps the saved one (only allowed when there is one)."""
    extension, govoice_user = extension.strip(), govoice_user.strip()
    system = telephony.label()
    if not EXTENSION_RE.match(extension):
        raise ValueError(f"The extension is the short {system} number, digits only (e.g. 100)")
    if not govoice_user:
        raise ValueError(f"Enter the {system} username (e.g. user100)")
    conn = db.connect()
    if not account_password:
        row = conn.execute("SELECT account_password FROM softphones WHERE username=?", (username,)).fetchone()
        account_password = vault.decrypt(row[0]) if row else None
        if not account_password:
            raise ValueError(f"Enter the {system} account password")
    try:
        login = fetch_sip_login(govoice_user, account_password)
    except FetchError as exc:
        raise ValueError(str(exc))
    conn.execute("""INSERT INTO softphones (username, extension, password, govoice_user, account_password, sip_user,
                                            access_token, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(username) DO UPDATE SET extension=excluded.extension, password=excluded.password,
                        govoice_user=excluded.govoice_user, account_password=excluded.account_password,
                        sip_user=excluded.sip_user, access_token=excluded.access_token, updated_at=excluded.updated_at""",
                 (username, extension, vault.encrypt(login["password"]), govoice_user, vault.encrypt(account_password),
                  login["sip_user"], vault.encrypt(login["access_token"]),
                  datetime.now().replace(microsecond=0).isoformat()))
    conn.commit()


def remove(username: str) -> bool:
    conn = db.connect()
    deleted = conn.execute("DELETE FROM softphones WHERE username=?", (username,)).rowcount
    conn.commit()
    return bool(deleted)


def _refresh(username: str, row) -> dict:
    """The SIP login and access token, fetched again from the phone system (they may have changed there). Falls back
    to the saved ones when it can't be reached; raises FetchError when it refuses the login."""
    saved = {"password": vault.decrypt(row["password"]), "sip_user": row["sip_user"],
             "access_token": vault.decrypt(row["access_token"])}
    if not row["govoice_user"]:  # set up before the phone system login was asked for
        return saved
    account_password = vault.decrypt(row["account_password"])
    if not account_password:  # refused earlier, or saved with an encryption key that is gone
        raise FetchError(f"{telephony.label()} refused the login {row['govoice_user']!r}", rejected=True)
    try:
        login = fetch_sip_login(row["govoice_user"], account_password)
    except FetchError as exc:
        if exc.rejected:  # forget the wrong password, so every page load doesn't send it again
            conn = db.connect()
            conn.execute("UPDATE softphones SET account_password=NULL WHERE username=?", (username,))
            conn.commit()
            raise
        return saved
    if login != saved:
        conn = db.connect()
        conn.execute("UPDATE softphones SET password=?, sip_user=?, access_token=?, updated_at=? WHERE username=?",
                     (vault.encrypt(login["password"]), login["sip_user"], vault.encrypt(login["access_token"]),
                      datetime.now().replace(microsecond=0).isoformat(), username))
        conn.commit()
    return login


def client_config(username: str, display_name: str | None) -> dict:
    """What the account's browser needs to register, or {"enabled": False, "reason": ...}."""
    conf = settings()
    row = db.connect().execute("SELECT * FROM softphones WHERE username=?", (username,)).fetchone()
    if not row:
        return {"enabled": False,
                "reason": f"No {telephony.label()} extension is set for your account yet: ask an admin (Users)"}
    try:
        login = _refresh(username, row)
    except FetchError as exc:
        return {"enabled": False, "reason": f"{exc}. Ask an admin to check the {telephony.label()} login in Users"}
    if not login["password"]:
        return {"enabled": False, "reason": "The saved SIP password can't be read (the encryption key changed): "
                                            "ask an admin to save your phone again in Users"}
    sip_user = login["sip_user"] or f"{conf['prefix']}{row['extension']}"
    return {"enabled": True, "ws_url": conf["ws_url"], "domain": conf["domain"],
            "uri": f"sip:{sip_user}@{conf['domain']}", "sip_user": sip_user, "password": login["password"],
            "access_token": login["access_token"] or "", "extension": row["extension"],
            "display_name": display_name or username, "ice_servers": conf["ice_servers"]}
