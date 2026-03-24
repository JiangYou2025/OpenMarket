"""Consumer model — user accounts, auth, and wallet.

Handles registration, JWT tokens, API keys, balance, and transactions.
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
from typing import Literal, Optional

log = logging.getLogger(__name__)

TransactionType = Literal["topup", "charge", "refund", "bonus"]


def _hash_password(password: str, salt: str) -> str:
    return hashlib.sha256(f"{salt}:{password}".encode()).hexdigest()


def _generate_consumer_key() -> str:
    return f"2d_ck_{secrets.token_urlsafe(32)}"


def _hash_key(key: str) -> str:
    return hashlib.sha256(key.encode()).hexdigest()


# ── Consumer ─────────────────────────────────────────────────

@dataclass
class Consumer:
    """A consumer account on the marketplace."""
    user_id: str = ""
    email: str = ""
    name: str = ""
    avatar_url: str = ""

    # Auth
    password_hash: str = ""
    password_salt: str = ""
    api_key_hash: str = ""

    # Wallet
    balance_usd: float = 0.0
    total_spent_usd: float = 0.0
    total_topup_usd: float = 0.0

    # Stats
    total_sessions: int = 0

    # Timestamps
    created_at: float = 0.0
    updated_at: float = 0.0
    last_login: float = 0.0

    # Status
    status: str = "active"  # active | suspended | deleted

    def __post_init__(self):
        if not self.user_id:
            self.user_id = f"u_{secrets.token_hex(6)}"
        if not self.created_at:
            self.created_at = time.time()
        if not self.updated_at:
            self.updated_at = self.created_at

    def set_password(self, password: str):
        self.password_salt = secrets.token_hex(16)
        self.password_hash = _hash_password(password, self.password_salt)

    def check_password(self, password: str) -> bool:
        return _hash_password(password, self.password_salt) == self.password_hash

    def issue_api_key(self) -> str:
        key = _generate_consumer_key()
        self.api_key_hash = _hash_key(key)
        self.updated_at = time.time()
        return key

    def verify_api_key(self, key: str) -> bool:
        return bool(self.api_key_hash) and _hash_key(key) == self.api_key_hash

    def can_afford(self, amount: float) -> bool:
        return self.balance_usd >= amount

    def charge(self, amount: float) -> bool:
        """Deduct from balance. Returns False if insufficient."""
        if self.balance_usd < amount:
            return False
        self.balance_usd = round(self.balance_usd - amount, 2)
        self.total_spent_usd = round(self.total_spent_usd + amount, 2)
        self.updated_at = time.time()
        return True

    def credit(self, amount: float):
        """Add to balance (topup or refund)."""
        self.balance_usd = round(self.balance_usd + amount, 2)
        self.total_topup_usd = round(self.total_topup_usd + amount, 2)
        self.updated_at = time.time()

    def refund(self, amount: float):
        """Refund to balance (doesn't count as topup)."""
        self.balance_usd = round(self.balance_usd + amount, 2)
        self.total_spent_usd = round(self.total_spent_usd - amount, 2)
        self.updated_at = time.time()

    def to_dict(self) -> dict:
        return asdict(self)

    def to_public_dict(self) -> dict:
        return {
            "user_id": self.user_id,
            "name": self.name,
            "email": self.email,
            "avatar_url": self.avatar_url,
            "balance_usd": self.balance_usd,
            "total_spent_usd": self.total_spent_usd,
            "total_sessions": self.total_sessions,
            "created_at": self.created_at,
        }

    @classmethod
    def from_dict(cls, d: dict) -> Consumer:
        known = cls.__dataclass_fields__.keys()
        return cls(**{k: v for k, v in d.items() if k in known})


# ── Transaction ──────────────────────────────────────────────

@dataclass
class Transaction:
    """A wallet transaction record."""
    tx_id: str = ""
    user_id: str = ""
    type: TransactionType = "charge"
    amount_usd: float = 0.0          # Positive for credit, negative for debit
    balance_after: float = 0.0
    description: str = ""
    session_id: str = ""              # If related to a session
    stripe_id: str = ""               # If related to Stripe payment
    created_at: float = 0.0

    def __post_init__(self):
        if not self.tx_id:
            self.tx_id = f"tx_{secrets.token_hex(6)}"
        if not self.created_at:
            self.created_at = time.time()

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> Transaction:
        known = cls.__dataclass_fields__.keys()
        return cls(**{k: v for k, v in d.items() if k in known})


# ── Consumer Store ───────────────────────────────────────────

_DEFAULT_PATH = Path(__file__).resolve().parent.parent / "marketplace_data"

WELCOME_BONUS = 2.0  # Free credit on registration


class ConsumerStore:
    """Thread-safe consumer account store with JSON persistence."""

    def __init__(self, data_dir: Optional[Path] = None):
        self.data_dir = data_dir or _DEFAULT_PATH
        self.data_dir.mkdir(exist_ok=True)
        self._users_file = self.data_dir / "consumers.json"
        self._tx_file = self.data_dir / "transactions.json"
        self._lock = threading.Lock()
        self._users: dict[str, Consumer] = {}        # user_id -> Consumer
        self._email_index: dict[str, str] = {}       # email -> user_id
        self._key_index: dict[str, str] = {}          # key_hash -> user_id
        self._transactions: list[Transaction] = []
        self._load()

    def _load(self):
        if self._users_file.exists():
            try:
                data = json.loads(self._users_file.read_text(encoding="utf-8"))
                for d in data:
                    c = Consumer.from_dict(d)
                    self._users[c.user_id] = c
                    if c.email:
                        self._email_index[c.email.lower()] = c.user_id
                    if c.api_key_hash:
                        self._key_index[c.api_key_hash] = c.user_id
                log.info("Loaded %d consumers", len(self._users))
            except Exception as e:
                log.error("Failed to load consumers: %s", e)

        if self._tx_file.exists():
            try:
                data = json.loads(self._tx_file.read_text(encoding="utf-8"))
                self._transactions = [Transaction.from_dict(d) for d in data]
                log.info("Loaded %d transactions", len(self._transactions))
            except Exception as e:
                log.error("Failed to load transactions: %s", e)

    def _save_users(self):
        data = [u.to_dict() for u in self._users.values()]
        self._users_file.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")

    def _save_transactions(self):
        data = [t.to_dict() for t in self._transactions]
        self._tx_file.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")

    # ── Registration & Auth ───────────────────────────────────

    def register(self, email: str, password: str, name: str = "") -> tuple[Consumer, str]:
        """Register a new consumer. Returns (consumer, api_key).

        Gives a welcome bonus.
        """
        email = email.lower().strip()
        with self._lock:
            if email in self._email_index:
                raise ValueError("Email already registered")

            c = Consumer(email=email, name=name or email.split("@")[0])
            c.set_password(password)
            api_key = c.issue_api_key()

            # Welcome bonus
            c.balance_usd = WELCOME_BONUS
            c.total_topup_usd = WELCOME_BONUS

            self._users[c.user_id] = c
            self._email_index[email] = c.user_id
            self._key_index[c.api_key_hash] = c.user_id

            # Record bonus transaction
            tx = Transaction(
                user_id=c.user_id,
                type="bonus",
                amount_usd=WELCOME_BONUS,
                balance_after=c.balance_usd,
                description="Welcome bonus",
            )
            self._transactions.append(tx)

            self._save_users()
            self._save_transactions()

        log.info("Consumer registered: %s (%s)", c.user_id, email)
        return c, api_key

    def authenticate(self, email: str, password: str) -> Optional[Consumer]:
        """Authenticate by email + password."""
        email = email.lower().strip()
        with self._lock:
            uid = self._email_index.get(email)
            if not uid:
                return None
            c = self._users.get(uid)
            if not c or not c.check_password(password):
                return None
            c.last_login = time.time()
            self._save_users()
            return c

    def get_by_api_key(self, api_key: str) -> Optional[Consumer]:
        """Authenticate by API key."""
        key_hash = _hash_key(api_key)
        with self._lock:
            uid = self._key_index.get(key_hash)
            if uid:
                return self._users.get(uid)
        return None

    def get(self, user_id: str) -> Optional[Consumer]:
        with self._lock:
            return self._users.get(user_id)

    def update(self, consumer: Consumer):
        with self._lock:
            self._users[consumer.user_id] = consumer
            self._save_users()

    # ── Wallet operations ─────────────────────────────────────

    def topup(self, user_id: str, amount: float, stripe_id: str = "") -> Transaction:
        """Add funds to consumer's wallet."""
        with self._lock:
            c = self._users.get(user_id)
            if not c:
                raise ValueError("User not found")
            c.credit(amount)
            tx = Transaction(
                user_id=user_id,
                type="topup",
                amount_usd=amount,
                balance_after=c.balance_usd,
                description=f"Top up ${amount:.2f}",
                stripe_id=stripe_id,
            )
            self._transactions.append(tx)
            self._save_users()
            self._save_transactions()
            return tx

    def charge(self, user_id: str, amount: float, session_id: str = "", description: str = "") -> Transaction:
        """Charge consumer's wallet. Raises ValueError if insufficient balance."""
        with self._lock:
            c = self._users.get(user_id)
            if not c:
                raise ValueError("User not found")
            if not c.charge(amount):
                raise ValueError("Insufficient balance")
            tx = Transaction(
                user_id=user_id,
                type="charge",
                amount_usd=-amount,
                balance_after=c.balance_usd,
                description=description or f"Session charge ${amount:.2f}",
                session_id=session_id,
            )
            self._transactions.append(tx)
            self._save_users()
            self._save_transactions()
            return tx

    def refund(self, user_id: str, amount: float, session_id: str = "", description: str = "") -> Transaction:
        """Refund to consumer's wallet."""
        with self._lock:
            c = self._users.get(user_id)
            if not c:
                raise ValueError("User not found")
            c.refund(amount)
            tx = Transaction(
                user_id=user_id,
                type="refund",
                amount_usd=amount,
                balance_after=c.balance_usd,
                description=description or f"Refund ${amount:.2f}",
                session_id=session_id,
            )
            self._transactions.append(tx)
            self._save_users()
            self._save_transactions()
            return tx

    def get_transactions(
        self,
        user_id: str,
        tx_type: str = "",
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[list[Transaction], int]:
        """Get transaction history for a user."""
        with self._lock:
            txs = [t for t in self._transactions if t.user_id == user_id]
        if tx_type:
            txs = [t for t in txs if t.type == tx_type]
        txs.sort(key=lambda t: t.created_at, reverse=True)
        total = len(txs)
        return txs[offset:offset + limit], total

    def get_balance(self, user_id: str) -> float:
        with self._lock:
            c = self._users.get(user_id)
            return c.balance_usd if c else 0.0


# ── Singleton ────────────────────────────────────────────────
_store: Optional[ConsumerStore] = None


def get_consumer_store() -> ConsumerStore:
    global _store
    if _store is None:
        _store = ConsumerStore()
    return _store
