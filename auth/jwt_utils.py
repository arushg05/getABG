"""
getABG Auth — JWT Token Utilities
Short-lived access tokens (httpOnly cookie) + rotating refresh tokens.
"""

import os
import uuid
import hashlib
import secrets
from datetime import datetime, timedelta, timezone
from typing import Optional, Tuple, Dict

import jwt

# ── Configuration ─────────────────────────────────────────────────────────────

SECRET_KEY = os.environ.get("AUTH_SECRET", "getABG-dev-secret-change-in-production")
ALGORITHM = "HS256"

ACCESS_TOKEN_EXPIRY_MINUTES = 15          # Short-lived access token
REFRESH_TOKEN_EXPIRY_DAYS = 30            # Long-lived refresh token


# ── Access Tokens ─────────────────────────────────────────────────────────────

def generate_access_token(user_id: str, email: str, plan: str) -> str:
    """Create a short-lived JWT access token."""
    now = datetime.now(timezone.utc)
    payload = {
        "sub": user_id,
        "email": email,
        "plan": plan,
        "iat": now,
        "exp": now + timedelta(minutes=ACCESS_TOKEN_EXPIRY_MINUTES),
        "type": "access",
    }
    return jwt.encode(payload, SECRET_KEY, algorithm=ALGORITHM)


def decode_access_token(token: str) -> Dict:
    """Decode and validate an access token. Raises jwt.InvalidTokenError on failure."""
    payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
    if payload.get("type") != "access":
        raise jwt.InvalidTokenError("Not an access token")
    return payload


# ── Refresh Tokens ────────────────────────────────────────────────────────────

def generate_refresh_token() -> Tuple[str, str, str, str]:
    """
    Generate a new refresh token.
    Returns: (token_id, raw_token, token_hash, expires_at_iso)
    - token_id: unique identifier stored in DB
    - raw_token: the actual secret sent to client (cookie value)
    - token_hash: SHA-256 hash stored in DB (never store raw token)
    - expires_at_iso: ISO expiry timestamp
    """
    token_id = str(uuid.uuid4())
    raw_token = secrets.token_urlsafe(48)
    token_hash = hashlib.sha256(raw_token.encode()).hexdigest()
    expires_at = (datetime.now(timezone.utc) + timedelta(days=REFRESH_TOKEN_EXPIRY_DAYS)).isoformat()
    return token_id, raw_token, token_hash, expires_at


def verify_refresh_token_hash(raw_token: str, stored_hash: str) -> bool:
    """Verify a raw refresh token against its stored hash."""
    return hashlib.sha256(raw_token.encode()).hexdigest() == stored_hash


def is_refresh_token_expired(expires_at_iso: str) -> bool:
    """Check if a refresh token has expired."""
    expires_at = datetime.fromisoformat(expires_at_iso)
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=timezone.utc)
    return datetime.now(timezone.utc) > expires_at
