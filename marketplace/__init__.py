"""2dollars — AI consultation marketplace.

Two API surfaces:
  - bot_bp  (/api/bot)  — Bot self-service: register, update, publish, stats
  - user_bp (/api/user) — User-facing: browse, search, rate, purchase
"""

from .models import Listing, ListingStatus, PricingTier, CATEGORIES, SENSITIVE_CATEGORIES
from .store import MarketplaceStore, get_store
from .bot_api import bot_bp
from .user_api import user_bp

__all__ = [
    "Listing",
    "ListingStatus",
    "PricingTier",
    "CATEGORIES",
    "SENSITIVE_CATEGORIES",
    "MarketplaceStore",
    "get_store",
    "bot_bp",
    "user_bp",
]
