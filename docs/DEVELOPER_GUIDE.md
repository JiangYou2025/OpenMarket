# 2dollars Developer Guide — Bot Integration API

> Register, manage, and monetize your AI bot on the 2dollars marketplace.

---

## Overview

The 2dollars API lets you programmatically register a bot, manage its listing, handle sensitive-category approvals, and track usage — all via a single API key.

## Authentication

Every registered bot gets a unique API key (format: `2d_sk_...`). This key is shown **once** at registration. Store it securely.

```
Authorization: Bearer 2d_sk_YOUR_KEY_HERE
```

## Quick Start

### 1. Register Your Bot

```bash
curl -X POST https://your-domain/api/2dollars/bots \
  -H "Content-Type: application/json" \
  -d '{
    "name": "Code Wizard",
    "description": "Writes, reviews, and debugs code in 20+ languages",
    "author": "YourOrg",
    "provider": "claude",
    "model": "claude-sonnet-4-6",
    "category": "coding",
    "tags": ["python", "javascript", "debugging"],
    "pricing_tier": "standard",
    "system_prompt": "You are an expert programmer...",
    "example_prompts": [
      "Review this Python function for bugs",
      "Write a REST API in Go"
    ]
  }'
```

**Response** (201):
```json
{
  "slug": "code-wizard",
  "name": "Code Wizard",
  "api_key": "2d_sk_abc123...",
  "status": "listed",
  ...
}
```

> Save `api_key` immediately! It is never shown again.

### 2. Check Your Listing

```bash
curl -H "Authorization: Bearer 2d_sk_abc123..." \
  https://your-domain/api/2dollars/me
```

### 3. Update Your Bot

```bash
curl -X PATCH https://your-domain/api/2dollars/me \
  -H "Authorization: Bearer 2d_sk_abc123..." \
  -H "Content-Type: application/json" \
  -d '{
    "description": "Now supports 30+ languages!",
    "tags": ["python", "javascript", "go", "rust"]
  }'
```

**Updatable fields**: `name`, `description`, `long_description`, `category`, `tags`, `system_prompt`, `example_prompts`, `avatar_url`, `webhook_url`, `pricing_tier`, `price_per_min`

### 4. Pause / Resume

```bash
# Go offline
curl -X POST -H "Authorization: Bearer 2d_sk_..." \
  https://your-domain/api/2dollars/me/pause

# Go live
curl -X POST -H "Authorization: Bearer 2d_sk_..." \
  https://your-domain/api/2dollars/me/resume
```

### 5. Rotate API Key

```bash
curl -X POST -H "Authorization: Bearer 2d_sk_OLD..." \
  https://your-domain/api/2dollars/me/key
```

Returns new key (old key immediately invalid).

### 6. Check Stats

```bash
curl -H "Authorization: Bearer 2d_sk_..." \
  https://your-domain/api/2dollars/me/stats
```

```json
{
  "slug": "code-wizard",
  "rating": 4.7,
  "rating_count": 23,
  "total_sessions": 156,
  "total_minutes": 412,
  "status": "listed"
}
```

---

## Sensitive Categories

Bots in `legal`, `medical`, or `finance` categories have an extra step: a licensed professional must approve each AI response before it's delivered to the user.

### How it works:

1. User sends message to your bot
2. AI generates response
3. Response is queued for review (user sees "pending")
4. You (the bot holder) review and approve/reject/edit

### Review Endpoints

```bash
# List pending approvals
curl -H "Authorization: Bearer 2d_sk_..." \
  https://your-domain/api/2dollars/me/pending

# Approve (deliver to user, start billing)
curl -X POST -H "Authorization: Bearer 2d_sk_..." \
  https://your-domain/api/2dollars/me/approve/APPROVAL_ID \
  -d '{"note": "Verified by Dr. Smith"}'

# Approve with edited response
curl -X POST -H "Authorization: Bearer 2d_sk_..." \
  https://your-domain/api/2dollars/me/approve/APPROVAL_ID \
  -d '{"response": "Edited professional answer...", "note": "Corrected dosage info"}'

# Reject (user not charged)
curl -X POST -H "Authorization: Bearer 2d_sk_..." \
  https://your-domain/api/2dollars/me/reject/APPROVAL_ID \
  -d '{"note": "Outside scope of practice"}'
```

Approvals expire after 30 minutes if not reviewed.

---

## Chat API (for external integrations)

Your users can chat with your bot via API:

```bash
curl -X POST https://your-domain/api/2dollars/chat \
  -H "Authorization: Bearer 2d_sk_..." \
  -H "Content-Type: application/json" \
  -d '{"message": "Write a quicksort in Python", "session_id": "user123"}'
```

**Response** (non-sensitive):
```json
{
  "reply": "Here's a quicksort implementation...",
  "bot": "code-wizard",
  "provider": "claude",
  "model": "claude-sonnet-4-6",
  "usage": {"input_tokens": 50, "output_tokens": 200}
}
```

**Response** (sensitive category, 202):
```json
{
  "status": "pending_approval",
  "approval_id": "abc123def456",
  "message": "Your question is being reviewed by a licensed professional.",
  "poll_url": "/api/2dollars/approvals/abc123def456"
}
```

---

## Categories

| Category | Key | Description |
|----------|-----|-------------|
| Coding | `coding` | Programming, debugging, code review |
| Writing | `writing` | Writing, translation, editing |
| Academic | `academic` | Research, papers, citations |
| Finance | `finance` | Financial analysis, investment (sensitive) |
| Creative | `creative` | Design, art, creative writing |
| Data | `data` | Data analysis, visualization |
| Legal | `legal` | Legal advice, contracts (sensitive) |
| Medical | `medical` | Health, medical info (sensitive) |
| Education | `education` | Teaching, tutoring |
| General | `general` | General-purpose assistant |

---

## Pricing Tiers

| Tier | $/min | Best for |
|------|-------|----------|
| `basic` | $0.04 | Simple tasks, high volume |
| `standard` | $0.13 | General use (default) |
| `premium` | $0.40 | Complex tasks, top models |
| `custom` | You set | Special pricing |

For custom pricing, set `pricing_tier: "custom"` and `price_per_min: 0.25` (your rate).

---

## Blog / Success Stories

Bots can publish success stories to build credibility:

```bash
curl -X POST https://your-domain/api/2dollars/blog \
  -H "Authorization: Bearer 2d_sk_..." \
  -H "Content-Type: application/json" \
  -d '{
    "title": "How Code Wizard helped ship a startup MVP in 3 days",
    "author": "Code Wizard Team",
    "summary": "A customer used Code Wizard to build their entire backend...",
    "content": "Full story here...",
    "bot_slug": "code-wizard",
    "tags": ["coding", "startup"],
    "cover_emoji": "🚀"
  }'
```

---

## Full API Reference

```
GET    /api/2dollars/help          — This reference
GET    /api/2dollars/bots          — Browse marketplace
GET    /api/2dollars/bots/<slug>   — Bot detail
POST   /api/2dollars/bots          — Register bot
GET    /api/2dollars/me            — Own listing (API key auth)
PATCH  /api/2dollars/me            — Update own listing
GET    /api/2dollars/me/stats      — Own stats
POST   /api/2dollars/me/key        — Rotate API key
POST   /api/2dollars/me/pause      — Go offline
POST   /api/2dollars/me/resume     — Go live
GET    /api/2dollars/me/pending    — List pending approvals
POST   /api/2dollars/me/approve/<id> — Approve response
POST   /api/2dollars/me/reject/<id>  — Reject response
POST   /api/2dollars/chat          — Send message to bot
GET    /api/2dollars/categories    — Category list
GET    /api/2dollars/pricing       — Pricing tiers
GET    /api/2dollars/stats         — Marketplace stats
GET    /api/2dollars/blog          — List blog posts
GET    /api/2dollars/blog/<id>     — Get blog post
POST   /api/2dollars/blog          — Create blog post
POST   /api/2dollars/blog/<id>/like — Like a post
```
