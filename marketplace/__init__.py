"""OpenMarket — AI consultation marketplace.

Three API surfaces:
  - bot_bp   (/api/p)     — Provider: register, manage listing, stats, approvals
  - user_bp  (/api/c)     — Consumer: browse, auth, wallet, sessions, ratings
  - admin_bp (/api/admin) — Admin: moderation, refunds, platform stats

User auth & billing delegated to odysseeia.com Claw API.
"""

from .models import Listing, ListingStatus, PricingTier, CATEGORIES, SENSITIVE_CATEGORIES
from .store import MarketplaceStore, get_store
from .session import Session, SessionStore, get_session_store
from .tag_engine import TagEngine, get_tag_engine
from .claw_client import ClawClient, get_claw_client
from .bot_api import bot_bp
from .user_api import user_bp
from .admin_api import admin_bp

__all__ = [
    # Models
    "Listing", "ListingStatus", "PricingTier",
    "Session",
    "CATEGORIES", "SENSITIVE_CATEGORIES",
    # Stores
    "MarketplaceStore", "get_store",
    "SessionStore", "get_session_store",
    # Claw integration
    "ClawClient", "get_claw_client",
    # Tag engine
    "TagEngine", "get_tag_engine",
    # Blueprints
    "bot_bp", "user_bp", "admin_bp",
]
