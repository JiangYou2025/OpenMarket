"""Session Engine — start, message, bill, end.

A session is a paid conversation between a consumer and a bot listing.
Billing happens based on the pricing tier (per_minute, per_token, per_session, flat).
"""

from __future__ import annotations

import json
import logging
import secrets
import threading
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Literal, Optional

log = logging.getLogger(__name__)

SessionStatus = Literal["active", "ended", "expired", "cancelled"]

PLATFORM_FEE_RATE = 0.20  # 20% platform cut
SESSION_TIMEOUT_MINUTES = 60  # Auto-end after 60 min inactivity


# ── Message ──────────────────────────────────────────────────

@dataclass
class Message:
    """A single message in a session."""
    message_id: str = ""
    session_id: str = ""
    role: str = "user"             # user | assistant | system
    content: str = ""
    tokens_used: int = 0
    created_at: float = 0.0

    # For approval queue (sensitive categories)
    approval_id: str = ""
    approval_status: str = ""      # "" | pending_review | approved | rejected

    def __post_init__(self):
        if not self.message_id:
            self.message_id = f"msg_{secrets.token_hex(6)}"
        if not self.created_at:
            self.created_at = time.time()

    def to_dict(self) -> dict:
        return asdict(self)

    def to_public_dict(self) -> dict:
        d = {
            "message_id": self.message_id,
            "role": self.role,
            "content": self.content,
            "created_at": self.created_at,
        }
        if self.approval_status:
            d["approval_status"] = self.approval_status
            d["approval_id"] = self.approval_id
        if self.role == "assistant":
            d["tokens_used"] = self.tokens_used
        return d

    @classmethod
    def from_dict(cls, d: dict) -> Message:
        known = cls.__dataclass_fields__.keys()
        return cls(**{k: v for k, v in d.items() if k in known})


# ── Session ──────────────────────────────────────────────────

@dataclass
class Session:
    """A paid conversation session."""
    session_id: str = ""
    user_id: str = ""
    listing_id: str = ""
    bot_name: str = ""

    # Pricing snapshot (frozen at session start)
    pricing_tier: str = "basic"
    price_usd: float = 2.0
    pricing_unit: str = "per_minute"
    pricing_unit_amount: int = 15    # e.g., 15 minutes per unit

    # Billing
    prepaid_usd: float = 0.0        # Amount pre-charged at start
    cost_usd: float = 0.0           # Running cost
    platform_fee_usd: float = 0.0   # Platform's cut
    provider_revenue_usd: float = 0.0  # Provider's cut
    refund_usd: float = 0.0         # Refunded if prepaid > actual cost

    # Usage
    total_messages: int = 0
    total_tokens: int = 0
    elapsed_minutes: float = 0.0

    # Status
    status: SessionStatus = "active"

    # Timestamps
    started_at: float = 0.0
    ended_at: float = 0.0
    last_activity: float = 0.0

    # Rating
    rating: float = 0.0
    rating_comment: str = ""

    def __post_init__(self):
        if not self.session_id:
            self.session_id = f"ses_{secrets.token_hex(6)}"
        if not self.started_at:
            self.started_at = time.time()
        if not self.last_activity:
            self.last_activity = self.started_at

    def compute_cost(self) -> float:
        """Calculate current cost based on pricing model and usage."""
        if self.pricing_unit == "per_minute":
            elapsed = (time.time() - self.started_at) / 60
            self.elapsed_minutes = round(elapsed, 2)
            # price_usd per pricing_unit_amount minutes
            rate = self.price_usd / self.pricing_unit_amount if self.pricing_unit_amount else 0
            cost = elapsed * rate

        elif self.pricing_unit == "per_token":
            rate = self.price_usd / self.pricing_unit_amount if self.pricing_unit_amount else 0
            cost = self.total_tokens * rate

        elif self.pricing_unit == "per_session":
            cost = self.price_usd

        elif self.pricing_unit == "flat":
            cost = self.price_usd

        else:
            cost = 0

        self.cost_usd = round(max(0, cost), 2)
        self.platform_fee_usd = round(self.cost_usd * PLATFORM_FEE_RATE, 2)
        self.provider_revenue_usd = round(self.cost_usd - self.platform_fee_usd, 2)
        return self.cost_usd

    def end(self) -> dict:
        """End the session and compute final billing."""
        self.status = "ended"
        self.ended_at = time.time()
        self.elapsed_minutes = round((self.ended_at - self.started_at) / 60, 2)
        final_cost = self.compute_cost()

        # Refund overpayment
        if self.prepaid_usd > final_cost:
            self.refund_usd = round(self.prepaid_usd - final_cost, 2)

        return {
            "session_id": self.session_id,
            "status": "ended",
            "summary": {
                "duration_minutes": self.elapsed_minutes,
                "total_messages": self.total_messages,
                "total_tokens": self.total_tokens,
                "total_cost_usd": self.cost_usd,
                "platform_fee_usd": self.platform_fee_usd,
                "provider_revenue_usd": self.provider_revenue_usd,
                "prepaid_usd": self.prepaid_usd,
                "refund_usd": self.refund_usd,
            },
        }

    def is_expired(self) -> bool:
        """Check if session timed out due to inactivity."""
        if self.status != "active":
            return False
        return (time.time() - self.last_activity) > SESSION_TIMEOUT_MINUTES * 60

    def to_dict(self) -> dict:
        return asdict(self)

    def to_consumer_dict(self) -> dict:
        """What the consumer sees."""
        self.compute_cost()
        return {
            "session_id": self.session_id,
            "listing_id": self.listing_id,
            "bot_name": self.bot_name,
            "status": "expired" if self.is_expired() else self.status,
            "pricing": {
                "tier": self.pricing_tier,
                "price_usd": self.price_usd,
                "unit": self.pricing_unit,
                "unit_amount": self.pricing_unit_amount,
            },
            "started_at": self.started_at,
            "elapsed_minutes": self.elapsed_minutes,
            "cost_so_far_usd": self.cost_usd,
            "prepaid_usd": self.prepaid_usd,
            "total_messages": self.total_messages,
            "ended_at": self.ended_at if self.status == "ended" else None,
            "refund_usd": self.refund_usd if self.status == "ended" else None,
        }

    def to_provider_dict(self) -> dict:
        """What the provider sees (includes revenue)."""
        d = self.to_consumer_dict()
        d["user_id"] = self.user_id
        d["total_tokens"] = self.total_tokens
        d["provider_revenue_usd"] = self.provider_revenue_usd
        d["platform_fee_usd"] = self.platform_fee_usd
        return d

    @classmethod
    def from_dict(cls, d: dict) -> Session:
        known = cls.__dataclass_fields__.keys()
        return cls(**{k: v for k, v in d.items() if k in known})


# ── Session Store ────────────────────────────────────────────

_DEFAULT_PATH = Path(__file__).resolve().parent.parent / "marketplace_data"


class SessionStore:
    """Thread-safe session store with JSON persistence."""

    def __init__(self, data_dir: Optional[Path] = None):
        self.data_dir = data_dir or _DEFAULT_PATH
        self.data_dir.mkdir(exist_ok=True)
        self._sessions_file = self.data_dir / "sessions.json"
        self._messages_dir = self.data_dir / "messages"
        self._messages_dir.mkdir(exist_ok=True)
        self._lock = threading.Lock()
        self._sessions: dict[str, Session] = {}
        self._load()

    def _load(self):
        if self._sessions_file.exists():
            try:
                data = json.loads(self._sessions_file.read_text(encoding="utf-8"))
                for d in data:
                    s = Session.from_dict(d)
                    self._sessions[s.session_id] = s
                log.info("Loaded %d sessions", len(self._sessions))
            except Exception as e:
                log.error("Failed to load sessions: %s", e)

    def _save(self):
        data = [s.to_dict() for s in self._sessions.values()]
        self._sessions_file.write_text(
            json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8",
        )

    def _messages_file(self, session_id: str) -> Path:
        return self._messages_dir / f"{session_id}.json"

    def _load_messages(self, session_id: str) -> list[Message]:
        f = self._messages_file(session_id)
        if f.exists():
            try:
                return [Message.from_dict(d) for d in json.loads(f.read_text(encoding="utf-8"))]
            except Exception:
                pass
        return []

    def _save_messages(self, session_id: str, messages: list[Message]):
        f = self._messages_file(session_id)
        f.write_text(
            json.dumps([m.to_dict() for m in messages], indent=2, ensure_ascii=False),
            encoding="utf-8",
        )

    # ── Session lifecycle ─────────────────────────────────────

    def create(self, session: Session) -> Session:
        with self._lock:
            self._sessions[session.session_id] = session
            self._save()
        log.info("Session created: %s (user=%s, listing=%s)",
                 session.session_id, session.user_id, session.listing_id)
        return session

    def get(self, session_id: str) -> Optional[Session]:
        with self._lock:
            s = self._sessions.get(session_id)
            if s and s.is_expired() and s.status == "active":
                s.end()
                self._save()
            return s

    def end_session(self, session_id: str) -> Optional[Session]:
        with self._lock:
            s = self._sessions.get(session_id)
            if not s or s.status != "active":
                return None
            s.end()
            self._save()
            return s

    # ── Messages ──────────────────────────────────────────────

    def add_message(self, session_id: str, message: Message) -> Optional[Message]:
        with self._lock:
            s = self._sessions.get(session_id)
            if not s or s.status != "active":
                return None
            s.total_messages += 1
            s.total_tokens += message.tokens_used
            s.last_activity = time.time()
            self._save()

        # Messages stored separately per session
        messages = self._load_messages(session_id)
        message.session_id = session_id
        messages.append(message)
        self._save_messages(session_id, messages)
        return message

    def get_messages(
        self,
        session_id: str,
        limit: int = 50,
        before: str = "",
    ) -> list[Message]:
        messages = self._load_messages(session_id)
        if before:
            idx = next((i for i, m in enumerate(messages) if m.message_id == before), len(messages))
            messages = messages[:idx]
        return messages[-limit:]

    # ── Queries ───────────────────────────────────────────────

    def list_by_user(
        self,
        user_id: str,
        status: str = "",
        listing_id: str = "",
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[list[Session], int]:
        with self._lock:
            results = [s for s in self._sessions.values() if s.user_id == user_id]
        if status:
            results = [s for s in results if s.status == status]
        if listing_id:
            results = [s for s in results if s.listing_id == listing_id]
        results.sort(key=lambda s: s.started_at, reverse=True)
        total = len(results)
        return results[offset:offset + limit], total

    def list_by_listing(
        self,
        listing_id: str,
        status: str = "",
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[list[Session], int]:
        with self._lock:
            results = [s for s in self._sessions.values() if s.listing_id == listing_id]
        if status:
            results = [s for s in results if s.status == status]
        results.sort(key=lambda s: s.started_at, reverse=True)
        total = len(results)
        return results[offset:offset + limit], total

    def active_count(self) -> int:
        with self._lock:
            return sum(1 for s in self._sessions.values() if s.status == "active")

    def cleanup_expired(self):
        """End all expired sessions."""
        with self._lock:
            for s in self._sessions.values():
                if s.is_expired() and s.status == "active":
                    s.end()
            self._save()


# ── Singleton ────────────────────────────────────────────────
_store: Optional[SessionStore] = None


def get_session_store() -> SessionStore:
    global _store
    if _store is None:
        _store = SessionStore()
    return _store
