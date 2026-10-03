-- Link the Gemini livestream detector (backend/) to the payments schema.
--
-- creators.handle: the "streamer id" typed in the detector dashboard. The detector sends it with
--                  every event and the payments API resolves it to a creator with a Stripe account.
-- detections.category / brand / quote / meta: the detector's richer moment data (beverage category,
--                  spoken quote, verifier reason, chat reaction, ...), kept for the frontend and audits.

alter table public.creators
  add column if not exists handle text;

create unique index if not exists creators_handle_key on public.creators (lower(handle));

alter table public.detections
  add column if not exists category text,
  add column if not exists brand    text,
  add column if not exists quote    text,
  add column if not exists meta     jsonb not null default '{}'::jsonb;
