# Suparade: hackathon submission

**Supabase Select Hackathon, October 3, 2026. Prompt: "build something agents want."**

Suparade lets a brand's AI agent pay live streamers for product placement as it happens. It is both our team name and our product name.

## The idea in one paragraph

In film, product placement is an established business: a laptop appears in a scene because the brand paid the producer. Live streaming on Twitch, YouTube and TikTok has no equivalent that works moment by moment and at small scale. Suparade is that equivalent. A brand such as Gatorade funds a campaign. An agent watches live streams, and when a streamer drinks a Gatorade or says something good about it, the agent sends that streamer a tip within moments, with a message that appears on screen.

## Why it works for each side

- **Brands** pay only when the product is actually seen or praised, so spend maps directly to exposure. Every payment comes with evidence.
- **Creators** are paid for moments they were already making, which gives every streamer a reason to keep the brand in frame.
- **Viewers** see the tip and its message on the stream, a second brand moment on top of the placement.

## How it answers the prompt

The prompt asks for something an agent wants. We treated the agent as the customer and asked what a brand's marketing agent cannot do today. Two things:

1. **It cannot see live video.** Suparade gives it brand sightings: a structured record of what happened, the exact words, how sure the model is, when it happened, and a clip to prove it.
2. **It cannot pay a creator safely.** Suparade gives it a payment tool where the limits are enforced by the database, not by the agent's good behaviour: a campaign budget, a per-tip cap, one tip per moment, and transfers that cannot be sent twice.

The guidance for the event asked each team to name the agent, its task and the observable benefit:

| | |
| --- | --- |
| **The agent** | A brand's tipping agent |
| **Its task** | Reward product placement as it happens |
| **The observable benefit** | A tip lands for the creator moments after the brand appears, with a transfer id and evidence a human can check |

The dashboard is the human side. A person starts a session, then watches every decision the agent makes, including the moments it refused to pay and why.

## How we used each technology

### Supabase

- **Postgres as the system of record** for brands, campaigns, creators, videos, detections, tips and the wallet ledger.
- **Money rules inside the database.** `reserve_tip` locks the campaign row, checks the budget, enforces the cap and the one-tip-per-detection rule, and writes the tip and the ledger debit in one transaction. Two concurrent tips cannot overspend a campaign.
- **An append-only ledger.** The balance is the sum of ledger rows, and each row has a unique reference, so every credit, debit and refund is written once.
- **Row level security** on every table: brand owners see only their own data, and paid tips are public so an overlay can show them.
- **Auth** to verify dashboard users before funding or onboarding.
- **Realtime.** The `tips` table is published so an overlay receives a tip the moment it is paid.

### Gemini

- **Multimodal analysis of every clip.** Video and audio together, so a silent sip and a spoken "this Gatorade hits" are both caught. The response is a typed JSON schema.
- **A second model as auditor.** Candidates are re-checked by Gemini Pro with a sceptical prompt before anything is paid.
- **Audience reaction.** The verifier reads the live chat around the moment and rates how viewers reacted; a strong reaction raises the tip.
- **Context across clips.** Each clip receives the previous clip's summary, so one long sip is not counted twice.
- **Bounding boxes** around the product on each evidence thumbnail.
- **Generated output.** In demo mode Gemini writes the thank-you line, speaks it with text to speech, and generates a thank-you card from the evidence frame. The demo stream itself was generated with Veo.

### Stripe

- **Connect** pays creators. Each creator is a connected account (Accounts v2, Express dashboard) and each tip is a transfer with an idempotency key.
- **The agent's reason travels with the money.** Every transfer's description and metadata carry what the agent saw and why it paid.
- **Checkout and a webhook** fund campaign budgets, designed to be paid by a Link Agent Wallet spend request.
- **Test mode only.** Live keys are refused unless explicitly allowed.

### Vercel

- Hosts the payments API as a Python function. The detector needs ffmpeg and long-running workers, so it runs beside it on a laptop or VM.

## Why you can trust this agent with money

| Risk | What stops it |
| --- | --- |
| The model imagines a moment | A second, stricter model must confirm it from the clip itself |
| Sarcasm or criticism gets paid | Spoken mentions must be positive |
| A rival brand gets paid | Competitor brands are blocked |
| Cartoons, ads or replays get paid | Only a real person on a live stream can earn a tip |
| A creator farms tips by repeating the brand | Staged moments are blocked; a cooldown and a repeat limit cap frequency |
| The brand appears next to unsafe content | Alcohol, vaping, NSFW content, slurs and gambling block a clip's tips |
| The agent overspends | Budget and cap are checked in the database under a row lock |
| A retry pays twice | Idempotency at every layer, from the event id to the Stripe transfer |
| Nobody can tell why money moved | Every paid event keeps the clip, a thumbnail, the quote, the verifier's reason and the transfer id |

The full rules are in [AGENT_DECISIONS.md](AGENT_DECISIONS.md).

## Demo walkthrough

`./scripts/run_e2e.sh` runs the whole thing. In about two minutes you see:

1. **The money path proved first.** A $0.50 test tip goes to the demo creator, and the script prints the Stripe transfer.
2. **The stream.** The dashboard opens and the demo stream plays, with a scripted chat alongside.
3. **A detection.** The streamer praises and drinks the product. A flag appears with the quote and confidence, marked `verifying`.
4. **The verdict.** The verifier confirms it and rates the chat reaction as high, which multiplies the tip by 1.5.
5. **The payment.** The flag moves to `paying via Stripe`, then `paid` with the transfer id. The campaign budget in the header drops.
6. **The evidence.** A thumbnail appears with a bounding box around the bottle.
7. **The alert.** A spoken thank-you plays and a generated card appears.
8. **A refusal.** Add `backend/demo/test_media/testcard_gatorade_voice.mp4`: the brand is named, the moment is flagged, and the verifier rejects it because no real person is on screen. Nothing is paid.

Afterwards the tip is in Supabase (`tips`, `wallet_ledger`, `detections`) and the transfer is in the Stripe Dashboard with the agent's reason in its description.

## What is real and what is not

We would rather be exact than impressive. "Working" below means the code path is implemented and is what `scripts/run_e2e.sh` exercises against Gemini, Supabase and the Stripe sandbox; the unit tests cover the tip policy, the payments client and the stream event path.

| | Status |
| --- | --- |
| Gemini detection, policy, verification and chat reaction | Working |
| Real Stripe test-mode transfers to an onboarded creator | Working |
| Budget, cap and idempotency enforced in Supabase | Working, with unit tests |
| Twitch and YouTube live URLs, webcam and screen share | Working |
| Evidence, bounding boxes, spoken alert and card | Working |
| Funding through Link Agent Wallet | Wired (Checkout and webhook), not yet run end to end. The demo credits the budget with a sandbox-only route |
| Fully autonomous spending | Tipping is autonomous within the funded budget. Funding through Link needs a human approval per spend request |
| The alert on the creator's real stream | Shown in our dashboard. Putting it inside a Twitch or YouTube broadcast is a separate integration |
| Real money | None. Test mode only |
| The detector on serverless | No. It runs on a laptop or VM |
| Many campaigns at once | One campaign per detector process |

## What we would build next

- **Many brands, many scouts.** A campaign per brand, with one scout per stream and an orchestrator allocating budget across them.
- **Stream discovery.** An agent that finds streams where the brand already appears or would fit.
- **Beyond drinks.** The detection schema is beverage-specific today. The schema already has a second campaign type, `cool_moment`, for tipping highly clippable moments so the brand travels with the clip.
- **Creator onboarding and overlays.** A browser source streamers add to their broadcast, fed by Supabase Realtime.
- **Disclosure and consent.** Paid placement needs sponsorship disclosure, and creators should opt in to being watched and paid. Both belong in the product before real money does.
- **Link funding end to end**, and tips over a threshold routed to a human for approval.

## Team

- Greg
- Thomas
- Pedro
- Matthew

## Where to look in the code

| If you want to see | Open |
| --- | --- |
| The Gemini prompt and schema | `backend/gemini_analyzer.py`, `backend/models.py` |
| The rules that block a tip | `backend/tip_policy.py` |
| The auditor prompt | `backend/verifier.py` |
| The pipeline for one clip | `backend/session_manager.py` |
| The money function | `reserve_tip` in `supabase/migrations/20261003000000_init.sql` |
| The Stripe transfer | `settle_tip` in `app/services/tips.py` |
| The one call that ties it together | `handle_stream_event` in `app/services/stream_events.py` |
