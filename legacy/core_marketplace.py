"""2dollars Marketplace — HuggingFace-style AI bot registry.

Bot onboarding, listing, sorting, and API key authorization.
Data persisted to workspaces/2dollars/data/marketplace.json.
"""

from __future__ import annotations

import hashlib
import json
import logging
import secrets
import threading
import time
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Optional

log = logging.getLogger(__name__)

# ── Storage ──────────────────────────────────────────────────────────
_DATA_DIR = Path(__file__).resolve().parent.parent.parent / "workspaces" / "2dollars" / "data"

# ── Categories ───────────────────────────────────────────────────────
CATEGORIES = [
    "coding",       # 编程开发
    "writing",      # 写作翻译
    "academic",     # 学术研究
    "finance",      # 金融分析
    "creative",     # 创意设计
    "data",         # 数据分析
    "legal",        # 法律咨询
    "medical",      # 医疗健康
    "education",    # 教育培训
    "general",      # 通用助手
]

# Categories where a licensed professional must approve AI responses before delivery
SENSITIVE_CATEGORIES = {"legal", "medical", "finance"}

# ── Pricing tiers ────────────────────────────────────────────────────
PRICING_TIERS = {
    "basic":    {"label": "Basic",    "price_per_min": 0.04, "models": ["haiku"]},
    "standard": {"label": "Standard", "price_per_min": 0.13, "models": ["sonnet", "gpt-4o-mini"]},
    "premium":  {"label": "Premium",  "price_per_min": 0.40, "models": ["opus", "gpt-4o", "gemini-pro"]},
    "custom":   {"label": "Custom",   "price_per_min": 0.00, "models": []},
}


def _generate_api_key() -> str:
    """Generate a 2dollars API key: 2d_sk_<random>."""
    return f"2d_sk_{secrets.token_urlsafe(32)}"


def _hash_key(key: str) -> str:
    """Hash API key for storage (only store hash, not plaintext)."""
    return hashlib.sha256(key.encode()).hexdigest()


# ── Bot Card (like HuggingFace model card) ───────────────────────────

@dataclass
class BotCard:
    """A marketplace listing for an AI bot."""

    # Identity
    bot_id: str = ""                    # links to BotInstance if internal
    slug: str = ""                      # URL-friendly: "code-wizard"
    name: str = ""                      # Display: "Code Wizard"
    description: str = ""               # Short pitch (1-2 sentences)
    long_description: str = ""          # Full markdown description
    author: str = ""                    # Creator name or org
    avatar_url: str = ""               # Bot avatar

    # Classification
    category: str = "general"           # Primary category
    tags: list[str] = field(default_factory=list)  # e.g. ["python", "debugging"]

    # AI backend
    provider: str = ""                  # "claude", "openai", "gemini", etc.
    model: str = ""                     # Specific model ID
    system_prompt: str = ""             # Bot personality/instructions

    # Pricing
    pricing_tier: str = "standard"      # basic/standard/premium/custom
    price_per_min: float = 0.0          # Override for custom tier ($/min)

    # Stats (auto-updated)
    rating: float = 0.0                 # 0-5 stars
    rating_count: int = 0               # Number of ratings
    total_sessions: int = 0             # Total conversations
    total_minutes: int = 0              # Total usage minutes

    # Authorization
    api_key_hash: str = ""              # Hashed API key (for external bots)
    webhook_url: str = ""               # External bot endpoint (if not using internal provider)

    # Status
    status: str = "draft"               # draft | listed | suspended | archived
    featured: bool = False              # Show on homepage
    verified: bool = False              # Verified by platform

    # Timestamps
    created_at: float = 0.0
    updated_at: float = 0.0

    # Example prompts for users to try
    example_prompts: list[str] = field(default_factory=list)

    def requires_approval(self) -> bool:
        """Whether this bot's responses need professional review before delivery."""
        return self.category in SENSITIVE_CATEGORIES

    def get_effective_price(self) -> float:
        """Get the effective price per minute."""
        if self.pricing_tier == "custom" and self.price_per_min > 0:
            return self.price_per_min
        tier = PRICING_TIERS.get(self.pricing_tier, PRICING_TIERS["standard"])
        return tier["price_per_min"]

    def to_listing_dict(self) -> dict:
        """Public listing info (no secrets)."""
        return {
            "bot_id": self.bot_id,
            "slug": self.slug,
            "name": self.name,
            "description": self.description,
            "author": self.author,
            "avatar_url": self.avatar_url,
            "category": self.category,
            "tags": self.tags,
            "provider": self.provider,
            "model": self.model,
            "pricing_tier": self.pricing_tier,
            "price_per_min": self.get_effective_price(),
            "rating": self.rating,
            "rating_count": self.rating_count,
            "total_sessions": self.total_sessions,
            "status": self.status,
            "featured": self.featured,
            "verified": self.verified,
            "requires_approval": self.requires_approval(),
            "example_prompts": self.example_prompts,
            "created_at": self.created_at,
        }

    def to_detail_dict(self) -> dict:
        """Full detail view (no secrets)."""
        d = self.to_listing_dict()
        d["long_description"] = self.long_description
        d["total_minutes"] = self.total_minutes
        d["updated_at"] = self.updated_at
        d["has_webhook"] = bool(self.webhook_url)
        return d

    def to_storage_dict(self) -> dict:
        """Full dict for persistence (includes hashed key, no plaintext)."""
        return asdict(self)


# ── Marketplace Store ────────────────────────────────────────────────

class MarketplaceStore:
    """Thread-safe bot marketplace registry with JSON persistence."""

    def __init__(self, data_dir: Path | None = None):
        self._data_dir = data_dir or _DATA_DIR
        self._data_dir.mkdir(parents=True, exist_ok=True)
        self._file = self._data_dir / "marketplace.json"
        self._bots: dict[str, BotCard] = {}   # slug -> BotCard
        self._key_index: dict[str, str] = {}  # key_hash -> slug
        self._lock = threading.Lock()
        self._load()

    def _load(self):
        """Load from disk."""
        if not self._file.exists():
            return
        try:
            data = json.loads(self._file.read_text(encoding="utf-8"))
            for item in data.get("bots", []):
                card = BotCard(**{k: v for k, v in item.items() if k in BotCard.__dataclass_fields__})
                self._bots[card.slug] = card
                if card.api_key_hash:
                    self._key_index[card.api_key_hash] = card.slug
            log.info("Marketplace loaded: %d bots", len(self._bots))
        except Exception as e:
            log.error("Failed to load marketplace: %s", e)

    def _save(self):
        """Persist to disk (caller must hold lock)."""
        data = {"bots": [b.to_storage_dict() for b in self._bots.values()]}
        self._file.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")

    # ── Registration ─────────────────────────────────────────────────

    def register(
        self,
        name: str,
        description: str,
        author: str,
        provider: str = "",
        model: str = "",
        category: str = "general",
        tags: list[str] | None = None,
        pricing_tier: str = "standard",
        price_per_min: float = 0.0,
        system_prompt: str = "",
        webhook_url: str = "",
        example_prompts: list[str] | None = None,
        bot_id: str = "",
        slug: str = "",
        **extra,
    ) -> tuple[BotCard, str]:
        """Register a new bot. Returns (BotCard, plaintext_api_key).

        The plaintext API key is returned ONCE at registration.
        Only the hash is stored.
        """
        # Generate slug from name if not provided
        if not slug:
            slug = name.lower().replace(" ", "-")
            slug = "".join(c for c in slug if c.isalnum() or c == "-")

        with self._lock:
            # Check uniqueness
            if slug in self._bots:
                # Append random suffix
                slug = f"{slug}-{secrets.token_hex(3)}"

            # Generate API key
            api_key = _generate_api_key()
            key_hash = _hash_key(api_key)

            # Generate bot_id if not linked to existing bot
            if not bot_id:
                bot_id = f"2d_{secrets.token_hex(4)}"

            now = time.time()
            card = BotCard(
                bot_id=bot_id,
                slug=slug,
                name=name,
                description=description,
                author=author,
                category=category if category in CATEGORIES else "general",
                tags=tags or [],
                provider=provider,
                model=model,
                system_prompt=system_prompt,
                pricing_tier=pricing_tier if pricing_tier in PRICING_TIERS else "standard",
                price_per_min=price_per_min,
                webhook_url=webhook_url,
                api_key_hash=key_hash,
                example_prompts=example_prompts or [],
                status="listed",   # Auto-list on registration
                created_at=now,
                updated_at=now,
            )

            self._bots[slug] = card
            self._key_index[key_hash] = slug
            self._save()

            log.info("Bot registered: %s (%s) by %s", name, slug, author)
            return card, api_key

    # ── Lookup ───────────────────────────────────────────────────────

    def get(self, slug: str) -> Optional[BotCard]:
        with self._lock:
            return self._bots.get(slug)

    def get_by_api_key(self, api_key: str) -> Optional[BotCard]:
        """Authenticate and return bot card from API key."""
        key_hash = _hash_key(api_key)
        with self._lock:
            slug = self._key_index.get(key_hash)
            if slug:
                return self._bots.get(slug)
        return None

    def get_by_bot_id(self, bot_id: str) -> Optional[BotCard]:
        with self._lock:
            for card in self._bots.values():
                if card.bot_id == bot_id:
                    return card
        return None

    # ── Listing & Search ─────────────────────────────────────────────

    def list_bots(
        self,
        category: str = "",
        tag: str = "",
        search: str = "",
        sort_by: str = "rating",        # rating | price | popular | newest
        status: str = "listed",
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[list[dict], int]:
        """List bots with filtering and sorting. Returns (items, total)."""
        with self._lock:
            bots = list(self._bots.values())

        # Filter
        if status:
            bots = [b for b in bots if b.status == status]
        if category:
            bots = [b for b in bots if b.category == category]
        if tag:
            bots = [b for b in bots if tag in b.tags]
        if search:
            q = search.lower()
            bots = [b for b in bots if q in b.name.lower() or q in b.description.lower() or q in " ".join(b.tags).lower()]

        # Sort
        if sort_by == "rating":
            bots.sort(key=lambda b: (b.rating, b.rating_count), reverse=True)
        elif sort_by == "price":
            bots.sort(key=lambda b: b.get_effective_price())
        elif sort_by == "popular":
            bots.sort(key=lambda b: b.total_sessions, reverse=True)
        elif sort_by == "newest":
            bots.sort(key=lambda b: b.created_at, reverse=True)

        total = len(bots)
        items = [b.to_listing_dict() for b in bots[offset:offset + limit]]
        return items, total

    # ── Update ───────────────────────────────────────────────────────

    def update(self, slug: str, **updates) -> Optional[BotCard]:
        """Update bot card fields. Returns updated card or None."""
        with self._lock:
            card = self._bots.get(slug)
            if not card:
                return None
            for k, v in updates.items():
                if k in BotCard.__dataclass_fields__ and k not in ("slug", "api_key_hash", "created_at"):
                    setattr(card, k, v)
            card.updated_at = time.time()
            self._save()
            return card

    def rotate_api_key(self, slug: str) -> Optional[str]:
        """Generate a new API key for a bot. Returns new plaintext key."""
        with self._lock:
            card = self._bots.get(slug)
            if not card:
                return None
            # Remove old key from index
            if card.api_key_hash:
                self._key_index.pop(card.api_key_hash, None)
            # Generate new
            new_key = _generate_api_key()
            card.api_key_hash = _hash_key(new_key)
            card.updated_at = time.time()
            self._key_index[card.api_key_hash] = slug
            self._save()
            return new_key

    # ── Stats ────────────────────────────────────────────────────────

    def record_session(self, slug: str, duration_min: float = 0, rating: float = 0):
        """Record a completed session and optional rating."""
        with self._lock:
            card = self._bots.get(slug)
            if not card:
                return
            card.total_sessions += 1
            card.total_minutes += int(duration_min)
            if 0 < rating <= 5:
                # Running average
                total = card.rating * card.rating_count + rating
                card.rating_count += 1
                card.rating = round(total / card.rating_count, 2)
            card.updated_at = time.time()
            self._save()

    # ── Delete ───────────────────────────────────────────────────────

    def remove(self, slug: str) -> bool:
        with self._lock:
            card = self._bots.pop(slug, None)
            if card:
                self._key_index.pop(card.api_key_hash, None)
                self._save()
                return True
            return False

    # ── Bulk ─────────────────────────────────────────────────────────

    def reload(self):
        """Re-read data from disk, replacing in-memory state."""
        with self._lock:
            self._bots.clear()
            self._key_index.clear()
        self._load()
        log.info("Marketplace reloaded: %d bots", len(self._bots))

    def count(self) -> int:
        with self._lock:
            return len(self._bots)

    def categories_summary(self) -> list[dict]:
        """Return category counts for nav/filter."""
        with self._lock:
            counts: dict[str, int] = {}
            for b in self._bots.values():
                if b.status == "listed":
                    counts[b.category] = counts.get(b.category, 0) + 1
        return [{"category": c, "count": counts.get(c, 0)} for c in CATEGORIES]


# ── Singleton ────────────────────────────────────────────────────────
_store: Optional[MarketplaceStore] = None


def get_marketplace() -> MarketplaceStore:
    global _store
    if _store is None:
        _store = MarketplaceStore()
    return _store


# ═══════════════════════════════════════════════════════════════════════
# Approval Queue — human-in-the-loop for sensitive categories
# ═══════════════════════════════════════════════════════════════════════

@dataclass
class PendingApproval:
    """An AI response awaiting professional review before delivery."""

    approval_id: str = ""
    bot_slug: str = ""
    session_id: str = ""

    # Content
    user_message: str = ""
    ai_response: str = ""
    provider_name: str = ""
    model_used: str = ""
    usage: dict = field(default_factory=dict)

    # Review
    status: str = "pending"       # pending | approved | edited | rejected | expired
    final_response: str = ""      # approved or edited response delivered to user
    reviewer_note: str = ""       # optional note from reviewer

    # Timing
    created_at: float = 0.0
    reviewed_at: float = 0.0
    timeout_minutes: int = 30     # auto-expire if not reviewed

    def is_expired(self) -> bool:
        return (
            self.status == "pending"
            and time.time() > self.created_at + self.timeout_minutes * 60
        )

    def to_user_dict(self) -> dict:
        """What the end user sees (no raw AI response until approved)."""
        d: dict = {
            "approval_id": self.approval_id,
            "status": "expired" if self.is_expired() else self.status,
            "created_at": self.created_at,
        }
        if self.status in ("approved", "edited"):
            d["response"] = self.final_response
            d["reviewed_at"] = self.reviewed_at
        elif self.status == "rejected":
            d["message"] = "The professional declined this response. You were not charged."
            if self.reviewer_note:
                d["note"] = self.reviewer_note
        elif self.is_expired():
            d["message"] = "The professional did not review this in time. You were not charged."
        else:
            d["message"] = "Your question is being reviewed by a licensed professional."
        return d

    def to_reviewer_dict(self) -> dict:
        """What the bot holder / reviewer sees (includes raw AI response)."""
        return {
            "approval_id": self.approval_id,
            "bot_slug": self.bot_slug,
            "session_id": self.session_id,
            "user_message": self.user_message,
            "ai_response": self.ai_response,
            "status": "expired" if self.is_expired() else self.status,
            "final_response": self.final_response,
            "reviewer_note": self.reviewer_note,
            "created_at": self.created_at,
            "reviewed_at": self.reviewed_at,
            "timeout_minutes": self.timeout_minutes,
        }


class ApprovalStore:
    """Thread-safe approval queue with JSON persistence."""

    def __init__(self, data_dir: Path | None = None):
        self._data_dir = data_dir or _DATA_DIR
        self._data_dir.mkdir(parents=True, exist_ok=True)
        self._file = self._data_dir / "approvals.json"
        self._items: dict[str, PendingApproval] = {}  # approval_id -> PendingApproval
        self._lock = threading.Lock()
        self._load()

    def _load(self):
        if not self._file.exists():
            return
        try:
            data = json.loads(self._file.read_text(encoding="utf-8"))
            for item in data.get("approvals", []):
                pa = PendingApproval(**{k: v for k, v in item.items() if k in PendingApproval.__dataclass_fields__})
                self._items[pa.approval_id] = pa
            log.info("Approvals loaded: %d items", len(self._items))
        except Exception as e:
            log.error("Failed to load approvals: %s", e)

    def _save(self):
        data = {"approvals": [asdict(a) for a in self._items.values()]}
        self._file.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")

    def create(
        self,
        bot_slug: str,
        session_id: str,
        user_message: str,
        ai_response: str,
        provider_name: str = "",
        model_used: str = "",
        usage: dict | None = None,
        timeout_minutes: int = 30,
    ) -> PendingApproval:
        """Queue an AI response for professional review."""
        aid = uuid.uuid4().hex[:12]
        now = time.time()
        pa = PendingApproval(
            approval_id=aid,
            bot_slug=bot_slug,
            session_id=session_id,
            user_message=user_message,
            ai_response=ai_response,
            provider_name=provider_name,
            model_used=model_used,
            usage=usage or {},
            created_at=now,
            timeout_minutes=timeout_minutes,
        )
        with self._lock:
            self._items[aid] = pa
            self._save()
        log.info("Approval queued: %s for bot %s", aid, bot_slug)
        return pa

    def get(self, approval_id: str) -> Optional[PendingApproval]:
        with self._lock:
            pa = self._items.get(approval_id)
            if pa and pa.is_expired() and pa.status == "pending":
                pa.status = "expired"
                self._save()
            return pa

    def list_pending(self, bot_slug: str) -> list[PendingApproval]:
        """List pending approvals for a specific bot."""
        with self._lock:
            result = []
            for pa in self._items.values():
                if pa.bot_slug != bot_slug:
                    continue
                if pa.is_expired() and pa.status == "pending":
                    pa.status = "expired"
                if pa.status == "pending":
                    result.append(pa)
            self._save()
            return result

    def approve(self, approval_id: str, edited_response: str = "", note: str = "") -> Optional[PendingApproval]:
        """Approve (optionally edit) a pending response."""
        with self._lock:
            pa = self._items.get(approval_id)
            if not pa or pa.status != "pending":
                return None
            if pa.is_expired():
                pa.status = "expired"
                self._save()
                return None
            pa.status = "edited" if edited_response else "approved"
            pa.final_response = edited_response if edited_response else pa.ai_response
            pa.reviewer_note = note
            pa.reviewed_at = time.time()
            self._save()
            log.info("Approval %s: %s by reviewer", approval_id, pa.status)
            return pa

    def reject(self, approval_id: str, note: str = "") -> Optional[PendingApproval]:
        """Reject a pending response. User is not charged."""
        with self._lock:
            pa = self._items.get(approval_id)
            if not pa or pa.status != "pending":
                return None
            if pa.is_expired():
                pa.status = "expired"
                self._save()
                return None
            pa.status = "rejected"
            pa.reviewer_note = note
            pa.reviewed_at = time.time()
            self._save()
            log.info("Approval %s: rejected", approval_id)
            return pa

    def cleanup_old(self, max_age_hours: int = 24):
        """Remove approvals older than max_age_hours (all statuses)."""
        cutoff = time.time() - max_age_hours * 3600
        with self._lock:
            to_remove = [k for k, v in self._items.items() if v.created_at < cutoff]
            for k in to_remove:
                del self._items[k]
            if to_remove:
                self._save()
                log.info("Cleaned up %d old approvals", len(to_remove))


# ── Approval Singleton ────────────────────────────────────────────────
_approval_store: Optional[ApprovalStore] = None


def get_approval_store() -> ApprovalStore:
    global _approval_store
    if _approval_store is None:
        _approval_store = ApprovalStore()
    return _approval_store


# ═══════════════════════════════════════════════════════════════════════
# Blog / Success Stories — community case studies
# ═══════════════════════════════════════════════════════════════════════

@dataclass
class BlogPost:
    """A success story / case study published on the marketplace."""

    post_id: str = ""
    title: str = ""
    author: str = ""
    summary: str = ""           # Short teaser (1-2 sentences)
    content: str = ""           # Full markdown body
    bot_slug: str = ""          # Related bot (optional)
    tags: list[str] = field(default_factory=list)
    cover_emoji: str = ""       # Emoji as cover icon

    # Stats
    views: int = 0
    likes: int = 0

    # Status
    status: str = "published"   # draft | published | archived

    # Timestamps
    created_at: float = 0.0
    updated_at: float = 0.0

    def to_listing_dict(self) -> dict:
        return {
            "post_id": self.post_id,
            "title": self.title,
            "author": self.author,
            "summary": self.summary,
            "bot_slug": self.bot_slug,
            "tags": self.tags,
            "cover_emoji": self.cover_emoji,
            "views": self.views,
            "likes": self.likes,
            "created_at": self.created_at,
        }

    def to_detail_dict(self) -> dict:
        d = self.to_listing_dict()
        d["content"] = self.content
        d["status"] = self.status
        d["updated_at"] = self.updated_at
        return d


class BlogStore:
    """Thread-safe blog post store with JSON persistence."""

    def __init__(self, data_dir: Path | None = None):
        self._data_dir = data_dir or _DATA_DIR
        self._data_dir.mkdir(parents=True, exist_ok=True)
        self._file = self._data_dir / "blog.json"
        self._posts: dict[str, BlogPost] = {}  # post_id -> BlogPost
        self._lock = threading.Lock()
        self._load()

    def _load(self):
        if not self._file.exists():
            return
        try:
            data = json.loads(self._file.read_text(encoding="utf-8"))
            for item in data.get("posts", []):
                post = BlogPost(**{k: v for k, v in item.items() if k in BlogPost.__dataclass_fields__})
                self._posts[post.post_id] = post
            log.info("Blog loaded: %d posts", len(self._posts))
        except Exception as e:
            log.error("Failed to load blog: %s", e)

    def _save(self):
        data = {"posts": [asdict(p) for p in self._posts.values()]}
        self._file.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")

    def create(
        self,
        title: str,
        author: str,
        summary: str,
        content: str,
        bot_slug: str = "",
        tags: list[str] | None = None,
        cover_emoji: str = "",
    ) -> BlogPost:
        post_id = uuid.uuid4().hex[:10]
        now = time.time()
        post = BlogPost(
            post_id=post_id,
            title=title,
            author=author,
            summary=summary,
            content=content,
            bot_slug=bot_slug,
            tags=tags or [],
            cover_emoji=cover_emoji or "✨",
            status="published",
            created_at=now,
            updated_at=now,
        )
        with self._lock:
            self._posts[post_id] = post
            self._save()
        log.info("Blog post created: %s by %s", title, author)
        return post

    def get(self, post_id: str) -> Optional[BlogPost]:
        with self._lock:
            return self._posts.get(post_id)

    def list_posts(
        self,
        tag: str = "",
        search: str = "",
        status: str = "published",
        limit: int = 20,
        offset: int = 0,
    ) -> tuple[list[dict], int]:
        with self._lock:
            posts = list(self._posts.values())

        if status:
            posts = [p for p in posts if p.status == status]
        if tag:
            posts = [p for p in posts if tag in p.tags]
        if search:
            q = search.lower()
            posts = [p for p in posts if q in p.title.lower() or q in p.summary.lower() or q in p.author.lower()]

        posts.sort(key=lambda p: p.created_at, reverse=True)
        total = len(posts)
        items = [p.to_listing_dict() for p in posts[offset:offset + limit]]
        return items, total

    def update(self, post_id: str, **updates) -> Optional[BlogPost]:
        with self._lock:
            post = self._posts.get(post_id)
            if not post:
                return None
            for k, v in updates.items():
                if k in BlogPost.__dataclass_fields__ and k not in ("post_id", "created_at"):
                    setattr(post, k, v)
            post.updated_at = time.time()
            self._save()
            return post

    def increment_views(self, post_id: str):
        with self._lock:
            post = self._posts.get(post_id)
            if post:
                post.views += 1
                self._save()

    def toggle_like(self, post_id: str, delta: int = 1):
        with self._lock:
            post = self._posts.get(post_id)
            if post:
                post.likes = max(0, post.likes + delta)
                self._save()

    def remove(self, post_id: str) -> bool:
        with self._lock:
            if self._posts.pop(post_id, None):
                self._save()
                return True
            return False

    def count(self) -> int:
        with self._lock:
            return sum(1 for p in self._posts.values() if p.status == "published")


# ── Blog Singleton ────────────────────────────────────────────────────
_blog_store: Optional[BlogStore] = None


def get_blog_store() -> BlogStore:
    global _blog_store
    if _blog_store is None:
        _blog_store = BlogStore()
    return _blog_store
