"""Bot API — self-service endpoints for AI bots to manage their listings.

All endpoints require API key auth via `Authorization: Bearer 2d_sk_xxx` header.
Except /register which creates the key.

Prefix: /api/bot
"""

from __future__ import annotations

import logging
import time
from functools import wraps

from flask import Blueprint, jsonify, request

from .models import Listing, PricingTier, CATEGORIES, SENSITIVE_CATEGORIES
from .store import get_store

log = logging.getLogger(__name__)

bot_bp = Blueprint("bot_api", __name__, url_prefix="/api/bot")


# ── Auth helper ───────────────────────────────────────────────


def _get_api_key() -> str | None:
    """Extract API key from Authorization header."""
    auth = request.headers.get("Authorization", "")
    if auth.startswith("Bearer "):
        return auth[7:].strip()
    return None


def require_bot_auth(f):
    """Decorator: authenticate bot via API key, inject listing as first arg."""
    @wraps(f)
    def wrapper(*args, **kwargs):
        key = _get_api_key()
        if not key:
            return jsonify({"error": "Missing Authorization header (Bearer 2d_sk_xxx)"}), 401
        listing = get_store().get_by_api_key(key)
        if not listing:
            return jsonify({"error": "Invalid API key"}), 401
        return f(listing, *args, **kwargs)
    return wrapper


# ── Registration (no auth) ────────────────────────────────────


@bot_bp.route("/register", methods=["POST"])
def register():
    """Register a new bot on the marketplace.

    Returns an API key (shown ONCE). Bot uses this key for all future requests.

    Required: name, provider
    Optional: bot_id, tagline, description, category, tags, model,
              system_prompt, pricing, example_prompts, avatar_url, webhook_url
    """
    data = request.get_json(silent=True) or {}

    name = data.get("name", "").strip()
    provider = data.get("provider", "").strip()

    if not name:
        return jsonify({"error": "name is required"}), 400
    if not provider:
        return jsonify({"error": "provider is required"}), 400

    category = data.get("category", "general")
    if category not in CATEGORIES:
        return jsonify({"error": f"Invalid category. Valid: {CATEGORIES}"}), 400

    # Build pricing
    pricing = []
    for p in data.get("pricing", []):
        pricing.append(PricingTier.from_dict(p))
    if not pricing:
        pricing = [PricingTier()]  # $2 / 15min default

    store = get_store()

    # Check duplicate by bot_id
    bot_id = data.get("bot_id", "").strip()
    if bot_id:
        existing = store.get_by_bot_id(bot_id)
        if existing:
            return jsonify({"error": "Bot already registered", "listing_id": existing.listing_id}), 409

    listing = Listing(
        bot_id=bot_id,
        owner_id=data.get("owner_id", ""),
        name=name,
        tagline=data.get("tagline", ""),
        description=data.get("description", ""),
        avatar_url=data.get("avatar_url", ""),
        category=category,
        tags=data.get("tags", []),
        example_prompts=data.get("example_prompts", []),
        provider=provider,
        model=data.get("model", ""),
        system_prompt=data.get("system_prompt", ""),
        pricing=pricing,
        status="draft",
    )

    # Issue API key
    api_key = listing.issue_api_key()
    store.create(listing)

    log.info("Bot registered: %s → %s", name, listing.listing_id)

    return jsonify({
        "message": f"Bot '{name}' registered successfully",
        "listing_id": listing.listing_id,
        "api_key": api_key,
        "warning": "Save this API key — it will NOT be shown again.",
        "next_steps": [
            "PUT /api/bot/me to update your listing",
            "POST /api/bot/me/publish to go live",
        ],
    }), 201


# ── Self-service (auth required) ──────────────────────────────


@bot_bp.route("/me", methods=["GET"])
@require_bot_auth
def get_me(listing: Listing):
    """Get your own listing details (full owner view)."""
    return jsonify(listing.to_owner_dict())


@bot_bp.route("/me", methods=["PUT"])
@require_bot_auth
def update_me(listing: Listing):
    """Update your listing details.

    Updatable: name, tagline, description, avatar_url, category, tags,
               example_prompts, provider, model, system_prompt, pricing
    """
    data = request.get_json(silent=True) or {}
    store = get_store()

    updatable = [
        "name", "tagline", "description", "avatar_url", "category",
        "tags", "example_prompts", "provider", "model", "system_prompt",
    ]
    for key in updatable:
        if key in data:
            if key == "category" and data[key] not in CATEGORIES:
                return jsonify({"error": f"Invalid category. Valid: {CATEGORIES}"}), 400
            setattr(listing, key, data[key])

    if "pricing" in data:
        listing.pricing = [PricingTier.from_dict(p) for p in data["pricing"]]
        listing._compute_min_price()

    listing.updated_at = time.time()
    store.update(listing)

    return jsonify({"message": "Updated", "listing": listing.to_owner_dict()})


@bot_bp.route("/me/publish", methods=["POST"])
@require_bot_auth
def publish_me(listing: Listing):
    """Publish your listing — makes it visible to users."""
    if listing.status == "active":
        return jsonify({"message": "Already published"}), 200

    if not listing.provider:
        return jsonify({"error": "Set a provider before publishing"}), 400
    if not listing.pricing:
        return jsonify({"error": "Set pricing before publishing"}), 400

    if listing.category in SENSITIVE_CATEGORIES:
        listing.publish()
        note = "Note: This category requires professional review of responses before delivery."
    else:
        listing.publish()
        note = None

    get_store().update(listing)
    log.info("Bot published: %s (%s)", listing.name, listing.listing_id)

    resp = {
        "message": f"'{listing.name}' is now live!",
        "listing": listing.to_public_dict(),
    }
    if note:
        resp["note"] = note
    return jsonify(resp)


@bot_bp.route("/me/suspend", methods=["POST"])
@require_bot_auth
def suspend_me(listing: Listing):
    """Take your listing offline temporarily."""
    listing.suspend()
    get_store().update(listing)
    return jsonify({"message": "Listing suspended. POST /api/bot/me/publish to re-activate."})


@bot_bp.route("/me/stats", methods=["GET"])
@require_bot_auth
def my_stats(listing: Listing):
    """Get your usage stats."""
    return jsonify({
        "listing_id": listing.listing_id,
        "name": listing.name,
        "status": listing.status,
        "total_sessions": listing.total_sessions,
        "total_minutes": listing.total_minutes,
        "total_revenue_usd": listing.total_revenue_usd,
        "rating": round(listing.rating, 2),
        "rating_count": listing.rating_count,
        "pricing": [t.to_dict() for t in listing.pricing],
    })


@bot_bp.route("/me/rotate-key", methods=["POST"])
@require_bot_auth
def rotate_key(listing: Listing):
    """Generate a new API key. The old key is immediately invalidated."""
    new_key = listing.issue_api_key()
    get_store().update(listing)
    log.info("API key rotated for: %s", listing.listing_id)
    return jsonify({
        "message": "New API key generated. Old key is now invalid.",
        "api_key": new_key,
        "warning": "Save this key — it will NOT be shown again.",
    })


@bot_bp.route("/me", methods=["DELETE"])
@require_bot_auth
def delete_me(listing: Listing):
    """Permanently delete your listing."""
    get_store().delete(listing.listing_id)
    log.info("Bot deleted: %s (%s)", listing.name, listing.listing_id)
    return jsonify({"message": "Listing deleted permanently"})


# ── Categories reference ──────────────────────────────────────


@bot_bp.route("/categories", methods=["GET"])
def list_categories():
    """List available categories (no auth needed)."""
    return jsonify({
        "categories": CATEGORIES,
        "sensitive": list(SENSITIVE_CATEGORIES),
    })
