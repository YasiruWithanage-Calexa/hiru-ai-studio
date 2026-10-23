-- Phase 3: the Director panel. Director personas and each production's board, chat threads
-- and messages (server-side, shared by everyone on the production), and production memory.
-- Read-only RLS for browsers as everywhere else; the API and the director_chat function write.

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
