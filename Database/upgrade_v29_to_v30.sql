-- ═══════════════════════════════════════════════════════════════════════════════════════════
-- Hiru AI Studio — upgrade a project from schema v29 to schema v30 (setup apart from scene cost, plan/2026-11-23b):
--   * `public.token_usage_totals(...)` also groups by `phase` and `job_id`, so Settings → Usage can split a month by
--     purpose (production setup, episode setup, scenes). Same arguments; two more columns in what it returns.
-- Nothing else changes: no table, no column, no price row.
--
-- Safe to re-run (the function is dropped and made again).
--
-- HOW TO APPLY: only on a project that already has schema v29 (upgrade_v28_to_v29.sql). SQL Editor → paste this whole
-- file → Run, once. A NEW project runs schema_v30.sql instead (v29 + this file gives the same schema as v30). Before
-- it is applied the API still works: it sees the v29 function has no `phase` column and sums the month's rows itself.
-- ═══════════════════════════════════════════════════════════════════════════════════════════
begin;

-- A month's tokens summed for the Usage page (plan/2026-11-23 §3.5). One row per production, model, kind, price
-- interval, long/short call, phase and job (phase and job decide the purpose: setup or scene, plan/2026-11-23b). `boundaries` (sorted) are the moments a price or a margin changes: `slot` 0 is before
-- the first, n is from boundaries[n]. `kind` follows contracts.costs.kind_of (the lists come from Python); video meter
-- rows are left out (a video is priced from its render). Every part that is not linear is split ROW BY ROW before it
-- is summed, as contracts.costs.picture_split does, so the sums price exactly as the rows would: an older row's
-- pictures are all of its input, cached input is capped at the input, and cached tokens come off the text first.
-- Dropped first: v29 made it with fewer columns, and `create or replace` cannot change what a function returns.
drop function if exists public.token_usage_totals(timestamptz, timestamptz, timestamptz[], text[], text[], integer);
create function public.token_usage_totals(
  since timestamptz, until timestamptz, boundaries timestamptz[], image_phases text[], metered_prefixes text[],
  long_from integer)
returns table (production_id uuid, model text, kind text, slot integer, long boolean, phase text, job_id uuid,
               calls bigint,
               input_tokens bigint, image_input_tokens bigint, cached_input_tokens bigint,
               cached_image_input_tokens bigint, output_tokens bigint)
language sql stable
set search_path = ''
as $$
  select u.production_id,
         u.model,
         case when u.phase = any(image_phases) then 'image' else 'text' end as kind,
         coalesce(pg_catalog.width_bucket(u.created_at, boundaries), 0) as slot,
         (long_from > 0 and u.input_tokens > long_from) as long,
         u.phase,
         u.job_id,
         count(*)::bigint,
         sum(u.input_tokens)::bigint,
         sum(p.pictures)::bigint,
         sum(p.cached)::bigint,
         sum(least(greatest(p.cached - (u.input_tokens - p.pictures), 0), p.pictures))::bigint,
         sum(u.output_tokens)::bigint
  from public.token_usage u
  cross join lateral (
    select least(coalesce(u.image_input_tokens, u.input_tokens), u.input_tokens) as pictures,
           least(u.cached_input_tokens, u.input_tokens) as cached
  ) p
  where u.created_at >= since and u.created_at < until
    and not exists (select 1 from pg_catalog.unnest(metered_prefixes) m(prefix)
                    where pg_catalog.starts_with(u.phase, m.prefix))
  group by 1, 2, 3, 4, 5, 6, 7;
$$;

revoke all on function public.token_usage_totals(timestamptz, timestamptz, timestamptz[], text[], text[], integer)
  from public, anon, authenticated;
grant execute on function public.token_usage_totals(timestamptz, timestamptz, timestamptz[], text[], text[], integer)
  to service_role;

notify pgrst, 'reload schema';

commit;
