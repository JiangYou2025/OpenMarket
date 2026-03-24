"""Provider API — self-service endpoints for AI bots to manage their listings.

All endpoints require API key auth via `Authorization: Bearer 2d_sk_xxx` header.
Except /register which creates the key.

Prefix: /api/p/
"""

from __future__ import annotations

import logging
import time
from functools import wraps

from flask import Blueprint, jsonify, request

from .models import Listing, PricingTier, CATEGORIES, SENSITIVE_CATEGORIES
from .session import get_session_store
from .store import get_store
from .tag_engine import get_tag_engine

log = logging.getLogger(__name__)

bot_bp = Blueprint("bot_api", __name__, url_prefix="/api/p")


# ── Auth helper ───────────────────────────────────────────────


def _get_api_key() -> str | None:
    auth = request.headers.get("Authorization", "")
    if auth.startswith("Bearer "):
        return auth[7:].strip()
    return None


def require_bot_auth(f):
    """Authenticate bot via API key, inject listing as first arg."""
    @wraps(f)
    def wrapper(*args, **kwargs):
        key = _get_api_key()
        if not key:
            return jsonify({"error": "Missing Authorization header", "code": "UNAUTHORIZED"}), 401
        listing = get_store().get_by_api_key(key)
        if not listing:
            return jsonify({"error": "Invalid API key", "code": "UNAUTHORIZED"}), 401
        return f(listing, *args, **kwargs)
    return wrapper


# ══════════════════════════════════════════════════════════════
# Registration (no auth)
# ══════════════════════════════════════════════════════════════


@bot_bp.route("/register", methods=["POST"])
def register():
    """Register a new bot. Returns API key (shown ONCE).

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

    pricing = [PricingTier.from_dict(p) for p in data.get("pricing", [])]
    if not pricing:
        pricing = [PricingTier()]

    store = get_store()

    bot_id = data.get("bot_id", "").strip()
    if bot_id:
        existing = store.get_by_bot_id(bot_id)
        if existing:
            return jsonify({"error": "Bot already registered", "listing_id": existing.listing_id, "code": "ALREADY_EXISTS"}), 409

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

    api_key = listing.issue_api_key()
    store.create(listing)

    # Index in tag engine
    get_tag_engine().index_listing(
        listing_id=listing.listing_id,
        tags=listing.tags,
        category=listing.category,
        name=listing.name,
        tagline=listing.tagline,
    )

    log.info("Bot registered: %s → %s", name, listing.listing_id)

    return jsonify({
        "message": f"Bot '{name}' registered successfully",
        "listing_id": listing.listing_id,
        "api_key": api_key,
        "warning": "Save this API key — it will NOT be shown again.",
        "next_steps": [
            "PUT /api/p/me to update your listing",
            "POST /api/p/me/publish to go live",
        ],
    }), 201


# ══════════════════════════════════════════════════════════════
# Self-service (auth required)
# ══════════════════════════════════════════════════════════════


@bot_bp.route("/me", methods=["GET"])
@require_bot_auth
def get_me(listing: Listing):
    """Your listing details (owner view)."""
    return jsonify(listing.to_owner_dict())


@bot_bp.route("/me", methods=["PUT"])
@require_bot_auth
def update_me(listing: Listing):
    """Update listing. Updatable: name, tagline, description, avatar_url, category,
    tags, example_prompts, provider, model, system_prompt, pricing, webhook_url."""
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

    # Re-index tags
    get_tag_engine().index_listing(
        listing_id=listing.listing_id,
        tags=listing.tags,
        category=listing.category,
        rating=listing.rating,
        rating_count=listing.rating_count,
        total_sessions=listing.total_sessions,
        published_at=listing.published_at,
        name=listing.name,
        tagline=listing.tagline,
    )

    return jsonify({"message": "Updated", "listing": listing.to_owner_dict()})


@bot_bp.route("/me/publish", methods=["POST"])
@require_bot_auth
def publish_me(listing: Listing):
    """Publish listing — makes it visible to users."""
    if listing.status == "active":
        return jsonify({"message": "Already published"}), 200
    if not listing.provider:
        return jsonify({"error": "Set a provider before publishing"}), 400
    if not listing.pricing:
        return jsonify({"error": "Set pricing before publishing"}), 400

    listing.publish()
    get_store().update(listing)

    # Index with full metadata
    get_tag_engine().index_listing(
        listing_id=listing.listing_id,
        tags=listing.tags,
        category=listing.category,
        rating=listing.rating,
        rating_count=listing.rating_count,
        total_sessions=listing.total_sessions,
        published_at=listing.published_at,
        name=listing.name,
        tagline=listing.tagline,
    )

    log.info("Bot published: %s (%s)", listing.name, listing.listing_id)

    resp = {"message": f"'{listing.name}' is now live!", "listing": listing.to_public_dict()}
    if listing.category in SENSITIVE_CATEGORIES:
        resp["note"] = "This category requires professional review of responses before delivery."
    return jsonify(resp)


@bot_bp.route("/me/suspend", methods=["POST"])
@require_bot_auth
def suspend_me(listing: Listing):
    """Take listing offline."""
    listing.suspend()
    get_store().update(listing)
    get_tag_engine().remove_listing(listing.listing_id)
    return jsonify({"message": "Listing suspended. POST /api/p/me/publish to re-activate."})


@bot_bp.route("/me", methods=["DELETE"])
@require_bot_auth
def delete_me(listing: Listing):
    """Permanently delete listing."""
    get_store().delete(listing.listing_id)
    get_tag_engine().remove_listing(listing.listing_id)
    log.info("Bot deleted: %s (%s)", listing.name, listing.listing_id)
    return jsonify({"message": "Listing deleted permanently"})


# ══════════════════════════════════════════════════════════════
# Stats & Sessions
# ══════════════════════════════════════════════════════════════


@bot_bp.route("/me/stats", methods=["GET"])
@require_bot_auth
def my_stats(listing: Listing):
    """Usage stats including revenue breakdown."""
    platform_fee = round(listing.total_revenue_usd * 0.20, 2)
    net = round(listing.total_revenue_usd - platform_fee, 2)
    return jsonify({
        "listing_id": listing.listing_id,
        "name": listing.name,
        "status": listing.status,
        "total_sessions": listing.total_sessions,
        "total_minutes": listing.total_minutes,
        "total_revenue_usd": listing.total_revenue_usd,
        "platform_fee_usd": platform_fee,
        "net_revenue_usd": net,
        "rating": round(listing.rating, 2),
        "rating_count": listing.rating_count,
        "pricing": [t.to_dict() for t in listing.pricing],
    })


@bot_bp.route("/me/sessions", methods=["GET"])
@require_bot_auth
def my_sessions(listing: Listing):
    """Sessions for your bot."""
    sessions, total = get_session_store().list_by_listing(
        listing_id=listing.listing_id,
        status=request.args.get("status", ""),
        limit=int(request.args.get("limit", 50)),
        offset=int(request.args.get("offset", 0)),
    )
    return jsonify({
        "sessions": [s.to_provider_dict() for s in sessions],
        "total": total,
    })


@bot_bp.route("/me/reviews", methods=["GET"])
@require_bot_auth
def my_reviews(listing: Listing):
    """Reviews received by your bot."""
    sessions, _ = get_session_store().list_by_listing(
        listing_id=listing.listing_id, status="ended", limit=500,
    )
    reviews = [
        {
            "session_id": s.session_id,
            "score": s.rating,
            "comment": s.rating_comment,
            "duration_minutes": s.elapsed_minutes,
            "created_at": s.ended_at,
        }
        for s in sessions if s.rating > 0
    ]
    reviews.sort(key=lambda r: r["created_at"], reverse=True)

    limit = int(request.args.get("limit", 50))
    offset = int(request.args.get("offset", 0))

    return jsonify({
        "reviews": reviews[offset:offset + limit],
        "average_rating": round(listing.rating, 2),
        "total": len(reviews),
    })


# ══════════════════════════════════════════════════════════════
# Key management
# ══════════════════════════════════════════════════════════════


@bot_bp.route("/me/rotate-key", methods=["POST"])
@require_bot_auth
def rotate_key(listing: Listing):
    """Generate new API key. Old key immediately invalidated."""
    new_key = listing.issue_api_key()
    get_store().update(listing)
    log.info("API key rotated for: %s", listing.listing_id)
    return jsonify({
        "message": "New API key generated. Old key is now invalid.",
        "api_key": new_key,
        "warning": "Save this key — it will NOT be shown again.",
    })


# ══════════════════════════════════════════════════════════════
# Approval queue (sensitive categories)
# ══════════════════════════════════════════════════════════════


@bot_bp.route("/me/approvals", methods=["GET"])
@require_bot_auth
def list_approvals(listing: Listing):
    """Pending approvals for your bot's responses."""
    ss = get_session_store()
    # Find active sessions for this listing
    sessions, _ = ss.list_by_listing(listing.listing_id, status="active", limit=100)

    approvals = []
    for session in sessions:
        messages = ss.get_messages(session.session_id, limit=100)
        for msg in messages:
            if msg.approval_status == "pending_review":
                approvals.append({
                    "approval_id": msg.approval_id,
                    "session_id": session.session_id,
                    "user_message": "",  # Find the preceding user message
                    "ai_response": msg.content,
                    "status": "pending",
                    "created_at": msg.created_at,
                })

    return jsonify({"approvals": approvals})


@bot_bp.route("/me/approvals/<approval_id>/approve", methods=["POST"])
@require_bot_auth
def approve_response(listing: Listing, approval_id: str):
    """Approve an AI response (optionally edit before sending)."""
    data = request.get_json(silent=True) or {}
    edited = data.get("edited_response", "")
    note = data.get("note", "")

    # Find and update the message
    ss = get_session_store()
    sessions, _ = ss.list_by_listing(listing.listing_id, status="active", limit=100)

    for session in sessions:
        messages = ss.get_messages(session.session_id, limit=100)
        for msg in messages:
            if msg.approval_id == approval_id and msg.approval_status == "pending_review":
                msg.approval_status = "approved"
                msg.content = edited if edited else msg.content
                ss._save_messages(session.session_id, messages)
                return jsonify({
                    "message": "Response approved and delivered",
                    "approval_id": approval_id,
                    "status": "approved",
                })

    return jsonify({"error": "Approval not found", "code": "NOT_FOUND"}), 404


@bot_bp.route("/me/approvals/<approval_id>/reject", methods=["POST"])
@require_bot_auth
def reject_response(listing: Listing, approval_id: str):
    """Reject an AI response. User is not charged for this message."""
    data = request.get_json(silent=True) or {}
    note = data.get("note", "")

    ss = get_session_store()
    sessions, _ = ss.list_by_listing(listing.listing_id, status="active", limit=100)

    for session in sessions:
        messages = ss.get_messages(session.session_id, limit=100)
        for msg in messages:
            if msg.approval_id == approval_id and msg.approval_status == "pending_review":
                msg.approval_status = "rejected"
                msg.content = f"[Rejected by reviewer] {note}" if note else "[Response rejected by reviewer]"
                ss._save_messages(session.session_id, messages)
                return jsonify({
                    "message": "Response rejected. User was not charged.",
                    "approval_id": approval_id,
                    "status": "rejected",
                })

    return jsonify({"error": "Approval not found", "code": "NOT_FOUND"}), 404


# ══════════════════════════════════════════════════════════════
# Categories (public)
# ══════════════════════════════════════════════════════════════


@bot_bp.route("/categories", methods=["GET"])
def list_categories():
    return jsonify({
        "categories": CATEGORIES,
        "sensitive": list(SENSITIVE_CATEGORIES),
    })
