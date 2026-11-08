-- Shot Planner Raphael keeps its result on the scene and may be named as a shot's planner (plan/2026-11-08e, Phase 4). A scene
-- Raphael never planned keeps the defaults; the clip fields of a shot have closed lists; a browser role reads the new columns
-- only where it could already read the row.
begin;
select plan(11);

select has_column('public', 'scenes', 'raphael', 'a scene keeps Raphael''s result');
select has_column('public', 'shots', 'slate', 'a shot keeps its slate');

insert into public.productions (id, title, orientation)
  values ('00000000-0000-0000-0000-0000000000e1', 'Raphael test', 'vertical');
insert into public.episodes (id, production_id, number, title)
  values ('00000000-0000-0000-0000-0000000000e2', '00000000-0000-0000-0000-0000000000e1', 1, 'Ep 1');
insert into public.scenes (id, production_id, episode_id, number, envelope_s)
  values ('00000000-0000-0000-0000-0000000000e3', '00000000-0000-0000-0000-0000000000e1',
          '00000000-0000-0000-0000-0000000000e2', 1, 60);
insert into public.shots (production_id, scene_id, number, duration_s, planner, role, priority, slate, stage, anchor, blend)
  values ('00000000-0000-0000-0000-0000000000e1', '00000000-0000-0000-0000-0000000000e3', 1, 6, 'raphael',
          'insert', 'nice', '1B-1', 2, '["1A-1"]'::jsonb, 'cut_in');

select is((select raphael from public.scenes where number = 1), '{}'::jsonb, 'a scene Raphael never planned has no result');
select is((select planner from public.shots where number = 1), 'raphael', 'a shot may be planned by Raphael');
select is((select stage from public.shots where number = 1), 2::smallint, 'and says which stage made it');
select lives_ok(
  $$insert into public.shots (production_id, scene_id, number, duration_s, planner)
    values ('00000000-0000-0000-0000-0000000000e1', '00000000-0000-0000-0000-0000000000e3', 2, 4, 'jonathan')$$,
  'and still by Jonathan, with the defaults for the clip fields');
select lives_ok(
  $$update public.scenes set raphael = '{"planner": "raphael", "clips": []}'::jsonb where number = 1$$,
  'a result can be stored on the scene');
select throws_ok(
  $$insert into public.shots (production_id, scene_id, number, duration_s, planner)
    values ('00000000-0000-0000-0000-0000000000e1', '00000000-0000-0000-0000-0000000000e3', 3, 4, 'other')$$,
  '23514', null, 'only the five planners may plan a shot');
select throws_ok(
  $$insert into public.shots (production_id, scene_id, number, duration_s, priority)
    values ('00000000-0000-0000-0000-0000000000e1', '00000000-0000-0000-0000-0000000000e3', 4, 4, 'urgent')$$,
  '23514', null, 'a priority is must, should or nice');
select throws_ok(
  $$insert into public.shots (production_id, scene_id, number, duration_s, blend)
    values ('00000000-0000-0000-0000-0000000000e1', '00000000-0000-0000-0000-0000000000e3', 5, 4, 'dissolve')$$,
  '23514', null, 'a blend is one of the five');
select throws_ok(
  $$insert into public.shots (production_id, scene_id, number, duration_s, stage)
    values ('00000000-0000-0000-0000-0000000000e1', '00000000-0000-0000-0000-0000000000e3', 6, 4, 3)$$,
  '23514', null, 'a stage is 0, 1 or 2');

select * from finish();
rollback;
