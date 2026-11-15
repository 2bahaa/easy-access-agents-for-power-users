"""Credential primitives: password hashing, JWT access tokens, opaque tokens and API keys.

Pure functions (no DB, no FastAPI) so they are easy to test and reuse.
"""

import hashlib
import hmac
import secrets
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError

_hasher = PasswordHasher()  # argon2id with library defaults (OWASP-recommended)
JWT_ALGORITHM = "HS256"
API_KEY_PREFIX = "eaa_"


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(password_hash: str, password: str) -> bool:
    try:
        return _hasher.verify(password_hash, password)
    except (VerifyMismatchError, VerificationError, InvalidHashError):
        return False


# A valid hash to verify against when the user does not exist, so login timing does not
# reveal which emails are registered.
DUMMY_PASSWORD_HASH = hash_password(secrets.token_urlsafe(16))


def sha256_hex(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def new_opaque_token() -> str:
    return secrets.token_urlsafe(32)


@dataclass(frozen=True)
class AccessClaims:
    user_id: uuid.UUID
    expires_at: datetime


def create_access_token(secret: str, user_id: uuid.UUID, ttl_s: int) -> tuple[str, datetime]:
    now = datetime.now(UTC)
    expires = now + timedelta(seconds=ttl_s)
    payload: dict[str, Any] = {
        "sub": str(user_id),
        "iat": int(now.timestamp()),
        "exp": int(expires.timestamp()),
        "typ": "access",
    }
    return jwt.encode(payload, secret, algorithm=JWT_ALGORITHM), expires


def decode_access_token(secret: str, token: str) -> AccessClaims | None:
    """Return the claims of a valid, unexpired access token; None otherwise."""
    try:
        payload = jwt.decode(
            token, secret, algorithms=[JWT_ALGORITHM], options={"require": ["sub", "exp", "typ"]}
        )
        if payload.get("typ") != "access":
            return None
        return AccessClaims(
            user_id=uuid.UUID(payload["sub"]),
            expires_at=datetime.fromtimestamp(payload["exp"], UTC),
        )
    except (jwt.PyJWTError, ValueError, KeyError):
        return None


@dataclass(frozen=True)
class GeneratedApiKey:
    token: str  # shown to the user once
    prefix: str  # stored, used for lookup
    key_hash: str  # stored


def generate_api_key() -> GeneratedApiKey:
    prefix = secrets.token_hex(6)  # 12 hex chars
    secret = secrets.token_urlsafe(32)
    token = f"{API_KEY_PREFIX}{prefix}_{secret}"
    return GeneratedApiKey(token=token, prefix=prefix, key_hash=sha256_hex(token))


def parse_api_key(token: str) -> str | None:
    """Return the lookup prefix of a well-formed API key, else None."""
    if not token.startswith(API_KEY_PREFIX):
        return None
    prefix, sep, secret = token.removeprefix(API_KEY_PREFIX).partition("_")
    if not sep or len(prefix) != 12 or not secret:
        return None
    return prefix


def api_key_matches(token: str, key_hash: str) -> bool:
    return hmac.compare_digest(sha256_hex(token), key_hash)
