-- A scene's production cost (plan/2026-11-06d): the editable, dated price list, and the scene a model call was for.
-- Schema v17 (Database/schema_v17.sql, upgrade_v16_to_v17.sql).
--
-- Nothing here stores a money figure: a cost is worked out at read time from metered usage (token_usage, video_renders)
-- and the price valid when the work was made, so a price fix applies to new work only (a new row with a later valid_from).

-- prices: one row per price and start date. kind 'tokens' = per million tokens, matched by the longest model_prefix;
-- 'video_second' = per second of video, matched by engine + model ('' = any) + resolution; 'estimate' = one frame or
-- one prompt (model_prefix 'frame' | 'prompt'), used only when no history says what one costs. Micro-dollars (1 USD =
-- 1,000,000) so no float is ever summed. Read by admins only; the API reads and adds prices with the service role.
create table if not exists public.prices (
  id                  uuid primary key default gen_random_uuid(),
  kind                text not null check (kind in ('tokens', 'video_second', 'estimate')),
  model_prefix        text not null default '',
  engine              text not null default '',
  model               text not null default '',
  resolution          text not null default '',
  input_micros        bigint not null default 0 check (input_micros >= 0),
  cached_input_micros bigint not null default 0 check (cached_input_micros >= 0),
  output_micros       bigint not null default 0 check (output_micros >= 0),
  per_second_micros   bigint not null default 0 check (per_second_micros >= 0),
  unit_micros         bigint not null default 0 check (unit_micros >= 0),
  valid_from          timestamptz not null default now(),
  note                text not null default '',
  set_by              uuid references public.profiles (id) on delete set null,
  created_at          timestamptz not null default now()
);
create index if not exists prices_kind_idx on public.prices (kind, valid_from desc);
create index if not exists prices_set_by_idx on public.prices (set_by);
comment on table public.prices is
  'The dated price list behind a scene''s cost (plan/2026-11-06d). Rows are added, never edited: a change applies to work made after its valid_from.';

alter table public.prices enable row level security;
drop policy if exists prices_read on public.prices;
create policy prices_read on public.prices
  for select to authenticated using ((select public.is_admin()));

-- The seed: list prices, provisional until a real bill confirms them (Phase 0). A model or size that is not listed has no
-- price on purpose: the scene's cost then says some prices are missing.
insert into public.prices (kind, model_prefix, engine, model, resolution, input_micros, cached_input_micros,
                           output_micros, per_second_micros, unit_micros, note, valid_from)
select v.*, timestamptz '2026-01-01 00:00:00+00' from (values
  ('tokens', 'gpt-5-nano', '', '', '', 50000, 5000, 400000, 0, 0, 'OpenAI list price, standard tier'),
  ('tokens', 'gpt-5-mini', '', '', '', 250000, 25000, 2000000, 0, 0, 'OpenAI list price, standard tier'),
  ('tokens', 'gpt-5', '', '', '', 1250000, 125000, 10000000, 0, 0, 'OpenAI list price, standard tier'),
  ('tokens', 'gpt-5.5', '', '', '', 5000000, 500000, 30000000, 0, 0, 'OpenAI list price, read 2026-11-06 by lab/cinematic: confirm'),
  ('tokens', 'gpt-6.1-sol', '', '', '', 2000000, 100000, 10000000, 0, 0, 'OpenAI list price below 272K input (2x input above it), read 2026-11-06 by lab/cinematic: confirm'),
  ('tokens', 'text-embedding-3-large', '', '', '', 130000, 130000, 0, 0, 0, 'list price, provisional: confirm against a real bill (plan/2026-11-06d Phase 0)'),
  ('tokens', 'text-embedding-3-small', '', '', '', 20000, 20000, 0, 0, 0, 'list price, provisional: confirm against a real bill (plan/2026-11-06d Phase 0)'),
  ('tokens', 'gpt-image-2', '', '', '', 8000000, 2000000, 30000000, 0, 0, 'list price, provisional: confirm against a real bill (plan/2026-11-06d Phase 0)'),
  ('video_second', '', 'veo_3_1', '', '720p', 0, 0, 0, 400000, 0, 'list price, provisional: confirm against a real bill (plan/2026-11-06d Phase 0)'),
  ('video_second', '', 'veo_3_1', '', '1080p', 0, 0, 0, 400000, 0, 'list price, provisional: confirm against a real bill (plan/2026-11-06d Phase 0)'),
  ('video_second', '', 'veo_3_1_fast', '', '720p', 0, 0, 0, 100000, 0, 'list price, provisional: confirm against a real bill (plan/2026-11-06d Phase 0)'),
  ('video_second', '', 'veo_3_1_fast', '', '1080p', 0, 0, 0, 120000, 0, 'list price, provisional: confirm against a real bill (plan/2026-11-06d Phase 0)'),
  ('video_second', '', 'omni_flash', '', '720p', 0, 0, 0, 100000, 0, 'derived from the preview''s token rate: confirm (plan/2026-11-06d Phase 0)'),
  ('estimate', 'frame', '', '', '', 0, 0, 0, 0, 80000, 'one first frame at medium quality: used only when no frame has been made yet'),
  ('estimate', 'prompt', '', '', '', 0, 0, 0, 0, 20000, 'one video prompt: used only when none has been made yet')
) as v(kind, model_prefix, engine, model, resolution, input_micros, cached_input_micros, output_micros,
       per_second_micros, unit_micros, note)
where not exists (select 1 from public.prices);

-- token_usage.scene_id: the scene a call was for (null = not tied to one scene, e.g. a whole-episode breakdown).
alter table public.token_usage add column if not exists scene_id uuid references public.scenes (id) on delete set null;
create index if not exists token_usage_scene_idx on public.token_usage (scene_id, created_at);
comment on column public.token_usage.scene_id is
  'The scene this call was made for (plan/2026-11-06d). Null for work on a whole episode or production.';

-- Old rows: a job that named one scene in its request is that scene's work.
update public.token_usage u
   set scene_id = s.id
  from public.jobs j
  join public.scenes s on s.id::text = j.request ->> 'scene_id'
 where u.job_id = j.id and u.scene_id is null;
