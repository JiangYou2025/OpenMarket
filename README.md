# OpenMarket

AI consultation marketplace — vending machine for AI bot services.

## Architecture

Two API surfaces:

### Provider API (`/api/bot/`) — Bot self-service
- `POST /register` — Register bot, get API key
- `GET/PUT /me` — View/update listing
- `POST /me/publish` — Go live
- `POST /me/suspend` — Take offline
- `GET /me/stats` — Usage stats & revenue
- `POST /me/rotate-key` — Regenerate API key

### Consumer API (`/api/user/`) — Browse & consume
- `GET /listings` — Search/filter bots (category, tag, keyword, sort)
- `GET /listings/:id` — Bot detail page
- `GET /categories` — Category list with counts
- `GET /featured` / `/popular` / `/newest` — Discovery endpoints
- `POST /listings/:id/rate` — Rate a bot (1-5)
- `GET /stats` — Platform stats

## Models

- **Listing** — Bot marketplace card (name, category, pricing, stats)
- **PricingTier** — Flexible pricing (per_minute, per_token, per_session, flat)

## Categories

general, coding, writing, translation, finance, academic, creative, business, health, legal, education, entertainment

## Auth

- Provider auth: `Authorization: Bearer 2d_sk_xxx`
- Consumer auth: TBD (session-based)
- Sensitive categories (legal, health, finance) require professional review

## Stack

- Python / Flask blueprints
- JSON file persistence (pluggable)
- Designed to integrate with Stripe for payments

## License

MIT
