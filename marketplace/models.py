"""Marketplace data models — bot listings, pricing, reviews."""

from __future__ import annotations

import hashlib
import secrets
import time
import uuid
from dataclasses import dataclass, field
from typing import Literal


def _generate_api_key() -> str:
    """Generate an OpenMarket provider API key: om_sk_<random>."""
    return f"om_sk_{secrets.token_urlsafe(32)}"


def _hash_key(key: str) -> str:
    """SHA-256 hash of an API key (only hash is stored)."""
    return hashlib.sha256(key.encode()).hexdigest()

ListingStatus = Literal["draft", "pending", "active", "suspended", "archived"]

PricingModel = Literal["per_minute", "per_token", "per_session", "flat"]


@dataclass
class PricingTier:
    """A single pricing tier for a bot listing."""
    name: str = "basic"                    # "basic", "pro", "unlimited"
    price_usd: float = 2.0                 # Price in USD
    unit: PricingModel = "per_minute"      # How to charge
    unit_amount: int = 15                  # e.g. 15 minutes, 10000 tokens
    description: str = ""

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "price_usd": self.price_usd,
            "unit": self.unit,
            "unit_amount": self.unit_amount,
            "description": self.description,
        }

    @classmethod
    def from_dict(cls, d: dict) -> PricingTier:
        return cls(**{k: v for k, v in d.items() if k in cls.__dataclass_fields__})


@dataclass
class Listing:
    """A bot listing on the marketplace.

    Links to an existing BotInstance via bot_id.
    """
    listing_id: str = ""                   # Unique marketplace listing ID
    bot_id: str = ""                       # Links to BotInstance.bot_id
    owner_id: str = ""                     # Who registered this (user key, e.g. "dc:12345")

    # Display info
    name: str = ""                         # Marketplace display name
    tagline: str = ""                      # One-line description
    description: str = ""                  # Full description (markdown)
    avatar_url: str = ""                   # Bot avatar
    category: str = "general"              # "coding", "writing", "finance", "academic", ...
    tags: list[str] = field(default_factory=list)
    example_prompts: list[str] = field(default_factory=list)

    # AI backend
    provider: str = "claude"               # AI provider name (from registry)
    model: str = ""                        # Specific model (empty = provider default)
    system_prompt: str = ""                # Custom system prompt for this listing
    webhook_url: str = ""                  # External bot endpoint (if set, bypasses built-in AI)

    # Pricing
    pricing: list[PricingTier] = field(default_factory=lambda: [
        PricingTier(name="basic", price_usd=2.0, unit="per_minute", unit_amount=15),
    ])
    min_price_usd: float = 2.0            # Computed from pricing tiers

    # Authorization (for bot self-service)
    api_key_hash: str = ""                 # SHA-256 of API key (plaintext returned once at registration)

    # Status & moderation
    status: ListingStatus = "draft"
    featured: bool = False
    verified: bool = False                 # Admin-verified quality

    # Stats (updated in real-time)
    total_sessions: int = 0
    total_minutes: int = 0
    total_revenue_usd: float = 0.0
    rating: float = 0.0                    # 0-5 stars
    rating_count: int = 0

    # Timestamps
    created_at: float = 0.0
    updated_at: float = 0.0
    published_at: float = 0.0

    def __post_init__(self):
        if not self.listing_id:
            self.listing_id = uuid.uuid4().hex[:10]
        if not self.created_at:
            self.created_at = time.time()
        if not self.updated_at:
            self.updated_at = self.created_at
        self._compute_min_price()

    def _compute_min_price(self):
        if self.pricing:
            self.min_price_usd = min(t.price_usd for t in self.pricing)

    def publish(self):
        self.status = "active"
        self.published_at = time.time()
        self.updated_at = time.time()

    def suspend(self):
        self.status = "suspended"
        self.updated_at = time.time()

    def archive(self):
        self.status = "archived"
        self.updated_at = time.time()

    def add_rating(self, score: float):
        """Add a rating (1-5) and update average."""
        score = max(1.0, min(5.0, score))
        total = self.rating * self.rating_count + score
        self.rating_count += 1
        self.rating = total / self.rating_count
        self.updated_at = time.time()

    def issue_api_key(self) -> str:
        """Generate a new API key. Returns plaintext (shown once)."""
        key = _generate_api_key()
        self.api_key_hash = _hash_key(key)
        self.updated_at = time.time()
        return key

    def verify_api_key(self, key: str) -> bool:
        """Check if a plaintext key matches the stored hash."""
        return bool(self.api_key_hash) and _hash_key(key) == self.api_key_hash

    def record_session(self, minutes: float, revenue_usd: float):
        """Record a completed session."""
        self.total_sessions += 1
        self.total_minutes += int(minutes)
        self.total_revenue_usd += revenue_usd
        self.updated_at = time.time()

    def to_dict(self) -> dict:
        return {
            "listing_id": self.listing_id,
            "bot_id": self.bot_id,
            "owner_id": self.owner_id,
            "name": self.name,
            "tagline": self.tagline,
            "description": self.description,
            "avatar_url": self.avatar_url,
            "category": self.category,
            "tags": self.tags,
            "example_prompts": self.example_prompts,
            "provider": self.provider,
            "model": self.model,
            "system_prompt": self.system_prompt,
            "pricing": [t.to_dict() for t in self.pricing],
            "min_price_usd": self.min_price_usd,
            "status": self.status,
            "featured": self.featured,
            "verified": self.verified,
            "total_sessions": self.total_sessions,
            "total_minutes": self.total_minutes,
            "total_revenue_usd": self.total_revenue_usd,
            "rating": self.rating,
            "rating_count": self.rating_count,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "published_at": self.published_at,
            "api_key_hash": self.api_key_hash,
        }

    def to_public_dict(self) -> dict:
        """Public-facing info (no secrets, no revenue)."""
        d = self.to_dict()
        for k in ("system_prompt", "total_revenue_usd", "owner_id", "api_key_hash"):
            d.pop(k, None)
        return d

    def to_owner_dict(self) -> dict:
        """Owner/bot view — includes revenue but no key hash."""
        d = self.to_dict()
        d.pop("api_key_hash", None)
        return d

    @classmethod
    def from_dict(cls, d: dict) -> Listing:
        pricing_raw = d.pop("pricing", [])
        # Filter to known fields
        known = cls.__dataclass_fields__.keys()
        filtered = {k: v for k, v in d.items() if k in known}
        obj = cls(**filtered)
        obj.pricing = [PricingTier.from_dict(p) for p in pricing_raw]
        obj._compute_min_price()
        return obj


# Predefined categories
CATEGORIES = [
    "general",
    "coding",
    "writing",
    "translation",
    "finance",
    "academic",
    "creative",
    "business",
    "health",
    "legal",
    "education",
    "entertainment",
]

# Categories requiring licensed professional review
SENSITIVE_CATEGORIES = {"legal", "health", "finance"}
