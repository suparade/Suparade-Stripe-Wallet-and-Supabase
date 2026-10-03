-- This project does not auto-grant table privileges, so grant them explicitly. RLS still limits what each role sees.
grant select, insert, update, delete on all tables in schema public to service_role;
grant usage, select on all sequences in schema public to service_role;

grant select, insert, update, delete on public.brands, public.campaigns to authenticated;
grant select on public.detections, public.tips, public.wallet_ledger, public.campaign_balances, public.creators, public.videos to authenticated;
grant select on public.creators, public.videos, public.tips to anon;
