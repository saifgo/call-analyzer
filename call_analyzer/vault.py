"""Encryption at rest for the credentials kept in the database (the softphones' GoVoice and SIP passwords).

Values are encrypted with Fernet (AES-128-CBC + HMAC-SHA256) and stored as "enc1:<token>". The key is SECRET_KEY
when set (any passphrase; it is hashed into a key), else a random key generated once into data/secret.key. Back that
file up with the database: without it the saved passwords can't be read and have to be entered again.

Values saved before encryption existed have no prefix; they are still read as they are, and db.connect() encrypts
them in place.
"""
import base64
import hashlib
import os
import threading

from .config import live, settings

PREFIX = "enc1:"
_lock = threading.Lock()
_fernet = None
_fernet_source: str | None = None


def key_path():
    return settings.data_dir / "secret.key"


def _load_key() -> tuple[bytes, str]:
    """The Fernet key and where it comes from (to notice SECRET_KEY changing while running)."""
    secret = live("SECRET_KEY")
    if secret:
        return base64.urlsafe_b64encode(hashlib.sha256(secret.encode()).digest()), f"env:{secret}"
    path = key_path()
    if not path.exists():
        from cryptography.fernet import Fernet
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        tmp.write_bytes(Fernet.generate_key())
        try:
            os.chmod(tmp, 0o600)
        except OSError:
            pass
        try:
            os.link(tmp, path)  # fails if another process created the key meanwhile: keep theirs
        except FileExistsError:
            pass
        except OSError:
            if not path.exists():
                tmp.replace(path)
        tmp.unlink(missing_ok=True)
    return path.read_bytes().strip(), f"file:{path}"


def _cipher():
    global _fernet, _fernet_source
    from cryptography.fernet import Fernet
    with _lock:
        key, source = _load_key()
        if _fernet is None or source != _fernet_source:
            _fernet, _fernet_source = Fernet(key), source
        return _fernet


def is_encrypted(value: str | None) -> bool:
    return bool(value) and value.startswith(PREFIX)


def encrypt(value: str | None) -> str | None:
    """Encrypt a secret for the database. None and "" stay as they are, so "not set" still reads as not set."""
    if not value or is_encrypted(value):
        return value
    return PREFIX + _cipher().encrypt(value.encode()).decode()


def decrypt(value: str | None) -> str | None:
    """The secret saved with encrypt(). Unencrypted (older) values come back as they are; a value that can't be
    decrypted (the key was lost or changed) comes back as None, as if it had never been saved."""
    if not is_encrypted(value):
        return value
    from cryptography.fernet import InvalidToken
    try:
        return _cipher().decrypt(value[len(PREFIX):].encode()).decode()
    except (InvalidToken, ValueError):
        return None
