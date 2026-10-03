# How Suparade uses Gemini

Gemini is the agent's eyes, ears and voice. Every decision to pay a creator starts with Gemini watching and listening to the stream, and every payment is confirmed by a second Gemini pass. This page maps each Gemini call to the code, with the modalities going in and out.

All calls use the official `google-genai` SDK ([backend/requirements.txt](../backend/requirements.txt)) through one shared client ([backend/gemini_analyzer.py:102](../backend/gemini_analyzer.py#L102)).

## At a glance

| Step | Input to Gemini | Output from Gemini | Model (default) | Code |
| --- | --- | --- | --- | --- |
| 1. Clip analysis | **Video + audio** (10 s mp4 or webm, inline) + live chat text + previous clip summary | Structured JSON (`ClipAnalysis`) | `gemini-flash-latest` | [gemini_analyzer.py:147](../backend/gemini_analyzer.py#L147) |
| 2. Verification and audience reaction | **Video + audio** of the same clip + the claimed moment + chat around it | Structured JSON (`Verification`) | `gemini-pro-latest` | [verifier.py:38](../backend/verifier.py#L38) |
| 3. Product bounding boxes | **Image** (evidence thumbnail) | Structured JSON (`BoxList`, `box_2d` coordinates) | `gemini-flash-latest` | [evidence.py:66](../backend/evidence.py#L66) |
| 4. Thank-you line | Text (what happened, quote, chat reaction) | Text | `gemini-flash-latest` | [alerts.py:35](../backend/alerts.py#L35) |
| 5. Spoken alert | Text | **Audio** (TTS, WAV) | `gemini-3.8-flash-tts` | [alerts.py:65](../backend/alerts.py#L65) |
| 6. Thank-you card | **Image** (evidence thumbnail) + text prompt | **Image** | `gemini-3.1-flash-image` | [alerts.py:81](../backend/alerts.py#L81) |

Gemini sees video, audio, images and text, and produces JSON, text, speech and images. Models are set in [backend/config.py](../backend/config.py) (`GEMINI_MODEL`, `GEMINI_VERIFY_MODEL`, `GEMINI_TEXT_MODEL`, `GEMINI_TTS_MODEL`, `GEMINI_IMAGE_MODEL`). Steps 4 to 6 run in demo mode.

## 1. Watching and listening to every clip

The stream is cut into 10 second clips. Twitch, YouTube and local files go through ffmpeg ([sources/url_source.py](../backend/sources/url_source.py)); webcam and screen share are recorded in the browser with `MediaRecorder` ([frontend/src/browserCapture.js](../frontend/src/browserCapture.js), [sources/browser_source.py](../backend/sources/browser_source.py)). Each clip is sent to Gemini as raw bytes, with no frame sampling or transcription step of our own:

```python
# backend/gemini_analyzer.py
contents = [
    types.Part.from_bytes(data=data, mime_type=mime_type),   # the clip: video + audio
    f"{context}Analyze this livestream clip.",                # previous summary + live chat
]
return await generate_json(config.GEMINI_MODEL, system, contents, ClipAnalysis)
```

Because Gemini gets the audio track as well as the pictures, one call catches both:

- **visual moments**: a silent sip, a can held up to the camera, a logo on the desk;
- **spoken moments**: "this Gatorade hits different", with the exact words returned as `quote`.

The response is forced into a Pydantic schema with `response_mime_type="application/json"` and `response_schema` ([gemini_analyzer.py:117](../backend/gemini_analyzer.py#L117)), so the agent gets typed fields instead of free text. `ClipAnalysis` ([models.py:86](../backend/models.py#L86)) contains:

| Field | What Gemini judges from the clip |
| --- | --- |
| `moments[]` | Category, offset in seconds, description, quote, brand, confidence |
| `moments[].sentiment` | Positive, neutral, negative or **sarcastic**, read from tone of voice and face |
| `moments[].subject_type` | A real person, an animated character or VTuber, or video playback |
| `moments[].looks_staged` | Whether the moment is performed just to trigger a reward |
| `brand_exposures[]` | Seconds each brand is on screen and how prominent it is |
| `safety` | Alcohol, vaping, NSFW, slurs (heard in the audio) and gambling |
| `looks_prerecorded_or_looped` | Whether the footage looks like a rerun rather than live |
| `clip_summary` | One sentence passed to the next clip, so one long sip is not counted twice |

The live chat posted during the clip is added as text, with timestamps relative to the clip start ([session_manager.py:201](../backend/session_manager.py#L201), [chat.py](../backend/chat.py)).

## 2. A second, sceptical pass before money moves

Moments that pass the tip policy are sent back to a stronger model with the **same video and audio**, the single claimed moment, and the chat from 5 seconds before to 12 seconds after it ([verifier.py:38](../backend/verifier.py#L38), called from [session_manager.py:322](../backend/session_manager.py#L322)). The prompt is an auditor's: confirm only what the clip clearly shows, by a real live person, with the stated sentiment.

In the same call Gemini rates `audience_reaction` (none, low, medium, high) from the chat and quotes up to three `chat_highlights`. A strong reaction raises the tip. Chat alone never confirms a moment; confirmation must come from the clip.

No Stripe transfer is sent unless this pass returns `confirmed: true`.

## 3. Evidence with bounding boxes

For every paid moment, a thumbnail is cut from the clip and sent to Gemini as an image. Gemini returns up to five labelled boxes (`box_2d`, normalised 0 to 1000) around the sponsor's product and any other drink ([evidence.py:66](../backend/evidence.py#L66), called from [session_manager.py:392](../backend/session_manager.py#L392)). The dashboard draws them over the thumbnail, so a brand can see exactly what it paid for.

## 4 to 6. Generated thank-you alert

In demo mode Gemini closes the loop on stream ([alerts.py](../backend/alerts.py), called from [session_manager.py:400](../backend/session_manager.py#L400)):

- **Text**: writes a one-line alert from what happened, the quote and the chat reaction.
- **Speech**: reads the line aloud with Gemini TTS (`response_modalities=["AUDIO"]`, prebuilt voice `Puck`).
- **Image**: turns the evidence frame into a branded thank-you card (`response_modalities=["IMAGE"]`).

The demo stream itself was generated with Veo.

## Reliability

- One helper, `generate_json` ([gemini_analyzer.py:117](../backend/gemini_analyzer.py#L117)), handles every structured call: schema, low temperature (0.2), and retries on 429 and 5xx with exponential backoff up to `GEMINI_MAX_RETRIES`.
- A clip that still fails is reported as `error` and the stream keeps going.
- Flash sees every clip; Pro sees only the few candidates that survive the policy. That keeps cost and latency low and puts the stronger model where money is decided.

## Try it

```bash
python -m backend.gemini_analyzer path/to/clip.mp4
```

This sends one clip to Gemini and prints the `ClipAnalysis` JSON. Only `GEMINI_API_KEY` in `backend/.env` is needed.
