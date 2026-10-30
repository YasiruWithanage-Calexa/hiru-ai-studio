-- Scene looks: which look of a character this scene uses. A person picks it in the Director panel's
-- Canon tab. A scene with no pick for a character follows the episode rule (the narrowest ready
-- look that covers the episode). One row per character per scene; deleting the row goes back to
-- the rule. Shape of a row: contracts.canon.SceneLook.
--
-- Same access model as before: RLS is READ-ONLY for browser roles; the API writes.

create table public.scene_looks (
  scene_id      uuid not null references public.scenes (id) on delete cascade,
  entity_id     uuid not null references public.canon_entities (id) on delete cascade,
  look_id       uuid not null references public.canon_looks (id) on delete cascade,
  production_id uuid not null references public.productions (id) on delete cascade,
  chosen_by     uuid references public.profiles (id) on delete set null,
  created_at    timestamptz not null default now(),
  updated_at    timestamptz not null default now(),
  primary key (scene_id, entity_id)
);
create index scene_looks_look_idx on public.scene_looks (look_id);
create index scene_looks_entity_idx on public.scene_looks (entity_id);
create index scene_looks_production_idx on public.scene_looks (production_id);
create index scene_looks_chosen_by_idx on public.scene_looks (chosen_by);
create trigger scene_looks_touch before update on public.scene_looks
  for each row execute function public.touch_updated_at();

alter table public.scene_looks enable row level security;
create policy scene_looks_read on public.scene_looks
  for select to authenticated using (public.can_view_production(production_id));
