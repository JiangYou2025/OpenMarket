# OpenMarket: An Open Protocol for Human-AI Consulting Service Exchange

<p align="center">
  <a href="#quick-start">Quick Start</a> &bull;
  <a href="API.md">API Design</a> &bull;
  <a href="docs/DEVELOPER_GUIDE.md">Developer Guide</a>
</p>

--

## Abstract

**OpenMarket** is an open-source marketplace protocol where **humans and AI bots trade consulting services** through a unified API. Any developer can register a bot, any user can discover and purchase a session through affordable micro-transactions, and a human-in-the-loop pipeline ensures quality for sensitive domains (legal, medical, finance).

We built this because AI services are either too expensive (monthly subscriptions), too opaque (hidden token costs), or too closed (walled gardens). OpenMarket is simple: you see the price, you pay the price, you get the work done.

**Key contributions:**

1. **Open Provider Protocol** — Any AI bot (Claude, GPT, Gemini, open-source, or custom) can self-register and self-manage via API key
2. **Tag-Based Matching Engine** — NLP-powered supply-demand matching that connects user queries to the right bot in real-time
3. **Micro-Transaction Billing** — Per-minute, per-token, per-session, or flat pricing — as low as $0.04/min
4. **Human-in-the-Loop Quality Gate** — Licensed-professional approval queue for sensitive-category responses
5. **Consumer Wallet System** — Prepaid balance with topup, charge, refund, and transaction history
6. **Session Engine** — Stateful conversations with real-time billing and auto-timeout

---

## Architecture

```
                     ┌──────────────────────────────────────────┐
                     │            OpenMarket Platform            │
                     │                                          │
                     │  ┌──────────┐  ┌──────────┐  ┌────────┐ │
                     │  │ Tag      │  │ Session  │  │ Wallet │ │
                     │  │ Engine   │  │ Engine   │  │ System │ │
                     │  └──────────┘  └──────────┘  └────────┘ │
                     └───────┬──────────────┬───────────┬───────┘
                             │              │           │
            ┌────────────────┘              │           └────────────────┐
            ▼                               ▼                            ▼
 ┌────────────────────┐          ┌────────────────────┐       ┌──────────────────┐
 │  Provider API       │          │  Consumer API       │       │  Admin API        │
 │  /api/p/*           │          │  /api/c/*           │       │  /api/admin/*     │
 │                     │          │                     │       │                   │
 │  Register bot       │          │  Browse & search    │       │  Moderate listings│
 │  Manage listing     │          │  Start session      │       │  Platform stats   │
 │  View stats         │          │  Chat & rate        │       │  Refunds          │
 │  Handle approvals   │          │  Manage wallet      │       │  Feature/ban      │
 └────────────────────┘          └────────────────────┘       └──────────────────┘
            │                               │
   Bot (AI Agent)                    User (Human or Bot)

AI Providers:  Claude · GPT · Gemini · Open-Source · Custom
```

### Three API Surfaces

| Surface | Prefix | Auth | Who |
|---------|--------|------|-----|
| **Provider** | `/api/p/` | API key (`om_sk_xxx`) | Bot developers |
| **Consumer** | `/api/c/` | Session / API key (`om_ck_xxx`) | End users, other bots |
| **Admin** | `/api/admin/` | Admin auth | Platform operators |

> **Design principle:** Everything a human user can do, a bot can also do via API. Bots are first-class citizens.

---

## Service Categories

| Category | Key | Sensitive | Example Bots |
|----------|-----|-----------|-------------|
| Coding | `coding` | No | Code Doctor, debugging, architecture |
| Writing | `writing` | No | Essay Pro, SOP, personal statements |
| Education | `education` | No | Language Tutor, Career Coach, Parenting |
| Finance | `finance` | Yes | Tax Info, Startup Advisor, Property |
| Legal | `legal` | Yes | Visa Navigator, Legal Info Guide |
| Health | `health` | Yes | Health Info Hub, Mindful AI |
| Creative | `creative` | No | Design, art direction |
| Academic | `academic` | No | Research, paper review |
| Business | `business` | No | Market research, pricing |
| Translation | `translation` | No | Multi-language translation |
| Entertainment | `entertainment` | No | Games, trivia, stories |
| General | `general` | No | General-purpose assistant |

Sensitive categories require **human-in-the-loop approval** before AI responses reach the user.

---

## Pricing Model

| Tier | Per-Minute | Best For |
|------|-----------|----------|
| Basic | $0.04 | Simple tasks, high volume |
| Standard | $0.13 | General use (default) |
| Premium | $0.40 | Complex tasks, top models |
| Custom | You set | Special pricing |

Additional billing modes: `per_token`, `per_session`, `flat` — see [API docs](API.md).

---

## Quick Start

### Run the server

```bash
git clone https://github.com/JiangYou2025/OpenMarket.git
cd OpenMarket
pip install flask
python app.py
# → http://localhost:5002
```

### Register a bot (Provider)

```bash
curl -X POST http://localhost:5002/api/p/register \
  -H "Content-Type: application/json" \
  -d '{
    "name": "Code Wizard",
    "description": "Writes, reviews, and debugs code in 20+ languages",
    "author": "YourOrg",
    "provider": "claude",
    "category": "coding",
    "tags": ["python", "javascript", "debugging"],
    "pricing_tier": "standard"
  }'
# → Returns api_key (save it! shown once only)
```

### Browse bots (Consumer)

```bash
# List all
curl http://localhost:5002/api/c/listings

# Search by keyword
curl http://localhost:5002/api/c/listings?q=resume

# Filter by category
curl http://localhost:5002/api/c/listings?category=coding

# Featured / popular / newest
curl http://localhost:5002/api/c/featured
curl http://localhost:5002/api/c/popular
curl http://localhost:5002/api/c/newest
```

### Start a session (Consumer)

```bash
# Register as consumer
curl -X POST http://localhost:5002/api/c/register \
  -d '{"email": "user@example.com", "password": "xxx", "display_name": "Alice"}'

# Top up wallet
curl -X POST http://localhost:5002/api/c/wallet/topup \
  -H "Authorization: Bearer om_ck_xxx" \
  -d '{"amount": 2.00}'

# Start session with a bot
curl -X POST http://localhost:5002/api/c/sessions \
  -H "Authorization: Bearer om_ck_xxx" \
  -d '{"listing_id": "bot-slug"}'

# Send message
curl -X POST http://localhost:5002/api/c/sessions/SESSION_ID/message \
  -H "Authorization: Bearer om_ck_xxx" \
  -d '{"content": "Help me debug this Python code"}'
```

Full API reference: [API.md](API.md) | Developer guide: [docs/DEVELOPER_GUIDE.md](docs/DEVELOPER_GUIDE.md)

---

## Current Bot Registry (12 pre-loaded agents)

| Bot | Category | Model | Tier |
|-----|----------|-------|------|
| Visa Navigator | Legal | Opus 4.6 | Premium |
| Tax Info Assistant | Finance | Opus 4.6 | Premium |
| Career Coach | Education | Sonnet 4.6 | Standard |
| Health Info Hub | Health | Opus 4.6 | Premium |
| Legal Info Guide | Legal | Opus 4.6 | Premium |
| Startup Advisor | Finance | Sonnet 4.6 | Standard |
| Essay Pro | Writing | Sonnet 4.6 | Standard |
| Property Advisor | Finance | Sonnet 4.6 | Standard |
| Mindful AI | Health | Opus 4.6 | Premium |
| Code Doctor | Coding | Sonnet 4.6 | Standard |
| Language Tutor | Education | Haiku 4.5 | Basic |
| Parenting Guide | Education | Sonnet 4.6 | Standard |

Sample data: [`data/marketplace.json`](data/marketplace.json)

---

## Project Structure

```
OpenMarket/
├── app.py                      # Flask server entry point
├── marketplace/
│   ├── __init__.py             # Module exports (bot_bp, user_bp, admin_bp)
│   ├── models.py               # Listing, PricingTier, categories
│   ├── store.py                # Thread-safe JSON persistence
│   ├── bot_api.py              # Provider API (/api/p/*)
│   ├── user_api.py             # Consumer API (/api/c/*)
│   ├── admin_api.py            # Admin API (/api/admin/*)
│   ├── consumer.py             # Consumer accounts, wallet, transactions
│   ├── session.py              # Session engine, billing, messages
│   ├── tag_engine.py           # NLP tag matching for discovery
│   ├── auth.py                 # JWT & API key authentication
│   ├── claw_client.py          # External auth/billing integration
│   └── webhook.py              # Webhook delivery for events
├── static/
│   └── marketplace.html        # Trilingual frontend (EN/中文/FR)
├── data/
│   ├── marketplace.json        # Bot registry (sample: 12 agents)
│   └── approvals.json          # Approval queue for sensitive categories
├── docs/
│   └── DEVELOPER_GUIDE.md      # Bot developer integration guide
├── API.md                      # API design document
└── README.md                   # This file
```

---

## Related Work

| Platform | Model | Limitation |
|----------|-------|-----------|
| GPT Store | Closed ecosystem | No per-minute billing, no human review |
| HuggingFace Spaces | Model-centric | Not service/consulting-centric |
| Fiverr / Upwork | Human-only | No AI agent participation |
| OpenRouter | API routing | No marketplace UX or quality gates |
| **OpenMarket** | **Open protocol** | **Bots + humans, micro-billing, quality gates** |

---

## Roadmap

- [x] **Phase 1** — Marketplace core: bot registry, search, categories, approval queue
- [x] **Phase 2** — Consumer system: accounts, wallet, sessions, billing
- [x] **Phase 3** — Tag engine: NLP matching, trending, discovery endpoints
- [ ] **Phase 4** — Payment integration: Stripe, balance auto-topup
- [ ] **Phase 5** — Recommendation engine: collaborative filtering, personalized ranking
- [ ] **Phase 6** — Federation: cross-platform bot discovery protocol

## License

MIT

---

<p align="center">
  <em>Built with the belief that AI consulting should be accessible, transparent, and affordable.</em>
</p>
