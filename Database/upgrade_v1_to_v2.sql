-- ═══════════════════════════════════════════════════════════════════════════════════════════
-- Hiru AI Studio — upgrade a project from schema v1 to schema v2 (Phases 2 and 3, and the usage
-- total behind the top-bar meter).
--
-- HOW TO APPLY: only on a project that already has schema_v1.sql. SQL Editor → paste this
-- whole file → Run, once. It runs in one transaction: if any statement fails, nothing changes.
-- A NEW project runs schema_v2.sql instead (v1 + this file gives the same schema as v2;
-- verified by comparing the dumps).
--
-- Afterwards: re-read the documents uploaded before the upgrade (their extracted text was not
-- kept yet, and the structure build needs it), and set SUPABASE__DB_URL (session pooler),
-- API__INTERNAL_URL and API__INTERNAL_SECRET for the functions.
-- ═══════════════════════════════════════════════════════════════════════════════════════════

begin;

-- ══ usage: monthly model-token total for GET /v1/usage ══════════════════════════════════════
-- Monthly model-token total for GET /v1/usage (the UI shows a percentage only).
-- Called by the API with the service role; browser roles have no use for it.
create or replace function public.token_usage_since(since timestamptz)
returns bigint
language sql stable
set search_path = ''
as $$
  select coalesce(sum(input_tokens::bigint + output_tokens::bigint), 0)::bigint
  from public.token_usage
  where created_at >= since;
$$;

revoke all on function public.token_usage_since(timestamptz) from public, anon, authenticated;
grant execute on function public.token_usage_since(timestamptz) to service_role;

-- ══ Phase 2: structure, canon, build questions, LangGraph checkpoint schema ═════════════════
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

-- ══ Phase 3: the Director panel ════════════════════════════════════════════════════════════
-- ── shots: a length a person chose ───────────────────────────────────────────────────────
-- Re-timing keeps it and reports what overruns; agents may not change it (PLAN.md §6.1).
alter table public.shots add column duration_locked boolean not null default false;
-- A director's edit renumbers shots in one upsert (keeping their ids, which frames and prompts
-- hang off); the numbers are unique again by the end of the statement, not after every row.
alter table public.shots drop constraint shots_scene_id_number_key;
alter table public.shots add constraint shots_scene_id_number_key
  unique (scene_id, number) deferrable initially deferred;

-- ── personas (a global library) and the board ────────────────────────────────────────────
create table public.director_personas (
  id         uuid primary key default gen_random_uuid(),
  slug       text not null unique check (slug ~ '^[a-z0-9-]{2,60}$'),
  name       text not null,
  initials   text not null check (char_length(initials) between 1 and 3),
  color      text not null default '#2F3A45' check (color ~ '^#[0-9A-Fa-f]{6}$'),
  specialty  text not null default '',
  traits     jsonb not null default '[]'::jsonb,           -- [{label, value 0-100}]
  style_note text not null default '',
  charter    text not null default '',                      -- the persona's directing brief, used in prompts
  active     boolean not null default true,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);
create trigger director_personas_touch before update on public.director_personas
  for each row execute function public.touch_updated_at();

create table public.production_director_board (
  production_id uuid not null references public.productions (id) on delete cascade,
  persona_id    uuid not null references public.director_personas (id) on delete cascade,
  seat          text not null check (seat in ('lead', 'advisor')),
  added_by      uuid references public.profiles (id) on delete set null,
  created_at    timestamptz not null default now(),
  primary key (production_id, persona_id)
);
create unique index production_director_board_one_lead
  on public.production_director_board (production_id) where seat = 'lead';
create index production_director_board_persona_idx on public.production_director_board (persona_id);
create index production_director_board_added_by_idx on public.production_director_board (added_by);

-- ── chat ─────────────────────────────────────────────────────────────────────────────────
create table public.chat_threads (
  id            uuid primary key default gen_random_uuid(),
  production_id uuid not null references public.productions (id) on delete cascade,
  scene_id      uuid references public.scenes (id) on delete cascade,
  title         text not null default '',
  created_by    uuid references public.profiles (id) on delete set null,
  created_at    timestamptz not null default now(),
  updated_at    timestamptz not null default now()
);
create index chat_threads_production_idx on public.chat_threads (production_id, scene_id);
create index chat_threads_scene_idx on public.chat_threads (scene_id);
create index chat_threads_created_by_idx on public.chat_threads (created_by);
create trigger chat_threads_touch before update on public.chat_threads
  for each row execute function public.touch_updated_at();

create table public.chat_messages (
  id             uuid primary key default gen_random_uuid(),
  production_id  uuid not null references public.productions (id) on delete cascade,
  thread_id      uuid not null references public.chat_threads (id) on delete cascade,
  kind           text not null check (kind in ('user', 'director')),
  author_user_id uuid references public.profiles (id) on delete set null,
  persona_id     uuid references public.director_personas (id) on delete set null,
  speaker        text not null default '',
  tone           text check (tone in ('lead', 'board')),
  text           text not null default '',
  blocks         jsonb not null default '[]'::jsonb,
  ops            jsonb not null default '[]'::jsonb,       -- operations the turn applied
  citations      jsonb not null default '[]'::jsonb,
  created_at     timestamptz not null default now()
);
create index chat_messages_thread_idx on public.chat_messages (thread_id, created_at);
create index chat_messages_production_idx on public.chat_messages (production_id);
create index chat_messages_author_idx on public.chat_messages (author_user_id);
create index chat_messages_persona_idx on public.chat_messages (persona_id);

-- ── production memory (PLAN.md §6.2) ─────────────────────────────────────────────────────
-- Approved decisions, director notes and answered questions, retrieved like documents (each
-- item is also indexed in `chunks` as corpus 'memory', source 'memory:<id>').
create table public.memory_items (
  id            uuid primary key default gen_random_uuid(),
  production_id uuid not null references public.productions (id) on delete cascade,
  scene_id      uuid references public.scenes (id) on delete set null,
  kind          text not null check (kind in ('decision', 'note', 'answer')),
  text          text not null check (char_length(text) between 1 and 2000),
  source_ref    jsonb not null default '{}'::jsonb,         -- {"message_id"} / {"question_id"} ...
  created_by    uuid references public.profiles (id) on delete set null,
  created_at    timestamptz not null default now()
);
create index memory_items_production_idx on public.memory_items (production_id, created_at desc);
create index memory_items_scene_idx on public.memory_items (scene_id);
create index memory_items_created_by_idx on public.memory_items (created_by);

-- ── RLS ──────────────────────────────────────────────────────────────────────────────────
alter table public.director_personas          enable row level security;
alter table public.production_director_board  enable row level security;
alter table public.chat_threads               enable row level security;
alter table public.chat_messages              enable row level security;
alter table public.memory_items               enable row level security;

create policy director_personas_read on public.director_personas
  for select to authenticated using ((select public.is_active_user()));
create policy production_director_board_read on public.production_director_board
  for select to authenticated using (public.can_view_production(production_id));
create policy chat_threads_read on public.chat_threads
  for select to authenticated using (public.can_view_production(production_id));
create policy chat_messages_read on public.chat_messages
  for select to authenticated using (public.can_view_production(production_id));
create policy memory_items_read on public.memory_items
  for select to authenticated using (public.can_view_production(production_id));

-- Everyone on a scene sees new messages as they land (multi-user awareness).
alter publication supabase_realtime add table public.chat_messages, public.production_director_board;

-- ── the persona library: generic archetypes, not real people ─────────────────────────────
insert into public.director_personas (slug, name, initials, color, specialty, traits, style_note, charter) values
  ('grounded-realist', 'Grounded Realist', 'GR', '#2F3A45', 'Naturalistic family drama',
   '[{"label":"Realism","value":85},{"label":"Tone","value":40},{"label":"Pacing","value":40},{"label":"Audience","value":60}]',
   'Available light, held frames, restraint with close-ups.',
   'Prefer eye-level framing and steady, motivated camera. Hold on reactions rather than cutting away. Save close-ups for the moment a decision lands. Light from practical sources: lamps, windows, the fire.'),
  ('classic-teledrama', 'Classic Teledrama', 'CT', '#5A3E2B', 'Prime-time Sri Lankan teledrama',
   '[{"label":"Realism","value":55},{"label":"Tone","value":70},{"label":"Pacing","value":55},{"label":"Audience","value":85}]',
   'Clear coverage, readable emotion, family-audience warmth.',
   'Cover every speaker clearly: establish, then singles in shot / reverse shot. Emotion should read from across a living room. Keep the geography obvious and the axis steady.'),
  ('tension-builder', 'Tension Builder', 'TB', '#1F2A44', 'Suspense and turning points',
   '[{"label":"Realism","value":65},{"label":"Tone","value":30},{"label":"Pacing","value":70},{"label":"Audience","value":55}]',
   'Withheld information, slow push-ins, silence before the turn.',
   'Delay the reveal. Use slow push-ins and inserts of objects that matter. Let silence sit before a line that changes the scene. Tighten the frame as the stakes rise.'),
  ('short-form', 'Short-Form Storyteller', 'SF', '#3D4F2F', 'Vertical cut-downs for social',
   '[{"label":"Realism","value":50},{"label":"Tone","value":60},{"label":"Pacing","value":85},{"label":"Audience","value":75}]',
   'A hook in the first shot, faces close, every second earns its place.',
   'Open on the most arresting image. Favour closer framings that read on a phone. Keep shots short and the speaker centred for vertical frames. Cut on action.'),
  ('lyrical-eye', 'Lyrical Eye', 'LE', '#4A2F4F', 'Mood, landscape and music-led moments',
   '[{"label":"Realism","value":45},{"label":"Tone","value":55},{"label":"Pacing","value":30},{"label":"Audience","value":50}]',
   'Landscape as feeling, golden light, music carrying the cut.',
   'Let place carry emotion: wide frames of sea, sky and village life between the drama. Use golden-hour and lamp light. Let music-only shots breathe at the turns of a scene.');

-- ── lines: a script edit reorders them in one upsert (20261023180232_phase3_line_order.sql) ──
alter table public.dialogue_lines drop constraint dialogue_lines_scene_id_ord_key;
alter table public.dialogue_lines add constraint dialogue_lines_scene_id_ord_key
  unique (scene_id, ord) deferrable initially deferred;

commit;
