# How the agent decides

A tipping agent is only useful if a brand can trust it with money. This page lists exactly what Suparade looks for, every rule that stops a tip, how a candidate is verified, and how the amount is set. Everything here is in `backend/gemini_analyzer.py`, `backend/tip_policy.py`, `backend/verifier.py`, `backend/session_manager.py` and `backend/config.py`.

The defaults below describe the demo campaign: sponsor **Gatorade**, set with `SPONSOR_BRAND`. All thresholds are environment variables; see [SETUP.md](SETUP.md).

## 1. What Gemini reports for each clip

Every 10 second clip is sent to Gemini (`GEMINI_MODEL`, default `gemini-flash-latest`) with its video, its audio, the previous clip's one-line summary and any chat posted during the clip. The response must match the `ClipAnalysis` schema.

**Moments.** One per beverage-related action:

| Category | Meaning |
| --- | --- |
| `sports_drink_mention` | The streamer names or talks about a sports or energy drink |
| `drinking_water` | The streamer visibly drinks water |
| `drinking_other` | The streamer visibly drinks any other beverage |
| `holding_or_showing_beverage` | The streamer holds, shows or points at a drink without drinking |
| `verbal_beverage_mention` | The streamer talks about drinks, hydration or thirst without naming a sports drink |

Each moment also carries:

| Field | Values |
| --- | --- |
| `sentiment` | `positive`, `neutral`, `negative`, `sarcastic` |
| `subject_type` | `real_person`, `animated_character`, `video_playback` |
| `looks_staged` | True when the moment looks forced or performed only to trigger a reward |
| `brand` | Named only if visible or spoken |
| `quote` | The exact words, when the moment involves speech |
| `offset_seconds` | When the moment starts within the clip |
| `confidence` | 0.0 to 1.0 |

**Brand exposure.** For every beverage brand visible in the clip: seconds visible and a prominence of `high`, `medium` or `low`. A bottle sitting in the background counts as exposure but is not a moment.

**Safety flags.** `alcohol`, `vaping`, `nsfw`, `slurs`, `gambling`, each true only if it clearly appears.

**Liveness.** `looks_prerecorded_or_looped`, and the clip's main `on_screen_subject`.

**Summary.** One sentence, passed to the next clip so a sip or sentence that spans two clips is not reported twice.

Chat is given to the model as context only. A moment must still be visible or audible in the clip itself.

## 2. What blocks a tip

Moments below `CONFIDENCE_THRESHOLD` (0.6) are dropped. Every other moment goes through the tip policy. Any reason below blocks the tip, and the dashboard shows the moment with its reasons.

| Block reason | Rule | Why |
| --- | --- | --- |
| `sentiment:<value>` | Spoken mentions must be `positive`. Visual moments (drinking, holding) must be `positive` or `neutral`. | A brand should not pay for criticism or sarcasm. Silent drinking is naturally neutral, so it is allowed. |
| `competitor_brand` | The moment's brand matches a name in `COMPETITOR_BRANDS`. | Never pay a creator for promoting a rival. |
| `subject:<type>` | The subject is not in `ALLOWED_SUBJECT_TYPES` (default `real_person`). | No tips for cartoons, VTuber models, ads or someone else's video playing on screen. |
| `looks_staged` | Gemini judged the moment forced or performed for a reward. | Stops creators waving a can at the camera for money. |
| `safety:<flag>` | The clip has an active safety flag and `SAFETY_BLOCKS_TIPS` is on. | Keeps the brand away from alcohol, vaping, NSFW content, slurs and gambling. |
| `prerecorded_or_looped` | The footage looks like a rerun or loop. | Tips are for live moments. |
| `repetitive` | The same category and brand has already been tipped `REPEAT_LIMIT` (3) times within `REPEAT_WINDOW_SECONDS` (600) of stream time. | Stops farming by repetition. |
| `cooldown` | Another tip was reserved within `COOLDOWN_SECONDS` (30) of stream time. | One tip per creator per half minute. |

Competitor mentions and safety flags are also counted per session and shown on the stream tile, so the brand sees them even when nothing is paid.

## 3. Verification

A moment that passes the policy becomes a candidate and is shown as `pending_verification`. It reserves its cooldown slot at once, so a later clip cannot be tipped while the check runs.

The verifier (`GEMINI_VERIFY_MODEL`, default `gemini-pro-latest`) receives the same clip, the single claimed moment and the live chat from 5 seconds before to 12 seconds after it. Its instructions are those of an auditor: confirm only if the clip clearly shows exactly what is claimed, by a real live person, with the stated sentiment. It rejects when the evidence is ambiguous, the drink is only in the background, the brand cannot be verified, the praise is sarcastic, or the footage looks like a replay, an ad or an animation.

A tip is paid only if the verifier confirms the moment with confidence at or above the threshold. If the verifier rejects it, or the call fails, nothing is paid, the slot is released and the dashboard shows the verifier's reason.

Chat never confirms a moment. It is used only to score the audience reaction.

## 4. How the amount is set

**Base amount by category** (`TIP_CENTS_BY_CATEGORY`):

| Category | Suggested tip |
| --- | --- |
| `sports_drink_mention` | $3.00 |
| `drinking_water` | $1.00 |
| `drinking_other` | $1.00 |
| `holding_or_showing_beverage` | $0.50 |
| `verbal_beverage_mention` | $0.50 |

**Audience reaction multiplier.** The verifier rates how chat reacted to this specific moment. Generic chatter does not count.

| Reaction | Meaning | Multiplier |
| --- | --- | --- |
| `none` | No chat, or nobody reacts | 1.0 |
| `low` | Chat is active but barely notices | 1.0 |
| `medium` | A few viewers clearly react | 1.25 |
| `high` | Many viewers react to the drink or brand | 1.5 |

**Campaign cap.** The payments API caps every tip at the campaign's `max_tip_cents` (default 500, which is $5.00). The dashboard shows both the requested and the paid amount when a tip is capped.

**Budget.** The tip is reserved only if the campaign's ledger balance covers it. Otherwise the payment is refused with `insufficient_budget`.

Example: a streamer praises Gatorade by name and chat floods with reactions. The base is $3.00, the `high` reaction multiplies it by 1.5 to $4.50, which is under the $5.00 cap, so $4.50 is transferred.

## 5. Sponsor screen-time bonus

Separately from moments, each clip earns a small bonus when the sponsor's product is clearly on screen.

- Seconds visible are weighted by prominence: `high` counts fully, `medium` counts half, `low` counts nothing.
- If the weighted total in a clip is at least `MIN_EXPOSURE_SECONDS` (2), the clip earns `EXPOSURE_CENTS_PER_SECOND` (5 cents) per weighted second, so at most 50 cents per 10 second clip.
- Safety flags, looped footage and a subject that is not a real person block the bonus.
- The bonus is paid without the verifier, as a `sponsor_screen_time` event.

Exposure totals for every brand, sponsor and competitors alike, are kept per session. The stream tile shows the sponsor's total time on screen.

## 6. Evidence

Every paid event keeps:

- the analysed clip and a thumbnail taken at the moment, served by the detector under `/evidence`;
- bounding boxes around the product on the thumbnail, drawn by Gemini;
- the quote, the verifier's reason, the chat reaction summary and up to three chat highlights;
- the Stripe transfer id, and on the Stripe side a transfer description that carries the agent's reason.

The full event is stored in `detections.meta` in Supabase, so every payment can be audited afterwards.

## 7. Test streams

`backend/demo/test_streams.json` lists streams with their expected outcome:

| Stream | Expected result |
| --- | --- |
| Demo stream (`backend/demo/demo_stream.mp4`, generated with Veo) | The streamer praises and drinks a Gatorade: verified tip, high chat reaction, bounding box, spoken thank-you alert and card |
| Streamer with no drink | Negative control: nothing flagged |
| Test card with a Gatorade voiceover | The mention is flagged, then rejected by the verifier because no real person is on screen |
| The same test card over several clips | Previous-clip context, chat reaction scored, verifier rejection |
| An animated lo-fi stream | Flagged but blocked as animated and looped |
| A live streamer with busy chat | Occasional real drinking moments get tipped |

The tip policy rules are covered by unit tests in `backend/tests/test_tip_policy.py`.
