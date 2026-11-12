-- The canon refine's write (plan/2026-11-12c §3.4, schema v23): an extracted card switches to the refined one, a locked
-- card keeps its version and the refined one waits as a proposal, a card changed since the job read it is skipped, a
-- re-run inserts nothing, a person's look and scene look are never replaced, and no browser role may call it.
begin;
select plan(13);

insert into public.productions (id, title, orientation)
  values ('00000000-0000-0000-0000-0000000000c1', 'Refine test', 'horizontal');
insert into public.episodes (id, production_id, number, title)
  values ('00000000-0000-0000-0000-0000000000c2', '00000000-0000-0000-0000-0000000000c1', 1, 'Ep 1');
insert into public.scenes (id, production_id, episode_id, number, envelope_s)
  values ('00000000-0000-0000-0000-0000000000c3', '00000000-0000-0000-0000-0000000000c1',
          '00000000-0000-0000-0000-0000000000c2', 1, 60);
-- Dinu (extract), Aruni (locked), Nimal (changed since read), the garage (a set), the gate (a spot)
insert into public.canon_entities (id, production_id, kind, code, name, locked) values
  ('00000000-0000-0000-0000-00000000c101', '00000000-0000-0000-0000-0000000000c1', 'character', 'C01', 'Dinu', false),
  ('00000000-0000-0000-0000-00000000c102', '00000000-0000-0000-0000-0000000000c1', 'character', 'C02', 'Aruni', true),
  ('00000000-0000-0000-0000-00000000c103', '00000000-0000-0000-0000-0000000000c1', 'character', 'C03', 'Nimal', false),
  ('00000000-0000-0000-0000-00000000c104', '00000000-0000-0000-0000-0000000000c1', 'location', 'L01', 'Canal', false),
  ('00000000-0000-0000-0000-00000000c105', '00000000-0000-0000-0000-0000000000c1', 'location', 'L02', 'Gate', false);
insert into public.canon_versions (id, entity_id, production_id, version, card, card_hash, source) values
  ('00000000-0000-0000-0000-00000000c201', '00000000-0000-0000-0000-00000000c101', '00000000-0000-0000-0000-0000000000c1', 1, '{}', 'a1', 'extract'),
  ('00000000-0000-0000-0000-00000000c202', '00000000-0000-0000-0000-00000000c102', '00000000-0000-0000-0000-0000000000c1', 1, '{}', 'a2', 'extract'),
  ('00000000-0000-0000-0000-00000000c203', '00000000-0000-0000-0000-00000000c103', '00000000-0000-0000-0000-0000000000c1', 1, '{}', 'a3', 'extract'),
  ('00000000-0000-0000-0000-00000000c204', '00000000-0000-0000-0000-00000000c103', '00000000-0000-0000-0000-0000000000c1', 2, '{}', 'a4', 'user'),
  ('00000000-0000-0000-0000-00000000c205', '00000000-0000-0000-0000-00000000c104', '00000000-0000-0000-0000-0000000000c1', 1, '{}', 'a5', 'extract'),
  ('00000000-0000-0000-0000-00000000c206', '00000000-0000-0000-0000-00000000c105', '00000000-0000-0000-0000-0000000000c1', 1, '{}', 'a6', 'extract');
update public.canon_entities set current_version_id = '00000000-0000-0000-0000-00000000c201' where code = 'C01';
update public.canon_entities set current_version_id = '00000000-0000-0000-0000-00000000c202' where code = 'C02';
update public.canon_entities set current_version_id = '00000000-0000-0000-0000-00000000c204' where code = 'C03';
update public.canon_entities set current_version_id = '00000000-0000-0000-0000-00000000c205' where code = 'L01';
update public.canon_entities set current_version_id = '00000000-0000-0000-0000-00000000c206' where code = 'L02';
-- a person's own look for Dinu, chosen for the scene
insert into public.canon_looks (id, entity_id, production_id, name, ranges, outfit) values
  ('00000000-0000-0000-0000-00000000c301', '00000000-0000-0000-0000-00000000c101', '00000000-0000-0000-0000-0000000000c1',
   'Mine', '[{"from":1,"to":1}]', 'a red shirt');
insert into public.scene_looks (scene_id, entity_id, look_id, production_id) values
  ('00000000-0000-0000-0000-0000000000c3', '00000000-0000-0000-0000-00000000c101',
   '00000000-0000-0000-0000-00000000c301', '00000000-0000-0000-0000-0000000000c1');

create temporary table payload as select $j${
  "versions": [
    {"entity_id": "00000000-0000-0000-0000-00000000c101", "expected_version_id": "00000000-0000-0000-0000-00000000c201",
     "card": {"age": "30"}, "card_hash": "b1", "provenance": {"age": {"source": "script", "line": 17, "reason": ""}}},
    {"entity_id": "00000000-0000-0000-0000-00000000c102", "expected_version_id": "00000000-0000-0000-0000-00000000c202",
     "card": {"age": "27"}, "card_hash": "b2"},
    {"entity_id": "00000000-0000-0000-0000-00000000c103", "expected_version_id": "00000000-0000-0000-0000-00000000c203",
     "card": {"age": "34"}, "card_hash": "b3"},
    {"entity_id": "00000000-0000-0000-0000-00000000c104", "expected_version_id": "00000000-0000-0000-0000-00000000c205",
     "card": {"look": "a canal"}, "card_hash": "b4", "class": "set", "parent_id": null},
    {"entity_id": "00000000-0000-0000-0000-00000000c105", "expected_version_id": "00000000-0000-0000-0000-00000000c206",
     "card": {"look": "a gate"}, "card_hash": "b5", "class": "spot", "parent_id": "00000000-0000-0000-0000-00000000c104"}
  ],
  "looks": [
    {"entity_id": "00000000-0000-0000-0000-00000000c101", "name": "Work", "ranges": [{"from": 1, "to": 1}], "outfit": "navy shirt"},
    {"entity_id": "00000000-0000-0000-0000-00000000c101", "name": "Mine", "ranges": [{"from": 1, "to": 1}], "outfit": "not mine"},
    {"entity_id": "00000000-0000-0000-0000-00000000c102", "name": "Nurse", "ranges": [{"from": 1, "to": 1}], "outfit": "white"}
  ],
  "scene_looks": [
    {"scene_id": "00000000-0000-0000-0000-0000000000c3", "entity_id": "00000000-0000-0000-0000-00000000c101", "look_name": "Work", "condition": "wet"},
    {"scene_id": "00000000-0000-0000-0000-0000000000c3", "entity_id": "00000000-0000-0000-0000-00000000c102", "look_name": "Nurse", "condition": "tired"}
  ]
}$j$::jsonb as body;

select is(
  public.canon_refine_apply('00000000-0000-0000-0000-0000000000c1', (select body from payload)),
  '{"switched": 3, "proposed": 1, "skipped_changed": 1, "unchanged": 0, "looks": 2, "scene_looks": 1}'::jsonb,
  'an extracted card switches, a locked one is a proposal, a changed one is skipped');
select is((select v.source from public.canon_entities e join public.canon_versions v on v.id = e.current_version_id
            where e.code = 'C01'), 'refine', 'Dinu now reads the refined card');
select is((select current_version_id from public.canon_entities where code = 'C02'),
          '00000000-0000-0000-0000-00000000c202'::uuid, 'the locked card keeps its version');
select is((select count(*)::int from public.canon_versions where entity_id = '00000000-0000-0000-0000-00000000c102'), 2,
          'the locked card''s refined version waits as a proposal');
select is((select current_version_id from public.canon_entities where code = 'C03'),
          '00000000-0000-0000-0000-00000000c204'::uuid, 'a card a person changed since the read is left alone');
select is((select class || ':' || coalesce(parent_id::text, '') from public.canon_entities where code = 'L02'),
          'spot:00000000-0000-0000-0000-00000000c104', 'a spot gets its class and its set');
select is((select outfit from public.canon_looks where name = 'Mine'), 'a red shirt', 'a person''s look is never replaced');
select is((select origin from public.canon_looks where name = 'Work'), 'refine', 'a refined look says so');
select is((select look_id from public.scene_looks where entity_id = '00000000-0000-0000-0000-00000000c101'),
          '00000000-0000-0000-0000-00000000c301'::uuid, 'a person''s scene look wins');
select is((select condition from public.scene_looks where entity_id = '00000000-0000-0000-0000-00000000c102'), 'tired',
          'a refined scene look carries the condition');

select is(
  public.canon_refine_apply('00000000-0000-0000-0000-0000000000c1', (select body from payload)) - 'scene_looks',
  '{"switched": 0, "proposed": 1, "skipped_changed": 1, "unchanged": 3, "looks": 0}'::jsonb,
  'a re-run with the same answer switches nothing new');
select is((select count(*)::int from public.canon_versions where production_id = '00000000-0000-0000-0000-0000000000c1'),
          11, 'and inserts no version');

set local role authenticated;
select throws_ok(
  $$select public.canon_refine_apply('00000000-0000-0000-0000-0000000000c1', '{}'::jsonb)$$,
  '42501', null, 'no browser role may write a refine');

select * from finish();
rollback;
