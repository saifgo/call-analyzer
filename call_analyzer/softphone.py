"""Browser softphone: the GoVoice SIP account each user signs in with from the web UI.

GoVoice is an Asterisk PBX with a WebRTC WebSocket (SOFTPHONE_WS_URL). The browser connects to it directly
(frontend/src/lib/softphone.tsx) and registers with the SIP username and password GoVoice gives the account. The
server keeps each account's extension and GoVoice login (e.g. user100 and its My Account password), fetches the SIP
sign-in from GoVoice's API with that login (fetch_sip_login), and hands it to that account's own browser. The passwords
and the access token are encrypted in the database (vault.py).
"""
import re
from datetime import datetime

import requests

from . import db, vault
from .config import live, settings as app_settings

EXTENSION_RE = re.compile(r"^\d{1,6}$")
SIP_API_TIMEOUT = 15
# The Authorization header GoVoice's web app sends before it has an access token (a fixed placeholder JWT).
WEB_APP_TOKEN = ("eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiIxMjM0NTY3ODkwIiwibmFtZSI6IkpvaG4gRG9lIiwiaWF0IjoxNT"
                 "E2MjM5MDIyfQ.SflKxwRJSMeKKF2QT4fwpMeJf36POk6yJV_adQssw5c")


class FetchError(Exception):
    """GoVoice didn't give the SIP password. rejected: it refused the login (not a network problem)."""

    def __init__(self, message: str, rejected: bool = False):
        super().__init__(message)
        self.rejected = rejected


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


def _tenant_prefix() -> str:
    """GoVoice SIP usernames are <tenant>_<extension>; the recordings folder (govoice_enreg_<tenant>) names the tenant."""
    match = re.search(r"_(\d+)$", live("GOVOICE_RECORDINGS_DIR"))
    return f"{match.group(1)}_" if match else ""


def settings() -> dict:
    return {"ws_url": live("SOFTPHONE_WS_URL", "wss://otn.govoice.tn:8089/ws"),
            "domain": live("SOFTPHONE_DOMAIN", "otn.govoice.tn"),
            "prefix": live("SOFTPHONE_USER_PREFIX") or _tenant_prefix(),
            "ice_servers": ice_servers(live("SOFTPHONE_ICE_SERVERS", "stun:stun.l.google.com:19302"))}


def _unshift(value: str, shift: int = 3) -> str:
    """GoVoice sends the SIP login Caesar-shifted (letters and digits moved 3 forward); its web phone shifts it back
    before signing in. 4082845868_433 -> 1759512535_100."""
    out = []
    for ch in value:
        if ch.isascii() and ch.isalpha():
            base = ord("A") if ch.isupper() else ord("a")
            out.append(chr((ord(ch) - base - shift) % 26 + base))
        elif ch.isascii() and ch.isdigit():
            out.append(chr((ord(ch) - ord("0") - shift) % 10 + ord("0")))
        else:
            out.append(ch)
    return "".join(out)


def _get_json(session: requests.Session, url: str, params: dict, token: str, login: str) -> dict:
    try:
        resp = session.get(url, params=params, headers={"Authorization": token}, timeout=SIP_API_TIMEOUT)
    except requests.RequestException as exc:
        raise FetchError(f"Can't reach GoVoice: {exc}")
    try:
        data = resp.json()
    except ValueError:
        data = None
    if not isinstance(data, dict):
        data = None
    status = (data.get("etat_ws") or data.get("etat_utilisateur")) if data else None
    if resp.status_code in (401, 403):
        raise FetchError(f"GoVoice refused the login {login!r}: {status or resp.reason}", rejected=True)
    if not resp.ok or data is None:
        raise FetchError(f"GoVoice answered {resp.status_code} {status or resp.text[:200]!r}")
    return data


def fetch_sip_login(govoice_user: str, account_password: str) -> dict:
    """The SIP sign-in of a GoVoice account, the way GoVoice's web app gets it: log in, get an access token, then
    ask for the SIP account. {"sip_user": "1759512535_100", "password": ..., "access_token": ...}; GoVoice wants the
    access token on every call the phone makes (X-Custom-Header)."""
    api = live("GOVOICE_BASE_URL", app_settings.govoice_base_url).rstrip("/") + "/govoice/Api/WS/"
    session = requests.Session()
    session.verify = live("GOVOICE_VERIFY_SSL", "true").lower() in ("1", "true", "yes", "on")
    session.headers.update({"Accept": "application/json, text/plain, */*", "Referer": "https://otn.govoice.tn/"})
    # 1. Log in (sets the session cookie): {"compte": "TuniVocher", "type_protocole": "WEBRTC"}
    account = _get_json(session, api + "CompteUtilisateur",
                        {"type_connexion": "web", "mobile": "", "login": govoice_user, "pwd": account_password},
                        WEB_APP_TOKEN, govoice_user).get("compte")
    if not account:
        raise FetchError(f"GoVoice refused the login {govoice_user!r}", rejected=True)
    # 2. Access token: {"etat_utilisateur": "OK", "poste": "100", "AccessToken": "$2y$10$...", ...}
    ipbx = _get_json(session, api + "ConnexionIPBXV3API",
                     {"compte": account, "login": govoice_user, "passwd": account_password}, WEB_APP_TOKEN, govoice_user)
    if str(ipbx.get("etat_utilisateur")).upper() != "OK" or not ipbx.get("AccessToken"):
        raise FetchError(f"GoVoice refused the login {govoice_user!r}: {ipbx.get('etat_utilisateur')}", rejected=True)
    # 3. SIP account (opaque parameter names): {"param_1": "<SIP username>", "param_2": "<SIP password>", ...},
    #    both shifted (see _unshift)
    sip = _get_json(session, api + "Etncuje3kifh698dh13",
                    {"98sfdh3hjf": account, "DSf536kv90": govoice_user, "48772Jhcbz": account_password,
                     "39Jehgr2": ipbx.get("poste", "")}, ipbx["AccessToken"], govoice_user)
    sip_user, password = _unshift(str(sip.get("param_1") or "").strip()), _unshift(str(sip.get("param_2") or ""))
    if not sip_user or not password:
        raise FetchError(f"No SIP login in GoVoice's answer ({sip.get('etat_ws') or ', '.join(sorted(sip))})")
    return {"sip_user": sip_user, "password": password, "access_token": ipbx["AccessToken"]}


def extensions() -> dict[str, dict]:
    """username -> {"extension", "govoice_user"}, for every account that has a softphone."""
    rows = db.connect().execute("SELECT username, extension, govoice_user FROM softphones").fetchall()
    return {r["username"]: {"extension": r["extension"], "govoice_user": r["govoice_user"] or ""} for r in rows}


def save(username: str, extension: str, govoice_user: str, account_password: str | None):
    """Set an account's extension and GoVoice login, and fetch its SIP password straight away (so a wrong login
    shows up here). account_password None keeps the saved one (only allowed when there is one)."""
    extension, govoice_user = extension.strip(), govoice_user.strip()
    if not EXTENSION_RE.match(extension):
        raise ValueError("The extension is the short GoVoice number, digits only (e.g. 100)")
    if not govoice_user:
        raise ValueError("Enter the GoVoice username (e.g. user100)")
    conn = db.connect()
    if not account_password:
        row = conn.execute("SELECT account_password FROM softphones WHERE username=?", (username,)).fetchone()
        account_password = vault.decrypt(row[0]) if row else None
        if not account_password:
            raise ValueError("Enter the GoVoice account password")
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
    """The SIP login and access token, fetched again from GoVoice (they may have changed there). Falls back to the
    saved ones when GoVoice can't be reached; raises FetchError when GoVoice refuses the login."""
    saved = {"password": vault.decrypt(row["password"]), "sip_user": row["sip_user"],
             "access_token": vault.decrypt(row["access_token"])}
    if not row["govoice_user"]:  # set up before the GoVoice login was asked for
        return saved
    account_password = vault.decrypt(row["account_password"])
    if not account_password:  # refused earlier, or saved with an encryption key that is gone
        raise FetchError(f"GoVoice refused the login {row['govoice_user']!r}", rejected=True)
    try:
        login = fetch_sip_login(row["govoice_user"], account_password)
    except FetchError as exc:
        if exc.rejected:  # forget the wrong password, so every page load doesn't send it to GoVoice again
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
        return {"enabled": False, "reason": "No GoVoice extension is set for your account yet: ask an admin (Users)"}
    try:
        login = _refresh(username, row)
    except FetchError as exc:
        return {"enabled": False, "reason": f"{exc}. Ask an admin to check the GoVoice login in Users"}
    if not login["password"]:
        return {"enabled": False, "reason": "The saved SIP password can't be read (the encryption key changed): "
                                            "ask an admin to save your phone again in Users"}
    sip_user = login["sip_user"] or f"{conf['prefix']}{row['extension']}"
    return {"enabled": True, "ws_url": conf["ws_url"], "domain": conf["domain"],
            "uri": f"sip:{sip_user}@{conf['domain']}", "sip_user": sip_user, "password": login["password"],
            "access_token": login["access_token"] or "", "extension": row["extension"],
            "display_name": display_name or username, "ice_servers": conf["ice_servers"]}
