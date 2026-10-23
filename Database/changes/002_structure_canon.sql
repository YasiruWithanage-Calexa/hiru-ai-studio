-- Phase 2 (2026-10-23): structure, canon, build questions, LangGraph checkpoint schema.
-- Same content as supabase/migrations/20261023103638_phase2_structure_canon.sql.
-- Run once in the SQL Editor of the hosted dev project, then re-ingest existing documents
-- (their extracted text is now kept in storage for the structure build).
begin;


-- ── documents: where the extracted text is kept ──────────────────────────────────────────
-- doc_ingest stores the normalised text once (pages separated by form feeds) so later engines
-- read the script without parsing the PDF again.
alter table public.documents add column text_path text;

-- ── canon ────────────────────────────────────────────────────────────────────────────────
create type public.canon_kind as enum ('character', 'location', 'prop');

create table public.canon_entities (
  id                 uuid primary key default gen_random_uuid(),
  production_id      uuid not null references public.productions (id) on delete cascade,
  kind               public.canon_kind not null,
  code               text not null check (code ~ '^[CLP][0-9]{2,3}$'),
  name               text not null check (char_length(name) between 1 and 120),
  aliases            text[] not null default '{}',
  core               boolean not null default false,
  locked             boolean not null default false,
  locked_by          uuid references public.profiles (id) on delete set null,
  locked_at          timestamptz,
  current_version_id uuid,                                  -- fk added below (circular)
  created_at         timestamptz not null default now(),
  updated_at         timestamptz not null default now(),
  unique (production_id, code)
);
create unique index canon_entities_name_key on public.canon_entities (production_id, kind, lower(name));
create index canon_entities_locked_by_idx on public.canon_entities (locked_by);
create trigger canon_entities_touch before update on public.canon_entities
  for each row execute function public.touch_updated_at();

create table public.canon_versions (
  id               uuid primary key default gen_random_uuid(),
  entity_id        uuid not null references public.canon_entities (id) on delete cascade,
  production_id    uuid not null references public.productions (id) on delete cascade,
  version          integer not null check (version >= 1),
  card             jsonb not null default '{}'::jsonb,       -- contracts.canon.CanonCard
  card_hash        text not null,                            -- unchanged card → no new version
  wardrobe_anchor  text not null default '',
  voice_pin        text not null default '',
  reference_prompt text not null default '',
  reference_assets jsonb not null default '[]'::jsonb,       -- storage paths of reference sheets
  source           text not null default 'extract' check (source in ('extract', 'user')),
  created_by       uuid references public.profiles (id) on delete set null,
  created_at       timestamptz not null default now(),
  unique (entity_id, version)
);
create index canon_versions_production_idx on public.canon_versions (production_id);
create index canon_versions_created_by_idx on public.canon_versions (created_by);

alter table public.canon_entities
  add constraint canon_entities_current_version_fkey
  foreign key (current_version_id) references public.canon_versions (id) on delete set null;
create index canon_entities_current_version_idx on public.canon_entities (current_version_id);

-- ── episodes, scenes, shots ──────────────────────────────────────────────────────────────
create table public.episodes (
  id            uuid primary key default gen_random_uuid(),
  production_id uuid not null references public.productions (id) on delete cascade,
  number        integer not null check (number >= 1),
  title         text not null default '',
  synopsis      text not null default '',
  status        text not null default 'draft' check (status in ('draft', 'building', 'ready', 'approved')),
  source_document_ids uuid[] not null default '{}',
  created_at    timestamptz not null default now(),
  updated_at    timestamptz not null default now(),
  unique (production_id, number)
);
create trigger episodes_touch before update on public.episodes
  for each row execute function public.touch_updated_at();

create table public.scenes (
  id             uuid primary key default gen_random_uuid(),
  production_id  uuid not null references public.productions (id) on delete cascade,
  episode_id     uuid not null references public.episodes (id) on delete cascade,
  number         integer not null check (number >= 1),
  heading        text not null default '',
  title          text not null default '',
  location_id    uuid references public.canon_entities (id) on delete set null,
  time_of_day    text not null default '',
  envelope_s     integer not null check (envelope_s >= 4),
  script         jsonb not null default '[]'::jsonb,         -- [contracts.production.ScriptBlock]
  script_version integer not null default 1,
  status         text not null default 'draft' check (status in ('draft', 'split', 'approved')),
  note           text not null default '',
  fit_report     jsonb not null default '{}'::jsonb,         -- the split kernel's issues and totals
  locked_by      uuid references public.profiles (id) on delete set null,
  locked_at      timestamptz,
  created_at     timestamptz not null default now(),
  updated_at     timestamptz not null default now(),
  unique (episode_id, number)
);
create index scenes_production_idx on public.scenes (production_id);
create index scenes_location_idx on public.scenes (location_id);
create index scenes_locked_by_idx on public.scenes (locked_by);
create trigger scenes_touch before update on public.scenes
  for each row execute function public.touch_updated_at();

create table public.shots (
  id             uuid primary key default gen_random_uuid(),
  production_id  uuid not null references public.productions (id) on delete cascade,
  scene_id       uuid not null references public.scenes (id) on delete cascade,
  number         integer not null check (number >= 1),
  title          text not null default '',
  framing        text not null default 'MS'
                   check (framing in ('WIDE', 'MS', 'MCU', 'CU', 'TWO', 'OTS', 'INSERT')),
  duration_s     integer not null check (duration_s in (4, 6, 8)),   -- 10 s stays off (PLAN.md Q4)
  start_s        integer not null default 0,
  sound_mode     text not null default 'ambient'
                   check (sound_mode in ('dialogue', 'voiceover', 'sung', 'ambient', 'music_only', 'silent')),
  camera_link    text not null default 'cut' check (camera_link in ('cut', 'continuous', 'match')),
  frame_strategy text not null default 'generate'
                   check (frame_strategy in ('generate', 'carry_last_frame', 'storyboard')),
  speaker_id     uuid references public.canon_entities (id) on delete set null,
  beats          jsonb not null default '[]'::jsonb,
  block_start    integer not null default 0,
  block_end      integer not null default 0,
  word_target    integer not null default 0,
  words          integer not null default 0,
  ir             jsonb not null default '{}'::jsonb,         -- shot producer IR (Phase 4)
  status         text not null default 'draft' check (status in ('draft', 'frame', 'prompt')),
  version        integer not null default 1,
  created_at     timestamptz not null default now(),
  updated_at     timestamptz not null default now(),
  unique (scene_id, number)
);
create index shots_production_idx on public.shots (production_id);
create index shots_speaker_idx on public.shots (speaker_id);
create trigger shots_touch before update on public.shots
  for each row execute function public.touch_updated_at();

create table public.dialogue_lines (
  id            uuid primary key default gen_random_uuid(),
  production_id uuid not null references public.productions (id) on delete cascade,
  scene_id      uuid not null references public.scenes (id) on delete cascade,
  ord           integer not null check (ord >= 0),
  speaker       text not null,                               -- as written in the script
  character_id  uuid references public.canon_entities (id) on delete set null,
  text          text not null,                               -- verbatim; engines never rewrite it
  delivery      text not null default '',
  words         integer not null default 0,
  shot_id       uuid references public.shots (id) on delete set null,
  beat_index    integer,
  start_s       real,
  overrun_s     real not null default 0,
  created_at    timestamptz not null default now(),
  updated_at    timestamptz not null default now(),
  unique (scene_id, ord)
);
create index dialogue_lines_production_idx on public.dialogue_lines (production_id);
create index dialogue_lines_character_idx on public.dialogue_lines (character_id);
create index dialogue_lines_shot_idx on public.dialogue_lines (shot_id);
create trigger dialogue_lines_touch before update on public.dialogue_lines
  for each row execute function public.touch_updated_at();

-- ── build questions ──────────────────────────────────────────────────────────────────────
create table public.questions (
  id            uuid primary key,                            -- deterministic per job + key
  production_id uuid not null references public.productions (id) on delete cascade,
  job_id        uuid references public.jobs (id) on delete set null,
  key           text not null,                               -- what it is about, stable across retries
  agent         text not null default '',
  scope         text not null default '',
  title         text not null,
  body          text not null,
  options       jsonb not null default '[]'::jsonb,
  allow_text    boolean not null default false,
  status        text not null default 'open' check (status in ('open', 'answered', 'defaulted')),
  answer        jsonb,
  answered_by   uuid references public.profiles (id) on delete set null,
  answered_at   timestamptz,
  created_at    timestamptz not null default now(),
  updated_at    timestamptz not null default now()
);
create index questions_production_idx on public.questions (production_id, status, created_at);
create index questions_job_idx on public.questions (job_id, status);
create index questions_answered_by_idx on public.questions (answered_by);
create trigger questions_touch before update on public.questions
  for each row execute function public.touch_updated_at();

-- ── LangGraph checkpoints ────────────────────────────────────────────────────────────────
-- The checkpointer (langgraph-checkpoint-postgres) creates and migrates its own tables in this
-- schema the first time a function connects. Not exposed through the API; no browser access.
create schema if not exists graph;
revoke all on schema graph from public, anon, authenticated;

-- ── row level security (read-only for browser roles) ─────────────────────────────────────
alter table public.canon_entities enable row level security;
alter table public.canon_versions enable row level security;
alter table public.episodes       enable row level security;
alter table public.scenes         enable row level security;
alter table public.shots          enable row level security;
alter table public.dialogue_lines enable row level security;
alter table public.questions      enable row level security;

create policy canon_entities_read on public.canon_entities
  for select to authenticated using (public.can_view_production(production_id));
create policy canon_versions_read on public.canon_versions
  for select to authenticated using (public.can_view_production(production_id));
create policy episodes_read on public.episodes
  for select to authenticated using (public.can_view_production(production_id));
create policy scenes_read on public.scenes
  for select to authenticated using (public.can_view_production(production_id));
create policy shots_read on public.shots
  for select to authenticated using (public.can_view_production(production_id));
create policy dialogue_lines_read on public.dialogue_lines
  for select to authenticated using (public.can_view_production(production_id));
create policy questions_read on public.questions
  for select to authenticated using (public.can_view_production(production_id));

-- ── realtime: the live build tree and its questions ──────────────────────────────────────
alter publication supabase_realtime add table
  public.episodes, public.scenes, public.shots, public.questions, public.canon_entities;

commit;
