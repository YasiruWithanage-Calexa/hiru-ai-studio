-- Shot Planner Jonathan keeps its plan on the scene and may be named as a shot's planner (plan/2026-11-06b, Phase 3). A scene
-- Jonathan never planned keeps the default; a browser role reads the new column only where it could already read the row.
begin;
select plan(6);

select has_column('public', 'scenes', 'jonathan', 'a scene keeps Jonathan''s plan');

insert into public.productions (id, title, orientation)
  values ('00000000-0000-0000-0000-0000000000f1', 'Jonathan test', 'vertical');
insert into public.episodes (id, production_id, number, title)
  values ('00000000-0000-0000-0000-0000000000f2', '00000000-0000-0000-0000-0000000000f1', 1, 'Ep 1');
insert into public.scenes (id, production_id, episode_id, number, envelope_s)
  values ('00000000-0000-0000-0000-0000000000f3', '00000000-0000-0000-0000-0000000000f1',
          '00000000-0000-0000-0000-0000000000f2', 1, 60);
insert into public.shots (production_id, scene_id, number, duration_s, planner)
  values ('00000000-0000-0000-0000-0000000000f1', '00000000-0000-0000-0000-0000000000f3', 1, 6, 'jonathan');

select is((select jonathan from public.scenes where number = 1), '{}'::jsonb, 'a scene Jonathan never planned has no plan');
select is((select planner from public.shots where number = 1), 'jonathan', 'a shot may be planned by Jonathan');
select lives_ok(
  $$insert into public.shots (production_id, scene_id, number, duration_s, planner)
    values ('00000000-0000-0000-0000-0000000000f1', '00000000-0000-0000-0000-0000000000f3', 2, 4, 'david')$$,
  'and still by David');
select lives_ok(
  $$update public.scenes set jonathan = '{"planner": "jonathan", "plan": {}}'::jsonb where number = 1$$,
  'a plan can be stored on the scene');
select throws_ok(
  $$insert into public.shots (production_id, scene_id, number, duration_s, planner)
    values ('00000000-0000-0000-0000-0000000000f1', '00000000-0000-0000-0000-0000000000f3', 3, 4, 'other')$$,
  '23514', null, 'only classic, adam, david or jonathan may plan a shot');

select * from finish();
rollback;
