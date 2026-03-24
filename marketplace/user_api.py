"""Consumer API — browse, auth, wallet, sessions, ratings.

Prefix: /api/c/
Auth delegated to odysseeia.com Claw API (at_/tgp_ tokens).
Billing delegated to Claw (usage tracking, checkout, plans).
"""

from __future__ import annotations

import logging

from flask import Blueprint, jsonify, request

from .auth import require_consumer
from .claw_client import get_claw_client, ClawError
from .models import CATEGORIES, SENSITIVE_CATEGORIES
from .session import Message, Session, get_session_store
from .store import get_store
from .tag_engine import get_tag_engine
from .webhook import call_webhook

log = logging.getLogger(__name__)

user_bp = Blueprint("user_api", __name__, url_prefix="/api/c")


# ═══════════════════════════════════════════════════════════════
# Browse (no auth)
# ═══════════════════════════════════════════════════════════════


@user_bp.route("/listings", methods=["GET"])
def browse_listings():
    """Browse/search active listings.

    Query: category, tag, q (text search), sort, min_price, max_price, limit, offset
    """
    store = get_store()
    engine = get_tag_engine()
    q = request.args.get("q", "").strip()

    # If there's a text query, use tag engine for smart matching
    if q:
        matches = engine.match(
            query=q,
            category=request.args.get("category", ""),
            limit=int(request.args.get("limit", 50)),
        )
        listings = []
        for m in matches:
            listing = store.get(m.listing_id)
            if listing and listing.status == "active":
                d = listing.to_public_dict()
                d["match_score"] = m.score
                d["matched_tags"] = m.matched_tags
                listings.append(d)
        return jsonify({"listings": listings, "total": len(listings)})

    # Standard filtering
    listings, total = store.list_active(
        category=request.args.get("category", ""),
        tag=request.args.get("tag", ""),
        sort_by=request.args.get("sort", "rating"),
        limit=int(request.args.get("limit", 50)),
        offset=int(request.args.get("offset", 0)),
    )

    # Price filter
    min_price = float(request.args.get("min_price", 0))
    max_price = float(request.args.get("max_price", 0))
    result = []
    for l in listings:
        d = l.to_public_dict()
        if min_price and d.get("min_price_usd", 0) < min_price:
            continue
        if max_price and d.get("min_price_usd", 0) > max_price:
            continue
        result.append(d)

    return jsonify({"listings": result, "total": total})


@user_bp.route("/listings/<listing_id>", methods=["GET"])
def get_listing(listing_id: str):
    listing = get_store().get(listing_id)
    if not listing or listing.status not in ("active", "suspended"):
        return jsonify({"error": "Listing not found", "code": "NOT_FOUND"}), 404
    d = listing.to_public_dict()
    d["requires_review"] = listing.category in SENSITIVE_CATEGORIES
    return jsonify(d)


@user_bp.route("/categories", methods=["GET"])
def list_categories():
    stats = get_store().stats()
    engine = get_tag_engine()
    categories = []
    for cat in CATEGORIES:
        categories.append({
            "name": cat,
            "count": stats.get("categories", {}).get(cat, 0),
            "sensitive": cat in SENSITIVE_CATEGORIES,
            "popular_tags": engine.tags_for_category(cat, limit=10),
        })
    return jsonify({"categories": categories})


@user_bp.route("/featured", methods=["GET"])
def featured():
    listings, _ = get_store().list_active(sort_by="featured", limit=10)
    return jsonify({"featured": [l.to_public_dict() for l in listings]})


@user_bp.route("/popular", methods=["GET"])
def popular():
    listings, _ = get_store().list_active(sort_by="popular", limit=10)
    return jsonify({"popular": [l.to_public_dict() for l in listings]})


@user_bp.route("/newest", methods=["GET"])
def newest():
    listings, _ = get_store().list_active(sort_by="newest", limit=10)
    return jsonify({"newest": [l.to_public_dict() for l in listings]})


# ── Tag discovery ─────────────────────────────────────────────

@user_bp.route("/tags/popular", methods=["GET"])
def popular_tags():
    return jsonify({"tags": get_tag_engine().popular_tags(limit=30)})


@user_bp.route("/tags/trending", methods=["GET"])
def trending_tags():
    return jsonify({"tags": get_tag_engine().trending(limit=20)})


@user_bp.route("/tags/<tag>/related", methods=["GET"])
def related_tags(tag: str):
    return jsonify({"related": get_tag_engine().related_tags(tag, limit=10)})


@user_bp.route("/tags/suggest", methods=["GET"])
def suggest_tags():
    partial = request.args.get("q", "")
    return jsonify({"suggestions": get_tag_engine().suggest_tags(partial, limit=10)})


# ═══════════════════════════════════════════════════════════════
# Auth (proxy to Claw)
# ═══════════════════════════════════════════════════════════════


@user_bp.route("/auth/register", methods=["POST"])
def register():
    """Register via Claw. Returns auth token."""
    data = request.get_json(silent=True) or {}
    username = data.get("username", "").strip()
    email = data.get("email", "").strip()
    password = data.get("password", "")

    if not username:
        return jsonify({"error": "username is required"}), 400
    if not password or len(password) < 6:
        return jsonify({"error": "password must be at least 6 characters"}), 400

    try:
        result = get_claw_client().register_user_self(username, email, password)
        return jsonify(result), 201
    except ClawError as e:
        return jsonify({"error": str(e), "code": "REGISTRATION_FAILED"}), e.status_code or 400


@user_bp.route("/auth/login", methods=["POST"])
def login():
    """Login via Claw. Returns auth token."""
    data = request.get_json(silent=True) or {}
    username = data.get("username", "").strip()
    password = data.get("password", "")

    if not username or not password:
        return jsonify({"error": "username and password required"}), 400

    try:
        result = get_claw_client().login(username, password)
        return jsonify(result)
    except ClawError as e:
        return jsonify({"error": str(e), "code": "UNAUTHORIZED"}), 401


# ═══════════════════════════════════════════════════════════════
# Account (auth required — Claw at_/tgp_ token)
# ═══════════════════════════════════════════════════════════════


@user_bp.route("/me", methods=["GET"])
@require_consumer
def get_me(user_data: dict):
    """Get user profile from Claw (tier, balance, usage, features)."""
    user_data.pop("_token", None)
    return jsonify(user_data)


@user_bp.route("/me/usage", methods=["GET"])
@require_consumer
def my_usage(user_data: dict):
    """Get usage history from Claw."""
    token = user_data.get("_token", "")
    try:
        usage = get_claw_client().get_my_usage(token, limit=int(request.args.get("limit", 50)))
        return jsonify({"usage": usage})
    except ClawError as e:
        return jsonify({"error": str(e)}), e.status_code or 500


# ═══════════════════════════════════════════════════════════════
# Wallet / Payment (proxy to Claw Stripe)
# ═══════════════════════════════════════════════════════════════


@user_bp.route("/plans", methods=["GET"])
def list_plans():
    """List available subscription plans from Claw."""
    try:
        plans = get_claw_client().list_plans()
        return jsonify({"plans": plans})
    except ClawError as e:
        return jsonify({"error": str(e)}), e.status_code or 500


@user_bp.route("/estimate", methods=["POST"])
def estimate_cost():
    """Estimate cost for an AI call."""
    data = request.get_json(silent=True) or {}
    try:
        result = get_claw_client().estimate_cost(
            model=data.get("model", "sonnet"),
            input_tokens=data.get("input_tokens", 0),
            output_tokens=data.get("output_tokens", 0),
            tier=data.get("tier", "basic"),
        )
        return jsonify(result)
    except ClawError as e:
        return jsonify({"error": str(e)}), e.status_code or 500


@user_bp.route("/checkout", methods=["POST"])
@require_consumer
def checkout(user_data: dict):
    """Initiate Stripe Checkout via Claw."""
    data = request.get_json(silent=True) or {}
    plan = data.get("plan", "basic")
    success_url = data.get("success_url", "")
    cancel_url = data.get("cancel_url", "")

    if not success_url or not cancel_url:
        return jsonify({"error": "success_url and cancel_url required"}), 400

    token = user_data.get("_token", "")
    try:
        result = get_claw_client().user_checkout(token, plan, success_url, cancel_url)
        return jsonify(result)
    except ClawError as e:
        return jsonify({"error": str(e)}), e.status_code or 500


@user_bp.route("/me/plan", methods=["PUT"])
@require_consumer
def upgrade_plan(user_data: dict):
    """Upgrade/downgrade subscription plan."""
    data = request.get_json(silent=True) or {}
    plan = data.get("plan", "")
    if not plan:
        return jsonify({"error": "plan is required"}), 400

    try:
        result = get_claw_client().set_user_plan(user_data["user_id"], plan)
        return jsonify(result)
    except ClawError as e:
        return jsonify({"error": str(e)}), e.status_code or 500


@user_bp.route("/me/plan", methods=["DELETE"])
@require_consumer
def cancel_plan(user_data: dict):
    """Cancel subscription."""
    immediate = request.args.get("immediate", "false").lower() == "true"
    try:
        result = get_claw_client().cancel_user_plan(user_data["user_id"], immediate=immediate)
        return jsonify(result)
    except ClawError as e:
        return jsonify({"error": str(e)}), e.status_code or 500


# ═══════════════════════════════════════════════════════════════
# Sessions (core — billing via Claw usage tracking)
# ═══════════════════════════════════════════════════════════════


@user_bp.route("/sessions", methods=["POST"])
@require_consumer
def start_session(user_data: dict):
    """Start a paid session.

    Checks usage limits via Claw before starting.
    """
    data = request.get_json(silent=True) or {}
    listing_id = data.get("listing_id", "")
    tier_name = data.get("pricing_tier", "basic")

    listing = get_store().get(listing_id)
    if not listing or listing.status != "active":
        return jsonify({"error": "Listing not found or not active", "code": "NOT_FOUND"}), 404

    # Find pricing tier
    tier = None
    for t in listing.pricing:
        if t.name == tier_name:
            tier = t
            break
    if not tier:
        tier = listing.pricing[0] if listing.pricing else None
    if not tier:
        return jsonify({"error": "No pricing available"}), 400

    # Check usage limits via Claw
    user_id = user_data.get("user_id", "")
    try:
        check = get_claw_client().check_usage(user_id)
        if not check.get("allowed", False):
            return jsonify({
                "error": f"Usage limit reached: {check.get('reason', 'limit exceeded')}",
                "code": "USAGE_LIMIT",
                "tier": check.get("tier", ""),
            }), 402
    except ClawError as e:
        log.warning("Claw usage check failed: %s (proceeding anyway)", e)

    # Create session
    session = Session(
        user_id=user_id,
        listing_id=listing.listing_id,
        bot_name=listing.name,
        pricing_tier=tier.name,
        price_usd=tier.price_usd,
        pricing_unit=tier.unit,
        pricing_unit_amount=tier.unit_amount,
        prepaid_usd=tier.price_usd,
    )

    get_session_store().create(session)
    log.info("Session started: %s (user=%s, bot=%s)", session.session_id, user_id, listing.name)

    resp = session.to_consumer_dict()
    resp["balance_usd"] = user_data.get("balance_usd", 0)
    return jsonify(resp), 201


@user_bp.route("/sessions/<session_id>/message", methods=["POST"])
@require_consumer
def send_message(user_data: dict, session_id: str):
    """Send a message in an active session."""
    ss = get_session_store()
    session = ss.get(session_id)

    if not session:
        return jsonify({"error": "Session not found", "code": "NOT_FOUND"}), 404
    if session.user_id != user_data.get("user_id"):
        return jsonify({"error": "Not your session", "code": "FORBIDDEN"}), 403
    if session.status != "active":
        return jsonify({"error": "Session is not active", "code": "SESSION_ENDED"}), 410

    data = request.get_json(silent=True) or {}
    content = data.get("content", "").strip()
    if not content:
        return jsonify({"error": "content is required"}), 400

    # Record user message
    user_msg = Message(session_id=session_id, role="user", content=content)
    ss.add_message(session_id, user_msg)

    # Check sensitive category
    listing = get_store().get(session.listing_id)
    requires_review = listing and listing.category in SENSITIVE_CATEGORIES

    if requires_review:
        bot_msg = Message(
            session_id=session_id,
            role="assistant",
            content="",
            approval_status="pending_review",
            approval_id=f"apr_{session_id[-6:]}_{session.total_messages}",
        )
        ss.add_message(session_id, bot_msg)
        return jsonify({
            "message_id": bot_msg.message_id,
            "role": "assistant",
            "status": "pending_review",
            "approval_id": bot_msg.approval_id,
            "message": "Your question is being reviewed by a licensed professional.",
            "code": "REVIEW_PENDING",
        }), 202
    else:
        # Route to webhook or built-in provider
        ai_content = ""
        tokens_used = 0

        if listing and getattr(listing, "webhook_url", ""):
            result = call_webhook(
                webhook_url=listing.webhook_url,
                session_id=session_id,
                message_id=user_msg.message_id,
                content=content,
                listing_id=session.listing_id,
                user_id=user_data.get("user_id", ""),
                elapsed_minutes=session.elapsed_minutes,
            )
            if result:
                ai_content = result["content"]
                tokens_used = result.get("tokens_used", 0)
            else:
                return jsonify({"error": "Bot provider unavailable", "code": "PROVIDER_ERROR"}), 503
        else:
            # TODO: Built-in AI provider
            ai_content = "[AI response — integrate built-in provider here]"
            tokens_used = 0

        bot_msg = Message(
            session_id=session_id,
            role="assistant",
            content=ai_content,
            tokens_used=tokens_used,
        )
        ss.add_message(session_id, bot_msg)

        # Record usage in Claw (async-safe, fire and forget on failure)
        if tokens_used > 0:
            try:
                get_claw_client().record_usage(
                    user_id=user_data.get("user_id", ""),
                    tokens_used=tokens_used,
                    model=listing.model if listing else "",
                    action="marketplace_chat",
                )
            except ClawError as e:
                log.warning("Failed to record usage in Claw: %s", e)

        return jsonify(bot_msg.to_public_dict())


@user_bp.route("/sessions/<session_id>", methods=["GET"])
@require_consumer
def get_session(user_data: dict, session_id: str):
    session = get_session_store().get(session_id)
    if not session:
        return jsonify({"error": "Session not found", "code": "NOT_FOUND"}), 404
    if session.user_id != user_data.get("user_id"):
        return jsonify({"error": "Not your session", "code": "FORBIDDEN"}), 403
    return jsonify(session.to_consumer_dict())


@user_bp.route("/sessions/<session_id>/end", methods=["POST"])
@require_consumer
def end_session(user_data: dict, session_id: str):
    """End session and record final usage in Claw."""
    ss = get_session_store()
    session = ss.get(session_id)

    if not session:
        return jsonify({"error": "Session not found", "code": "NOT_FOUND"}), 404
    if session.user_id != user_data.get("user_id"):
        return jsonify({"error": "Not your session", "code": "FORBIDDEN"}), 403
    if session.status != "active":
        return jsonify({"error": "Session already ended", "code": "SESSION_ENDED"}), 410

    result = session.end()
    ss.end_session(session_id)

    # Update listing stats
    listing = get_store().get(session.listing_id)
    if listing:
        listing.record_session(session.elapsed_minutes, session.cost_usd)
        get_store().update(listing)

    result["message"] = "Session ended."
    return jsonify(result)


@user_bp.route("/sessions", methods=["GET"])
@require_consumer
def list_sessions(user_data: dict):
    sessions, total = get_session_store().list_by_user(
        user_id=user_data.get("user_id", ""),
        status=request.args.get("status", ""),
        listing_id=request.args.get("listing_id", ""),
        limit=int(request.args.get("limit", 50)),
        offset=int(request.args.get("offset", 0)),
    )
    return jsonify({"sessions": [s.to_consumer_dict() for s in sessions], "total": total})


@user_bp.route("/sessions/<session_id>/messages", methods=["GET"])
@require_consumer
def get_messages(user_data: dict, session_id: str):
    session = get_session_store().get(session_id)
    if not session:
        return jsonify({"error": "Session not found", "code": "NOT_FOUND"}), 404
    if session.user_id != user_data.get("user_id"):
        return jsonify({"error": "Not your session", "code": "FORBIDDEN"}), 403

    messages = get_session_store().get_messages(
        session_id,
        limit=int(request.args.get("limit", 50)),
        before=request.args.get("before", ""),
    )
    return jsonify({"messages": [m.to_public_dict() for m in messages]})


@user_bp.route("/sessions/<session_id>/rate", methods=["POST"])
@require_consumer
def rate_session(user_data: dict, session_id: str):
    session = get_session_store().get(session_id)
    if not session:
        return jsonify({"error": "Session not found", "code": "NOT_FOUND"}), 404
    if session.user_id != user_data.get("user_id"):
        return jsonify({"error": "Not your session", "code": "FORBIDDEN"}), 403
    if session.status != "ended":
        return jsonify({"error": "Can only rate ended sessions"}), 400

    data = request.get_json(silent=True) or {}
    score = data.get("score")
    if score is None or not (1 <= score <= 5):
        return jsonify({"error": "score must be 1-5"}), 400

    session.rating = float(score)
    session.rating_comment = data.get("comment", "")

    listing = get_store().get(session.listing_id)
    if listing:
        listing.add_rating(float(score))
        get_store().update(listing)

    return jsonify({
        "message": "Thanks for rating!",
        "rating": round(listing.rating, 2) if listing else score,
        "rating_count": listing.rating_count if listing else 1,
    })


# ═══════════════════════════════════════════════════════════════
# Platform stats (public)
# ═══════════════════════════════════════════════════════════════


@user_bp.route("/stats", methods=["GET"])
def platform_stats():
    stats = get_store().stats()
    stats.pop("total_revenue_usd", None)
    stats["active_sessions"] = get_session_store().active_count()
    stats["tag_summary"] = get_tag_engine().summary()
    return jsonify(stats)
