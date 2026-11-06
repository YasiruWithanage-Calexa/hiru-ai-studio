-- Shot Planner David keeps its plan on the scene and may be named as a shot's planner (plan/2026-11-05e, Phase 3). A scene
-- David never planned keeps the default; a browser role reads the new column only where it could already read the row.
begin;
select plan(6);

select has_column('public', 'scenes', 'david', 'a scene keeps David''s plan');

insert into public.productions (id, title, orientation)
  values ('00000000-0000-0000-0000-0000000000e1', 'David test', 'vertical');
insert into public.episodes (id, production_id, number, title)
  values ('00000000-0000-0000-0000-0000000000e2', '00000000-0000-0000-0000-0000000000e1', 1, 'Ep 1');
insert into public.scenes (id, production_id, episode_id, number, envelope_s)
  values ('00000000-0000-0000-0000-0000000000e3', '00000000-0000-0000-0000-0000000000e1',
          '00000000-0000-0000-0000-0000000000e2', 1, 60);
insert into public.shots (production_id, scene_id, number, duration_s, planner)
  values ('00000000-0000-0000-0000-0000000000e1', '00000000-0000-0000-0000-0000000000e3', 1, 6, 'david');

select is((select david from public.scenes where number = 1), '{}'::jsonb, 'a scene David never planned has no plan');
select is((select planner from public.shots where number = 1), 'david', 'a shot may be planned by David');
select lives_ok(
  $$insert into public.shots (production_id, scene_id, number, duration_s, planner)
    values ('00000000-0000-0000-0000-0000000000e1', '00000000-0000-0000-0000-0000000000e3', 2, 4, 'adam')$$,
  'and still by Adam');
select lives_ok(
  $$update public.scenes set david = '{"planner": "david", "plan": {}}'::jsonb where number = 1$$,
  'a plan can be stored on the scene');
select throws_ok(
  $$insert into public.shots (production_id, scene_id, number, duration_s, planner)
    values ('00000000-0000-0000-0000-0000000000e1', '00000000-0000-0000-0000-0000000000e3', 3, 4, 'other')$$,
  '23514', null, 'only classic, adam or david may plan a shot');

select * from finish();
rollback;
