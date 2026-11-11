-- The scene breakdown's two memories and the scene packet (plan/2026-11-11 §5, schema v21): the tables are there with RLS
-- on, a packet's scene key has the memory's shape, and a browser role reads a production's rows only where it can see the
-- production and never writes them.
begin;
select plan(9);

select has_table('public', 'source_memories', 'each document keeps its source memory');
select has_table('public', 'breakdown_memories', 'each production keeps its breakdown memory');
select has_table('public', 'scene_packets', 'each scene keeps its packet');

insert into public.productions (id, title, orientation)
  values ('00000000-0000-0000-0000-0000000000f1', 'Breakdown test', 'horizontal');
insert into public.episodes (id, production_id, number, title)
  values ('00000000-0000-0000-0000-0000000000f2', '00000000-0000-0000-0000-0000000000f1', 1, 'Ep 1');
insert into public.scenes (id, production_id, episode_id, number, envelope_s)
  values ('00000000-0000-0000-0000-0000000000f3', '00000000-0000-0000-0000-0000000000f1',
          '00000000-0000-0000-0000-0000000000f2', 1, 60);

select lives_ok(
  $$insert into public.breakdown_memories (production_id, body)
    values ('00000000-0000-0000-0000-0000000000f1', '{"document": "x"}'::jsonb)$$,
  'a production keeps one breakdown memory');
select lives_ok(
  $$insert into public.scene_packets (scene_id, production_id, scene_key, script_version)
    values ('00000000-0000-0000-0000-0000000000f3', '00000000-0000-0000-0000-0000000000f1', 'E01-S01', 1)$$,
  'a scene keeps its packet');
select is((select waits from public.scene_packets where scene_key = 'E01-S01'), '[]'::jsonb,
          'a packet waits for nothing unless it says so');
select throws_ok(
  $$insert into public.scene_packets (scene_id, production_id, scene_key)
    values ('00000000-0000-0000-0000-0000000000f3', '00000000-0000-0000-0000-0000000000f1', 'scene one')$$,
  '23514', null, 'a scene key is the memory''s id (E01-S03)');

-- a browser role that is no member sees nothing and writes nothing
set local role authenticated;
set local request.jwt.claims to '{"sub": "00000000-0000-0000-0000-0000000000ff", "role": "authenticated"}';
select is_empty($$select 1 from public.scene_packets$$, 'a stranger reads no packet');
select throws_ok(
  $$insert into public.breakdown_memories (production_id, body)
    values ('00000000-0000-0000-0000-0000000000f1', '{}'::jsonb)$$,
  '42501', null, 'no browser writes a memory');

select * from finish();
rollback;
