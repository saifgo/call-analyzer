"""User accounts and login sessions, stored in the same SQLite database as the calls."""
import hashlib
import hmac
import re
import secrets
from datetime import datetime, timedelta

from . import db
from .config import settings

# scrypt parameters (~16 MB of memory, ~50 ms per hash): slow enough to make password guessing expensive.
SCRYPT_N, SCRYPT_R, SCRYPT_P = 2 ** 14, 8, 1
MIN_PASSWORD_LENGTH = 8


def _now() -> datetime:
    return datetime.now().replace(microsecond=0)


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.scrypt(password.encode(), salt=salt, n=SCRYPT_N, r=SCRYPT_R, p=SCRYPT_P)
    return f"scrypt${SCRYPT_N}${SCRYPT_R}${SCRYPT_P}${salt.hex()}${digest.hex()}"


def check_password(password: str, stored: str) -> bool:
    try:
        _, n, r, p, salt, digest = stored.split("$")
        actual = hashlib.scrypt(password.encode(), salt=bytes.fromhex(salt), n=int(n), r=int(r), p=int(p))
    except ValueError:
        return False
    return hmac.compare_digest(actual.hex(), digest)


# A real hash to compare against when the user doesn't exist, so response time doesn't reveal valid usernames.
_DUMMY_HASH = hash_password(secrets.token_hex(8))


# --- Users ------------------------------------------------------------------------------------
# Roles: "admin" sees and manages everything; "agent" only sees the calls and reports of the agent
# extensions linked to the account (read-only).

ROLES = ("admin", "agent")
USERNAME_RE = re.compile(r"^[\w.@-]{1,64}$")


def list_users() -> list[str]:
    return [r[0] for r in db.connect().execute("SELECT username FROM users ORDER BY username")]


def user_exists(username: str) -> bool:
    return db.connect().execute("SELECT 1 FROM users WHERE username=?", (username,)).fetchone() is not None


def _agents_by_user(conn) -> dict[str, list[str]]:
    linked: dict[str, list[str]] = {}
    for username, agent in conn.execute("SELECT username, agent FROM user_agents ORDER BY agent"):
        linked.setdefault(username, []).append(agent)
    return linked


def get_user(username: str) -> dict | None:
    """{username, role, display_name, agents, created_at}, or None."""
    conn = db.connect()
    row = conn.execute("SELECT username, role, display_name, created_at FROM users WHERE username=?",
                       (username,)).fetchone()
    if not row:
        return None
    agents = [r[0] for r in conn.execute("SELECT agent FROM user_agents WHERE username=? ORDER BY agent", (username,))]
    return {**dict(row), "agents": agents}


def list_accounts() -> list[dict]:
    conn = db.connect()
    linked = _agents_by_user(conn)
    rows = conn.execute("SELECT username, role, display_name, created_at FROM users ORDER BY username")
    return [{**dict(r), "agents": linked.get(r["username"], [])} for r in rows]


def admin_count() -> int:
    return db.connect().execute("SELECT COUNT(*) FROM users WHERE role='admin'").fetchone()[0]


def _clean_agents(agents) -> list[str]:
    return sorted({a.strip() for a in agents if a and a.strip()})


def set_password(username: str, password: str):
    """Create the user (as an admin), or change their password (which also signs them out everywhere)."""
    if len(password) < MIN_PASSWORD_LENGTH:
        raise ValueError(f"Password must be at least {MIN_PASSWORD_LENGTH} characters")
    conn = db.connect()
    conn.execute("""INSERT INTO users (username, password_hash, created_at) VALUES (?, ?, ?)
                    ON CONFLICT(username) DO UPDATE SET password_hash=excluded.password_hash""",
                 (username, hash_password(password), _now().isoformat()))
    conn.execute("DELETE FROM sessions WHERE username=?", (username,))
    conn.commit()


def create_user(username: str, password: str, role: str = "admin", display_name: str = "",
                agents: list[str] = ()):
    if not USERNAME_RE.match(username):
        raise ValueError("Username can only use letters, digits and . _ @ - (up to 64 characters)")
    if user_exists(username):
        raise ValueError(f"User {username!r} already exists")
    if role not in ROLES:
        raise ValueError(f"Role must be one of {', '.join(ROLES)}")
    if len(password) < MIN_PASSWORD_LENGTH:
        raise ValueError(f"Password must be at least {MIN_PASSWORD_LENGTH} characters")
    conn = db.connect()
    conn.execute("INSERT INTO users (username, password_hash, created_at, role, display_name) VALUES (?, ?, ?, ?, ?)",
                 (username, hash_password(password), _now().isoformat(), role, display_name.strip() or None))
    conn.executemany("INSERT INTO user_agents (username, agent) VALUES (?, ?)",
                     [(username, a) for a in _clean_agents(agents)])
    conn.commit()


def update_user(username: str, *, role: str | None = None, display_name: str | None = None,
                agents: list[str] | None = None):
    """Change an account's role, name or linked agent extensions. A role change signs them out everywhere."""
    current = get_user(username)
    if not current:
        raise ValueError(f"No user {username!r}")
    conn = db.connect()
    if role is not None and role != current["role"]:
        if role not in ROLES:
            raise ValueError(f"Role must be one of {', '.join(ROLES)}")
        if current["role"] == "admin" and admin_count() <= 1:
            raise ValueError("This is the last admin account; make another admin first")
        conn.execute("UPDATE users SET role=? WHERE username=?", (role, username))
        conn.execute("DELETE FROM sessions WHERE username=?", (username,))
    if display_name is not None:
        conn.execute("UPDATE users SET display_name=? WHERE username=?", (display_name.strip() or None, username))
    if agents is not None:
        conn.execute("DELETE FROM user_agents WHERE username=?", (username,))
        conn.executemany("INSERT INTO user_agents (username, agent) VALUES (?, ?)",
                         [(username, a) for a in _clean_agents(agents)])
    conn.commit()


def delete_user(username: str) -> bool:
    user = get_user(username)
    if user and user["role"] == "admin" and admin_count() <= 1:
        raise ValueError("This is the last admin account; make another admin first")
    conn = db.connect()
    conn.execute("DELETE FROM sessions WHERE username=?", (username,))
    conn.execute("DELETE FROM user_agents WHERE username=?", (username,))
    deleted = conn.execute("DELETE FROM users WHERE username=?", (username,)).rowcount
    conn.commit()
    return bool(deleted)


def authenticate(username: str, password: str) -> bool:
    row = db.connect().execute("SELECT password_hash FROM users WHERE username=?", (username,)).fetchone()
    ok = check_password(password, row[0] if row else _DUMMY_HASH)
    return ok and row is not None


def ensure_admin():
    """Create ADMIN_USERNAME with ADMIN_PASSWORD at startup if that account doesn't exist yet."""
    if settings.admin_username and settings.admin_password and not user_exists(settings.admin_username):
        try:
            set_password(settings.admin_username, settings.admin_password)
        except ValueError as exc:  # don't stop the server over a bad setting; it stays locked behind login
            print(f"WARNING: user {settings.admin_username!r} not created from ADMIN_PASSWORD: {exc}")
            return
        print(f"Created user {settings.admin_username!r} from ADMIN_USERNAME/ADMIN_PASSWORD")


# --- Sessions ---------------------------------------------------------------------------------
# The cookie holds a random token; only its SHA-256 is stored, so a leaked database can't be used to log in.

def _token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def create_session(username: str) -> str:
    token = secrets.token_urlsafe(32)
    now = _now()
    conn = db.connect()
    conn.execute("DELETE FROM sessions WHERE expires_at < ?", (now.isoformat(),))
    conn.execute("INSERT INTO sessions (token_hash, username, created_at, expires_at) VALUES (?, ?, ?, ?)",
                 (_token_hash(token), username, now.isoformat(),
                  (now + timedelta(days=settings.session_days)).isoformat()))
    conn.commit()
    return token


def session_user(token: str | None) -> str | None:
    if not token:
        return None
    row = db.connect().execute("SELECT username FROM sessions WHERE token_hash=? AND expires_at > ?",
                               (_token_hash(token), _now().isoformat())).fetchone()
    return row[0] if row else None


def delete_session(token: str | None):
    if token:
        conn = db.connect()
        conn.execute("DELETE FROM sessions WHERE token_hash=?", (_token_hash(token),))
        conn.commit()
