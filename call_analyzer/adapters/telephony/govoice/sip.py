"""The SIP sign-in of a GoVoice account, fetched the way GoVoice's own web phone does it."""
import requests

from ....config import live, settings
from ..base import SipLoginError

SIP_API_TIMEOUT = 15
# The Authorization header GoVoice's web app sends before it has an access token (a fixed placeholder JWT).
WEB_APP_TOKEN = ("eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiIxMjM0NTY3ODkwIiwibmFtZSI6IkpvaG4gRG9lIiwiaWF0IjoxNT"
                 "E2MjM5MDIyfQ.SflKxwRJSMeKKF2QT4fwpMeJf36POk6yJV_adQssw5c")


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
        raise SipLoginError(f"Can't reach GoVoice: {exc}")
    try:
        data = resp.json()
    except ValueError:
        data = None
    if not isinstance(data, dict):
        data = None
    status = (data.get("etat_ws") or data.get("etat_utilisateur")) if data else None
    if resp.status_code in (401, 403):
        raise SipLoginError(f"GoVoice refused the login {login!r}: {status or resp.reason}", rejected=True)
    if not resp.ok or data is None:
        raise SipLoginError(f"GoVoice answered {resp.status_code} {status or resp.text[:200]!r}")
    return data


def fetch_sip_login(govoice_user: str, account_password: str) -> dict:
    """The SIP sign-in of a GoVoice account, the way GoVoice's web app gets it: log in, get an access token, then
    ask for the SIP account. {"sip_user": "1759512535_100", "password": ..., "access_token": ...}; GoVoice wants the
    access token on every call the phone makes (X-Custom-Header)."""
    api = live("GOVOICE_BASE_URL", settings.govoice_base_url).rstrip("/") + "/govoice/Api/WS/"
    session = requests.Session()
    session.verify = live("GOVOICE_VERIFY_SSL", "true").lower() in ("1", "true", "yes", "on")
    session.headers.update({"Accept": "application/json, text/plain, */*", "Referer": "https://otn.govoice.tn/"})
    # 1. Log in (sets the session cookie): {"compte": "TuniVocher", "type_protocole": "WEBRTC"}
    account = _get_json(session, api + "CompteUtilisateur",
                        {"type_connexion": "web", "mobile": "", "login": govoice_user, "pwd": account_password},
                        WEB_APP_TOKEN, govoice_user).get("compte")
    if not account:
        raise SipLoginError(f"GoVoice refused the login {govoice_user!r}", rejected=True)
    # 2. Access token: {"etat_utilisateur": "OK", "poste": "100", "AccessToken": "$2y$10$...", ...}
    ipbx = _get_json(session, api + "ConnexionIPBXV3API",
                     {"compte": account, "login": govoice_user, "passwd": account_password}, WEB_APP_TOKEN, govoice_user)
    if str(ipbx.get("etat_utilisateur")).upper() != "OK" or not ipbx.get("AccessToken"):
        raise SipLoginError(f"GoVoice refused the login {govoice_user!r}: {ipbx.get('etat_utilisateur')}",
                            rejected=True)
    # 3. SIP account (opaque parameter names): {"param_1": "<SIP username>", "param_2": "<SIP password>", ...},
    #    both shifted (see _unshift)
    sip = _get_json(session, api + "Etncuje3kifh698dh13",
                    {"98sfdh3hjf": account, "DSf536kv90": govoice_user, "48772Jhcbz": account_password,
                     "39Jehgr2": ipbx.get("poste", "")}, ipbx["AccessToken"], govoice_user)
    sip_user, password = _unshift(str(sip.get("param_1") or "").strip()), _unshift(str(sip.get("param_2") or ""))
    if not sip_user or not password:
        raise SipLoginError(f"No SIP login in GoVoice's answer ({sip.get('etat_ws') or ', '.join(sorted(sip))})")
    return {"sip_user": sip_user, "password": password, "access_token": ipbx["AccessToken"]}
