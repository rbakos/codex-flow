from __future__ import annotations

from typing import Optional
from .config import settings

try:
    from cryptography.fernet import Fernet
except Exception:  # pragma: no cover - optional dependency
    Fernet = None  # type: ignore


def _get_fernet() -> Optional[Fernet]:  # type: ignore
    key = settings.secret_key
    if not key or not Fernet:
        return None
    # Accept both urlsafe base64 fernet keys and raw 32-byte base64 strings
    try:
        return Fernet(key)  # type: ignore
    except Exception:
        return None


def encrypt_text(plain: str) -> tuple[str, bool]:
    f = _get_fernet()
    if not f:
        return plain, False
    token = f.encrypt(plain.encode("utf-8"))
    return token.decode("utf-8"), True


def decrypt_text(token: str) -> tuple[str, bool]:
    f = _get_fernet()
    if not f:
        return token, False
    try:
        plain = f.decrypt(token.encode("utf-8")).decode("utf-8")
        return plain, True
    except Exception:
        return token, False

