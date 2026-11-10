import hashlib
import hmac
import os
from datetime import datetime, timedelta, timezone

import jwt

from app.core.config import settings

# --- Password hashing (stdlib PBKDF2-HMAC-SHA256, no native deps) ---
_ITERATIONS = 260_000
_ALGO = "pbkdf2_sha256"


def hash_password(password: str) -> str:
    salt = os.urandom(16)
    dk = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, _ITERATIONS)
    return f"{_ALGO}${_ITERATIONS}${salt.hex()}${dk.hex()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        algo, iters, salt_hex, hash_hex = stored.split("$")
        if algo != _ALGO:
            return False
        dk = hashlib.pbkdf2_hmac(
            "sha256", password.encode(), bytes.fromhex(salt_hex), int(iters)
        )
        return hmac.compare_digest(dk.hex(), hash_hex)
    except (ValueError, AttributeError):
        return False


# --- JWT (HS256, stdlib-backed) ---
def create_access_token(subject: str, role: str = "user") -> str:
    ttl = (
        settings.ADMIN_TOKEN_EXPIRE_MINUTES
        if role == "admin"
        else settings.ACCESS_TOKEN_EXPIRE_MINUTES
    )
    expire = datetime.now(timezone.utc) + timedelta(minutes=ttl)
    payload = {"sub": subject, "role": role, "exp": expire}
    return jwt.encode(payload, settings.JWT_SECRET, algorithm=settings.JWT_ALGORITHM)


def decode_access_token(token: str) -> dict:
    return jwt.decode(
        token, settings.JWT_SECRET, algorithms=[settings.JWT_ALGORITHM]
    )


# --- Short-lived signup token: proof that an email passed OTP verification ---
def create_signup_token(email: str, minutes: int = 15) -> str:
    expire = datetime.now(timezone.utc) + timedelta(minutes=minutes)
    payload = {"sub": email, "purpose": "signup", "exp": expire}
    return jwt.encode(payload, settings.JWT_SECRET, algorithm=settings.JWT_ALGORITHM)


def decode_signup_token(token: str) -> str:
    """Return the verified email from a signup token, or raise if invalid."""
    payload = jwt.decode(token, settings.JWT_SECRET, algorithms=[settings.JWT_ALGORITHM])
    if payload.get("purpose") != "signup":
        raise ValueError("Not a signup token")
    return payload["sub"]
