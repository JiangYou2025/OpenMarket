"""Marketplace API — Flask blueprint for bot listings and onboarding."""

from __future__ import annotations

import time
import logging

from flask import Blueprint, jsonify, request

from .models import Listing, PricingTier, CATEGORIES
from .store import get_store

log = logging.getLogger(__name__)

marketplace_bp = Blueprint("marketplace", __name__, url_prefix="/api/marketplace")


# ── Public endpoints (no auth required) ───────────────────────


@marketplace_bp.route("/listings", methods=["GET"])
def list_listings():
    """Browse active bot listings.

    Query params:
        category, tag, sort_by (rating|price_low|price_high|popular|newest|featured),
        limit, offset
    """
    store = get_store()
    listings, total = store.list_active(
        category=request.args.get("category", ""),
        tag=request.args.get("tag", ""),
        sort_by=request.args.get("sort_by", "rating"),
        limit=int(request.args.get("limit", 50)),
        offset=int(request.args.get("offset", 0)),
    )
    return jsonify({
        "listings": [l.to_public_dict() for l in listings],
        "total": total,
        "categories": CATEGORIES,
    })


@marketplace_bp.route("/listings/<listing_id>", methods=["GET"])
def get_listing(listing_id: str):
    """Get a single listing's public details."""
    listing = get_store().get(listing_id)
    if not listing:
        return jsonify({"error": "Listing not found"}), 404
    return jsonify(listing.to_public_dict())


@marketplace_bp.route("/categories", methods=["GET"])
def list_categories():
    """List available categories with counts."""
    stats = get_store().stats()
    return jsonify({
        "categories": CATEGORIES,
        "counts": stats.get("categories", {}),
    })


@marketplace_bp.route("/stats", methods=["GET"])
def marketplace_stats():
    """Platform-wide stats."""
    return jsonify(get_store().stats())


# ── Bot onboarding (auth required) ───────────────────────────


@marketplace_bp.route("/onboard", methods=["POST"])
def onboard_bot():
    """Register a bot on the marketplace.

    Minimum required fields: bot_id, name, provider.
    Everything else has sensible defaults.

    Example:
    {
        "bot_id": "e00f2ea9",
        "name": "CodeHelper",
        "tagline": "Your AI coding assistant",
        "category": "coding",
        "provider": "claude",
        "model": "claude-sonnet-4-6",
        "pricing": [
            {"name": "basic", "price_usd": 2.0, "unit": "per_minute", "unit_amount": 15}
        ]
    }
    """
    data = request.get_json(silent=True) or {}

    # Validate required fields
    bot_id = data.get("bot_id", "").strip()
    name = data.get("name", "").strip()
    provider = data.get("provider", "").strip()

    if not bot_id:
        return jsonify({"error": "bot_id is required"}), 400
    if not name:
        return jsonify({"error": "name is required"}), 400
    if not provider:
        return jsonify({"error": "provider is required"}), 400

    store = get_store()

    # Check if bot already has a listing
    existing = store.get_by_bot_id(bot_id)
    if existing:
        return jsonify({
            "error": "Bot already registered",
            "listing_id": existing.listing_id,
        }), 409

    # Validate category
    category = data.get("category", "general")
    if category not in CATEGORIES:
        return jsonify({"error": f"Invalid category. Valid: {CATEGORIES}"}), 400

    # Build pricing tiers
    pricing = []
    for p in data.get("pricing", []):
        pricing.append(PricingTier.from_dict(p))
    if not pricing:
        pricing = [PricingTier()]  # Default: $2 / 15min

    # Create listing
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

    store.create(listing)
    log.info("Bot onboarded: %s (%s) → listing %s", name, bot_id, listing.listing_id)

    return jsonify({
        "message": f"Bot '{name}' registered successfully",
        "listing_id": listing.listing_id,
        "status": "draft",
        "next_steps": [
            f"PUT /api/marketplace/listings/{listing.listing_id} to update details",
            f"POST /api/marketplace/listings/{listing.listing_id}/publish to go live",
        ],
    }), 201


@marketplace_bp.route("/listings/<listing_id>", methods=["PUT"])
def update_listing(listing_id: str):
    """Update a listing's details."""
    store = get_store()
    listing = store.get(listing_id)
    if not listing:
        return jsonify({"error": "Listing not found"}), 404

    data = request.get_json(silent=True) or {}

    # Updatable fields
    updatable = [
        "name", "tagline", "description", "avatar_url", "category",
        "tags", "example_prompts", "provider", "model", "system_prompt",
        "featured", "verified",
    ]
    for key in updatable:
        if key in data:
            setattr(listing, key, data[key])

    # Update pricing if provided
    if "pricing" in data:
        listing.pricing = [PricingTier.from_dict(p) for p in data["pricing"]]
        listing._compute_min_price()

    listing.updated_at = time.time()
    store.update(listing)

    return jsonify({"message": "Updated", "listing": listing.to_dict()})


@marketplace_bp.route("/listings/<listing_id>/publish", methods=["POST"])
def publish_listing(listing_id: str):
    """Publish a listing — makes it visible on the marketplace."""
    store = get_store()
    listing = store.get(listing_id)
    if not listing:
        return jsonify({"error": "Listing not found"}), 404

    if listing.status == "active":
        return jsonify({"message": "Already published"}), 200

    # Validate minimum requirements
    if not listing.name:
        return jsonify({"error": "Name is required to publish"}), 400
    if not listing.provider:
        return jsonify({"error": "Provider is required to publish"}), 400
    if not listing.pricing:
        return jsonify({"error": "At least one pricing tier is required"}), 400

    listing.publish()
    store.update(listing)
    log.info("Listing published: %s (%s)", listing.name, listing.listing_id)

    return jsonify({
        "message": f"'{listing.name}' is now live on the marketplace!",
        "listing": listing.to_public_dict(),
    })


@marketplace_bp.route("/listings/<listing_id>/suspend", methods=["POST"])
def suspend_listing(listing_id: str):
    """Suspend a listing — removes from public view."""
    store = get_store()
    listing = store.get(listing_id)
    if not listing:
        return jsonify({"error": "Listing not found"}), 404

    listing.suspend()
    store.update(listing)
    return jsonify({"message": "Listing suspended"})


@marketplace_bp.route("/listings/<listing_id>", methods=["DELETE"])
def delete_listing(listing_id: str):
    """Delete a listing permanently."""
    if get_store().delete(listing_id):
        return jsonify({"message": "Deleted"})
    return jsonify({"error": "Not found"}), 404


@marketplace_bp.route("/listings/<listing_id>/rate", methods=["POST"])
def rate_listing(listing_id: str):
    """Rate a bot (1-5 stars)."""
    store = get_store()
    listing = store.get(listing_id)
    if not listing:
        return jsonify({"error": "Listing not found"}), 404

    data = request.get_json(silent=True) or {}
    score = data.get("score")
    if score is None or not (1 <= score <= 5):
        return jsonify({"error": "score must be 1-5"}), 400

    listing.add_rating(float(score))
    store.update(listing)

    return jsonify({
        "message": "Thanks for rating!",
        "new_rating": round(listing.rating, 2),
        "total_ratings": listing.rating_count,
    })


# ── Quick onboard: auto-detect bots and register ─────────────


@marketplace_bp.route("/auto-onboard", methods=["POST"])
def auto_onboard():
    """Auto-detect running bots and register them on marketplace.

    Scans BotManager for bots not yet listed and creates draft listings.
    """
    from bot_instance import manager
    from core.providers.registry import get_provider

    store = get_store()
    onboarded = []
    skipped = []

    for bot in manager.all():
        # Skip if already listed
        existing = store.get_by_bot_id(bot.bot_id)
        if existing:
            skipped.append({"bot_id": bot.bot_id, "label": bot.label, "reason": "already listed"})
            continue

        # Determine provider from bot config
        provider_name = "claude"  # default

        listing = Listing(
            bot_id=bot.bot_id,
            name=bot.label,
            tagline=f"AI assistant powered by {provider_name}",
            provider=provider_name,
            system_prompt=bot.system_prompt or "",
            status="draft",
        )

        store.create(listing)
        onboarded.append({
            "bot_id": bot.bot_id,
            "label": bot.label,
            "listing_id": listing.listing_id,
        })

    return jsonify({
        "message": f"Auto-onboarded {len(onboarded)} bots",
        "onboarded": onboarded,
        "skipped": skipped,
    })


# ── Owner dashboard ──────────────────────────────────────────


@marketplace_bp.route("/my-listings", methods=["GET"])
def my_listings():
    """List all listings owned by the current user."""
    owner_id = request.args.get("owner_id", "")
    if not owner_id:
        return jsonify({"error": "owner_id is required"}), 400

    listings = get_store().list_by_owner(owner_id)
    return jsonify({
        "listings": [l.to_dict() for l in listings],
        "total": len(listings),
    })
