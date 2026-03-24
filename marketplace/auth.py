"""Auth helpers — JWT tokens and API key verification.

Supports dual auth: JWT (browser) and API key (programmatic).
Both consumers and bots can call consumer endpoints.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import time
from base64 import urlsafe_b64decode, urlsafe_b64encode
from functools import wraps
from typing import Optional

from flask import jsonify, request

log = logging.getLogger(__name__)

# Secret for JWT signing (should come from env in production)
JWT_SECRET = "2dollars-jwt-secret-change-in-production"
JWT_EXPIRY = 86400 * 7  # 7 days


# ── Simple JWT (no external deps) ────────────────────────────

def _b64e(data: bytes) -> str:
    return urlsafe_b64encode(data).rstrip(b"=").decode()


def _b64d(s: str) -> bytes:
    s += "=" * (4 - len(s) % 4)
    return urlsafe_b64decode(s)


def create_token(user_id: str, extra: dict | None = None) -> str:
    """Create a JWT-like token. Minimal implementation, no external deps."""
    header = _b64e(json.dumps({"alg": "HS256", "typ": "JWT"}).encode())
    payload_data = {
        "sub": user_id,
        "iat": int(time.time()),
        "exp": int(time.time()) + JWT_EXPIRY,
    }
    if extra:
        payload_data.update(extra)
    payload = _b64e(json.dumps(payload_data).encode())
    sig = _b64e(hmac.new(JWT_SECRET.encode(), f"{header}.{payload}".encode(), hashlib.sha256).digest())
    return f"{header}.{payload}.{sig}"


def verify_token(token: str) -> Optional[dict]:
    """Verify and decode a token. Returns payload or None."""
    try:
        parts = token.split(".")
        if len(parts) != 3:
            return None
        header, payload, sig = parts
        expected_sig = _b64e(hmac.new(JWT_SECRET.encode(), f"{header}.{payload}".encode(), hashlib.sha256).digest())
        if not hmac.compare_digest(sig, expected_sig):
            return None
        data = json.loads(_b64d(payload))
        if data.get("exp", 0) < time.time():
            return None
        return data
    except Exception:
        return None


# ── Request auth extraction ──────────────────────────────────

def get_auth_from_request() -> tuple[str, str]:
    """Extract auth type and credential from request.

    Returns: (auth_type, credential)
        auth_type: "jwt" | "consumer_key" | "provider_key" | "admin_key" | "none"
        credential: the token or key string
    """
    auth = request.headers.get("Authorization", "")
    if not auth.startswith("Bearer "):
        return "none", ""

    token = auth[7:].strip()

    # API keys by prefix
    if token.startswith("2d_ck_"):
        return "consumer_key", token
    if token.startswith("2d_sk_"):
        return "provider_key", token
    if token.startswith("2d_ak_"):
        return "admin_key", token

    # Otherwise assume JWT
    return "jwt", token


# ── Decorators ───────────────────────────────────────────────

def require_consumer(f):
    """Require consumer auth (JWT or consumer API key).

    Injects `consumer` as first argument.
    """
    @wraps(f)
    def wrapper(*args, **kwargs):
        from .consumer import get_consumer_store

        auth_type, credential = get_auth_from_request()
        consumer = None

        if auth_type == "jwt":
            payload = verify_token(credential)
            if payload:
                consumer = get_consumer_store().get(payload["sub"])
        elif auth_type == "consumer_key":
            consumer = get_consumer_store().get_by_api_key(credential)

        if not consumer:
            return jsonify({"error": "Authentication required", "code": "UNAUTHORIZED"}), 401
        if consumer.status != "active":
            return jsonify({"error": "Account suspended", "code": "FORBIDDEN"}), 403

        return f(consumer, *args, **kwargs)
    return wrapper


def require_provider(f):
    """Require provider auth (provider API key).

    Injects `listing` as first argument.
    """
    @wraps(f)
    def wrapper(*args, **kwargs):
        from .store import get_store

        auth_type, credential = get_auth_from_request()
        if auth_type != "provider_key":
            return jsonify({"error": "Provider API key required", "code": "UNAUTHORIZED"}), 401

        listing = get_store().get_by_api_key(credential)
        if not listing:
            return jsonify({"error": "Invalid API key", "code": "UNAUTHORIZED"}), 401

        return f(listing, *args, **kwargs)
    return wrapper
