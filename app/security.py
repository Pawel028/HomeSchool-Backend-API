"""Password/PIN hashing and token helpers."""

from __future__ import annotations

import hashlib
import secrets
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError

from app.config import get_settings

_hashers: dict[str, PasswordHasher] = {}


def _hasher() -> PasswordHasher:
    env = get_settings().app_env
    if env not in _hashers:
        # Cheaper parameters in tests only; production uses the library defaults (argon2id).
        _hashers[env] = (
            PasswordHasher(time_cost=1, memory_cost=8 * 1024, parallelism=1) if env == "test" else PasswordHasher()
        )
    return _hashers[env]


def hash_secret(value: str) -> str:
    return _hasher().hash(value)


def verify_secret(hashed: str, value: str) -> bool:
    try:
        return _hasher().verify(hashed, value)
    except (VerifyMismatchError, VerificationError, InvalidHashError):
        return False


def new_opaque_token() -> tuple[str, str]:
    """Returns (token, sha256 hex digest). Only the digest is stored."""
    token = secrets.token_urlsafe(48)
    return token, token_digest(token)


def token_digest(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def now() -> datetime:
    return datetime.now(UTC)


def _encode(claims: dict[str, Any], ttl: timedelta) -> str:
    s = get_settings()
    issued = now()
    payload = {"iss": s.jwt_issuer, "iat": issued, "exp": issued + ttl, "jti": str(uuid.uuid4()), **claims}
    return jwt.encode(payload, s.jwt_secret.get_secret_value(), algorithm="HS256")


def decode_token(token: str, expected_type: str | None = None) -> dict[str, Any]:
    s = get_settings()
    claims = jwt.decode(
        token,
        s.jwt_secret.get_secret_value(),
        algorithms=["HS256"],
        issuer=s.jwt_issuer,
        options={"require": ["exp", "iat", "iss", "sub", "typ"]},
    )
    if expected_type and claims.get("typ") != expected_type:
        raise jwt.InvalidTokenError("wrong token type")
    return claims


def create_access_token(user_id: uuid.UUID) -> str:
    return _encode({"sub": str(user_id), "typ": "access"}, timedelta(minutes=get_settings().access_token_minutes))


def create_elevation_token(user_id: uuid.UUID) -> str:
    return _encode({"sub": str(user_id), "typ": "elev"}, timedelta(minutes=get_settings().elevation_minutes))


def create_child_token(
    child_id: uuid.UUID, family_id: uuid.UUID, session_id: uuid.UUID, device_id: str
) -> tuple[str, datetime]:
    ttl = timedelta(minutes=get_settings().child_token_minutes)
    token = _encode(
        {
            "sub": str(child_id),
            "typ": "child",
            "scope": "child:learn",
            "fam": str(family_id),
            "sid": str(session_id),
            "did": device_id,
        },
        ttl,
    )
    return token, now() + ttl
