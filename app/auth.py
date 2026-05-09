from __future__ import annotations

import base64
import hashlib
import secrets
from typing import Optional

from fastapi import HTTPException
from starlette.requests import Request

from .db import get_connection


SESSION_USERNAME_KEY = "username"

_PBKDF2_ALGO = "sha256"
_DEFAULT_ITERATIONS = 310_000
_SALT_BYTES = 16
_DK_BYTES = 32


def hash_password(password: str) -> str:
    if not isinstance(password, str):
        raise TypeError("password must be a string")
    password_b = password.encode("utf-8")
    salt = secrets.token_bytes(_SALT_BYTES)
    iterations = _DEFAULT_ITERATIONS
    dk = hashlib.pbkdf2_hmac(_PBKDF2_ALGO, password_b, salt, iterations, dklen=_DK_BYTES)

    return "pbkdf2_sha256$" + str(iterations) + "$" + _b64(salt) + "$" + _b64(dk)


def verify_password(password: str, password_hash: str) -> bool:
    try:
        algo, iters_s, salt_b64, dk_b64 = password_hash.split("$", 3)
    except ValueError:
        return False
    if algo != "pbkdf2_sha256":
        return False

    try:
        iterations = int(iters_s)
    except ValueError:
        return False

    salt = _unb64(salt_b64)
    expected = _unb64(dk_b64)
    actual = hashlib.pbkdf2_hmac(
        _PBKDF2_ALGO,
        password.encode("utf-8"),
        salt,
        iterations,
        dklen=len(expected),
    )
    return secrets.compare_digest(actual, expected)


def _b64(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode("ascii")


def _unb64(s: str) -> bytes:
    return base64.urlsafe_b64decode(s.encode("ascii"))


def create_user(conn, *, username: str, password: str, is_active: bool = True) -> None:
    username = username.strip()
    if not username:
        raise ValueError("username cannot be empty")
    if len(password) < 8:
        raise ValueError("password must be at least 8 chars")

    conn.execute(
        """
        INSERT INTO users(username, password_hash, is_active)
        VALUES (?, ?, ?)
        ON CONFLICT(username) DO UPDATE SET
            password_hash = excluded.password_hash,
            is_active = excluded.is_active
        """,
        (username, hash_password(password), 1 if is_active else 0),
    )
    conn.commit()


def authenticate_user(conn, *, username: str, password: str) -> bool:
    row = conn.execute(
        "SELECT username, password_hash, is_active FROM users WHERE username = ?",
        (username,),
    ).fetchone()
    if row is None:
        return False
    if row["is_active"] != 1:
        return False
    return verify_password(password, row["password_hash"])


def get_session_username(request: Request) -> Optional[str]:
    username = request.session.get(SESSION_USERNAME_KEY)
    if username is None:
        return None
    if not isinstance(username, str):
        return None
    username = username.strip()
    return username or None


def require_active_user(request: Request, *, db_path: str) -> str:
    username = get_session_username(request)
    if not username:
        raise HTTPException(status_code=401, detail="Unauthorized")

    conn = get_connection(db_path)
    try:
        row = conn.execute("SELECT username, is_active FROM users WHERE username = ?", (username,)).fetchone()
        if row is None or row["is_active"] != 1:
            raise HTTPException(status_code=401, detail="Unauthorized")
        return username
    finally:
        conn.close()

