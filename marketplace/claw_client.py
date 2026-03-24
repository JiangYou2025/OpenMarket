"""Claw Client — SDK for odysseeia.com Stripe User Claw API.

OpenMarket delegates all user auth, billing, and payment to Claw.
This module is the single integration point.

Usage:
    client = get_claw_client()
    user = client.get_user("alice")
    client.record_usage("alice", tokens=1500, model="sonnet")
"""

from __future__ import annotations

import logging
import os
import time
from typing import Optional

import requests

log = logging.getLogger(__name__)

# Config — override via environment
CLAW_BASE_URL = os.environ.get("CLAW_BASE_URL", "https://odysseeia.com")
CLAW_SERVER_TOKEN = os.environ.get("CLAW_SERVER_TOKEN", "")  # sk_xxx — required for server-side calls

REQUEST_TIMEOUT = 15  # seconds


class ClawError(Exception):
    """Error from the Claw API."""
    def __init__(self, message: str, status_code: int = 0, code: str = ""):
        super().__init__(message)
        self.status_code = status_code
        self.code = code


class ClawClient:
    """Client for odysseeia.com Stripe User Claw API."""

    def __init__(self, base_url: str = "", server_token: str = ""):
        self.base_url = (base_url or CLAW_BASE_URL).rstrip("/")
        self.server_token = server_token or CLAW_SERVER_TOKEN

    def _headers(self, token: str = "") -> dict:
        """Build auth headers. Uses server token by default."""
        tok = token or self.server_token
        h = {"Content-Type": "application/json"}
        if tok:
            h["Authorization"] = f"Bearer {tok}"
        return h

    def _request(self, method: str, path: str, token: str = "", **kwargs) -> dict:
        """Make an HTTP request to Claw API."""
        url = f"{self.base_url}{path}"
        kwargs.setdefault("timeout", REQUEST_TIMEOUT)
        kwargs["headers"] = self._headers(token)

        try:
            resp = getattr(requests, method)(url, **kwargs)
        except requests.RequestException as e:
            log.error("Claw request failed: %s %s → %s", method.upper(), path, e)
            raise ClawError(f"Claw API unavailable: {e}", status_code=503)

        if resp.status_code >= 400:
            try:
                body = resp.json()
                msg = body.get("error", body.get("message", resp.text))
            except Exception:
                msg = resp.text
            raise ClawError(msg, status_code=resp.status_code)

        try:
            return resp.json()
        except Exception:
            return {}

    # ── Public endpoints (no auth) ────────────────────────────

    def health(self) -> dict:
        return self._request("get", "/health")

    def list_plans(self) -> list[dict]:
        """List active subscription plans."""
        return self._request("get", "/api/v1/plans")

    def list_tiers(self) -> list[dict]:
        return self._request("get", "/api/v1/tiers")

    def estimate_cost(self, model: str, input_tokens: int, output_tokens: int, tier: str = "basic") -> dict:
        """Estimate cost for an AI call."""
        return self._request("post", "/api/v1/estimate", json={
            "model": model,
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "tier": tier,
        })

    # ── Token validation ──────────────────────────────────────

    def validate_token(self, token: str) -> dict:
        """Validate any token (at_, tgp_, sk_). Returns user info if valid."""
        return self._request("post", "/api/v1/tokens/validate", json={"token": token})

    # ── User auth (proxy — user's own token) ──────────────────

    def login(self, username: str, password: str) -> dict:
        """Login user, returns auth token."""
        return self._request("post", "/api/v1/auth/login", json={
            "username": username,
            "password": password,
        })

    def register_user_self(self, username: str, email: str, password: str) -> dict:
        """Self-registration via auth API."""
        return self._request("post", "/api/v1/auth/register", json={
            "username": username,
            "email": email,
            "password": password,
        })

    def get_me(self, user_token: str) -> dict:
        """Get user's own profile using their token.

        Returns: user_id, tier, balance_usd, tokens_remaining, features, etc.
        """
        return self._request("get", "/api/v1/me", token=user_token)

    def get_my_usage(self, user_token: str, limit: int = 50) -> list[dict]:
        """Get user's usage history using their token."""
        return self._request("get", f"/api/v1/me/usage?limit={limit}", token=user_token)

    def user_checkout(self, user_token: str, plan: str, success_url: str, cancel_url: str) -> dict:
        """User-initiated Stripe checkout."""
        return self._request("post", "/api/v1/me/checkout", token=user_token, json={
            "plan": plan,
            "success_url": success_url,
            "cancel_url": cancel_url,
        })

    # ── Server-side calls (sk_ token) ─────────────────────────

    def get_user(self, user_id: str) -> dict:
        """Get user info + billing data (server-side)."""
        return self._request("get", f"/api/v1/users/{user_id}")

    def user_exists(self, user_id: str) -> bool:
        """Check if user exists."""
        try:
            result = self._request("get", f"/api/v1/users/{user_id}/exists")
            return result.get("exists", False)
        except ClawError:
            return False

    def register_user(self, user_id: str, display_name: str = "", tier: str = "basic") -> dict:
        """Register a new user (server-side)."""
        return self._request("post", f"/api/v1/users/{user_id}/register", json={
            "display_name": display_name or user_id,
            "tier": tier,
        })

    def check_usage(self, user_id: str) -> dict:
        """Check if user is within usage limits.

        Returns: {"allowed": true/false, "reason": "ok", "tier": "basic"}
        """
        return self._request("post", "/api/v1/usage/check", json={"user_id": user_id})

    def record_usage(
        self,
        user_id: str,
        tokens_used: int = 0,
        input_tokens: int = 0,
        output_tokens: int = 0,
        model: str = "",
        action: str = "chat",
    ) -> dict:
        """Record token consumption for a user.

        Called after each AI response in a session.
        """
        return self._request("post", "/api/v1/usage", json={
            "user_id": user_id,
            "tokens_used": tokens_used,
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "model": model,
            "action": action,
        })

    def server_checkout(self, user_id: str, plan: str, success_url: str, cancel_url: str) -> dict:
        """Server-initiated Stripe checkout for a user."""
        return self._request("post", "/api/v1/checkout", json={
            "user_id": user_id,
            "plan": plan,
            "success_url": success_url,
            "cancel_url": cancel_url,
        })

    def set_user_plan(self, user_id: str, plan: str) -> dict:
        """Change user's subscription plan."""
        return self._request("put", f"/api/v1/users/{user_id}/plan", json={"plan": plan})

    def cancel_user_plan(self, user_id: str, immediate: bool = False) -> dict:
        """Cancel user's subscription."""
        q = "?immediate=true" if immediate else ""
        return self._request("delete", f"/api/v1/users/{user_id}/plan{q}")

    def get_usage(self, user_id: str = "", limit: int = 100, since: float = 0) -> list[dict]:
        """Get usage records (server view)."""
        params = []
        if user_id:
            params.append(f"user_id={user_id}")
        if limit:
            params.append(f"limit={limit}")
        if since:
            params.append(f"since={since}")
        q = "?" + "&".join(params) if params else ""
        return self._request("get", f"/api/v1/usage{q}")


# ── Singleton ────────────────────────────────────────────────
_client: Optional[ClawClient] = None


def get_claw_client() -> ClawClient:
    global _client
    if _client is None:
        _client = ClawClient()
        log.info("Claw client initialized: %s", _client.base_url)
    return _client
