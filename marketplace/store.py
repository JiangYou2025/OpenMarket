"""Marketplace persistence — JSON-backed store for listings."""

from __future__ import annotations

import json
import logging
import threading
from pathlib import Path
from typing import Optional

from .models import Listing, PricingTier, CATEGORIES, _hash_key

log = logging.getLogger(__name__)

# Default storage location
_DEFAULT_PATH = Path(__file__).resolve().parent.parent.parent / "marketplace_data"


class MarketplaceStore:
    """Thread-safe store for marketplace listings."""

    def __init__(self, data_dir: Optional[Path] = None):
        self.data_dir = data_dir or _DEFAULT_PATH
        self.data_dir.mkdir(exist_ok=True)
        self._file = self.data_dir / "listings.json"
        self._lock = threading.Lock()
        self._listings: dict[str, Listing] = {}
        self._key_index: dict[str, str] = {}  # key_hash -> listing_id
        self._load()

    def _load(self):
        if self._file.exists():
            try:
                raw = json.loads(self._file.read_text(encoding="utf-8"))
                for d in raw:
                    listing = Listing.from_dict(d)
                    self._listings[listing.listing_id] = listing
                    if listing.api_key_hash:
                        self._key_index[listing.api_key_hash] = listing.listing_id
                log.info("Loaded %d marketplace listings", len(self._listings))
            except Exception as e:
                log.error("Failed to load marketplace data: %s", e)

    def _save(self):
        data = [l.to_dict() for l in self._listings.values()]
        self._file.write_text(
            json.dumps(data, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )

    # ── CRUD ──────────────────────────────────────────────────────

    def create(self, listing: Listing) -> Listing:
        with self._lock:
            self._listings[listing.listing_id] = listing
            if listing.api_key_hash:
                self._key_index[listing.api_key_hash] = listing.listing_id
            self._save()
        log.info("Created listing %s: %s", listing.listing_id, listing.name)
        return listing

    def get(self, listing_id: str) -> Optional[Listing]:
        with self._lock:
            return self._listings.get(listing_id)

    def get_by_bot_id(self, bot_id: str) -> Optional[Listing]:
        with self._lock:
            for l in self._listings.values():
                if l.bot_id == bot_id:
                    return l
            return None

    def get_by_api_key(self, api_key: str) -> Optional[Listing]:
        """Authenticate a bot by API key. Returns listing or None."""
        key_hash = _hash_key(api_key)
        with self._lock:
            lid = self._key_index.get(key_hash)
            if lid:
                return self._listings.get(lid)
        return None

    def update(self, listing: Listing) -> Listing:
        with self._lock:
            # Update key index if hash changed
            old = self._listings.get(listing.listing_id)
            if old and old.api_key_hash and old.api_key_hash != listing.api_key_hash:
                self._key_index.pop(old.api_key_hash, None)
            if listing.api_key_hash:
                self._key_index[listing.api_key_hash] = listing.listing_id
            self._listings[listing.listing_id] = listing
            self._save()
        return listing

    def delete(self, listing_id: str) -> bool:
        with self._lock:
            listing = self._listings.pop(listing_id, None)
            if listing:
                if listing.api_key_hash:
                    self._key_index.pop(listing.api_key_hash, None)
                self._save()
                return True
            return False

    # ── Query ─────────────────────────────────────────────────────

    def list_active(
        self,
        category: str = "",
        tag: str = "",
        search: str = "",
        sort_by: str = "rating",
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[list[Listing], int]:
        """List active listings with filtering, search, and sorting."""
        with self._lock:
            results = [l for l in self._listings.values() if l.status == "active"]

        if category:
            results = [l for l in results if l.category == category]
        if tag:
            results = [l for l in results if tag in l.tags]
        if search:
            q = search.lower()
            results = [
                l for l in results
                if q in l.name.lower()
                or q in l.tagline.lower()
                or q in l.description.lower()
                or any(q in t.lower() for t in l.tags)
            ]

        total = len(results)

        sort_keys = {
            "rating": lambda l: (-l.rating, -l.rating_count),
            "price_low": lambda l: l.min_price_usd,
            "price_high": lambda l: -l.min_price_usd,
            "popular": lambda l: -l.total_sessions,
            "newest": lambda l: -l.published_at,
            "featured": lambda l: (not l.featured, -l.rating),
        }
        key_fn = sort_keys.get(sort_by, sort_keys["rating"])
        results.sort(key=key_fn)

        results = results[offset: offset + limit]
        return results, total

    def list_by_owner(self, owner_id: str) -> list[Listing]:
        with self._lock:
            return [l for l in self._listings.values() if l.owner_id == owner_id]

    def all(self) -> list[Listing]:
        with self._lock:
            return list(self._listings.values())

    def stats(self) -> dict:
        with self._lock:
            listings = list(self._listings.values())
        active = [l for l in listings if l.status == "active"]
        return {
            "total_listings": len(listings),
            "active_listings": len(active),
            "total_sessions": sum(l.total_sessions for l in listings),
            "total_revenue_usd": sum(l.total_revenue_usd for l in listings),
            "categories": {
                cat: len([l for l in active if l.category == cat])
                for cat in CATEGORIES
                if any(l.category == cat for l in active)
            },
        }


# ── Singleton ─────────────────────────────────────────────────
_store: Optional[MarketplaceStore] = None


def get_store() -> MarketplaceStore:
    global _store
    if _store is None:
        _store = MarketplaceStore()
    return _store
