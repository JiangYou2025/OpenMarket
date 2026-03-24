"""Webhook — forward user messages to external bot providers.

When a listing has a webhook_url set, the platform calls it instead of
using the built-in AI provider. The external bot processes the message
and returns a response.
"""

from __future__ import annotations

import logging
import time
from typing import Optional

import requests

log = logging.getLogger(__name__)

WEBHOOK_TIMEOUT = 30  # seconds


def call_webhook(
    webhook_url: str,
    session_id: str,
    message_id: str,
    content: str,
    listing_id: str = "",
    user_id: str = "",
    elapsed_minutes: float = 0,
) -> Optional[dict]:
    """Forward a user message to an external bot via webhook.

    Sends:
        {
            "event": "message",
            "session_id": "ses_xxx",
            "message_id": "msg_xxx",
            "content": "user's message",
            "metadata": { ... }
        }

    Expects response:
        {
            "content": "bot's reply",
            "tokens_used": 500
        }

    Returns parsed response dict or None on failure.
    """
    payload = {
        "event": "message",
        "session_id": session_id,
        "message_id": message_id,
        "content": content,
        "metadata": {
            "listing_id": listing_id,
            "user_id": user_id,
            "elapsed_minutes": elapsed_minutes,
            "timestamp": time.time(),
        },
    }

    try:
        resp = requests.post(
            webhook_url,
            json=payload,
            timeout=WEBHOOK_TIMEOUT,
            headers={
                "Content-Type": "application/json",
                "User-Agent": "OpenMarket/1.0",
                "X-OpenMarket-Event": "message",
            },
        )
        resp.raise_for_status()
        data = resp.json()

        return {
            "content": data.get("content", ""),
            "tokens_used": data.get("tokens_used", 0),
        }

    except requests.Timeout:
        log.warning("Webhook timeout: %s (session=%s)", webhook_url, session_id)
        return {"content": "[Bot did not respond in time. Please try again.]", "tokens_used": 0}

    except requests.RequestException as e:
        log.error("Webhook error: %s → %s", webhook_url, e)
        return None

    except (ValueError, KeyError) as e:
        log.error("Webhook bad response: %s → %s", webhook_url, e)
        return None


def call_webhook_session_event(
    webhook_url: str,
    event: str,
    session_id: str,
    listing_id: str = "",
    user_id: str = "",
    **extra,
) -> bool:
    """Notify external bot of session lifecycle events (start, end).

    Events: "session_start", "session_end"
    Returns True if webhook acknowledged.
    """
    payload = {
        "event": event,
        "session_id": session_id,
        "metadata": {
            "listing_id": listing_id,
            "user_id": user_id,
            "timestamp": time.time(),
            **extra,
        },
    }

    try:
        resp = requests.post(
            webhook_url,
            json=payload,
            timeout=10,
            headers={
                "Content-Type": "application/json",
                "User-Agent": "OpenMarket/1.0",
                "X-OpenMarket-Event": event,
            },
        )
        return resp.status_code < 400
    except Exception as e:
        log.warning("Webhook event %s failed: %s → %s", event, webhook_url, e)
        return False
