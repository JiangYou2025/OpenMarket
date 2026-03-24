"""Consumer API — browse, auth, wallet, sessions, ratings.

Prefix: /api/c/
Supports both human users (JWT) and bots (API key).
"""

from __future__ import annotations

import logging
import time

from flask import Blueprint, jsonify, request

from .auth import create_token, require_consumer
from .consumer import Consumer, get_consumer_store
from .models import CATEGORIES, SENSITIVE_CATEGORIES
from .session import Message, Session, get_session_store
from .store import get_store
from .tag_engine import get_tag_engine

log = logging.getLogger(__name__)

user_bp = Blueprint("user_api", __name__, url_prefix="/api/c")


# ══════════════════════════════════════════════════════════════
# Browse (no auth)
# ══════════════════════════════════════════════════════════════


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
    """Single listing detail."""
    listing = get_store().get(listing_id)
    if not listing or listing.status not in ("active", "suspended"):
        return jsonify({"error": "Listing not found", "code": "NOT_FOUND"}), 404
    d = listing.to_public_dict()
    d["requires_review"] = listing.category in SENSITIVE_CATEGORIES
    return jsonify(d)


@user_bp.route("/categories", methods=["GET"])
def list_categories():
    """Categories with counts and popular tags."""
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


# ══════════════════════════════════════════════════════════════
# Auth
# ══════════════════════════════════════════════════════════════


@user_bp.route("/auth/register", methods=["POST"])
def register():
    """Register consumer. Returns JWT + API key."""
    data = request.get_json(silent=True) or {}
    email = data.get("email", "").strip()
    password = data.get("password", "")
    name = data.get("name", "")

    if not email:
        return jsonify({"error": "email is required"}), 400
    if not password or len(password) < 6:
        return jsonify({"error": "password must be at least 6 characters"}), 400

    try:
        consumer, api_key = get_consumer_store().register(email, password, name)
    except ValueError as e:
        return jsonify({"error": str(e), "code": "ALREADY_EXISTS"}), 409

    token = create_token(consumer.user_id)
    return jsonify({
        "user_id": consumer.user_id,
        "token": token,
        "api_key": api_key,
        "balance_usd": consumer.balance_usd,
        "message": f"Welcome! You have ${consumer.balance_usd:.2f} free credit.",
    }), 201


@user_bp.route("/auth/login", methods=["POST"])
def login():
    """Login. Returns JWT token."""
    data = request.get_json(silent=True) or {}
    consumer = get_consumer_store().authenticate(
        data.get("email", ""), data.get("password", ""),
    )
    if not consumer:
        return jsonify({"error": "Invalid email or password", "code": "UNAUTHORIZED"}), 401

    token = create_token(consumer.user_id)
    return jsonify({
        "user_id": consumer.user_id,
        "token": token,
        "balance_usd": consumer.balance_usd,
    })


# ══════════════════════════════════════════════════════════════
# Account (auth required)
# ══════════════════════════════════════════════════════════════


@user_bp.route("/me", methods=["GET"])
@require_consumer
def get_me(consumer: Consumer):
    return jsonify(consumer.to_public_dict())


@user_bp.route("/me", methods=["PUT"])
@require_consumer
def update_me(consumer: Consumer):
    data = request.get_json(silent=True) or {}
    for key in ("name", "avatar_url"):
        if key in data:
            setattr(consumer, key, data[key])
    consumer.updated_at = time.time()
    get_consumer_store().update(consumer)
    return jsonify({"message": "Updated", "user": consumer.to_public_dict()})


@user_bp.route("/me/api-key", methods=["POST"])
@require_consumer
def regenerate_api_key(consumer: Consumer):
    new_key = consumer.issue_api_key()
    get_consumer_store().update(consumer)
    return jsonify({
        "api_key": new_key,
        "warning": "Save this key — it will NOT be shown again.",
    })


# ══════════════════════════════════════════════════════════════
# Wallet
# ══════════════════════════════════════════════════════════════


@user_bp.route("/wallet/balance", methods=["GET"])
@require_consumer
def wallet_balance(consumer: Consumer):
    return jsonify({"balance_usd": consumer.balance_usd})


@user_bp.route("/wallet/topup", methods=["POST"])
@require_consumer
def wallet_topup(consumer: Consumer):
    """Top up wallet. In production → Stripe Checkout."""
    data = request.get_json(silent=True) or {}
    amount = float(data.get("amount_usd", 0))
    if amount < 2:
        return jsonify({"error": "Minimum top-up is $2.00"}), 400

    # TODO: Stripe Checkout integration
    tx = get_consumer_store().topup(consumer.user_id, amount)
    return jsonify({
        "message": f"${amount:.2f} added to your balance",
        "balance_usd": consumer.balance_usd + amount,
        "tx_id": tx.tx_id,
    })


@user_bp.route("/wallet/transactions", methods=["GET"])
@require_consumer
def wallet_transactions(consumer: Consumer):
    txs, total = get_consumer_store().get_transactions(
        user_id=consumer.user_id,
        tx_type=request.args.get("type", ""),
        limit=int(request.args.get("limit", 50)),
        offset=int(request.args.get("offset", 0)),
    )
    return jsonify({"transactions": [t.to_dict() for t in txs], "total": total})


# ══════════════════════════════════════════════════════════════
# Sessions (core billing loop)
# ══════════════════════════════════════════════════════════════


@user_bp.route("/sessions", methods=["POST"])
@require_consumer
def start_session(consumer: Consumer):
    """Start a paid session. Pre-charges minimum from wallet."""
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

    # Check balance
    prepaid = tier.price_usd
    if not consumer.can_afford(prepaid):
        return jsonify({
            "error": f"Insufficient balance. Need ${prepaid:.2f}, have ${consumer.balance_usd:.2f}",
            "code": "INSUFFICIENT_BALANCE",
            "balance_usd": consumer.balance_usd,
            "required_usd": prepaid,
        }), 402

    # Create session
    session = Session(
        user_id=consumer.user_id,
        listing_id=listing.listing_id,
        bot_name=listing.name,
        pricing_tier=tier.name,
        price_usd=tier.price_usd,
        pricing_unit=tier.unit,
        pricing_unit_amount=tier.unit_amount,
        prepaid_usd=prepaid,
    )

    # Charge
    cs = get_consumer_store()
    try:
        cs.charge(
            consumer.user_id, prepaid,
            session_id=session.session_id,
            description=f"Session with {listing.name} ({tier.name})",
        )
    except ValueError as e:
        return jsonify({"error": str(e), "code": "INSUFFICIENT_BALANCE"}), 402

    get_session_store().create(session)

    resp = session.to_consumer_dict()
    resp["balance_remaining"] = cs.get_balance(consumer.user_id)
    return jsonify(resp), 201


@user_bp.route("/sessions/<session_id>/message", methods=["POST"])
@require_consumer
def send_message(consumer: Consumer, session_id: str):
    """Send a message in an active session."""
    ss = get_session_store()
    session = ss.get(session_id)

    if not session:
        return jsonify({"error": "Session not found", "code": "NOT_FOUND"}), 404
    if session.user_id != consumer.user_id:
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
        # TODO: Call AI provider / webhook here
        bot_msg = Message(
            session_id=session_id,
            role="assistant",
            content="[AI response — integrate provider here]",
            tokens_used=0,
        )
        ss.add_message(session_id, bot_msg)
        return jsonify(bot_msg.to_public_dict())


@user_bp.route("/sessions/<session_id>", methods=["GET"])
@require_consumer
def get_session(consumer: Consumer, session_id: str):
    """Session status + real-time cost."""
    session = get_session_store().get(session_id)
    if not session:
        return jsonify({"error": "Session not found", "code": "NOT_FOUND"}), 404
    if session.user_id != consumer.user_id:
        return jsonify({"error": "Not your session", "code": "FORBIDDEN"}), 403
    return jsonify(session.to_consumer_dict())


@user_bp.route("/sessions/<session_id>/end", methods=["POST"])
@require_consumer
def end_session(consumer: Consumer, session_id: str):
    """End session and settle billing."""
    ss = get_session_store()
    session = ss.get(session_id)

    if not session:
        return jsonify({"error": "Session not found", "code": "NOT_FOUND"}), 404
    if session.user_id != consumer.user_id:
        return jsonify({"error": "Not your session", "code": "FORBIDDEN"}), 403
    if session.status != "active":
        return jsonify({"error": "Session already ended", "code": "SESSION_ENDED"}), 410

    result = session.end()
    ss.end_session(session_id)

    # Refund overpayment
    cs = get_consumer_store()
    if session.refund_usd > 0:
        cs.refund(
            consumer.user_id, session.refund_usd,
            session_id=session_id,
            description=f"Refund from {session.bot_name} session",
        )

    # Update listing stats
    listing = get_store().get(session.listing_id)
    if listing:
        listing.record_session(session.elapsed_minutes, session.cost_usd)
        get_store().update(listing)

    result["balance_after"] = cs.get_balance(consumer.user_id)
    result["message"] = (
        f"Session ended. ${session.refund_usd:.2f} refunded."
        if session.refund_usd > 0
        else "Session ended."
    )
    return jsonify(result)


@user_bp.route("/sessions", methods=["GET"])
@require_consumer
def list_sessions(consumer: Consumer):
    sessions, total = get_session_store().list_by_user(
        user_id=consumer.user_id,
        status=request.args.get("status", ""),
        listing_id=request.args.get("listing_id", ""),
        limit=int(request.args.get("limit", 50)),
        offset=int(request.args.get("offset", 0)),
    )
    return jsonify({"sessions": [s.to_consumer_dict() for s in sessions], "total": total})


@user_bp.route("/sessions/<session_id>/messages", methods=["GET"])
@require_consumer
def get_messages(consumer: Consumer, session_id: str):
    session = get_session_store().get(session_id)
    if not session:
        return jsonify({"error": "Session not found", "code": "NOT_FOUND"}), 404
    if session.user_id != consumer.user_id:
        return jsonify({"error": "Not your session", "code": "FORBIDDEN"}), 403

    messages = get_session_store().get_messages(
        session_id,
        limit=int(request.args.get("limit", 50)),
        before=request.args.get("before", ""),
    )
    return jsonify({"messages": [m.to_public_dict() for m in messages]})


@user_bp.route("/sessions/<session_id>/rate", methods=["POST"])
@require_consumer
def rate_session(consumer: Consumer, session_id: str):
    session = get_session_store().get(session_id)
    if not session:
        return jsonify({"error": "Session not found", "code": "NOT_FOUND"}), 404
    if session.user_id != consumer.user_id:
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


# ══════════════════════════════════════════════════════════════
# Platform stats (public)
# ══════════════════════════════════════════════════════════════


@user_bp.route("/stats", methods=["GET"])
def platform_stats():
    stats = get_store().stats()
    stats.pop("total_revenue_usd", None)
    stats["active_sessions"] = get_session_store().active_count()
    stats["tag_summary"] = get_tag_engine().summary()
    return jsonify(stats)
