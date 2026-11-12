-- Canon refine (plan/2026-11-12c §3.3, §3.4). Schema v23 (Database/schema_v23.sql, upgrade_v22_to_v23.sql).
--
-- A canon version may come from 'refine' (an agent read the finished breakdown and wrote real cards) and records where
-- each refined field came from; a place or thing gets a class (only sets, vehicles and props are painted) and a spot
-- its parent set; looks and scene looks say who made them, and a scene look carries the scene's condition.
-- canon_refine_apply() writes one refine's answer in one transaction.

-- a version written by the canon refine; what each refined field was read from
alter table public.canon_versions drop constraint if exists canon_versions_source_check;
alter table public.canon_versions
  add constraint canon_versions_source_check check (source in ('extract', 'user', 'inferred', 'refine'));
comment on column public.canon_versions.source is
  'extract: read from a document; user: a person''s edit; inferred: implied by the script, not named in it (plan/2026-11-12); refine: written by the canon refine from the breakdown (plan/2026-11-12c)';
alter table public.canon_versions add column if not exists provenance jsonb not null default '{}'::jsonb;
comment on column public.canon_versions.provenance is
  'field -> {source: script|inferred, line, reason}: where each refined value came from (plan/2026-11-12c)';

-- what kind of place or thing an entry is, and the set a spot belongs to
alter table public.canon_entities add column if not exists class text;
alter table public.canon_entities drop constraint if exists canon_entities_class_check;
alter table public.canon_entities add constraint canon_entities_class_check
  check (class is null or class in ('set', 'vehicle', 'region', 'spot', 'unseen', 'prop', 'mentioned'));
alter table public.canon_entities add column if not exists parent_id uuid
  references public.canon_entities (id) on delete set null;
create index if not exists canon_entities_parent_idx on public.canon_entities (parent_id);
comment on column public.canon_entities.class is
  'place: set, vehicle, region, spot, unseen; thing: prop, mentioned; null: not classed (a person, or not refined). Only sets, vehicles and props get a reference plate (plan/2026-11-12c)';
comment on column public.canon_entities.parent_id is 'a spot''s set or vehicle (plan/2026-11-12c)';

-- who made a look, and the condition a scene puts on it
alter table public.canon_looks add column if not exists origin text not null default 'person';
alter table public.canon_looks drop constraint if exists canon_looks_origin_check;
alter table public.canon_looks add constraint canon_looks_origin_check check (origin in ('person', 'refine'));
alter table public.scene_looks add column if not exists condition text not null default '';
alter table public.scene_looks add column if not exists why text not null default '';
alter table public.scene_looks add column if not exists origin text not null default 'person';
alter table public.scene_looks drop constraint if exists scene_looks_origin_check;
alter table public.scene_looks add constraint scene_looks_origin_check check (origin in ('person', 'refine'));
comment on column public.scene_looks.condition is
  'the state of the outfit and the person in this scene only (wet from the rain, lying still); never part of the look (plan/2026-11-12c)';

-- ── canon refine (plan/2026-11-12c §3.4) ─────────────────────────────────────────────────
-- Writes a canon refine's answer in ONE transaction, so readers see all of the old canon or all of the new:
--   1. every new version is inserted (never current yet); a card the entity already has (same card_hash) is reused,
--      so a re-run with the same answer inserts nothing;
--   2. an entity switches to its new version only if its current version is the one the job read
--      (expected_version_id), that version came from extract, inferred or refine, and the entity is not locked;
--   3. otherwise the new version stays a proposal (inserted, not current) for a person to accept;
--   4. draft looks are added where the character has no look of that name (a person's look is never replaced), and a
--      scene look is written only where no person chose one (origin 'person' wins).
-- Called by the canon refine job with the service role; browser roles have no use for it.
create or replace function public.canon_refine_apply(p_production uuid, p_payload jsonb)
returns jsonb
language plpgsql
set search_path = ''
as $$
declare
  v jsonb;
  item jsonb;
  ent public.canon_entities%rowtype;
  cur_source text;
  ver_id uuid;
  next_no integer;
  chosen uuid;
  n integer;
  switched integer := 0;
  proposed integer := 0;
  changed integer := 0;
  kept integer := 0;
  looks_made integer := 0;
  scene_looks_made integer := 0;
  actor uuid := nullif(p_payload->>'actor', '')::uuid;
begin
  for v in select value from jsonb_array_elements(coalesce(p_payload->'versions', '[]'::jsonb)) loop
    select * into ent from public.canon_entities
      where id = (v->>'entity_id')::uuid and production_id = p_production
      for update;
    if not found then
      continue;
    end if;
    ver_id := null;
    select cv.id into ver_id from public.canon_versions cv
      where cv.entity_id = ent.id and cv.card_hash = v->>'card_hash'
      order by cv.version desc limit 1;
    if ver_id is null then
      select coalesce(max(cv.version), 0) + 1 into next_no from public.canon_versions cv where cv.entity_id = ent.id;
      insert into public.canon_versions (entity_id, production_id, version, card, card_hash, wardrobe_anchor,
                                         voice_pin, reference_prompt, source, provenance, created_by)
      values (ent.id, p_production, next_no, coalesce(v->'card', '{}'::jsonb), v->>'card_hash',
              coalesce(v->>'wardrobe_anchor', ''), coalesce(v->>'voice_pin', ''),
              coalesce(v->>'reference_prompt', ''), 'refine', coalesce(v->'provenance', '{}'::jsonb), actor)
      returning id into ver_id;
    end if;
    if ent.current_version_id = ver_id then
      kept := kept + 1;
    elsif ent.current_version_id is distinct from nullif(v->>'expected_version_id', '')::uuid then
      changed := changed + 1;
    else
      select cv.source into cur_source from public.canon_versions cv where cv.id = ent.current_version_id;
      if not ent.locked and coalesce(cur_source, 'extract') in ('extract', 'inferred', 'refine') then
        update public.canon_entities set current_version_id = ver_id where id = ent.id;
        switched := switched + 1;
      else
        proposed := proposed + 1;
      end if;
    end if;
    if v ? 'class' and (not ent.locked or ent.class is null) then
      update public.canon_entities
        set class = nullif(v->>'class', ''),
            parent_id = (select p.id from public.canon_entities p
                          where p.id = nullif(v->>'parent_id', '')::uuid and p.production_id = p_production
                            and p.id <> ent.id)
        where id = ent.id;
    end if;
  end loop;

  for item in select value from jsonb_array_elements(coalesce(p_payload->'looks', '[]'::jsonb)) loop
    insert into public.canon_looks (entity_id, production_id, name, ranges, outfit, hair, makeup, accessories,
                                    status, origin, created_by)
    select e.id, p_production, item->>'name', coalesce(item->'ranges', '[]'::jsonb), coalesce(item->>'outfit', ''),
           coalesce(item->>'hair', ''), coalesce(item->>'makeup', ''), coalesce(item->>'accessories', ''),
           'draft', 'refine', actor
      from public.canon_entities e
      where e.id = (item->>'entity_id')::uuid and e.production_id = p_production and e.kind = 'character'
    on conflict (entity_id, lower(name)) do nothing;
    get diagnostics n = row_count;
    looks_made := looks_made + n;
  end loop;

  for item in select value from jsonb_array_elements(coalesce(p_payload->'scene_looks', '[]'::jsonb)) loop
    chosen := null;
    select l.id into chosen from public.canon_looks l
      where l.entity_id = (item->>'entity_id')::uuid and l.production_id = p_production
        and lower(l.name) = lower(item->>'look_name');
    if chosen is null
       or not exists (select 1 from public.scenes s
                       where s.id = (item->>'scene_id')::uuid and s.production_id = p_production) then
      continue;
    end if;
    insert into public.scene_looks (scene_id, entity_id, look_id, production_id, condition, why, origin)
    values ((item->>'scene_id')::uuid, (item->>'entity_id')::uuid, chosen, p_production,
            coalesce(item->>'condition', ''), coalesce(item->>'why', ''), 'refine')
    on conflict (scene_id, entity_id) do update
      set look_id = excluded.look_id, condition = excluded.condition, why = excluded.why
      where public.scene_looks.origin = 'refine';
    get diagnostics n = row_count;
    scene_looks_made := scene_looks_made + n;
  end loop;

  return jsonb_build_object('switched', switched, 'proposed', proposed, 'skipped_changed', changed,
                            'unchanged', kept, 'looks', looks_made, 'scene_looks', scene_looks_made);
end;
$$;

revoke all on function public.canon_refine_apply(uuid, jsonb) from public, anon, authenticated;
grant execute on function public.canon_refine_apply(uuid, jsonb) to service_role;
