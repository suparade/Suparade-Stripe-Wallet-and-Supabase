# Suparade

Agentic product placement tipping. Gemini watches a livestream, spots moments where the streamer uses or praises the sponsor's product, a second Gemini pass verifies them, and the streamer gets a real Stripe tip with an on screen message. Brands fund campaign budgets through Link Agent Wallet.

This repo has two parts that run together:

| Part | Folder | What it does | Runs on |
| --- | --- | --- | --- |
| Gemini detector + dashboard | `backend/`, `frontend/` | Cuts the stream into clips, Gemini video understanding, tip policy, verifier, chat reaction, thank you alerts | Laptop or VM (needs ffmpeg), port 8000, dashboard on 5173 |
| Payments API | `app/`, `supabase/` | Campaign budgets, creators, detections and tips in Supabase, Stripe Connect payouts, Link funding | Vercel, or locally on port 8001 |

```
stream URL / webcam -> ffmpeg 10s clips -> Gemini (video+audio+chat) -> tip policy -> Gemini verifier
   -> POST /agent/stream-events (payments API) -> Supabase ledger (budget lock) -> Stripe transfer to streamer
   -> dashboard shows "paid $X via Stripe tr_..." + spoken thank you alert; tips table -> Supabase Realtime pop up
```

Details on the detector: [backend/README.md](backend/README.md).

## End to end test (Gemini + Supabase + Stripe)

Needs: Python 3.9+ (3.11+ recommended), ffmpeg (`brew install ffmpeg`), Node 18+, a Gemini API key, and the payments setup below done once (Supabase migrations, Stripe sandbox key, a seeded campaign with a funded budget and an onboarded streamer whose `creators.handle` matches the dashboard's streamer id, `demo-streamer` for the seed).

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt -r backend/requirements.txt
cp backend/.env.example backend/.env   # set GEMINI_API_KEY and SUPARADE_CAMPAIGN_ID

# terminal 1: payments API
set -a; source .env; set +a; uvicorn app.main:app --port 8001
# terminal 2: Gemini detector
.venv/bin/uvicorn backend.main:app --port 8000
# terminal 3: dashboard
cd frontend && npm install && npm run dev   # http://localhost:5173
```

1. Check payments without Gemini: `python -m backend.payments demo-streamer` sends one $0.50 tip and prints the Stripe transfer.
2. In the dashboard, keep streamer id `demo-streamer`, tick **Demo mode**, and add `backend/demo/demo_stream.mp4` (or a Twitch or YouTube live URL, or your webcam).
3. Watch a flag go `verifying` -> `paying via Stripe` -> `paid $X via Stripe` with the `tr_...` id. The header shows the campaign budget left. Refusals show the reason (`insufficient_budget`, `unknown_streamer`, `creator_not_payable`).
4. In Supabase the tip is in `tips` (status `paid`), the debit in `wallet_ledger`, and the moment in `detections` (with `category`, `quote` and the full Gemini event in `meta`).

Every 10s clip with enough sponsor screen time also pays a small `sponsor_screen_time` bonus, so keep the campaign funded (dev credit below).

## How the money moves

1. **Fund:** the brand calls `POST /campaigns/{id}/fund` and gets a Stripe Checkout URL. The brand's Link agent creates a spend request, the brand approves it in the Link app, and the agent pays that Checkout. The Stripe webhook credits the campaign ledger.
2. **Detect:** the finder agent registers video URLs and posts detections.
3. **Tip:** the tipper agent calls `POST /agent/tips`. The database checks the budget and reserves the tip in one transaction, then we send a Stripe transfer to the creator's connected account.
4. **Show:** the tip row flips to `paid`. The frontend subscribes to the `tips` table with Supabase Realtime and shows the amount and message at `show_at_seconds`.

Safety built in: one tip per detection, budget checked under a row lock, per tip cap (`campaigns.max_tip_cents`), Stripe idempotency key per tip, creators cannot be paid until Stripe says transfers are active, live Stripe keys are refused unless `ALLOW_LIVE_MODE=1`.

## Payments API setup

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env        # fill in the values
```

1. **Database:** run the files in `supabase/migrations/` in order in the Supabase SQL editor (or `supabase db push`).
2. **Run locally:** `set -a; source .env; set +a; uvicorn app.main:app --reload --port 8001` (port 8000 is the Gemini detector)
3. **Stripe webhook (local):** `stripe listen --forward-to localhost:8001/webhooks/stripe` and put the printed `whsec_...` in `.env`.
   The only event we need is `checkout.session.completed` (it credits campaign budgets). Creator payout status is checked directly with Stripe, so no connected account events are needed.
4. **Test platform balance:** transfers need available funds. In test mode, pay a Checkout with card `4000000000000077`, which adds to the available balance immediately.
5. **Check Stripe:** `python -m scripts.stripe_check --add-test-funds 2000` (key, balance, Connect check, optional test funds).
6. **Seed a demo:** `python -m scripts.seed_demo "<video url>"` prints the ids and a creator onboarding link. The creator gets the handle `demo-streamer`, which is the detector's default streamer id.
7. **Fund the campaign (sandbox):** set `ALLOW_DEV_FUNDING=1` and `POST /campaigns/{id}/dev-credit` with the agent key. Real funding goes through Checkout and Link.
8. **Tests:** `pytest` (payments API) and `python -m unittest discover -s backend/tests -t .` (detector).

Deploy on Vercel: `api/index.py` and `vercel.json` are set up, and `.vercelignore` keeps the detector out of the deployment. Add the same env vars in the Vercel project settings, then point the detector's `SUPARADE_API_URL` at the Vercel URL.

## Agent API (header `X-Agent-Key: <AGENT_API_KEY>`)

| Method and path | Who | Purpose |
| --- | --- | --- |
| `GET /agent/campaigns/{id}/context` | tipper | Brand context, rules, budget left, max tip, recent tips |
| `POST /agent/videos` | finder | Register a video URL (`url`, `platform`, `title`, `creator_id`) |
| `GET /agent/videos?status=pending` | finder | Videos to scan |
| `PATCH /agent/videos/{id}` | finder | Set status: `pending`, `scanning`, `done`, `failed` |
| `POST /agent/detections` | finder | Log a moment: `campaign_id`, `video_id`, `kind`, `timestamp_seconds`, `confidence`, `description` |
| `POST /agent/tips` | tipper | `detection_id`, `amount_cents`, `message`, `reasoning`, `show_at_seconds` |
| `POST /agent/stream-events` | Gemini detector | One call per confirmed moment: the detector's event JSON plus `campaign_id`, `source_url`, `message`. Resolves the streamer by `creators.handle`, registers the stream as a video, logs the detection, caps the amount at `max_tip_cents`, reserves the budget and sends the Stripe transfer. Idempotent on `event_id`. |

`POST /agent/tips` error codes: `insufficient_budget`, `creator_not_payable`, `video_has_no_creator`, `campaign_not_active` (all 409), `amount_out_of_range` (422), `detection_not_found` (404). Calling it twice for the same detection returns the same tip. `POST /agent/stream-events` returns the same codes plus `unknown_streamer` (409) and `campaign_not_found` (404).

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
- Creators are created with Stripe's Accounts v2 API: Express dashboard, recipient configuration, `stripe_balance.stripe_transfers` capability. Stripe requires the platform to carry losses for Express accounts, so accept the loss liability acknowledgement once in Dashboard > Settings > Connect > Platform profile, or account creation fails with a liability error.
- Accounts v2 events do not reach classic webhooks, so payout readiness is polled: `POST /creators/{id}/refresh-status`, and automatically right before a tip is reserved.
- Creators default to US accounts. Set `CREATOR_COUNTRY` to change it (cross border payouts have extra Stripe rules).

## Known limits

- A tip left `pending` by a Stripe network error is retried by calling `POST /agent/tips` (or `/agent/stream-events`) again for the same detection or event; the detector does this automatically a few times.
- Link funding (Checkout plus webhook) is wired but not yet exercised end to end; the demo uses dev credit.
- The detector keeps sessions in memory: restarting it stops the streams it was watching. Paid tips are safe in Supabase.
