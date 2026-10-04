# Livestream Beverage Moment Detector

Watches a livestream with Gemini video understanding and flags every moment a
streamer mentions a sports drink, drinks water, or does anything beverage
related, so the brand can tip them. Confirmed tips are paid for real through
the payments API in this repo (`app/`, Supabase + Stripe); see the root README
for the end to end setup.

```
Twitch/YouTube URL -> streamlink -> ffmpeg (10s mp4 clips) ┐
Webcam / screen-share -> MediaRecorder (10s webm clips)    ┴-> Gemini (video+audio, JSON schema)
   -> threshold + cooldown -> verifier -> payments API (Supabase ledger + Stripe transfer)
   -> WebSocket dashboard + events.jsonl + EVENT_WEBHOOK_URL
```

Each clip is sent to Gemini with both video and audio, so it catches visual
moments (sipping, showing a bottle) and spoken ones ("this Gatorade hits").
Latency is roughly one clip length plus 2-5s of model time.

## Run

```bash
# backend (from repo root)
python3 -m venv .venv
.venv/bin/pip install -r backend/requirements.txt   # includes streamlink; ffmpeg must be installed (brew install ffmpeg)
cp backend/.env.example backend/.env                # then set GEMINI_API_KEY
.venv/bin/uvicorn backend.main:app --port 8000

# frontend
cd frontend && npm install && npm run dev            # http://localhost:5173
```

In the dashboard, either paste a Twitch / YouTube live URL, or click **Webcam**
or **Screen-share a tab** (tick "share tab audio" so speech is analyzed). A
video in `backend/demo/` also works in the URL box and is replayed in real
time, which is handy for demos. Other local paths are refused, because
`/api/sessions/{id}/media` serves the session's file.

## Deploy (Supabase Compute)

The detector runs on Supabase Compute, built from `backend/Dockerfile` as
`[compute.detector]` in `supabase/config.toml`. Deploy with
`./scripts/deploy_detector.sh`. It writes `backend/.env.compute` with the
detector's own values and a generated `DETECTOR_KEY`. See
[docs/SETUP.md](../docs/SETUP.md#deploying-the-detector-to-supabase-compute).

Test the model alone on a clip:

```bash
.venv/bin/python -m backend.gemini_analyzer path/to/clip.mp4
```

## Payments (Supabase + Stripe)

Set `SUPARADE_API_URL` and `SUPARADE_CAMPAIGN_ID` in `backend/.env` (the agent
key is read from the root `.env`). Every confirmed tip is sent to
`POST {SUPARADE_API_URL}/agent/stream-events`, which maps `streamer_id` to a
creator (`creators.handle`), logs the moment, checks the campaign budget, caps
the amount at the campaign's `max_tip_cents`, and sends a Stripe transfer. In
the dashboard the event goes `paying` -> `tipped` (with the Stripe transfer id)
or `payment_failed` (with the reason, for example `insufficient_budget` or
`unknown_streamer`). Without `SUPARADE_API_URL`, tips are simulated.

Quick check without Gemini: `.venv/bin/python -m backend.payments demo-streamer`
sends one $0.50 test tip.

## Handoff contract

Paid tips are also POSTed to `EVENT_WEBHOOK_URL` if set, and appended to
`backend/events.jsonl`, as JSON:

```json
{
  "event_id": "uuid",
  "session_id": "3f6baba05dba",
  "streamer_id": "demo-streamer",
  "category": "sports_drink_mention",
  "confidence": 0.95,
  "description": "Streamer mentions grabbing their Gatorade.",
  "quote": "let me grab my Gatorade real quick",
  "brand": "Gatorade",
  "stream_offset_seconds": 13.3,
  "detected_at": "2026-10-03T18:44:55.155750+00:00",
  "suggested_tip_cents": 300
}
```

Paid events also carry `payment_status`, `stripe_transfer_id`, `tip_id` and
`detection_id`.

`category` is one of `sports_drink_mention`, `drinking_water`, `drinking_other`,
`holding_or_showing_beverage`, `verbal_beverage_mention`. `streamer_id` is
whatever is typed in the dashboard when the session starts.

Only one tip-worthy event per streamer is emitted every `COOLDOWN_SECONDS` of
stream time; detections inside the cooldown still show on the dashboard but
are not sent to the webhook.

## API

| Method | Path | Purpose |
| --- | --- | --- |
| POST | `/api/sessions` | `{source: "url" \| "browser", url?, streamer_id}` |
| POST | `/api/sessions/{id}/chunk` | multipart `file` (+ `duration`) for browser sessions |
| DELETE | `/api/sessions/{id}` | stop a session |
| GET | `/api/events` | recent detections |
| GET | `/api/payments` | campaign budget left and payout status (from the payments API) |
| WS | `/ws/events` | live `event` / `chunk` / `session` messages |

With `DETECTOR_KEY` set (the Compute deploy sets it), the POST and DELETE
session routes need the `X-Detector-Key` header.

## Config (`backend/.env`)

`GEMINI_MODEL` (default `gemini-flash-latest`), `CHUNK_SECONDS` (10),
`CONFIDENCE_THRESHOLD` (0.6), `COOLDOWN_SECONDS` (30), `SUPARADE_API_URL`,
`SUPARADE_CAMPAIGN_ID`, `SUPARADE_AGENT_KEY`, `EVENT_WEBHOOK_URL`, `DETECTOR_KEY`.
Tip amounts per category are in `backend/config.py`.

Never commit `backend/.env`. The hackathon account revokes leaked keys.
