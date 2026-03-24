"""User API — browse, search, and consume AI consultation services.

All endpoints are public (no auth required for browsing).
Session/payment endpoints will require user auth (future).

Prefix: /api/user
"""

from __future__ import annotations

import logging

from flask import Blueprint, jsonify, request

from .models import CATEGORIES, SENSITIVE_CATEGORIES
from .store import get_store

log = logging.getLogger(__name__)

user_bp = Blueprint("user_api", __name__, url_prefix="/api/user")


# ── Browse & Search ───────────────────────────────────────────


@user_bp.route("/listings", methods=["GET"])
def browse_listings():
    """Browse active bot listings.

    Query params:
        category  — filter by category (e.g. "coding", "finance")
        tag       — filter by tag (e.g. "python")
        q         — full-text search (name, tagline, description, tags)
        sort      — rating (default) | price_low | price_high | popular | newest | featured
        limit     — max results (default 50)
        offset    — pagination offset (default 0)
    """
    store = get_store()
    listings, total = store.list_active(
        category=request.args.get("category", ""),
        tag=request.args.get("tag", ""),
        search=request.args.get("q", ""),
        sort_by=request.args.get("sort", "rating"),
        limit=int(request.args.get("limit", 50)),
        offset=int(request.args.get("offset", 0)),
    )

    return jsonify({
        "listings": [l.to_public_dict() for l in listings],
        "total": total,
    })


@user_bp.route("/listings/<listing_id>", methods=["GET"])
def get_listing(listing_id: str):
    """Get detailed info for a single listing."""
    listing = get_store().get(listing_id)
    if not listing or listing.status not in ("active", "suspended"):
        return jsonify({"error": "Listing not found"}), 404

    d = listing.to_public_dict()
    d["requires_review"] = listing.category in SENSITIVE_CATEGORIES
    return jsonify(d)


# ── Categories ────────────────────────────────────────────────


@user_bp.route("/categories", methods=["GET"])
def list_categories():
    """List all categories with active listing counts."""
    stats = get_store().stats()
    categories = []
    for cat in CATEGORIES:
        categories.append({
            "name": cat,
            "count": stats.get("categories", {}).get(cat, 0),
            "sensitive": cat in SENSITIVE_CATEGORIES,
        })
    return jsonify({"categories": categories})


# ── Featured / Recommendations ────────────────────────────────


@user_bp.route("/featured", methods=["GET"])
def featured_listings():
    """Get featured/promoted listings for the homepage."""
    store = get_store()
    listings, _ = store.list_active(sort_by="featured", limit=10)
    return jsonify({
        "featured": [l.to_public_dict() for l in listings],
    })


@user_bp.route("/popular", methods=["GET"])
def popular_listings():
    """Get most popular listings by session count."""
    store = get_store()
    listings, _ = store.list_active(sort_by="popular", limit=10)
    return jsonify({
        "popular": [l.to_public_dict() for l in listings],
    })


@user_bp.route("/newest", methods=["GET"])
def newest_listings():
    """Get newest listings."""
    store = get_store()
    listings, _ = store.list_active(sort_by="newest", limit=10)
    return jsonify({
        "newest": [l.to_public_dict() for l in listings],
    })


# ── Rating ────────────────────────────────────────────────────


@user_bp.route("/listings/<listing_id>/rate", methods=["POST"])
def rate_listing(listing_id: str):
    """Rate a bot after a session (1-5 stars).

    Body: {"score": 4}
    """
    store = get_store()
    listing = store.get(listing_id)
    if not listing or listing.status != "active":
        return jsonify({"error": "Listing not found"}), 404

    data = request.get_json(silent=True) or {}
    score = data.get("score")
    if score is None or not (1 <= score <= 5):
        return jsonify({"error": "score must be 1-5"}), 400

    listing.add_rating(float(score))
    store.update(listing)

    return jsonify({
        "message": "Thanks for rating!",
        "rating": round(listing.rating, 2),
        "rating_count": listing.rating_count,
    })


# ── Platform stats ────────────────────────────────────────────


@user_bp.route("/stats", methods=["GET"])
def platform_stats():
    """Public platform statistics."""
    stats = get_store().stats()
    # Don't expose revenue to public
    stats.pop("total_revenue_usd", None)
    return jsonify(stats)
