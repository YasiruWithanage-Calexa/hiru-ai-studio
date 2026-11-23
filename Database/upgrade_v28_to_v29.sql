-- ═══════════════════════════════════════════════════════════════════════════════════════════
-- Hiru AI Studio — upgrade a project from schema v28 to schema v29 (usage in USD, plan/2026-11-23):
--   * `token_usage.image_input_tokens`: of a picture call's input, the pictures sent in (OpenAI bills them at a higher
--     rate than text). Null on every older row: such a row is priced as all pictures, as it was before.
--   * `prices`: an image-input rate, long-context rates (a call above `long_context_from` input tokens), a text-output
--     rate for a video model billed by tokens, and the kind 'video_tokens' (Gemini Omni 1.2 Flash).
--   * the corrected list prices, read on the official pages 2026-11-23. Rows are ADDED, never edited. Each is dated
--     from when the rate really applied to us, so past spending is priced right (D5): a backdated row starts one
--     second after the row it corrects (2026-01-01 00:00:01) so the later row wins; Omni 1.2's per-second rows start
--     2026-11-19, the day the product moved to it.
--   * `public.token_usage_totals(...)`: a month's tokens summed by production, model, kind and price interval, so the
--     Settings → Usage page prices sums instead of every row.
--
-- Safe to re-run (the price rows are inserted only when the same row is not there yet).
--
-- HOW TO APPLY: only on a project that already has schema v28. SQL Editor → paste this whole file → Run, once. A NEW
-- project runs schema_v29.sql instead (v28 + this file gives the same schema as v29). Nothing is applied to the hosted
-- project until the person says so. Before it is applied the API still works: usage writers retry a row without the
-- new column, and the Usage page sums rows in the API instead of calling the function.
-- ═══════════════════════════════════════════════════════════════════════════════════════════
begin;

alter table public.token_usage add column if not exists image_input_tokens integer;
comment on column public.token_usage.image_input_tokens is
  'Of input_tokens, the pictures sent to an image model (plan/2026-11-23). Null = not recorded (priced as all pictures).';

alter table public.prices add column if not exists image_input_micros        bigint not null default 0 check (image_input_micros >= 0);
alter table public.prices add column if not exists cached_image_input_micros bigint not null default 0 check (cached_image_input_micros >= 0);
alter table public.prices add column if not exists text_output_micros        bigint not null default 0 check (text_output_micros >= 0);
alter table public.prices add column if not exists long_context_from         integer not null default 0 check (long_context_from >= 0);
alter table public.prices add column if not exists long_input_micros         bigint not null default 0 check (long_input_micros >= 0);
alter table public.prices add column if not exists long_cached_input_micros  bigint not null default 0 check (long_cached_input_micros >= 0);
alter table public.prices add column if not exists long_output_micros        bigint not null default 0 check (long_output_micros >= 0);

alter table public.prices drop constraint if exists prices_kind_check;
alter table public.prices add constraint prices_kind_check
  check (kind in ('tokens', 'video_tokens', 'video_second', 'estimate'));

insert into public.prices (kind, model_prefix, engine, model, resolution, input_micros, cached_input_micros,
                           output_micros, image_input_micros, cached_image_input_micros, text_output_micros,
                           long_context_from, long_input_micros, long_cached_input_micros, long_output_micros,
                           per_second_micros, valid_from, note)
select v.* from (values
  ('tokens', 'gpt-5.5', '', '', '', 5000000::bigint, 500000::bigint, 30000000::bigint, 0::bigint, 0::bigint, 0::bigint,
   272000, 10000000::bigint, 1000000::bigint, 45000000::bigint, 0::bigint, timestamptz '2026-01-01 00:00:01+00',
   'OpenAI list price, standard tier (developers.openai.com/api/docs/pricing, read 2026-11-23); long context above 272K input'),
  ('tokens', 'gpt-6.1-sol', '', '', '', 2000000, 100000, 10000000, 0, 0, 0,
   272000, 4000000, 200000, 15000000, 0, timestamptz '2026-01-01 00:00:01+00',
   'OpenAI list price, standard tier (developers.openai.com/api/docs/pricing, read 2026-11-23); long context above 272K input'),
  ('tokens', 'gpt-6.1-terra', '', '', '', 1000000, 50000, 5000000, 0, 0, 0,
   272000, 2000000, 100000, 7500000, 0, timestamptz '2026-01-01 00:00:01+00',
   'OpenAI list price, standard tier (developers.openai.com/api/docs/pricing, read 2026-11-23); long context above 272K input'),
  ('tokens', 'gpt-image-2', '', '', '', 5000000, 1250000, 30000000, 8000000, 2000000, 0,
   0, 0, 0, 0, 0, timestamptz '2026-01-01 00:00:01+00',
   'OpenAI list price, standard tier (developers.openai.com/api/docs/pricing, read 2026-11-23): text in 5.00, pictures in 8.00'),
  ('video_tokens', 'gemini-omni-1.2-flash', '', '', '', 1500000, 0, 12000000, 0, 0, 9000000,
   0, 0, 0, 0, 0, timestamptz '2026-01-01 00:00:00+00',
   'Google list price, standard paid tier (aistudio.google.com/docs/pricing, read 2026-11-23): in 1.50, video 12.00, text and thinking 9.00'),
  ('video_second', '', 'omni_flash', 'gemini-omni-1.1-flash', '720p', 0, 0, 0, 0, 0, 0,
   0, 0, 0, 0, 100000, timestamptz '2026-01-01 00:00:00+00',
   'retired engine (plan/2026-11-19): kept so renders made with it keep their price'),
  ('video_second', '', 'omni_flash', '', '360p', 0, 0, 0, 0, 0, 0,
   0, 0, 0, 0, 23000, timestamptz '2026-11-19 00:00:00+00',
   'Google list price, standard paid tier (aistudio.google.com/docs/pricing, read 2026-11-23): Omni 1.2, 1,931 tokens a second'),
  ('video_second', '', 'omni_flash', '', '720p', 0, 0, 0, 0, 0, 0,
   0, 0, 0, 0, 70000, timestamptz '2026-11-19 00:00:00+00',
   'Google list price, standard paid tier (aistudio.google.com/docs/pricing, read 2026-11-23): Omni 1.2, 5,792 tokens a second'),
  ('video_second', '', 'omni_flash', '', '1080p', 0, 0, 0, 0, 0, 0,
   0, 0, 0, 0, 104000, timestamptz '2026-11-19 00:00:00+00',
   'Google list price, standard paid tier (aistudio.google.com/docs/pricing, read 2026-11-23): Omni 1.2, 8,688 tokens a second')
) as v(kind, model_prefix, engine, model, resolution, input_micros, cached_input_micros, output_micros,
       image_input_micros, cached_image_input_micros, text_output_micros, long_context_from, long_input_micros,
       long_cached_input_micros, long_output_micros, per_second_micros, valid_from, note)
where not exists (
  select 1 from public.prices p
  where p.kind = v.kind and p.model_prefix = v.model_prefix and p.engine = v.engine and p.model = v.model
    and p.resolution = v.resolution and p.valid_from = v.valid_from);

-- A month's tokens summed for the Usage page (plan/2026-11-23 §3.5). One row per production, model, kind, price
-- interval and long/short call. `boundaries` (sorted) are the moments a price or a margin changes: `slot` 0 is before
-- the first, n is from boundaries[n]. `kind` follows contracts.costs.kind_of (the lists come from Python); video meter
-- rows are left out (a video is priced from its render). Every part that is not linear is split ROW BY ROW before it
-- is summed, as contracts.costs.picture_split does, so the sums price exactly as the rows would: an older row's
-- pictures are all of its input, cached input is capped at the input, and cached tokens come off the text first.
create or replace function public.token_usage_totals(
  since timestamptz, until timestamptz, boundaries timestamptz[], image_phases text[], metered_prefixes text[],
  long_from integer)
returns table (production_id uuid, model text, kind text, slot integer, long boolean, calls bigint,
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
  group by 1, 2, 3, 4, 5;
$$;

revoke all on function public.token_usage_totals(timestamptz, timestamptz, timestamptz[], text[], text[], integer)
  from public, anon, authenticated;
grant execute on function public.token_usage_totals(timestamptz, timestamptz, timestamptz[], text[], text[], integer)
  to service_role;

notify pgrst, 'reload schema';

commit;
