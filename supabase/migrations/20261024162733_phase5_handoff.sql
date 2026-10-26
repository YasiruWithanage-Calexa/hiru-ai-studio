-- Phase 5: Prompt & handoff. Takes a person brings back from Flow (one accepted per shot; an
-- accepted take's last frame opens a shot that carries on from it), and the monthly usage
-- budget behind the top-bar percentage.
--
-- Same access model as before: RLS is READ-ONLY for browser roles; the API writes.

-- ── takes ────────────────────────────────────────────────────────────────────────────────
create table public.takes (
  id              uuid primary key default gen_random_uuid(),
  production_id   uuid not null references public.productions (id) on delete cascade,
  shot_id         uuid not null references public.shots (id) on delete cascade,
  prompt_id       uuid references public.video_prompts (id) on delete set null,
  prompt_version  integer,                                  -- the version it was generated from
  storage_path    text not null,                            -- takes bucket; never sent to a browser
  mime            text not null check (mime in ('video/mp4', 'video/quicktime', 'video/webm')),
  bytes           bigint not null check (bytes > 0),
  duration_s      real,                                     -- probed; null when the probe failed
  status          text not null default 'uploaded' check (status in ('uploaded', 'accepted', 'rejected')),
  reason          text,                                     -- why it was rejected
  last_frame_path text,                                     -- frames bucket, once extracted
  uploaded_by     uuid references public.profiles (id) on delete set null,
  accepted_by     uuid references public.profiles (id) on delete set null,
  accepted_at     timestamptz,
  created_at      timestamptz not null default now(),
  updated_at      timestamptz not null default now(),
  check ((status = 'accepted') = (accepted_at is not null))
);
-- One accepted take per shot: accepting another moves the choice.
create unique index takes_one_accepted on public.takes (shot_id) where status = 'accepted';
create index takes_shot_idx on public.takes (shot_id, created_at);
create index takes_production_idx on public.takes (production_id);
create index takes_prompt_idx on public.takes (prompt_id);
create index takes_uploaded_by_idx on public.takes (uploaded_by);
create index takes_accepted_by_idx on public.takes (accepted_by);
create trigger takes_touch before update on public.takes
  for each row execute function public.touch_updated_at();

-- ── the monthly usage budget (model tokens; the UI shows a percentage only) ──────────────
create table public.usage_budget (
  month         date primary key check (extract(day from month) = 1),
  budget_tokens bigint not null check (budget_tokens > 0),
  set_by        uuid references public.profiles (id) on delete set null,
  updated_at    timestamptz not null default now()
);
create index usage_budget_set_by_idx on public.usage_budget (set_by);
create trigger usage_budget_touch before update on public.usage_budget
  for each row execute function public.touch_updated_at();

-- ── RLS (read-only for browser roles; the budget is the API's alone) ─────────────────────
alter table public.takes        enable row level security;
alter table public.usage_budget enable row level security;

create policy takes_read on public.takes
  for select to authenticated using (public.can_view_production(production_id));

alter publication supabase_realtime add table public.takes;

-- ── storage: takes (private; the API streams them through tickets) ───────────────────────
insert into storage.buckets (id, name, public, file_size_limit, allowed_mime_types)
values ('takes', 'takes', false, 31457280, array['video/mp4', 'video/quicktime', 'video/webm'])
on conflict (id) do nothing;
