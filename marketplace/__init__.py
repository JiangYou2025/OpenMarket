"""OpenMarket — AI consultation marketplace.

Two API surfaces:
  - bot_bp  (/api/p)  — Provider: register, manage listing, stats, approvals
  - user_bp (/api/c)  — Consumer: browse, auth, wallet, sessions, ratings
"""

from .models import Listing, ListingStatus, PricingTier, CATEGORIES, SENSITIVE_CATEGORIES
from .store import MarketplaceStore, get_store
from .consumer import Consumer, ConsumerStore, get_consumer_store
from .session import Session, SessionStore, get_session_store
from .tag_engine import TagEngine, get_tag_engine
from .bot_api import bot_bp
from .user_api import user_bp

__all__ = [
    # Models
    "Listing", "ListingStatus", "PricingTier",
    "Consumer", "Session",
    "CATEGORIES", "SENSITIVE_CATEGORIES",
    # Stores
    "MarketplaceStore", "get_store",
    "ConsumerStore", "get_consumer_store",
    "SessionStore", "get_session_store",
    # Tag engine
    "TagEngine", "get_tag_engine",
    # Blueprints
    "bot_bp", "user_bp",
]
