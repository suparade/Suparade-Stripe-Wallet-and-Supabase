# Setup and operations

This page takes you from a fresh clone to a paid sandbox tip, then covers every environment variable, the tests, deployment and troubleshooting.

Everything here uses Stripe **test mode**. No real money moves. Live keys are refused unless `ALLOW_LIVE_MODE=1`.

## Prerequisites

| Tool | Version | Used for |
| --- | --- | --- |
| Python | 3.9+, 3.11+ recommended | Both services |
| Node.js | 18+ | Dashboard |
| ffmpeg | Any recent | Cutting streams into clips (`brew install ffmpeg`) |
| Supabase project | | Database, auth, Realtime |
| Stripe sandbox account | Connect enabled | Creator payouts and funding |
| Gemini API key | | Clip analysis, verification, alerts |
| Stripe CLI | Optional | Forwarding webhooks locally |

## Detection only, in two minutes

To see Gemini flag moments without Supabase or Stripe:

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r backend/requirements.txt
cp backend/.env.example backend/.env
```

In `backend/.env`, set `GEMINI_API_KEY` and clear `SUPARADE_API_URL`. Then:

```bash
uvicorn backend.main:app --port 8000
```

```bash
cd frontend && npm install && npm run dev
```

Open http://localhost:5173, tick **Demo mode** and add `backend/demo/demo_stream.mp4`. Tips are marked `simulated`.

## Full setup, with real sandbox payouts

### 1. Database

Run the three files in `supabase/migrations/` in order, in the Supabase SQL editor or with `supabase db push`. They create the tables, the money functions, row level security, the grants and the Realtime publication. See [DATA_MODEL.md](DATA_MODEL.md).

### 2. Payments API environment

```bash
cp .env.example .env
```

Fill in the Supabase URL and service role key, your Stripe test secret key and a long random `AGENT_API_KEY`. Set `ALLOW_DEV_FUNDING=1` for the demo. All variables are listed [below](#environment-variables).

### 3. Install

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt -r backend/requirements.txt
```

### 4. Stripe sandbox

1. In the Stripe Dashboard, open Settings, Connect, Platform profile and accept the loss liability acknowledgement. Creator accounts are Express accounts, and Stripe requires the platform to carry losses for them; without this, account creation fails with a liability error.
2. Check the key and give the platform a test balance, because transfers need available funds:

```bash
set -a; source .env; set +a
python -m scripts.stripe_check --add-test-funds 2000
```

Paying a Checkout with test card `4000000000000077` also adds to the available balance immediately.

### 5. Seed a demo campaign and creator

```bash
python -m scripts.seed_demo "https://example.com/some-video.mp4"
```

This creates a brand, an active campaign, a creator with the handle `demo-streamer` and a video, and prints their ids and a Stripe onboarding link. Open the link and finish the test onboarding so the creator can be paid. Keep the `campaign_id`.

### 6. Fund the campaign

Start the payments API with the environment loaded:

```bash
set -a; source .env; set +a; uvicorn app.main:app --port 8001
```

Then, in a second terminal with the same environment loaded (`set -a; source .env; set +a`), credit the budget with the sandbox route:

```bash
curl -X POST "http://localhost:8001/campaigns/<campaign_id>/dev-credit" \
  -H "X-Agent-Key: $AGENT_API_KEY" -H "Content-Type: application/json" \
  -d '{"amount_cents": 1500}'
```

Real funding goes through `POST /campaigns/{id}/fund`, which returns a Stripe Checkout URL; see [Link Agent Wallet](#link-agent-wallet).

### 7. Detector environment

```bash
cp backend/.env.example backend/.env
```

Set `GEMINI_API_KEY` and `SUPARADE_CAMPAIGN_ID`. Leave `SUPARADE_API_URL=http://localhost:8001`. The agent key is read from the root `.env`, so it lives in one place.

### 8. Run everything

```bash
./scripts/run_e2e.sh
```

The script checks the environment, installs packages, frees ports 8000, 8001 and 5173, starts the three services, adds $15.00 of dev credit if the budget is under $10.00, sends a $0.50 test tip, opens the dashboard and starts the demo stream. Logs go to `backend/logs/`. Press Ctrl+C to stop everything.

To watch something else, pass a file path or a live URL:

```bash
./scripts/run_e2e.sh https://www.twitch.tv/<channel>
```

To run the services by hand instead, use three terminals:

```bash
set -a; source .env; set +a; uvicorn app.main:app --port 8001
```

```bash
uvicorn backend.main:app --port 8000
```

```bash
cd frontend && npm install && npm run dev
```

### 9. What you should see

1. `python -m backend.payments demo-streamer` sends one $0.50 tip and prints the Stripe transfer. This checks the money path without Gemini.
2. In the dashboard, keep the streamer id `demo-streamer`, tick **Demo mode** and add the demo stream, a live URL or your webcam.
3. A flag goes `verifying`, then `paying via Stripe`, then `paid $X via Stripe` with the `tr_...` id. The header shows the campaign budget left.
4. In Supabase, the tip is in `tips` with status `paid`, the debit is in `wallet_ledger`, and the moment is in `detections`.
5. In the Stripe Dashboard, the transfer's description carries the agent's reason.

Each clip with enough sponsor screen time also pays a small bonus, so keep the campaign funded during long runs.

## Environment variables

### Payments API (`.env` at the repo root)

| Variable | Required | Default | Purpose |
| --- | --- | --- | --- |
| `SUPABASE_URL` | Yes | | Project URL |
| `SUPABASE_SERVICE_ROLE_KEY` | Yes | | Bypasses row level security. Server side only |
| `STRIPE_SECRET_KEY` | Yes | | Test key (`sk_test_...`) |
| `STRIPE_WEBHOOK_SECRET` | For funding | | `whsec_...`, verifies webhook signatures |
| `AGENT_API_KEY` | Yes | | Shared secret sent in `X-Agent-Key` |
| `FRONTEND_URL` | No | `http://localhost:3000` | Return URL for onboarding and checkout, and an allowed CORS origin |
| `ALLOW_DEV_FUNDING` | No | `0` | Enables the dev credit route. Keep off outside demos |
| `ALLOW_LIVE_MODE` | No | `0` | Allows live Stripe keys. Leave off |
| `CREATOR_COUNTRY` | No | `US` | Country for creator payout accounts |

### Detector (`backend/.env`)

| Variable | Default | Purpose |
| --- | --- | --- |
| `GEMINI_API_KEY` | | Required |
| `GEMINI_MODEL` | `gemini-flash-latest` | Analyses every clip |
| `GEMINI_VERIFY_MODEL` | `gemini-pro-latest` | Verifies candidates |
| `VERIFY_ENABLED` | `true` | Turn the second pass off for testing |
| `GEMINI_TEXT_MODEL` | `gemini-flash-latest` | Writes the thank-you line |
| `GEMINI_TTS_MODEL` | `gemini-3.8-flash-tts` | Speaks it |
| `TTS_VOICE` | `Puck` | Voice for the alert |
| `GEMINI_IMAGE_MODEL` | `gemini-3.1-flash-image` | Generates the thank-you card |
| `ALERT_CARDS` | `true` | Generate cards in demo mode |
| `GEMINI_MAX_RETRIES` | `4` | Retries on 429 and 5xx |
| `CHUNK_SECONDS` | `10` | Clip length |
| `MAX_BACKLOG` | `3` | Clips queued before the oldest are skipped |
| `CONFIDENCE_THRESHOLD` | `0.6` | Minimum confidence, for detection and verification |
| `COOLDOWN_SECONDS` | `30` | Minimum stream time between tips |
| `REPEAT_LIMIT` | `3` | Tips per category and brand per window |
| `REPEAT_WINDOW_SECONDS` | `600` | That window |
| `SPONSOR_BRAND` | `Gatorade` | The brand paying for tips |
| `COMPETITOR_BRANDS` | Ten drink brands | Never tipped |
| `ALLOWED_SUBJECT_TYPES` | `real_person` | Who can earn tips |
| `SAFETY_BLOCKS_TIPS` | `true` | Safety flags block a clip's tips |
| `EXPOSURE_CENTS_PER_SECOND` | `5` | Screen-time bonus rate |
| `MIN_EXPOSURE_SECONDS` | `2` | Weighted seconds needed for a bonus |
| `BOXES_ENABLED` | `true` | Bounding boxes on evidence thumbnails |
| `TWITCH_CHAT` | `true` | Read Twitch chat anonymously |
| `CHAT_CONTEXT_SECONDS` | `5` | Chat included before a moment |
| `CHAT_REACTION_SECONDS` | `12` | Chat included after a moment |
| `SUPARADE_API_URL` | `http://localhost:8001` in the example | Payments API. Empty simulates tips |
| `SUPARADE_CAMPAIGN_ID` | | Campaign whose budget pays the tips |
| `SUPARADE_AGENT_KEY` | Falls back to root `AGENT_API_KEY` | Agent key |
| `PAYMENTS_TIMEOUT_SECONDS` | `30` | Per call |
| `PAYMENTS_MAX_ATTEMPTS` | `3` | Retries on network errors and 5xx |
| `EVENT_WEBHOOK_URL` | | Optional extra webhook for every paid tip |
| `CORS_ORIGINS` | `http://localhost:5173` | Allowed dashboard origins |
| `DETECTOR_KEY` | Empty: every endpoint open | Key required in `X-Detector-Key` to start, feed or stop sessions. The Compute deploy generates one |

Tip amounts per category and the reaction multipliers are constants in `backend/config.py`. See [AGENT_DECISIONS.md](AGENT_DECISIONS.md).

## Tests

```bash
pytest
```

```bash
python -m unittest discover -s backend/tests -t .
```

```bash
node --test supabase/compute/overlay/overlay.test.mjs frontend/detectorProxy.test.js
```

`pytest` runs the payments API and MCP server tests in `tests/` and the detector tests in `backend/tests/`: 55 in total. The second command runs the detector's 25 on their own, and the third the overlay's 9 and the dashboard proxy's 4. They use fakes for Supabase, Stripe and Gemini, so they need no keys.

| File | Covers |
| --- | --- |
| `tests/test_smoke.py` | Health check, auth on agent and user routes, tip validation, unsigned webhooks rejected |
| `tests/test_stream_events.py` | The stream event path: paying once, capping, unknown streamer or campaign, webcam sessions, zero amounts, the reason on the transfer |
| `backend/tests/test_tip_policy.py` | Every block rule, cooldown and repetition |
| `backend/tests/test_payments.py` | The payments client: retries on server errors and pending transfers, refusals not retried, simulated mode |
| `backend/tests/test_pay_flow.py` | The session's pay step: a paid tip, a failed payment releasing its slot, capping before paying |
| `backend/tests/test_detector_key.py` | `X-Detector-Key` on the session endpoints, and local files limited to `backend/demo/` |
| `tests/test_compute_mcp.py` | The MCP server's helpers: key handling, input checks, and how campaigns, sightings and tips are shaped |
| `supabase/compute/overlay/overlay.test.mjs` | The overlay: which Realtime changes become alerts, amounts, config and page rendering |
| `frontend/detectorProxy.test.js` | The dashboard's proxy to the Compute detector: target paths, `wss`, and where the detector key comes from and goes |

To test Gemini alone on a clip:

```bash
python -m backend.gemini_analyzer path/to/clip.mp4
```

## Deploying the payments API to Vercel

`api/index.py` exposes the FastAPI app, and `vercel.json` routes every path to it. `.vercelignore` keeps the detector, dashboard, tests, scripts and migrations out of the deployment.

1. Import the repository in Vercel.
2. Add the root `.env` variables in the project's settings.
3. Deploy, then set the detector's `SUPARADE_API_URL` to the Vercel URL.
4. For funding, add a Stripe webhook endpoint at `<vercel url>/webhooks/stripe` for `checkout.session.completed` and put its signing secret in `STRIPE_WEBHOOK_SECRET`.

The detector does not go to Vercel: it needs ffmpeg and long-running workers. It runs on Supabase Compute, below.

## Deploying the detector to Supabase Compute

The detector runs as a Supabase Compute service in the `hackathon-2026` project: https://pvoesovsparqqzosgwki.supabase.co/compute/v1/detector. Compute is in private alpha, so the project needs access, and the CLI needs version 2.119 or later.

`[compute.detector]` in `supabase/config.toml` holds the setup: built from `backend/Dockerfile` with `backend/` as the build context, 4 GB and 2 vCPU, a public URL, and one instance, because sessions live in memory. Don't run `supabase config push` against that file: it only sets up Compute, so every other setting would be pushed as its default. Deploy services by name. A bare `supabase compute push` deploys every service in the file, and the detector's build needs the `backend/.env.compute` that the script writes.

1. Log the CLI in with `supabase login`.
2. Set `SUPARADE_API_URL` to the payments API's `https://` URL. The container cannot reach localhost, so without an `https://` URL the deployed detector simulates tips.
3. Run `./scripts/deploy_detector.sh`.

The script writes `backend/.env.compute` (gitignored) with only the detector's values: the Gemini key, the campaign id, the agent key, `CORS_ORIGINS` and `SUPARADE_API_URL`. That file is shipped in the build and becomes the container's `backend/.env`, because our access token cannot set project secrets. The script also generates `DETECTOR_KEY` on the first run and keeps it in that file. It then runs `supabase compute deploy detector`.

Check the deploy:

```bash
curl https://pvoesovsparqqzosgwki.supabase.co/compute/v1/detector/api/health
```

```bash
SUPABASE_EXPERIMENTAL_COMPUTE=1 supabase compute status detector --project-ref pvoesovsparqqzosgwki
```

```bash
SUPABASE_EXPERIMENTAL_COMPUTE=1 supabase compute logs detector --project-ref pvoesovsparqqzosgwki
```

Calls that start, feed or stop a session need the `X-Detector-Key` header with the value from `backend/.env.compute`. Local video files must be in `backend/demo/`. Any other path is refused, because `/api/sessions/{id}/media` serves a session's file.

### The dashboard against the detector on Compute

```bash
cd frontend && npm run dev:compute
```

This opens the dashboard at http://localhost:5174. `vite.compute.config.js` proxies `/api`, `/evidence` and `/ws` to `https://pvoesovsparqqzosgwki.supabase.co/compute/v1/detector`; set `DETECTOR_URL` to use another one. The local dashboard on port 5173, which `run_e2e.sh` uses, is unchanged.

Watching works without a key. To start, feed or stop a stream, the dev server adds `X-Detector-Key` to `/api` requests, so the key never reaches the browser. It takes the key from `DETECTOR_KEY` in the environment, or from `backend/.env.compute`. That file only exists on the machine that last ran `scripts/deploy_detector.sh`. Without it, those buttons get a 401 and the dev server says so when it starts.

## Deploying the MCP server and the overlay to Supabase Compute

Both are declared in `supabase/config.toml` and need no secrets: Compute passes each service the project URL, a service key and a browser-safe key, the same defaults Edge Functions get. Deploy them by name:

```bash
npx -y supabase@latest compute deploy mcp overlay --project-ref pvoesovsparqqzosgwki
```

Check them. Each `/health` reports whether the keys arrived, never their values:

```bash
curl https://pvoesovsparqqzosgwki.supabase.co/compute/v1/mcp/health
```

```bash
curl https://pvoesovsparqqzosgwki.supabase.co/compute/v1/overlay/health
```

The MCP endpoint is `https://pvoesovsparqqzosgwki.supabase.co/compute/v1/mcp/mcp`. Every request needs `X-Agent-Key`, which the server checks with the payments API, so the service stores no key. `watch_stream` and `stop_watching` also need `X-Detector-Key`, which is passed through to the detector. Its tools are `list_campaigns`, `brand_sightings`, `tips`, `scout_status`, `watch_stream` and `stop_watching`.

The overlay is `https://pvoesovsparqqzosgwki.supabase.co/compute/v1/overlay?campaign=<campaign id>`. Add it to OBS as a browser source. `&brand=` changes the sponsor name, `&test` shows a sample alert and `&debug` shows the Realtime connection.

## Stripe webhook, locally

```bash
stripe listen --forward-to localhost:8001/webhooks/stripe
```

Put the printed `whsec_...` in `.env`. The only event needed is `checkout.session.completed`. Creator payout status is read directly from Stripe, so no connected-account events are required.

## Link Agent Wallet

Campaign funding is designed for a brand's agent paying with Stripe's Link Agent Wallet:

1. The brand calls `POST /campaigns/{id}/fund` and receives a Checkout URL.
2. The brand's Link agent creates a spend request for that amount.
3. The brand approves it in the Link app. Approval is required for each spend request and expires after 10 minutes.
4. The agent pays the Checkout, and the webhook credits the campaign ledger.

Notes:

- Hosted use of Link needs an OAuth client approved by Stripe. For a demo, log the brand's own Link account into the CLI: `npm i -g @stripe/link-cli`, then `link-cli auth login`.
- Link agent payments are available to US and Canadian consumers.
- Link has no Python SDK, so a funding agent drives it with `link-cli` or `@stripe/link-sdk`. This backend provides the Checkout and the webhook.
- This path is wired but has not been exercised end to end. The demo uses dev credit.

## Troubleshooting

| Symptom | Cause | Fix |
| --- | --- | --- |
| `unknown_streamer` | No creator has the handle typed in the dashboard | Use `demo-streamer`, or set `creators.handle` |
| `creator_not_payable` | The creator has not finished Stripe onboarding | Finish the onboarding link, then call `POST /creators/{id}/refresh-status` |
| `insufficient_budget` | The campaign balance is too low | Add dev credit |
| A tip is `failed` with a balance error from Stripe | The platform has no available test balance | `python -m scripts.stripe_check --add-test-funds 2000` |
| Creator account creation fails with a liability error | Loss liability not accepted | Accept it under Connect, Platform profile |
| `invalid_agent_key` | Detector and payments API disagree on the key | Use one `AGENT_API_KEY` in the root `.env` |
| `dev_funding_disabled` | `ALLOW_DEV_FUNDING` is off | Set it to `1` and restart the payments API |
| "Live Stripe key detected" | A live key is configured | Use a test key |
| Tips show as `simulated` | `SUPARADE_API_URL`, the campaign id or the agent key is missing | Set all three |
| Clips are reported `skipped` | Analysis is slower than the stream | Expected under load; raise `MAX_BACKLOG` or `CHUNK_SECONDS` |
| No speech is analysed for a screen share | Tab audio was not shared | Tick "share tab audio" when sharing |
| The detector cannot open a stream | ffmpeg or streamlink is missing, or the channel is offline | Install ffmpeg; check the URL is live |
| `invalid_detector_key` | The detector has a `DETECTOR_KEY` and the call did not send it | Send `X-Detector-Key`; the deployed value is in `backend/.env.compute` |
| `local files must be in backend/demo/` | A session was started with a file outside `backend/demo/` | Move the video into `backend/demo/` |
| The Compute deploy or `supabase projects list` says Unauthorized | An old `SUPABASE_ACCESS_TOKEN` in the shell overrides `supabase login`. `supabase login` then saves that old token again instead of opening the browser | `unset SUPABASE_ACCESS_TOKEN`, run `supabase login`, and replace the token wherever your shell sets it |

Restarting the detector stops the streams it was watching, because sessions are held in memory. Paid tips are safe in Supabase.
