-- Suparade backend schema
-- Flow: brand funds campaign (Link -> Stripe Checkout) -> finder agent logs videos and detections
--       -> tipper agent reserves a tip (budget checked atomically) -> Stripe transfer to creator
--       -> tip row flips to paid -> Supabase Realtime pushes it to the on screen pop up.

create extension if not exists "pgcrypto";

-- ---------------------------------------------------------------------------
-- Tables
-- ---------------------------------------------------------------------------

create table public.brands (
  id          uuid primary key default gen_random_uuid(),
  owner_id    uuid references auth.users (id) on delete set null,  -- nullable so the demo seed works without auth
  name        text not null,
  created_at  timestamptz not null default now()
);

create table public.campaigns (
  id                   uuid primary key default gen_random_uuid(),
  brand_id             uuid not null references public.brands (id) on delete cascade,
  name                 text not null,
  type                 text not null default 'brand_mention'
                         check (type in ('brand_mention', 'cool_moment')),
  brand_context        text not null default '',   -- what the agents should know about the brand
  tipper_instructions  text not null default '',   -- extra guidance for how the tipper decides amounts
  max_tip_cents        bigint not null default 500 check (max_tip_cents > 0),
  currency             text not null default 'usd',
  status               text not null default 'active'
                         check (status in ('draft', 'active', 'paused', 'ended')),
  created_at           timestamptz not null default now()
);

create table public.creators (
  id                 uuid primary key default gen_random_uuid(),
  user_id            uuid references auth.users (id) on delete set null,
  display_name       text not null,
  stripe_account_id  text unique,
  transfers_enabled  boolean not null default false,
  created_at         timestamptz not null default now()
);

create table public.videos (
  id          uuid primary key default gen_random_uuid(),
  url         text not null unique,
  platform    text,
  title       text,
  creator_id  uuid references public.creators (id) on delete set null,
  status      text not null default 'pending'
                check (status in ('pending', 'scanning', 'done', 'failed')),
  created_at  timestamptz not null default now()
);

create table public.detections (
  id                 uuid primary key default gen_random_uuid(),
  campaign_id        uuid not null references public.campaigns (id) on delete cascade,
  video_id           uuid not null references public.videos (id) on delete cascade,
  kind               text not null check (kind in ('brand_mention', 'cool_moment')),
  timestamp_seconds  numeric not null check (timestamp_seconds >= 0),
  confidence         numeric not null check (confidence between 0 and 1),
  description        text not null default '',
  idempotency_key    text not null unique,
  created_at         timestamptz not null default now()
);

-- One tip per detection, enforced by the unique constraint.
create table public.tips (
  id                uuid primary key default gen_random_uuid(),
  detection_id      uuid not null unique references public.detections (id) on delete restrict,
  campaign_id       uuid not null references public.campaigns (id) on delete restrict,
  creator_id        uuid not null references public.creators (id) on delete restrict,
  video_id          uuid not null references public.videos (id) on delete restrict,
  amount_cents      bigint not null check (amount_cents > 0),
  currency          text not null default 'usd',
  message           text not null,
  reasoning         text not null default '',
  show_at_seconds   numeric not null default 0,   -- when in the video the pop up should appear
  status            text not null default 'pending'
                      check (status in ('pending', 'paid', 'failed')),
  stripe_transfer_id text,
  failure_reason    text,
  created_at        timestamptz not null default now(),
  paid_at           timestamptz
);

-- Append only money ledger per campaign. Positive = credit, negative = debit.
-- `ref` is unique, which makes every credit and debit idempotent.
create table public.wallet_ledger (
  id           bigint generated always as identity primary key,
  campaign_id  uuid not null references public.campaigns (id) on delete cascade,
  kind         text not null check (kind in ('funding', 'tip', 'refund')),
  amount_cents bigint not null check (amount_cents <> 0),
  ref          text not null unique,
  created_at   timestamptz not null default now()
);

create index on public.campaigns (brand_id);
create index on public.videos (status);
create index on public.detections (campaign_id, video_id);
create index on public.tips (campaign_id, status);
create index on public.tips (video_id);
create index on public.wallet_ledger (campaign_id);

create view public.campaign_balances
  with (security_invoker = true) as
select c.id as campaign_id,
       coalesce(sum(l.amount_cents), 0)::bigint as balance_cents
from public.campaigns c
left join public.wallet_ledger l on l.campaign_id = c.id
group by c.id;

-- ---------------------------------------------------------------------------
-- Money functions (service role only)
-- ---------------------------------------------------------------------------

-- Credit a campaign budget. Safe to call twice with the same ref.
create or replace function public.credit_campaign(
  p_campaign_id  uuid,
  p_amount_cents bigint,
  p_ref          text
) returns boolean
language plpgsql
security definer
set search_path = public
as $$
begin
  if p_amount_cents <= 0 then
    raise exception 'amount_out_of_range';
  end if;

  insert into wallet_ledger (campaign_id, kind, amount_cents, ref)
  values (p_campaign_id, 'funding', p_amount_cents, p_ref)
  on conflict (ref) do nothing;

  return found;  -- true if a new credit row was written
end;
$$;

-- Atomically check the budget and reserve a tip.
-- Locks the campaign row so two tips can never overspend it.
-- Returns the existing tip if this detection was already tipped (idempotent).
create or replace function public.reserve_tip(
  p_detection_id    uuid,
  p_amount_cents    bigint,
  p_message         text,
  p_reasoning       text,
  p_show_at_seconds numeric
) returns public.tips
language plpgsql
security definer
set search_path = public
as $$
declare
  d        public.detections;
  c        public.campaigns;
  v        public.videos;
  cr       public.creators;
  existing public.tips;
  t        public.tips;
  balance  bigint;
begin
  select * into d from detections where id = p_detection_id;
  if not found then
    raise exception 'detection_not_found';
  end if;

  select * into c from campaigns where id = d.campaign_id for update;

  -- Checked after the lock so concurrent calls for the same detection collapse into one tip.
  select * into existing from tips where detection_id = p_detection_id;
  if found then
    return existing;
  end if;

  if c.status <> 'active' then
    raise exception 'campaign_not_active';
  end if;
  if p_amount_cents <= 0 or p_amount_cents > c.max_tip_cents then
    raise exception 'amount_out_of_range';
  end if;

  select * into v from videos where id = d.video_id;
  if v.creator_id is null then
    raise exception 'video_has_no_creator';
  end if;

  select * into cr from creators where id = v.creator_id;
  if cr.stripe_account_id is null or not cr.transfers_enabled then
    raise exception 'creator_not_payable';
  end if;

  select coalesce(sum(amount_cents), 0) into balance
  from wallet_ledger where campaign_id = c.id;
  if balance < p_amount_cents then
    raise exception 'insufficient_budget';
  end if;

  insert into tips (detection_id, campaign_id, creator_id, video_id,
                    amount_cents, currency, message, reasoning, show_at_seconds)
  values (d.id, c.id, cr.id, v.id,
          p_amount_cents, c.currency, p_message, coalesce(p_reasoning, ''),
          coalesce(p_show_at_seconds, d.timestamp_seconds))
  returning * into t;

  insert into wallet_ledger (campaign_id, kind, amount_cents, ref)
  values (c.id, 'tip', -p_amount_cents, 'tip:' || t.id);

  return t;
end;
$$;

-- Mark a pending tip failed and give the money back to the campaign budget.
create or replace function public.fail_tip(
  p_tip_id uuid,
  p_reason text
) returns public.tips
language plpgsql
security definer
set search_path = public
as $$
declare
  t public.tips;
begin
  update tips
     set status = 'failed', failure_reason = p_reason
   where id = p_tip_id and status = 'pending'
  returning * into t;

  if found then
    insert into wallet_ledger (campaign_id, kind, amount_cents, ref)
    values (t.campaign_id, 'refund', t.amount_cents, 'refund:' || t.id)
    on conflict (ref) do nothing;
  else
    select * into t from tips where id = p_tip_id;
  end if;

  return t;
end;
$$;

revoke all on function public.credit_campaign(uuid, bigint, text) from public, anon, authenticated;
revoke all on function public.reserve_tip(uuid, bigint, text, text, numeric) from public, anon, authenticated;
revoke all on function public.fail_tip(uuid, text) from public, anon, authenticated;
grant execute on function public.credit_campaign(uuid, bigint, text) to service_role;
grant execute on function public.reserve_tip(uuid, bigint, text, text, numeric) to service_role;
grant execute on function public.fail_tip(uuid, text) to service_role;

-- ---------------------------------------------------------------------------
-- Row level security
-- The backend uses the service role key, which bypasses RLS.
-- These policies are for the frontend (anon and authenticated keys).
-- ---------------------------------------------------------------------------

alter table public.brands        enable row level security;
alter table public.campaigns     enable row level security;
alter table public.creators      enable row level security;
alter table public.videos        enable row level security;
alter table public.detections    enable row level security;
alter table public.tips          enable row level security;
alter table public.wallet_ledger enable row level security;

-- Brands: owners manage their own.
create policy brands_owner_all on public.brands
  for all to authenticated
  using (owner_id = auth.uid())
  with check (owner_id = auth.uid());

-- Campaigns: owners manage campaigns under their brands.
create policy campaigns_owner_all on public.campaigns
  for all to authenticated
  using (exists (select 1 from public.brands b where b.id = brand_id and b.owner_id = auth.uid()))
  with check (exists (select 1 from public.brands b where b.id = brand_id and b.owner_id = auth.uid()));

-- Detections and ledger: brand owners can read their own.
create policy detections_owner_read on public.detections
  for select to authenticated
  using (exists (
    select 1 from public.campaigns c
    join public.brands b on b.id = c.brand_id
    where c.id = campaign_id and b.owner_id = auth.uid()));

create policy ledger_owner_read on public.wallet_ledger
  for select to authenticated
  using (exists (
    select 1 from public.campaigns c
    join public.brands b on b.id = c.brand_id
    where c.id = campaign_id and b.owner_id = auth.uid()));

-- Tips: brand owners see all of theirs; anyone can see PAID tips (powers the public pop up).
create policy tips_owner_read on public.tips
  for select to authenticated
  using (exists (
    select 1 from public.campaigns c
    join public.brands b on b.id = c.brand_id
    where c.id = campaign_id and b.owner_id = auth.uid()));

create policy tips_public_paid_read on public.tips
  for select to anon, authenticated
  using (status = 'paid');

-- Creators and videos: readable by everyone (needed for the overlay), written only by the backend.
-- Creators can also update nothing directly; onboarding goes through the API.
create policy creators_public_read on public.creators
  for select to anon, authenticated using (true);

create policy videos_public_read on public.videos
  for select to anon, authenticated using (true);

-- ---------------------------------------------------------------------------
-- Realtime: the frontend subscribes to tips to show the pop up the moment a tip is paid.
-- ---------------------------------------------------------------------------

alter publication supabase_realtime add table public.tips;
