-- Hiru AI Studio — foundation: people, roles, productions, audit, jobs.
--
-- Access model (PLAN.md §9):
--   * profiles.app_role: 'admin' | 'member'. Admins see and do everything.
--   * production_members.role: what a member may do inside one production.
--   * RLS governs VISIBILITY only. There are deliberately no INSERT/UPDATE/DELETE policies for
--     browser roles: every write goes through the API (service role), which enforces the
--     permission table in contracts/roles.py. A missing write policy means "denied".

-- ── types ────────────────────────────────────────────────────────────────────────────────
create type public.app_role as enum ('admin', 'member');
create type public.production_role as enum ('producer', 'director', 'writer', 'production', 'reviewer');
create type public.production_kind as enum ('drama_series', 'daily', 'special');
create type public.production_status as enum ('draft', 'ready_for_director', 'in_production', 'archived');
create type public.orientation as enum ('horizontal', 'vertical');
create type public.job_status as enum ('pending', 'running', 'waiting_input', 'done', 'failed', 'cancelled');

create or replace function public.touch_updated_at()
returns trigger
language plpgsql
set search_path = ''
as $$
begin
  new.updated_at := now();
  return new;
end;
$$;

-- ── profiles ─────────────────────────────────────────────────────────────────────────────
create table public.profiles (
  id           uuid primary key references auth.users (id) on delete cascade,
  email        text not null,
  display_name text not null default '',
  app_role     public.app_role not null default 'member',
  active       boolean not null default true,
  created_at   timestamptz not null default now(),
  updated_at   timestamptz not null default now()
);
create unique index profiles_email_key on public.profiles (lower(email));
create trigger profiles_touch before update on public.profiles
  for each row execute function public.touch_updated_at();

-- ── productions ──────────────────────────────────────────────────────────────────────────
create table public.productions (
  id          uuid primary key default gen_random_uuid(),
  title       text not null check (char_length(title) between 1 and 200),
  kind        public.production_kind not null default 'drama_series',
  orientation public.orientation not null,
  status      public.production_status not null default 'draft',
  summary     text not null default '',
  settings    jsonb not null default '{}'::jsonb,
  created_by  uuid references public.profiles (id) on delete set null,
  created_at  timestamptz not null default now(),
  updated_at  timestamptz not null default now()
);
create index productions_updated_idx on public.productions (updated_at desc);
create trigger productions_touch before update on public.productions
  for each row execute function public.touch_updated_at();

create table public.production_members (
  production_id uuid not null references public.productions (id) on delete cascade,
  user_id       uuid not null references public.profiles (id) on delete cascade,
  role          public.production_role not null,
  added_by      uuid references public.profiles (id) on delete set null,
  created_at    timestamptz not null default now(),
  updated_at    timestamptz not null default now(),
  primary key (production_id, user_id)
);
create index production_members_user_idx on public.production_members (user_id);
create trigger production_members_touch before update on public.production_members
  for each row execute function public.touch_updated_at();

-- ── invitations ──────────────────────────────────────────────────────────────────────────
-- Sign-up is invite-only. An admin creates an invitation and the API sends Supabase's invite
-- email; when the invited user's auth row appears, handle_new_user() applies every pending
-- invitation for that email (workspace role + production roles).
create table public.invitations (
  id              uuid primary key default gen_random_uuid(),
  email           text not null check (email = lower(email)),
  app_role        public.app_role not null default 'member',
  production_id   uuid references public.productions (id) on delete cascade,
  production_role public.production_role,
  invited_by      uuid references public.profiles (id) on delete set null,
  accepted_at     timestamptz,
  created_at      timestamptz not null default now(),
  check ((production_id is null) = (production_role is null))
);
create unique index invitations_pending_key
  on public.invitations (email, coalesce(production_id, '00000000-0000-0000-0000-000000000000'::uuid))
  where accepted_at is null;

-- ── audit ────────────────────────────────────────────────────────────────────────────────
create table public.audit_log (
  id            bigint generated always as identity primary key,
  production_id uuid references public.productions (id) on delete cascade,
  actor_user_id uuid references public.profiles (id) on delete set null,
  actor_agent   text,                -- set when an agent made the change on a user's behalf
  action        text not null,       -- e.g. 'production.create', 'member.role_change'
  entity        text not null,
  entity_id     text,
  diff          jsonb not null default '{}'::jsonb,
  created_at    timestamptz not null default now()
);
create index audit_log_production_idx on public.audit_log (production_id, created_at desc);

-- ── jobs ─────────────────────────────────────────────────────────────────────────────────
create table public.jobs (
  id            uuid primary key default gen_random_uuid(),
  kind          text not null,       -- contracts.jobs.JobKind; text so a new kind needs no migration
  status        public.job_status not null default 'pending',
  production_id uuid references public.productions (id) on delete cascade,
  requested_by  uuid references public.profiles (id) on delete set null,
  request       jsonb not null default '{}'::jsonb,
  result        jsonb,
  error         text,
  cursor        integer not null default 0,
  created_at    timestamptz not null default now(),
  updated_at    timestamptz not null default now()
);
create index jobs_production_idx on public.jobs (production_id, created_at desc);
create index jobs_requested_by_idx on public.jobs (requested_by, created_at desc);
create trigger jobs_touch before update on public.jobs
  for each row execute function public.touch_updated_at();

create table public.job_events (
  seq        bigint generated always as identity primary key,
  job_id     uuid not null references public.jobs (id) on delete cascade,
  type       text not null,          -- contracts.jobs.JobEventType
  agent      text,
  payload    jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now()
);
create index job_events_job_idx on public.job_events (job_id, seq);

-- ── access helpers ───────────────────────────────────────────────────────────────────────
-- SECURITY DEFINER so policies can consult membership without recursing through RLS.
-- An inactive profile has no access at all, whatever its roles say.
create or replace function public.is_admin()
returns boolean
language sql stable security definer
set search_path = ''
as $$
  select exists (
    select 1 from public.profiles p
    where p.id = auth.uid() and p.active and p.app_role = 'admin'
  );
$$;

create or replace function public.is_active_user()
returns boolean
language sql stable security definer
set search_path = ''
as $$
  select exists (select 1 from public.profiles p where p.id = auth.uid() and p.active);
$$;

create or replace function public.my_production_role(target uuid)
returns public.production_role
language sql stable security definer
set search_path = ''
as $$
  select m.role
  from public.production_members m
  join public.profiles p on p.id = m.user_id
  where m.production_id = target and m.user_id = auth.uid() and p.active;
$$;

create or replace function public.can_view_production(target uuid)
returns boolean
language sql stable security definer
set search_path = ''
as $$
  select public.is_admin() or public.my_production_role(target) is not null;
$$;

revoke all on function public.is_admin() from public, anon;
revoke all on function public.is_active_user() from public, anon;
revoke all on function public.my_production_role(uuid) from public, anon;
revoke all on function public.can_view_production(uuid) from public, anon;
grant execute on function public.is_admin() to authenticated;
grant execute on function public.is_active_user() to authenticated;
grant execute on function public.my_production_role(uuid) to authenticated;
grant execute on function public.can_view_production(uuid) to authenticated;

-- ── new user → profile + invitations ─────────────────────────────────────────────────────
create or replace function public.handle_new_user()
returns trigger
language plpgsql security definer
set search_path = ''
as $$
declare
  v_email text := lower(coalesce(new.email, ''));
  v_name  text := coalesce(new.raw_user_meta_data ->> 'display_name',
                           new.raw_user_meta_data ->> 'full_name',
                           split_part(v_email, '@', 1));
  v_role  public.app_role := 'member';
begin
  if exists (select 1 from public.invitations i
             where i.email = v_email and i.accepted_at is null and i.app_role = 'admin') then
    v_role := 'admin';
  end if;

  insert into public.profiles (id, email, display_name, app_role)
  values (new.id, v_email, v_name, v_role)
  on conflict (id) do nothing;

  insert into public.production_members (production_id, user_id, role, added_by)
  select i.production_id, new.id, i.production_role, i.invited_by
  from public.invitations i
  where i.email = v_email and i.accepted_at is null and i.production_id is not null
  on conflict (production_id, user_id) do nothing;

  update public.invitations set accepted_at = now()
  where email = v_email and accepted_at is null;

  return new;
end;
$$;

create trigger on_auth_user_created
  after insert on auth.users
  for each row execute function public.handle_new_user();

-- ── row level security (read-only for browser roles) ─────────────────────────────────────
alter table public.profiles           enable row level security;
alter table public.productions        enable row level security;
alter table public.production_members enable row level security;
alter table public.invitations        enable row level security;
alter table public.audit_log          enable row level security;
alter table public.jobs               enable row level security;
alter table public.job_events         enable row level security;

-- Staff directory: every active signed-in user may see who else is on the workspace.
create policy profiles_read on public.profiles
  for select to authenticated
  using (public.is_active_user());

create policy productions_read on public.productions
  for select to authenticated
  using (public.can_view_production(id));

create policy production_members_read on public.production_members
  for select to authenticated
  using (public.can_view_production(production_id));

create policy invitations_read on public.invitations
  for select to authenticated
  using (public.is_admin());

create policy audit_log_read on public.audit_log
  for select to authenticated
  using (public.is_admin()
         or (production_id is not null and public.can_view_production(production_id)));

create policy jobs_read on public.jobs
  for select to authenticated
  using (public.is_admin()
         or (production_id is not null and public.can_view_production(production_id))
         or (production_id is null and requested_by = auth.uid()));

create policy job_events_read on public.job_events
  for select to authenticated
  using (exists (select 1 from public.jobs j where j.id = job_id));  -- inherits jobs_read

-- ── realtime ─────────────────────────────────────────────────────────────────────────────
-- The browser follows job progress here (RLS applies to Realtime postgres_changes).
alter publication supabase_realtime add table public.jobs, public.job_events;
