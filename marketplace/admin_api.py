"""Admin API — platform management endpoints.

All endpoints require admin API key: Authorization: Bearer 2d_ak_xxx

Prefix: /api/admin
"""

from __future__ import annotations

import logging
import time
from functools import wraps

from flask import Blueprint, jsonify, request

from .consumer import get_consumer_store
from .models import CATEGORIES
from .session import get_session_store
from .store import get_store
from .tag_engine import get_tag_engine

log = logging.getLogger(__name__)

admin_bp = Blueprint("admin_api", __name__, url_prefix="/api/admin")

# Admin keys — in production, load from env
ADMIN_KEYS = {"2d_ak_default_change_me"}


def require_admin(f):
    """Require admin API key."""
    @wraps(f)
    def wrapper(*args, **kwargs):
        auth = request.headers.get("Authorization", "")
        if not auth.startswith("Bearer "):
            return jsonify({"error": "Admin auth required", "code": "UNAUTHORIZED"}), 401
        key = auth[7:].strip()
        if not key.startswith("2d_ak_") or key not in ADMIN_KEYS:
            return jsonify({"error": "Invalid admin key", "code": "FORBIDDEN"}), 403
        return f(*args, **kwargs)
    return wrapper


# ═══════════════════════════════════════════════════════════════
# Listings management
# ═══════════════════════════════════════════════════════════════


@admin_bp.route("/listings", methods=["GET"])
@require_admin
def list_all_listings():
    """All listings including draft/suspended."""
    store = get_store()
    listings = store.all()

    status = request.args.get("status", "")
    if status:
        listings = [l for l in listings if l.status == status]

    category = request.args.get("category", "")
    if category:
        listings = [l for l in listings if l.category == category]

    listings.sort(key=lambda l: l.created_at, reverse=True)

    limit = int(request.args.get("limit", 100))
    offset = int(request.args.get("offset", 0))

    return jsonify({
        "listings": [l.to_dict() for l in listings[offset:offset + limit]],
        "total": len(listings),
    })


@admin_bp.route("/listings/<listing_id>", methods=["GET"])
@require_admin
def get_listing(listing_id: str):
    """Get any listing (full details including secrets)."""
    listing = get_store().get(listing_id)
    if not listing:
        return jsonify({"error": "Not found", "code": "NOT_FOUND"}), 404
    return jsonify(listing.to_dict())


@admin_bp.route("/listings/<listing_id>", methods=["PUT"])
@require_admin
def update_listing(listing_id: str):
    """Update any listing (set featured, verified, status, etc.)."""
    store = get_store()
    listing = store.get(listing_id)
    if not listing:
        return jsonify({"error": "Not found", "code": "NOT_FOUND"}), 404

    data = request.get_json(silent=True) or {}
    admin_updatable = [
        "name", "tagline", "description", "category", "tags",
        "featured", "verified", "status",
    ]
    for key in admin_updatable:
        if key in data:
            setattr(listing, key, data[key])

    listing.updated_at = time.time()
    store.update(listing)

    # Re-index
    if listing.status == "active":
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
    else:
        get_tag_engine().remove_listing(listing.listing_id)

    return jsonify({"message": "Updated", "listing": listing.to_dict()})


@admin_bp.route("/listings/<listing_id>/suspend", methods=["POST"])
@require_admin
def suspend_listing(listing_id: str):
    """Force-suspend a listing."""
    store = get_store()
    listing = store.get(listing_id)
    if not listing:
        return jsonify({"error": "Not found", "code": "NOT_FOUND"}), 404

    listing.suspend()
    store.update(listing)
    get_tag_engine().remove_listing(listing.listing_id)

    log.info("Admin suspended listing: %s (%s)", listing.name, listing_id)
    return jsonify({"message": f"Listing '{listing.name}' suspended"})


@admin_bp.route("/listings/<listing_id>", methods=["DELETE"])
@require_admin
def delete_listing(listing_id: str):
    """Force-delete a listing."""
    store = get_store()
    listing = store.get(listing_id)
    if not listing:
        return jsonify({"error": "Not found", "code": "NOT_FOUND"}), 404

    name = listing.name
    store.delete(listing_id)
    get_tag_engine().remove_listing(listing_id)

    log.info("Admin deleted listing: %s (%s)", name, listing_id)
    return jsonify({"message": f"Listing '{name}' deleted permanently"})


# ═══════════════════════════════════════════════════════════════
# Users management
# ═══════════════════════════════════════════════════════════════


@admin_bp.route("/users", methods=["GET"])
@require_admin
def list_users():
    """List all consumer accounts."""
    cstore = get_consumer_store()
    # Access internal dict (admin only)
    with cstore._lock:
        users = list(cstore._users.values())

    status = request.args.get("status", "")
    if status:
        users = [u for u in users if u.status == status]

    users.sort(key=lambda u: u.created_at, reverse=True)

    limit = int(request.args.get("limit", 100))
    offset = int(request.args.get("offset", 0))

    return jsonify({
        "users": [u.to_public_dict() for u in users[offset:offset + limit]],
        "total": len(users),
    })


@admin_bp.route("/users/<user_id>", methods=["GET"])
@require_admin
def get_user(user_id: str):
    """Get user details."""
    consumer = get_consumer_store().get(user_id)
    if not consumer:
        return jsonify({"error": "Not found", "code": "NOT_FOUND"}), 404
    return jsonify(consumer.to_public_dict())


@admin_bp.route("/users/<user_id>", methods=["PUT"])
@require_admin
def update_user(user_id: str):
    """Admin update: adjust balance, suspend/activate.

    Body: {"balance_adjust": 5.0, "status": "suspended"}
    """
    cstore = get_consumer_store()
    consumer = cstore.get(user_id)
    if not consumer:
        return jsonify({"error": "Not found", "code": "NOT_FOUND"}), 404

    data = request.get_json(silent=True) or {}

    if "status" in data:
        consumer.status = data["status"]

    if "name" in data:
        consumer.name = data["name"]

    # Balance adjustment (positive = add, negative = deduct)
    adjust = data.get("balance_adjust", 0)
    if adjust:
        if adjust > 0:
            cstore.topup(user_id, adjust)
        elif adjust < 0 and consumer.can_afford(abs(adjust)):
            cstore.charge(user_id, abs(adjust), description="Admin adjustment")

    consumer.updated_at = time.time()
    cstore.update(consumer)

    log.info("Admin updated user %s: %s", user_id, data)
    return jsonify({"message": "Updated", "user": consumer.to_public_dict()})


# ═══════════════════════════════════════════════════════════════
# Sessions
# ═══════════════════════════════════════════════════════════════


@admin_bp.route("/sessions", methods=["GET"])
@require_admin
def list_sessions():
    """All sessions across the platform."""
    sstore = get_session_store()
    with sstore._lock:
        sessions = list(sstore._sessions.values())

    status = request.args.get("status", "")
    if status:
        sessions = [s for s in sessions if s.status == status]

    listing_id = request.args.get("listing_id", "")
    if listing_id:
        sessions = [s for s in sessions if s.listing_id == listing_id]

    user_id = request.args.get("user_id", "")
    if user_id:
        sessions = [s for s in sessions if s.user_id == user_id]

    sessions.sort(key=lambda s: s.started_at, reverse=True)

    limit = int(request.args.get("limit", 100))
    offset = int(request.args.get("offset", 0))

    return jsonify({
        "sessions": [s.to_provider_dict() for s in sessions[offset:offset + limit]],
        "total": len(sessions),
    })


# ═══════════════════════════════════════════════════════════════
# Approvals (admin override)
# ═══════════════════════════════════════════════════════════════


@admin_bp.route("/approvals", methods=["GET"])
@require_admin
def list_approvals():
    """All pending approvals across the platform."""
    sstore = get_session_store()
    with sstore._lock:
        sessions = [s for s in sstore._sessions.values() if s.status == "active"]

    approvals = []
    for session in sessions:
        messages = sstore.get_messages(session.session_id, limit=200)
        for msg in messages:
            if msg.approval_status == "pending_review":
                # Find preceding user message
                idx = next((i for i, m in enumerate(messages) if m.message_id == msg.message_id), 0)
                user_msg = messages[idx - 1].content if idx > 0 else ""
                approvals.append({
                    "approval_id": msg.approval_id,
                    "session_id": session.session_id,
                    "listing_id": session.listing_id,
                    "bot_name": session.bot_name,
                    "user_message": user_msg,
                    "ai_response": msg.content,
                    "status": "pending",
                    "created_at": msg.created_at,
                })

    return jsonify({"approvals": approvals, "total": len(approvals)})


@admin_bp.route("/approvals/<approval_id>/override", methods=["POST"])
@require_admin
def override_approval(approval_id: str):
    """Admin force-approve or force-reject.

    Body: {"action": "approve|reject", "edited_response": "...", "note": "..."}
    """
    data = request.get_json(silent=True) or {}
    action = data.get("action", "approve")
    edited = data.get("edited_response", "")
    note = data.get("note", "")

    sstore = get_session_store()
    with sstore._lock:
        sessions = list(sstore._sessions.values())

    for session in sessions:
        messages = sstore.get_messages(session.session_id, limit=200)
        for msg in messages:
            if msg.approval_id == approval_id and msg.approval_status == "pending_review":
                if action == "reject":
                    msg.approval_status = "rejected"
                    msg.content = f"[Admin rejected] {note}" if note else "[Response rejected by admin]"
                else:
                    msg.approval_status = "approved"
                    if edited:
                        msg.content = edited
                sstore._save_messages(session.session_id, messages)
                log.info("Admin %s approval %s", action, approval_id)
                return jsonify({"message": f"Approval {action}d by admin", "approval_id": approval_id})

    return jsonify({"error": "Approval not found", "code": "NOT_FOUND"}), 404


# ═══════════════════════════════════════════════════════════════
# Transactions
# ═══════════════════════════════════════════════════════════════


@admin_bp.route("/transactions", methods=["GET"])
@require_admin
def list_transactions():
    """All transactions across the platform."""
    cstore = get_consumer_store()
    with cstore._lock:
        txs = list(cstore._transactions)

    tx_type = request.args.get("type", "")
    if tx_type:
        txs = [t for t in txs if t.type == tx_type]

    user_id = request.args.get("user_id", "")
    if user_id:
        txs = [t for t in txs if t.user_id == user_id]

    txs.sort(key=lambda t: t.created_at, reverse=True)

    limit = int(request.args.get("limit", 100))
    offset = int(request.args.get("offset", 0))

    return jsonify({
        "transactions": [t.to_dict() for t in txs[offset:offset + limit]],
        "total": len(txs),
    })


@admin_bp.route("/refund/<tx_id>", methods=["POST"])
@require_admin
def admin_refund(tx_id: str):
    """Admin-initiated refund for a specific transaction."""
    cstore = get_consumer_store()

    # Find the original transaction
    with cstore._lock:
        original = None
        for t in cstore._transactions:
            if t.tx_id == tx_id:
                original = t
                break

    if not original:
        return jsonify({"error": "Transaction not found", "code": "NOT_FOUND"}), 404

    if original.type != "charge":
        return jsonify({"error": "Can only refund charge transactions", "code": "BAD_REQUEST"}), 400

    refund_amount = abs(original.amount_usd)
    data = request.get_json(silent=True) or {}
    reason = data.get("reason", "Admin refund")

    tx = cstore.refund(
        original.user_id,
        refund_amount,
        session_id=original.session_id,
        description=f"Admin refund: {reason}",
    )

    log.info("Admin refund: $%.2f to user %s (tx %s)", refund_amount, original.user_id, tx_id)

    return jsonify({
        "message": f"${refund_amount:.2f} refunded to user {original.user_id}",
        "refund_tx_id": tx.tx_id,
        "original_tx_id": tx_id,
    })


# ═══════════════════════════════════════════════════════════════
# Platform stats (full, including revenue)
# ═══════════════════════════════════════════════════════════════


@admin_bp.route("/stats", methods=["GET"])
@require_admin
def admin_stats():
    """Full platform stats including revenue."""
    store = get_store()
    cstore = get_consumer_store()
    sstore = get_session_store()

    listing_stats = store.stats()

    with cstore._lock:
        total_users = len(cstore._users)
        total_balance = sum(u.balance_usd for u in cstore._users.values())
        total_topups = sum(u.total_topup_usd for u in cstore._users.values())
        total_spent = sum(u.total_spent_usd for u in cstore._users.values())

    active_sessions = sstore.active_count()

    tag_summary = get_tag_engine().summary()

    return jsonify({
        "listings": listing_stats,
        "users": {
            "total": total_users,
            "total_balance_usd": round(total_balance, 2),
            "total_topups_usd": round(total_topups, 2),
            "total_spent_usd": round(total_spent, 2),
        },
        "sessions": {
            "active": active_sessions,
        },
        "tag_engine": tag_summary,
        "platform_revenue_usd": round(listing_stats.get("total_revenue_usd", 0) * 0.20, 2),
    })
