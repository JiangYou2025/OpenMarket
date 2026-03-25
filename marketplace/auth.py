"""Auth — delegates user authentication to odysseeia.com Claw API.

Token types:
  - at_xxx  — user auth token (login session)
  - tgp_xxx — user API token (programmatic)
  - sk_xxx  — server token (our server calling Claw)
  - om_sk_  — provider API key (bot self-service, local to OpenMarket)
  - om_ak_  — admin key (local to OpenMarket)

Consumer auth flow:
  1. User passes `at_` or `tgp_` token in Authorization header
  2. OpenMarket calls Claw `GET /api/v1/me` with that token
  3. If valid, Claw returns user profile (user_id, tier, balance, etc.)
  4. OpenMarket injects that profile into the endpoint handler
"""

from __future__ import annotations

import logging
import time
from functools import wraps
from typing import Optional

from flask import jsonify, request

log = logging.getLogger(__name__)

# Cache validated tokens briefly to avoid hammering Claw on every request
_token_cache: dict[str, tuple[dict, float]] = {}  # token -> (user_data, expires_at)
TOKEN_CACHE_TTL = 60  # seconds


def _get_bearer_token() -> str:
    """Extract Bearer token from Authorization header."""
    auth = request.headers.get("Authorization", "")
    if auth.startswith("Bearer "):
        return auth[7:].strip()
    return ""


def _identify_token(token: str) -> str:
    """Identify token type by prefix."""
    if token.startswith("at_"):
        return "claw_auth"
    if token.startswith("tgp_"):
        return "claw_user"
    if token.startswith("sk_"):
        return "claw_server"
    if token.startswith("om_sk_"):
        return "provider_key"
    if token.startswith("om_ak_"):
        return "admin_key"
    return "unknown"


def validate_consumer_token(token: str) -> Optional[dict]:
    """Validate at_ or tgp_ token via Claw API.

    Returns user profile dict or None.
    Caches results for TOKEN_CACHE_TTL seconds.
    """
    # Check cache
    now = time.time()
    cached = _token_cache.get(token)
    if cached and cached[1] > now:
        return cached[0]

    # Call Claw
    from .claw_client import get_claw_client, ClawError
    try:
        user_data = get_claw_client().get_me(token)
        _token_cache[token] = (user_data, now + TOKEN_CACHE_TTL)
        return user_data
    except ClawError as e:
        log.debug("Claw auth failed: %s", e)
        _token_cache.pop(token, None)
        return None


def clear_token_cache(token: str = ""):
    """Clear cached token validation. Empty string = clear all."""
    if token:
        _token_cache.pop(token, None)
    else:
        _token_cache.clear()


# ── Decorators ───────────────────────────────────────────────


def require_consumer(f):
    """Require consumer auth (Claw at_/tgp_ token).

    Injects `user_data` dict as first argument. Contains:
      user_id, tier, balance_usd, tokens_remaining_day, features, etc.
    """
    @wraps(f)
    def wrapper(*args, **kwargs):
        token = _get_bearer_token()
        if not token:
            return jsonify({"error": "Authorization header required", "code": "UNAUTHORIZED"}), 401

        token_type = _identify_token(token)

        if token_type in ("claw_auth", "claw_user"):
            user_data = validate_consumer_token(token)
            if not user_data:
                return jsonify({"error": "Invalid or expired token", "code": "UNAUTHORIZED"}), 401
            # Inject the raw token so downstream can proxy calls
            user_data["_token"] = token
            return f(user_data, *args, **kwargs)
        else:
            return jsonify({
                "error": "Consumer token required (at_xxx or tgp_xxx)",
                "code": "UNAUTHORIZED",
            }), 401

    return wrapper


def require_provider(f):
    """Require provider auth (om_sk_ API key).

    Injects `listing` as first argument.
    """
    @wraps(f)
    def wrapper(*args, **kwargs):
        from .store import get_store

        token = _get_bearer_token()
        if not token or not token.startswith("om_sk_"):
            return jsonify({"error": "Provider API key required (om_sk_xxx)", "code": "UNAUTHORIZED"}), 401

        listing = get_store().get_by_api_key(token)
        if not listing:
            return jsonify({"error": "Invalid API key", "code": "UNAUTHORIZED"}), 401

        return f(listing, *args, **kwargs)
    return wrapper
