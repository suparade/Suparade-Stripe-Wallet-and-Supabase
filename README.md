# Suparade backend

Supabase + Stripe backend for the agent tipping app. A finder agent logs moments in videos (brand mentions or cool moments), a tipper agent decides how much to tip and when, and the creator gets paid through Stripe Connect. Brands fund campaign budgets through Link Agent Wallet.

## How the money moves

1. **Fund:** the brand calls `POST /campaigns/{id}/fund` and gets a Stripe Checkout URL. The brand's Link agent creates a spend request, the brand approves it in the Link app, and the agent pays that Checkout. The Stripe webhook credits the campaign ledger.
2. **Detect:** the finder agent registers video URLs and posts detections.
3. **Tip:** the tipper agent calls `POST /agent/tips`. The database checks the budget and reserves the tip in one transaction, then we send a Stripe transfer to the creator's connected account.
4. **Show:** the tip row flips to `paid`. The frontend subscribes to the `tips` table with Supabase Realtime and shows the amount and message at `show_at_seconds`.

Safety built in: one tip per detection, budget checked under a row lock, per tip cap (`campaigns.max_tip_cents`), Stripe idempotency key per tip, creators cannot be paid until Stripe says transfers are active, live Stripe keys are refused unless `ALLOW_LIVE_MODE=1`.

## Setup

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env        # fill in the values
```

1. **Database:** run `supabase/migrations/20261003000000_init.sql` in the Supabase SQL editor (or `supabase db push`).
2. **Run locally:** `set -a; source .env; set +a; uvicorn app.main:app --reload --port 8000`
3. **Stripe webhook (local):** `stripe listen --forward-to localhost:8000/webhooks/stripe --forward-connect-to localhost:8000/webhooks/stripe` and put the printed `whsec_...` in `.env`.
   In the dashboard, also enable events on **connected accounts** so `account.updated` arrives. Events needed: `checkout.session.completed`, `account.updated`.
4. **Test platform balance:** transfers need available funds. In test mode, pay a Checkout with card `4000000000000077`, which adds to the available balance immediately.
5. **Seed a demo:** `python -m scripts.seed_demo "<video url>"` prints the ids and a creator onboarding link.
6. **Tests:** `pytest`

Deploy on Vercel: `api/index.py` and `vercel.json` are set up. Add the same env vars in the Vercel project settings.

## Agent API (header `X-Agent-Key: <AGENT_API_KEY>`)

| Method and path | Who | Purpose |
| --- | --- | --- |
| `GET /agent/campaigns/{id}/context` | tipper | Brand context, rules, budget left, max tip, recent tips |
| `POST /agent/videos` | finder | Register a video URL (`url`, `platform`, `title`, `creator_id`) |
| `GET /agent/videos?status=pending` | finder | Videos to scan |
| `PATCH /agent/videos/{id}` | finder | Set status: `pending`, `scanning`, `done`, `failed` |
| `POST /agent/detections` | finder | Log a moment: `campaign_id`, `video_id`, `kind`, `timestamp_seconds`, `confidence`, `description` |
| `POST /agent/tips` | tipper | `detection_id`, `amount_cents`, `message`, `reasoning`, `show_at_seconds` |

`POST /agent/tips` error codes: `insufficient_budget`, `creator_not_payable`, `video_has_no_creator`, `campaign_not_active` (all 409), `amount_out_of_range` (422), `detection_not_found` (404). Calling it twice for the same detection returns the same tip.

## Frontend API (header `Authorization: Bearer <supabase access token>`)

| Method and path | Purpose |
| --- | --- |
| `POST /creators` | Create a creator profile for the signed in user |
| `POST /creators/{id}/connect` | Stripe onboarding URL for the streamer |
| `POST /creators/{id}/refresh-status` | Sync payout status from Stripe |
| `POST /campaigns/{id}/fund` | Checkout URL to top up a campaign budget |

Brands, campaigns, detections, tips and the ledger are read directly from Supabase by the frontend (row level security limits brands to their own data; paid tips are public so the pop up works).

## Link Agent Wallet notes

- Link needs an OAuth client approved through Stripe's [application form](https://docs.google.com/forms/d/1frwbtMaUUAaMMv0rHEk_qCvKUHJUxHCr8vkLknnBS9w/viewform) for hosted use. For the hackathon, log the brand's own Link account into the CLI instead: `npm i -g @stripe/link-cli`, then `link-cli auth login`.
- Link spend requests need a human approval in the Link app (10 minute window), and are limited to US and Canadian consumers. Link has no Python SDK, so the funding agent drives it with `link-cli` or `@stripe/link-sdk`. This backend only provides the Checkout and the webhook.
- If the Link approval step stalls during the demo, set `ALLOW_DEV_FUNDING=1` and use `POST /campaigns/{id}/dev-credit` with the agent key to credit the budget.
- Creators are created as Express accounts requesting only the `transfers` capability. If you pay creators outside the platform's country, Stripe may require the recipient service agreement, which needs a small change in `app/services/connect.py`.

## Known limits

- The SQL migration was syntax checked but not run against a live database yet. Run it first and tell me about any errors.
- A tip left `pending` by a Stripe network error is retried by calling `POST /agent/tips` again for the same detection.
- The Vercel and Stripe flows were not exercised end to end here (no keys), only unit level checks.
