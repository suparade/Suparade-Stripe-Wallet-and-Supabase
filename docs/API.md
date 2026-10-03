# API reference

Suparade has two HTTP APIs. The **payments API** (`app/`) is what agents call to record moments and pay creators. The **detector API** (`backend/`) is what the dashboard calls to start and watch stream sessions.

## Payments API

Base URL: your Vercel deployment, or `http://localhost:8001` locally. `GET /health` returns `{"ok": true}`.

### Authentication

| Caller | Header | Checked against |
| --- | --- | --- |
| Agents (finder, tipper, the Gemini detector) | `X-Agent-Key: <AGENT_API_KEY>` | A shared secret, compared in constant time |
| Dashboard users | `Authorization: Bearer <Supabase access token>` | Supabase Auth |

A missing or wrong agent key returns `401 invalid_agent_key`. A missing or invalid user token returns `401 missing_bearer_token` or `401 invalid_token`.

### Agent routes

These are the tools a brand's agents use.

| Method and path | Purpose |
| --- | --- |
| `GET /agent/campaigns/{id}/context` | Everything the tipper needs before deciding: brand name, campaign type and status, `brand_context`, `tipper_instructions`, `max_tip_cents`, currency, `balance_cents` and the ten most recent tips |
| `POST /agent/videos` | Register a video URL: `url`, `platform`, `title`, `creator_id`. Upserts on `url` |
| `GET /agent/videos?status=pending&limit=20` | List videos, optionally by status |
| `PATCH /agent/videos/{id}` | Set status: `pending`, `scanning`, `done` or `failed` |
| `POST /agent/detections` | Log a moment: `campaign_id`, `video_id`, `kind`, `timestamp_seconds`, `confidence`, `description`, optional `idempotency_key` |
| `POST /agent/tips` | Pay a detection: `detection_id`, `amount_cents`, `message`, `reasoning`, optional `show_at_seconds` |
| `POST /agent/stream-events` | One call per confirmed moment from the Gemini detector. Logs the moment and pays it |

**`POST /agent/tips`** checks the budget, reserves the tip and sends the Stripe transfer. Calling it again for the same detection returns the same tip, and retries the transfer if it was left pending.

**`POST /agent/stream-events`** does the whole chain in one call:

1. Resolves the streamer by `creators.handle` (case-insensitive) or by creator id.
2. Registers the stream as a video linked to that creator.
3. Logs the detection, idempotent on `event_id`.
4. Caps the amount at the campaign's `max_tip_cents`.
5. Reserves the budget and sends the Stripe transfer.

Request body: the detector's event (see [the event contract](#the-event-contract)) plus `campaign_id`, and optionally `source_url`, `message` and `reasoning`. Unknown fields are accepted and stored in `detections.meta`.

Response (the `tip` object is the full `tips` row; selected fields shown, values illustrative):

```json
{
  "detection_id": "uuid",
  "video_id": "uuid",
  "creator_id": "uuid",
  "requested_cents": 450,
  "amount_cents": 450,
  "capped": false,
  "status": "paid",
  "tip": {
    "id": "uuid",
    "status": "paid",
    "amount_cents": 450,
    "message": "Gatorade tipped $4.50 for: Streamer praises Gatorade",
    "stripe_transfer_id": "tr_..."
  }
}
```

If no `message` is sent, one is built from the brand, the amount and the description. If no `reasoning` is sent, one is built from the category, confidence, the verifier's reason and the chat reaction. A suggested amount of zero returns `status: "skipped_zero_amount"` and no tip.

### Error codes

| Code | HTTP status | Meaning |
| --- | --- | --- |
| `campaign_not_found` | 404 | No campaign with that id |
| `detection_not_found` | 404 | No detection with that id |
| `video_not_found` | 404 | No video with that id |
| `unknown_streamer` | 409 | No creator has that handle |
| `campaign_not_active` | 409 | The campaign is draft, paused or ended |
| `video_has_no_creator` | 409 | The video is not linked to a creator |
| `creator_not_payable` | 409 | The creator has not finished Stripe onboarding |
| `insufficient_budget` | 409 | The campaign balance does not cover the tip |
| `amount_out_of_range` | 422 | The amount is not positive, or exceeds `max_tip_cents` |
| `kind_does_not_match_campaign_type` | 422 | The detection's `kind` differs from the campaign's type |

### User routes

| Method and path | Purpose |
| --- | --- |
| `POST /creators` | Create a creator profile for the signed-in user: `display_name` |
| `POST /creators/{id}/connect` | Returns a Stripe-hosted onboarding URL. Creates the connected account on first call |
| `POST /creators/{id}/refresh-status` | Reads the account from Stripe and syncs `transfers_enabled` |
| `POST /campaigns/{id}/fund` | Returns a Stripe Checkout URL to top up the budget: `amount_cents`, up to 500,000 |

Callers can only act on their own creator profile or their own brand's campaign; otherwise the API returns `403 not_your_creator_profile` or `403 not_your_campaign`.

### Sandbox and webhook routes

| Method and path | Purpose |
| --- | --- |
| `POST /campaigns/{id}/dev-credit` | Credits a campaign without a payment. Needs the agent key and `ALLOW_DEV_FUNDING=1`; otherwise `403 dev_funding_disabled` |
| `POST /webhooks/stripe` | Verifies the Stripe signature. On `checkout.session.completed` with `purpose=campaign_funding` and `payment_status=paid`, credits the campaign once |

## Detector API

Base URL: `http://localhost:8000`. The dashboard's dev server proxies `/api`, `/evidence` and `/ws` to it.

| Method and path | Purpose |
| --- | --- |
| `GET /api/health` | Models in use, clip length, sponsor brand, whether the Gemini key is set and whether payments are enabled |
| `GET /api/payments` | Campaign brand, status, `balance_cents` and `max_tip_cents`, fetched from the payments API. The agent key stays server side |
| `POST /api/sessions` | Start watching a stream |
| `GET /api/sessions` | List active sessions |
| `POST /api/sessions/{id}/chunk` | Upload one clip for a browser session: multipart `file`, optional `duration` |
| `GET /api/sessions/{id}/media` | The local file a demo session is replaying |
| `POST /api/sessions/{id}/chat` | Inject chat: `{user, text}` or `{messages: [{user, text}]}`, up to 50 per call |
| `DELETE /api/sessions/{id}` | Stop a session |
| `GET /api/events` | Recent events |
| `GET /evidence/...` | Saved clips, thumbnails, alert audio and cards |
| `WS /ws/events` | Live feed |

**`POST /api/sessions`** body:

| Field | Type | Meaning |
| --- | --- | --- |
| `source` | `"url"` or `"browser"` | A URL or file the server pulls, or clips the browser uploads |
| `url` | string | Twitch or YouTube live URL, or a local file path. Required for `source: "url"` |
| `streamer_id` | string | Matches `creators.handle`. Defaults to `demo-streamer` |
| `demo_alerts` | boolean | Generate the spoken thank-you alert and card for paid tips |
| `chat_script` | string | Path to a JSON chat script to replay alongside the stream |

### WebSocket messages

Each message is `{"type": ..., "data": ...}`. On connect the server sends the current sessions and their recent chat.

| Type | Sent when | Data |
| --- | --- | --- |
| `session` | A session starts or its totals change | Session summary: clips analysed and skipped, events, sponsor screen time, competitor mentions, safety counts, tips paid |
| `session_stopped` | A session is stopped | `{id}` |
| `chunk` | A clip changes state | `ChunkStatus`: `analyzing`, `nothing_found`, `detected`, `error` or `skipped`, with latency and the clip summary |
| `event` | A moment is reported or its state changes | The full event, plus `tipped: true` when it has been paid |
| `safety` | A clip has a brand-safety flag | The flags, notes and stream offset |
| `chat` | A chat message arrives | `{session_id, user, text, at}` |
| `alert` | A demo thank-you alert is ready | The event with `alert_message`, `alert_audio_url` and, later, `card_url` |

The same event is published several times as it moves through its states. Use `event_id` as the key.

## The event contract

`BeverageEvent` is the shape the detector sends to the payments API, to the dashboard, to `events.jsonl` and to the optional `EVENT_WEBHOOK_URL`. New fields are always optional. The values below are illustrative.

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
  "suggested_tip_cents": 450,
  "sentiment": "positive",
  "subject_type": "real_person",
  "is_sponsor": true,
  "is_competitor": false,
  "status": "tipped",
  "block_reasons": [],
  "verification_reason": "The streamer clearly names and praises the drink on camera.",
  "audience_reaction": "high",
  "reaction_summary": "Chat spams the brand name after the sip.",
  "chat_highlights": ["W Gatorade"],
  "reaction_multiplier": 1.5,
  "thumbnail_url": "/evidence/...",
  "clip_url": "/evidence/...",
  "boxes": [{"label": "Gatorade bottle", "box_2d": [412, 530, 780, 640]}],
  "payment_status": "paid",
  "stripe_transfer_id": "tr_...",
  "tip_id": "uuid",
  "detection_id": "uuid"
}
```

| Field group | Fields |
| --- | --- |
| Identity | `event_id`, `session_id`, `streamer_id`, `detected_at`, `stream_offset_seconds` |
| What happened | `category`, `description`, `quote`, `brand`, `confidence`, `sentiment`, `subject_type`, `is_sponsor`, `is_competitor`, `exposure_seconds` |
| Decision | `status`, `block_reasons`, `verification_reason`, `suggested_tip_cents`, `requested_tip_cents` (set when the campaign cap lowered the amount) |
| Audience | `audience_reaction`, `reaction_summary`, `chat_highlights`, `reaction_multiplier` |
| Evidence | `clip_url`, `thumbnail_url`, `boxes` (`box_2d` is `[ymin, xmin, ymax, xmax]` on a 0 to 1000 scale) |
| Payment | `payment_status` (`paid`, `pending`, `failed`, `simulated`), `payment_error`, `stripe_transfer_id`, `tip_id`, `detection_id` |
| Demo alert | `alert_message`, `alert_audio_url`, `card_url` |

`category` is one of `sports_drink_mention`, `drinking_water`, `drinking_other`, `holding_or_showing_beverage`, `verbal_beverage_mention` or `sponsor_screen_time`.

`status` is one of `blocked`, `pending_verification`, `rejected_by_verifier`, `paying`, `tipped` or `payment_failed`. See [ARCHITECTURE.md](ARCHITECTURE.md#event-states).
