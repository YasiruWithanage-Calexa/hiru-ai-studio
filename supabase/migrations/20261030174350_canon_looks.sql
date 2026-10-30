-- Looks: what a character wears for a stretch of episodes. A character keeps ONE base sheet (the
-- entity's reference sheet: who they are) and many looks, each painted from the base sheet so the
-- face and body stay the same and only clothes, hair, makeup and accessories change. Shape of a
-- row: contracts.canon.CanonLook.
--
-- Same access model as before: RLS is READ-ONLY for browser roles; the API and the frame_render
-- function (service role) write.

create table public.canon_looks (
  id            uuid primary key default gen_random_uuid(),
  entity_id     uuid not null references public.canon_entities (id) on delete cascade,
  production_id uuid not null references public.productions (id) on delete cascade,
  name          text not null check (char_length(name) between 1 and 120),
  -- Inclusive episode numbers: [{"from": 1, "to": 20}, {"from": 44, "to": 44}]
  ranges        jsonb not null default '[]'::jsonb check (jsonb_typeof(ranges) = 'array'),
  outfit        text not null default '',
  hair          text not null default '',
  makeup        text not null default '',
  accessories   text not null default '',                  -- jewelry, watch, cap, glasses, bag
  status        text not null default 'draft' check (status in ('draft', 'ready')),
  sheet_assets  jsonb not null default '[]'::jsonb,        -- look sheets in the `references` bucket, newest first
  created_by    uuid references public.profiles (id) on delete set null,
  created_at    timestamptz not null default now(),
  updated_at    timestamptz not null default now()
);
create unique index canon_looks_name_key on public.canon_looks (entity_id, lower(name));
create index canon_looks_production_idx on public.canon_looks (production_id);
create index canon_looks_created_by_idx on public.canon_looks (created_by);
create trigger canon_looks_touch before update on public.canon_looks
  for each row execute function public.touch_updated_at();

alter table public.canon_looks enable row level security;
create policy canon_looks_read on public.canon_looks
  for select to authenticated using (public.can_view_production(production_id));
