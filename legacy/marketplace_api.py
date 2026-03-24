"""2dollars Marketplace API — Flask blueprint.

Public endpoints (no auth):
    GET  /api/2dollars/bots              — Browse marketplace
    GET  /api/2dollars/bots/<slug>       — Bot detail
    GET  /api/2dollars/categories        — Category list
    GET  /api/2dollars/pricing           — Pricing tiers

Authenticated endpoints (session auth):
    POST /api/2dollars/bots              — Register a new bot
    PUT  /api/2dollars/bots/<slug>       — Update bot
    DEL  /api/2dollars/bots/<slug>       — Remove bot
    POST /api/2dollars/bots/<slug>/key   — Rotate API key

Bot auth (API key in header):
    POST /api/2dollars/chat              — Incoming chat via API key
"""

from pathlib import Path

from flask import Blueprint, jsonify, request, send_from_directory

from core.marketplace import get_marketplace, get_approval_store, get_blog_store, CATEGORIES, PRICING_TIERS, SENSITIVE_CATEGORIES

bp = Blueprint("marketplace", __name__)

_STATIC = Path(__file__).resolve().parent / "static"


@bp.route("/marketplace")
@bp.route("/2dollars")
def marketplace_page():
    """Serve the marketplace frontend."""
    return send_from_directory(str(_STATIC), "marketplace.html")


# ── Public: Browse ───────────────────────────────────────────────────

@bp.route("/api/2dollars/bots", methods=["GET"])
def list_bots():
    """Browse the bot marketplace."""
    store = get_marketplace()
    items, total = store.list_bots(
        category=request.args.get("category", ""),
        tag=request.args.get("tag", ""),
        search=request.args.get("q", ""),
        sort_by=request.args.get("sort", "rating"),
        limit=min(int(request.args.get("limit", 50)), 100),
        offset=int(request.args.get("offset", 0)),
    )
    return jsonify({"bots": items, "total": total})


@bp.route("/api/2dollars/bots/<slug>", methods=["GET"])
def get_bot(slug):
    """Get bot detail by slug."""
    store = get_marketplace()
    card = store.get(slug)
    if not card or card.status not in ("listed", "featured"):
        return jsonify({"error": "Bot not found"}), 404
    return jsonify(card.to_detail_dict())


@bp.route("/api/2dollars/categories", methods=["GET"])
def list_categories():
    """List categories with bot counts."""
    store = get_marketplace()
    return jsonify({"categories": store.categories_summary()})


@bp.route("/api/2dollars/pricing", methods=["GET"])
def list_pricing():
    """List pricing tiers."""
    tiers = []
    for key, info in PRICING_TIERS.items():
        tiers.append({
            "tier": key,
            "label": info["label"],
            "price_per_min": info["price_per_min"],
            "price_per_2_dollars": round(2.0 / info["price_per_min"]) if info["price_per_min"] > 0 else 0,
            "models": info["models"],
        })
    return jsonify({"tiers": tiers})


# ── Authenticated: Register & Manage ─────────────────────────────────

@bp.route("/api/2dollars/bots", methods=["POST"])
def register_bot():
    """Register a new bot on the marketplace.

    Minimal required fields: name, description, author.
    Returns the bot card + API key (shown ONCE).
    """
    from flask import session as flask_session
    if not flask_session.get("authenticated"):
        # Also accept API key auth for programmatic registration
        auth = request.headers.get("Authorization", "")
        if not auth.startswith("Bearer 2d_sk_"):
            return jsonify({"error": "Authentication required"}), 401

    data = request.get_json(force=True)

    # Validate required fields
    name = (data.get("name") or "").strip()
    description = (data.get("description") or "").strip()
    author = (data.get("author") or "").strip()

    if not name:
        return jsonify({"error": "name is required"}), 400
    if not description:
        return jsonify({"error": "description is required"}), 400
    if not author:
        return jsonify({"error": "author is required"}), 400

    store = get_marketplace()
    card, api_key = store.register(
        name=name,
        description=description,
        author=author,
        provider=data.get("provider", ""),
        model=data.get("model", ""),
        category=data.get("category", "general"),
        tags=data.get("tags", []),
        pricing_tier=data.get("pricing_tier", "standard"),
        price_per_min=float(data.get("price_per_min", 0)),
        system_prompt=data.get("system_prompt", ""),
        webhook_url=data.get("webhook_url", ""),
        example_prompts=data.get("example_prompts", []),
        bot_id=data.get("bot_id", ""),
        slug=data.get("slug", ""),
    )

    result = card.to_detail_dict()
    result["api_key"] = api_key  # Only returned once!
    return jsonify(result), 201


@bp.route("/api/2dollars/bots/<slug>", methods=["PUT"])
def update_bot(slug):
    """Update a bot's marketplace listing."""
    from flask import session as flask_session
    if not flask_session.get("authenticated"):
        return jsonify({"error": "Authentication required"}), 401

    data = request.get_json(force=True)

    # Fields that can be updated
    allowed = {
        "name", "description", "long_description", "author", "avatar_url",
        "category", "tags", "provider", "model", "system_prompt",
        "pricing_tier", "price_per_min", "webhook_url", "example_prompts",
        "status", "featured", "verified",
    }
    updates = {k: v for k, v in data.items() if k in allowed}

    if not updates:
        return jsonify({"error": "No valid fields to update"}), 400

    store = get_marketplace()
    card = store.update(slug, **updates)
    if not card:
        return jsonify({"error": "Bot not found"}), 404
    return jsonify(card.to_detail_dict())


@bp.route("/api/2dollars/bots/<slug>", methods=["DELETE"])
def delete_bot(slug):
    """Remove a bot from the marketplace."""
    from flask import session as flask_session
    if not flask_session.get("authenticated"):
        return jsonify({"error": "Authentication required"}), 401

    store = get_marketplace()
    if store.remove(slug):
        return jsonify({"ok": True})
    return jsonify({"error": "Bot not found"}), 404


@bp.route("/api/2dollars/bots/<slug>/key", methods=["POST"])
def rotate_key(slug):
    """Rotate API key for a bot. Returns new key (shown ONCE)."""
    from flask import session as flask_session
    if not flask_session.get("authenticated"):
        return jsonify({"error": "Authentication required"}), 401

    store = get_marketplace()
    new_key = store.rotate_api_key(slug)
    if not new_key:
        return jsonify({"error": "Bot not found"}), 404
    return jsonify({"api_key": new_key, "slug": slug})


# ── Bot API Key Auth: Chat endpoint ──────────────────────────────────

@bp.route("/api/2dollars/chat", methods=["POST"])
def chat():
    """Chat with a marketplace bot via API key.

    Header: Authorization: Bearer 2d_sk_xxx
    Body: {"message": "hello", "session_id": "optional"}
    """
    auth = request.headers.get("Authorization", "")
    if not auth.startswith("Bearer "):
        return jsonify({"error": "API key required. Header: Authorization: Bearer 2d_sk_xxx"}), 401

    api_key = auth[7:]
    store = get_marketplace()
    card = store.get_by_api_key(api_key)
    if not card:
        return jsonify({"error": "Invalid API key"}), 401
    if card.status != "listed":
        return jsonify({"error": "Bot is not active"}), 403

    data = request.get_json(force=True)
    message = (data.get("message") or "").strip()
    if not message:
        return jsonify({"error": "message is required"}), 400

    # Route to the AI provider
    import asyncio
    from core.providers.registry import route_chat, get_provider
    from core.providers.base import ExecutionContext

    provider_name = card.provider
    if not provider_name:
        return jsonify({"error": "Bot has no AI provider configured"}), 400

    provider = get_provider(provider_name)
    if not provider:
        return jsonify({"error": f"Provider '{provider_name}' not available"}), 503

    ctx = ExecutionContext(
        system_prompt=card.system_prompt,
        session_id=data.get("session_id", ""),
    )

    # Run async provider in sync Flask context
    loop = asyncio.new_event_loop()
    try:
        result = loop.run_until_complete(
            route_chat(
                provider_name=provider_name,
                message=message,
                system_prompt=card.system_prompt,
                ctx=ctx,
            )
        )
    finally:
        loop.close()

    if result.error:
        return jsonify({"error": result.error}), 500

    # ── Sensitive categories: queue for professional approval ──────
    if card.requires_approval():
        approval = get_approval_store().create(
            bot_slug=card.slug,
            session_id=data.get("session_id", ""),
            user_message=message,
            ai_response=result.text,
            provider_name=result.provider_name,
            model_used=result.model_used,
            usage=result.usage,
        )
        return jsonify({
            "status": "pending_approval",
            "approval_id": approval.approval_id,
            "message": "Your question is being reviewed by a licensed professional. No charge until approved.",
            "poll_url": f"/api/2dollars/approvals/{approval.approval_id}",
            "bot": card.slug,
        }), 202

    # ── Non-sensitive: deliver immediately ─────────────────────────
    store.record_session(card.slug, duration_min=1)

    return jsonify({
        "reply": result.text,
        "bot": card.slug,
        "provider": result.provider_name,
        "model": result.model_used,
        "usage": result.usage,
    })


# ── Quick onboard: one-click from existing BotInstance ───────────────

@bp.route("/api/2dollars/onboard/<bot_id>", methods=["POST"])
def onboard_existing(bot_id):
    """One-click onboard an existing TGPort bot to the marketplace.

    Pulls name, system_prompt from BotInstance and creates a listing.
    """
    from flask import session as flask_session
    if not flask_session.get("authenticated"):
        return jsonify({"error": "Authentication required"}), 401

    from bot_instance import manager
    instance = manager.get(bot_id)
    if not instance:
        return jsonify({"error": f"Bot '{bot_id}' not found in TGPort"}), 404

    # Check if already onboarded
    store = get_marketplace()
    existing = store.get_by_bot_id(bot_id)
    if existing:
        return jsonify({"error": f"Bot already listed as '{existing.slug}'", "slug": existing.slug}), 409

    data = request.get_json(silent=True) or {}

    card, api_key = store.register(
        name=data.get("name", instance.label),
        description=data.get("description", f"{instance.label} — powered by TGPort"),
        author=data.get("author", "TGPort"),
        provider=data.get("provider", "claude"),
        model=data.get("model", ""),
        category=data.get("category", "general"),
        tags=data.get("tags", []),
        pricing_tier=data.get("pricing_tier", "standard"),
        system_prompt=instance.system_prompt or "",
        bot_id=bot_id,
        example_prompts=data.get("example_prompts", []),
    )

    result = card.to_detail_dict()
    result["api_key"] = api_key
    return jsonify(result), 201


# ── Stats endpoint ───────────────────────────────────────────────────

@bp.route("/api/2dollars/stats", methods=["GET"])
def marketplace_stats():
    """Overall marketplace statistics."""
    store = get_marketplace()
    bots, total = store.list_bots(status="listed", limit=9999)
    total_sessions = sum(b.get("total_sessions", 0) for b in bots)
    return jsonify({
        "total_bots": total,
        "total_sessions": total_sessions,
        "categories": store.categories_summary(),
    })


# ═══════════════════════════════════════════════════════════════════════
# Approval Queue — human-in-the-loop for sensitive categories
# Professional review required before response delivery & billing
# ═══════════════════════════════════════════════════════════════════════


@bp.route("/api/2dollars/approvals/<approval_id>", methods=["GET"])
def poll_approval(approval_id):
    """User polls approval status. No auth needed (approval_id is capability token)."""
    pa = get_approval_store().get(approval_id)
    if not pa:
        return jsonify({"error": "Approval not found"}), 404
    return jsonify(pa.to_user_dict())


# ═══════════════════════════════════════════════════════════════════════
# Bot Self-Service API — authenticate with API key, manage own listing
# No web UI needed. Bots use these to register and manage themselves.
# ═══════════════════════════════════════════════════════════════════════

def _bot_auth():
    """Extract and verify bot API key from Authorization header.

    Returns (BotCard, None) on success, (None, error_response) on failure.
    """
    auth = request.headers.get("Authorization", "")
    if not auth.startswith("Bearer 2d_sk_"):
        return None, (jsonify({"error": "API key required", "hint": "Authorization: Bearer 2d_sk_xxx"}), 401)
    card = get_marketplace().get_by_api_key(auth[7:])
    if not card:
        return None, (jsonify({"error": "Invalid API key"}), 401)
    return card, None


@bp.route("/api/2dollars/me", methods=["GET"])
def bot_me():
    """Bot checks its own listing. Auth: API key."""
    card, err = _bot_auth()
    if err:
        return err
    d = card.to_detail_dict()
    d["slug"] = card.slug
    return jsonify(d)


@bp.route("/api/2dollars/me", methods=["PATCH"])
def bot_update_self():
    """Bot updates its own listing. Auth: API key.

    Updatable: name, description, long_description, category, tags,
    system_prompt, example_prompts, avatar_url, webhook_url, pricing_tier.
    """
    card, err = _bot_auth()
    if err:
        return err

    data = request.get_json(force=True)
    allowed = {
        "name", "description", "long_description", "category", "tags",
        "system_prompt", "example_prompts", "avatar_url", "webhook_url",
        "pricing_tier", "price_per_min",
    }
    updates = {k: v for k, v in data.items() if k in allowed}
    if not updates:
        return jsonify({"error": "Nothing to update", "allowed_fields": sorted(allowed)}), 400

    store = get_marketplace()
    updated = store.update(card.slug, **updates)
    return jsonify(updated.to_detail_dict())


@bp.route("/api/2dollars/me/key", methods=["POST"])
def bot_rotate_own_key():
    """Bot rotates its own API key. Returns new key ONCE."""
    card, err = _bot_auth()
    if err:
        return err
    new_key = get_marketplace().rotate_api_key(card.slug)
    return jsonify({"api_key": new_key, "slug": card.slug})


@bp.route("/api/2dollars/me/stats", methods=["GET"])
def bot_own_stats():
    """Bot checks its own usage stats."""
    card, err = _bot_auth()
    if err:
        return err
    return jsonify({
        "slug": card.slug,
        "rating": card.rating,
        "rating_count": card.rating_count,
        "total_sessions": card.total_sessions,
        "total_minutes": card.total_minutes,
        "status": card.status,
    })


@bp.route("/api/2dollars/me/pause", methods=["POST"])
def bot_pause():
    """Bot pauses itself (go offline). Auth: API key."""
    card, err = _bot_auth()
    if err:
        return err
    get_marketplace().update(card.slug, status="draft")
    return jsonify({"ok": True, "status": "draft", "message": "Bot paused. POST /api/2dollars/me/resume to go live."})


@bp.route("/api/2dollars/me/resume", methods=["POST"])
def bot_resume():
    """Bot resumes itself (go live). Auth: API key."""
    card, err = _bot_auth()
    if err:
        return err
    get_marketplace().update(card.slug, status="listed")
    return jsonify({"ok": True, "status": "listed", "message": "Bot is live."})


# ── Bot Holder: Approval Review ────────────────────────────────────────

@bp.route("/api/2dollars/me/pending", methods=["GET"])
def bot_list_pending():
    """List pending approvals for the authenticated bot. Auth: API key."""
    card, err = _bot_auth()
    if err:
        return err
    pending = get_approval_store().list_pending(card.slug)
    return jsonify({
        "bot": card.slug,
        "pending": [pa.to_reviewer_dict() for pa in pending],
        "count": len(pending),
    })


@bp.route("/api/2dollars/me/approve/<approval_id>", methods=["POST"])
def bot_approve(approval_id):
    """Approve a pending response (deliver to user, start billing). Auth: API key.

    Body (optional): {"response": "edited text", "note": "reviewer comment"}
    If no "response" field, the original AI response is delivered as-is.
    """
    card, err = _bot_auth()
    if err:
        return err

    astore = get_approval_store()
    pa = astore.get(approval_id)
    if not pa:
        return jsonify({"error": "Approval not found"}), 404
    if pa.bot_slug != card.slug:
        return jsonify({"error": "This approval belongs to a different bot"}), 403
    if pa.status != "pending":
        return jsonify({"error": f"Cannot approve: status is '{pa.status}'"}), 409

    data = request.get_json(silent=True) or {}
    edited = (data.get("response") or "").strip()
    note = (data.get("note") or "").strip()

    result = astore.approve(approval_id, edited_response=edited, note=note)
    if not result:
        return jsonify({"error": "Approval expired or already processed"}), 410

    # Now bill: record the session
    get_marketplace().record_session(card.slug, duration_min=1)

    return jsonify({
        "ok": True,
        "status": result.status,
        "approval_id": approval_id,
        "message": "Response approved and delivered to user.",
    })


@bp.route("/api/2dollars/me/reject/<approval_id>", methods=["POST"])
def bot_reject(approval_id):
    """Reject a pending response (user not charged). Auth: API key.

    Body (optional): {"note": "reason for rejection"}
    """
    card, err = _bot_auth()
    if err:
        return err

    astore = get_approval_store()
    pa = astore.get(approval_id)
    if not pa:
        return jsonify({"error": "Approval not found"}), 404
    if pa.bot_slug != card.slug:
        return jsonify({"error": "This approval belongs to a different bot"}), 403
    if pa.status != "pending":
        return jsonify({"error": f"Cannot reject: status is '{pa.status}'"}), 409

    data = request.get_json(silent=True) or {}
    note = (data.get("note") or "").strip()

    result = astore.reject(approval_id, note=note)
    if not result:
        return jsonify({"error": "Approval expired or already processed"}), 410

    return jsonify({
        "ok": True,
        "status": "rejected",
        "approval_id": approval_id,
        "message": "Response rejected. User was not charged.",
    })


# ── Quick reference endpoint ─────────────────────────────────────────

@bp.route("/api/2dollars/reload", methods=["POST"])
def reload_marketplace():
    """Admin: reload marketplace data from disk."""
    from flask import session as flask_session
    if not flask_session.get("authenticated"):
        return jsonify({"error": "Authentication required"}), 401
    store = get_marketplace()
    store.reload()
    return jsonify({"ok": True, "total_bots": store.count()})


# ═══════════════════════════════════════════════════════════════════════
# Blog / Success Stories
# ═══════════════════════════════════════════════════════════════════════


@bp.route("/api/2dollars/blog", methods=["GET"])
def list_blog_posts():
    """List published blog posts / success stories."""
    store = get_blog_store()
    posts, total = store.list_posts(
        tag=request.args.get("tag", ""),
        search=request.args.get("q", ""),
        limit=min(int(request.args.get("limit", 20)), 50),
        offset=int(request.args.get("offset", 0)),
    )
    return jsonify({"posts": posts, "total": total})


@bp.route("/api/2dollars/blog/<post_id>", methods=["GET"])
def get_blog_post(post_id):
    """Get a single blog post (increments view count)."""
    store = get_blog_store()
    post = store.get(post_id)
    if not post or post.status != "published":
        return jsonify({"error": "Post not found"}), 404
    store.increment_views(post_id)
    return jsonify(post.to_detail_dict())


@bp.route("/api/2dollars/blog", methods=["POST"])
def create_blog_post():
    """Create a new blog post / success story.

    Required: title, author, summary, content.
    Optional: bot_slug, tags, cover_emoji.
    No auth required — community feature. Anyone can share.
    """

    data = request.get_json(force=True)
    title = (data.get("title") or "").strip()
    author = (data.get("author") or "").strip()
    summary = (data.get("summary") or "").strip()
    content = (data.get("content") or "").strip()

    if not title:
        return jsonify({"error": "title is required"}), 400
    if not content:
        return jsonify({"error": "content is required"}), 400
    if not author:
        return jsonify({"error": "author is required"}), 400
    if not summary:
        summary = content[:120] + ("..." if len(content) > 120 else "")

    store = get_blog_store()
    post = store.create(
        title=title,
        author=author,
        summary=summary,
        content=content,
        bot_slug=data.get("bot_slug", ""),
        tags=data.get("tags", []),
        cover_emoji=data.get("cover_emoji", ""),
    )
    return jsonify(post.to_detail_dict()), 201


@bp.route("/api/2dollars/blog/<post_id>", methods=["PUT"])
def update_blog_post(post_id):
    """Update a blog post."""
    from flask import session as flask_session
    if not flask_session.get("authenticated"):
        return jsonify({"error": "Authentication required"}), 401

    data = request.get_json(force=True)
    allowed = {"title", "summary", "content", "bot_slug", "tags", "cover_emoji", "status"}
    updates = {k: v for k, v in data.items() if k in allowed}
    if not updates:
        return jsonify({"error": "No valid fields to update"}), 400

    store = get_blog_store()
    post = store.update(post_id, **updates)
    if not post:
        return jsonify({"error": "Post not found"}), 404
    return jsonify(post.to_detail_dict())


@bp.route("/api/2dollars/blog/<post_id>", methods=["DELETE"])
def delete_blog_post(post_id):
    """Delete a blog post."""
    from flask import session as flask_session
    if not flask_session.get("authenticated"):
        return jsonify({"error": "Authentication required"}), 401

    store = get_blog_store()
    if store.remove(post_id):
        return jsonify({"ok": True})
    return jsonify({"error": "Post not found"}), 404


@bp.route("/api/2dollars/blog/<post_id>/like", methods=["POST"])
def like_blog_post(post_id):
    """Like a blog post (no auth needed)."""
    store = get_blog_store()
    post = store.get(post_id)
    if not post:
        return jsonify({"error": "Post not found"}), 404
    store.toggle_like(post_id, delta=1)
    return jsonify({"ok": True, "likes": post.likes + 1})


@bp.route("/api/2dollars/help", methods=["GET"])
def api_help():
    """Quick reference for all API endpoints."""
    return jsonify({
        "2dollars_api": "v1",
        "public_endpoints": {
            "GET /api/2dollars/bots": "Browse all bots (params: category, q, sort, limit, offset)",
            "GET /api/2dollars/bots/<slug>": "Get bot detail",
            "GET /api/2dollars/categories": "List categories",
            "GET /api/2dollars/pricing": "Pricing tiers",
            "GET /api/2dollars/stats": "Marketplace stats",
            "GET /api/2dollars/help": "This help",
            "GET /api/2dollars/approvals/<id>": "Poll approval status (for sensitive category responses)",
        },
        "register": {
            "POST /api/2dollars/bots": {
                "description": "Register a new bot (returns API key ONCE)",
                "required_fields": ["name", "description", "author"],
                "optional_fields": ["provider", "model", "category", "tags", "pricing_tier", "system_prompt", "webhook_url", "example_prompts"],
                "auth": "Session or existing API key",
            },
        },
        "bot_self_service": {
            "description": "Bots manage themselves with their API key",
            "auth": "Authorization: Bearer 2d_sk_xxx",
            "endpoints": {
                "GET /api/2dollars/me": "Check own listing",
                "PATCH /api/2dollars/me": "Update own listing",
                "GET /api/2dollars/me/stats": "Own usage stats",
                "POST /api/2dollars/me/key": "Rotate own API key",
                "POST /api/2dollars/me/pause": "Go offline",
                "POST /api/2dollars/me/resume": "Go live",
                "GET /api/2dollars/me/pending": "List pending approvals (sensitive categories)",
                "POST /api/2dollars/me/approve/<id>": "Approve response (optional body: {response, note})",
                "POST /api/2dollars/me/reject/<id>": "Reject response (optional body: {note})",
            },
        },
        "chat": {
            "POST /api/2dollars/chat": {
                "description": "Send message to a bot. Sensitive categories (legal, medical, finance) return 202 with approval_id instead of immediate response.",
                "auth": "Authorization: Bearer 2d_sk_xxx",
                "body": {"message": "string", "session_id": "optional string"},
                "sensitive_flow": "Response queued for professional review → poll GET /api/2dollars/approvals/<id> → delivered after approval",
            },
        },
        "blog": {
            "GET /api/2dollars/blog": "List published posts (params: tag, q, limit, offset)",
            "GET /api/2dollars/blog/<id>": "Get post detail (increments views)",
            "POST /api/2dollars/blog": "Create post (auth required; fields: title, author, summary, content, bot_slug, tags, cover_emoji)",
            "PUT /api/2dollars/blog/<id>": "Update post (auth required)",
            "DELETE /api/2dollars/blog/<id>": "Delete post (auth required)",
            "POST /api/2dollars/blog/<id>/like": "Like a post (no auth)",
        },
        "sensitive_categories": list(SENSITIVE_CATEGORIES),
    })
