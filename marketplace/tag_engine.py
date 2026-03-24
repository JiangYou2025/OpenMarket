"""Tag Engine — fast supply-demand matching for the marketplace.

Core idea: every listing has tags, every search query maps to tags.
The engine scores listings by tag relevance, freshness, and quality.

Usage:
    engine = get_tag_engine()
    results = engine.match("I need help debugging Python async code")
    results = engine.match_tags(["python", "async", "debugging"])
    trending = engine.trending(limit=20)
"""

from __future__ import annotations

import logging
import math
import re
import threading
import time
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from typing import Optional

log = logging.getLogger(__name__)


# ── Tag normalization ────────────────────────────────────────

def normalize_tag(tag: str) -> str:
    """Normalize a tag: lowercase, strip, collapse whitespace, replace spaces with hyphens."""
    tag = tag.lower().strip()
    tag = re.sub(r"\s+", "-", tag)
    tag = re.sub(r"[^a-z0-9\-\u4e00-\u9fff]", "", tag)  # keep alphanumeric, hyphens, CJK
    return tag


def extract_tags_from_query(query: str) -> list[str]:
    """Extract potential tags from a natural language query.

    Splits on common delimiters, removes stop words, normalizes.
    """
    stop_words = {
        "i", "me", "my", "need", "want", "help", "with", "for", "a", "an",
        "the", "to", "and", "or", "in", "on", "of", "is", "are", "can",
        "how", "what", "which", "some", "any", "please", "looking",
        "find", "search", "get", "do", "does",
        "我", "需要", "想", "帮", "找", "一个", "的", "和", "或", "在",
        "有", "什么", "怎么", "如何", "请", "帮忙",
    }
    # Split on spaces, commas, periods
    tokens = re.split(r"[\s,.\-;:!?/]+", query.lower())
    tags = []
    for t in tokens:
        t = normalize_tag(t)
        if t and t not in stop_words and len(t) >= 2:
            tags.append(t)
    return tags


# ── Tag stats ────────────────────────────────────────────────

@dataclass
class TagStats:
    """Statistics for a single tag across the marketplace."""
    tag: str = ""
    listing_count: int = 0          # How many active listings have this tag
    total_sessions: int = 0         # Total sessions across listings with this tag
    avg_rating: float = 0.0         # Average rating of listings with this tag
    search_count: int = 0           # How many times this tag was searched
    last_searched: float = 0.0      # Timestamp of last search

    @property
    def trending_score(self) -> float:
        """Trending = recent searches * listing activity."""
        recency = max(0, 1 - (time.time() - self.last_searched) / 86400)  # decay over 24h
        return self.search_count * recency * (1 + math.log1p(self.total_sessions))


# ── Match result ─────────────────────────────────────────────

@dataclass
class MatchResult:
    """A scored match between a query and a listing."""
    listing_id: str = ""
    score: float = 0.0              # Composite match score (higher = better)
    matched_tags: list[str] = field(default_factory=list)
    tag_score: float = 0.0          # How well tags match
    quality_score: float = 0.0      # Rating + sessions
    freshness_score: float = 0.0    # How recently updated

    def to_dict(self) -> dict:
        return {
            "listing_id": self.listing_id,
            "score": round(self.score, 4),
            "matched_tags": self.matched_tags,
        }


# ── Tag Engine ───────────────────────────────────────────────

class TagEngine:
    """Fast tag-based matching engine.

    Maintains an inverted index: tag -> set of listing_ids.
    Computes composite scores combining tag relevance, quality, and freshness.
    """

    def __init__(self):
        self._lock = threading.Lock()
        # Inverted index: tag -> set of listing_ids
        self._tag_to_listings: dict[str, set[str]] = defaultdict(set)
        # Forward index: listing_id -> set of tags
        self._listing_tags: dict[str, set[str]] = {}
        # Listing metadata cache (lightweight, for scoring)
        self._listing_meta: dict[str, dict] = {}
        # Tag search stats
        self._tag_stats: dict[str, TagStats] = {}
        # Category -> tag associations (for boosting)
        self._category_tags: dict[str, set[str]] = defaultdict(set)

    # ── Index management ──────────────────────────────────────

    def index_listing(
        self,
        listing_id: str,
        tags: list[str],
        category: str = "",
        rating: float = 0.0,
        rating_count: int = 0,
        total_sessions: int = 0,
        published_at: float = 0.0,
        name: str = "",
        tagline: str = "",
    ):
        """Add or update a listing in the index."""
        normalized = [normalize_tag(t) for t in tags if normalize_tag(t)]

        # Also extract implicit tags from name and tagline
        name_tags = extract_tags_from_query(f"{name} {tagline}")
        all_tags = set(normalized) | set(name_tags)

        with self._lock:
            # Remove old entries
            old_tags = self._listing_tags.get(listing_id, set())
            for t in old_tags - all_tags:
                self._tag_to_listings[t].discard(listing_id)

            # Add new entries
            self._listing_tags[listing_id] = all_tags
            for t in all_tags:
                self._tag_to_listings[t].add(listing_id)

            # Cache metadata
            self._listing_meta[listing_id] = {
                "rating": rating,
                "rating_count": rating_count,
                "total_sessions": total_sessions,
                "published_at": published_at,
                "explicit_tags": set(normalized),  # user-defined tags get a boost
            }

            # Track category-tag associations
            if category:
                self._category_tags[category].update(normalized)

    def remove_listing(self, listing_id: str):
        """Remove a listing from the index."""
        with self._lock:
            tags = self._listing_tags.pop(listing_id, set())
            for t in tags:
                self._tag_to_listings[t].discard(listing_id)
            self._listing_meta.pop(listing_id, None)

    def reindex_all(self, listings: list[dict]):
        """Rebuild the entire index from a list of listing dicts."""
        with self._lock:
            self._tag_to_listings.clear()
            self._listing_tags.clear()
            self._listing_meta.clear()
            self._category_tags.clear()

        for l in listings:
            if l.get("status") == "active":
                self.index_listing(
                    listing_id=l["listing_id"],
                    tags=l.get("tags", []),
                    category=l.get("category", ""),
                    rating=l.get("rating", 0),
                    rating_count=l.get("rating_count", 0),
                    total_sessions=l.get("total_sessions", 0),
                    published_at=l.get("published_at", 0),
                    name=l.get("name", ""),
                    tagline=l.get("tagline", ""),
                )

        log.info("Tag engine reindexed: %d listings, %d unique tags",
                 len(self._listing_tags), len(self._tag_to_listings))

    # ── Matching ──────────────────────────────────────────────

    def match_tags(
        self,
        tags: list[str],
        category: str = "",
        limit: int = 20,
        exclude_ids: set[str] | None = None,
    ) -> list[MatchResult]:
        """Match listings by tags. Returns scored results sorted by relevance.

        Scoring formula:
            score = tag_score * 0.5 + quality_score * 0.3 + freshness_score * 0.2

        tag_score: (matched_explicit / total_query_tags) * 1.5 + (matched_implicit / total) * 0.5
        quality_score: normalized(rating * log(1 + sessions))
        freshness_score: decay over 30 days from published_at
        """
        normalized = [normalize_tag(t) for t in tags if normalize_tag(t)]
        if not normalized:
            return []

        exclude = exclude_ids or set()

        # Record search stats
        now = time.time()
        with self._lock:
            for t in normalized:
                if t not in self._tag_stats:
                    self._tag_stats[t] = TagStats(tag=t)
                self._tag_stats[t].search_count += 1
                self._tag_stats[t].last_searched = now

        # Find candidate listings (any tag overlap)
        with self._lock:
            candidates: dict[str, set[str]] = {}  # listing_id -> matched tags
            for t in normalized:
                for lid in self._tag_to_listings.get(t, set()):
                    if lid not in exclude:
                        if lid not in candidates:
                            candidates[lid] = set()
                        candidates[lid].add(t)

        if not candidates:
            return []

        # Score each candidate
        results = []
        query_tag_count = len(normalized)

        with self._lock:
            for lid, matched in candidates.items():
                meta = self._listing_meta.get(lid, {})
                explicit_tags = meta.get("explicit_tags", set())

                # Tag score: explicit matches worth more
                explicit_matches = len(matched & explicit_tags)
                implicit_matches = len(matched) - explicit_matches
                tag_score = (
                    (explicit_matches / query_tag_count) * 1.5
                    + (implicit_matches / query_tag_count) * 0.5
                )

                # Category bonus
                if category and category in self._category_tags:
                    cat_tags = self._category_tags[category]
                    if matched & cat_tags:
                        tag_score *= 1.2

                # Quality score: rating * log(1 + sessions), normalized to 0-1
                rating = meta.get("rating", 0)
                sessions = meta.get("total_sessions", 0)
                raw_quality = rating * math.log1p(sessions)
                quality_score = min(1.0, raw_quality / 25)  # 5-star * log(1+70000) ≈ 56, cap at 25

                # Freshness score: decay over 30 days
                published = meta.get("published_at", 0)
                age_days = (now - published) / 86400 if published else 30
                freshness_score = max(0, 1 - age_days / 30)

                # Composite
                score = tag_score * 0.5 + quality_score * 0.3 + freshness_score * 0.2

                results.append(MatchResult(
                    listing_id=lid,
                    score=score,
                    matched_tags=sorted(matched),
                    tag_score=round(tag_score, 4),
                    quality_score=round(quality_score, 4),
                    freshness_score=round(freshness_score, 4),
                ))

        # Sort by score descending
        results.sort(key=lambda r: r.score, reverse=True)
        return results[:limit]

    def match(
        self,
        query: str,
        category: str = "",
        limit: int = 20,
        exclude_ids: set[str] | None = None,
    ) -> list[MatchResult]:
        """Match listings by natural language query.

        Extracts tags from query, then delegates to match_tags.
        """
        tags = extract_tags_from_query(query)
        return self.match_tags(tags, category=category, limit=limit, exclude_ids=exclude_ids)

    # ── Tag discovery ─────────────────────────────────────────

    def trending(self, limit: int = 20) -> list[dict]:
        """Get trending tags by recent search activity."""
        with self._lock:
            stats = list(self._tag_stats.values())
        stats.sort(key=lambda s: s.trending_score, reverse=True)
        return [
            {
                "tag": s.tag,
                "listing_count": s.listing_count,
                "search_count": s.search_count,
                "trending_score": round(s.trending_score, 2),
            }
            for s in stats[:limit]
        ]

    def popular_tags(self, limit: int = 30) -> list[dict]:
        """Get most popular tags by listing count."""
        with self._lock:
            tag_counts = [
                (tag, len(lids))
                for tag, lids in self._tag_to_listings.items()
                if lids
            ]
        tag_counts.sort(key=lambda x: x[1], reverse=True)
        return [{"tag": t, "count": c} for t, c in tag_counts[:limit]]

    def related_tags(self, tag: str, limit: int = 10) -> list[dict]:
        """Find tags that frequently co-occur with the given tag."""
        tag = normalize_tag(tag)
        with self._lock:
            # Get listings that have this tag
            listing_ids = self._tag_to_listings.get(tag, set())
            if not listing_ids:
                return []
            # Count co-occurring tags
            co_tags: Counter = Counter()
            for lid in listing_ids:
                for t in self._listing_tags.get(lid, set()):
                    if t != tag:
                        co_tags[t] += 1
        return [{"tag": t, "co_count": c} for t, c in co_tags.most_common(limit)]

    def suggest_tags(self, partial: str, limit: int = 10) -> list[str]:
        """Autocomplete: suggest tags matching a partial input."""
        partial = normalize_tag(partial)
        if not partial:
            return []
        with self._lock:
            matches = [
                (tag, len(lids))
                for tag, lids in self._tag_to_listings.items()
                if tag.startswith(partial) and lids
            ]
        matches.sort(key=lambda x: x[1], reverse=True)
        return [t for t, _ in matches[:limit]]

    def tags_for_category(self, category: str, limit: int = 20) -> list[dict]:
        """Get popular tags within a specific category."""
        with self._lock:
            cat_tags = self._category_tags.get(category, set())
            if not cat_tags:
                return []
            result = [
                (t, len(self._tag_to_listings.get(t, set())))
                for t in cat_tags
            ]
        result.sort(key=lambda x: x[1], reverse=True)
        return [{"tag": t, "count": c} for t, c in result[:limit]]

    # ── Stats ─────────────────────────────────────────────────

    def refresh_tag_stats(self):
        """Recalculate tag stats from current index. Call periodically."""
        with self._lock:
            for tag, lids in self._tag_to_listings.items():
                if tag not in self._tag_stats:
                    self._tag_stats[tag] = TagStats(tag=tag)
                st = self._tag_stats[tag]
                st.listing_count = len(lids)
                total_sessions = 0
                total_rating = 0.0
                rated = 0
                for lid in lids:
                    meta = self._listing_meta.get(lid, {})
                    total_sessions += meta.get("total_sessions", 0)
                    if meta.get("rating", 0) > 0:
                        total_rating += meta["rating"]
                        rated += 1
                st.total_sessions = total_sessions
                st.avg_rating = round(total_rating / rated, 2) if rated else 0

    def summary(self) -> dict:
        """Engine summary stats."""
        with self._lock:
            return {
                "total_listings_indexed": len(self._listing_tags),
                "unique_tags": len(self._tag_to_listings),
                "categories_tracked": len(self._category_tags),
                "tags_with_search_history": len(self._tag_stats),
            }


# ── Singleton ────────────────────────────────────────────────
_engine: Optional[TagEngine] = None


def get_tag_engine() -> TagEngine:
    global _engine
    if _engine is None:
        _engine = TagEngine()
    return _engine
