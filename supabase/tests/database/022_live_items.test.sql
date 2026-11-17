-- `/live` in one query (plan/2026-11-13d phase 3, schema v25): active work of one production only, finished work only
-- when it changed after `since`, the build's newest event number, and no browser role may call it.
begin;
select plan(8);

insert into public.productions (id, title, orientation) values
  ('00000000-0000-0000-0000-0000000000d1', 'Live test', 'horizontal'),
  ('00000000-0000-0000-0000-0000000000d9', 'Other', 'horizontal');
insert into public.episodes (id, production_id, number, title)
  values ('00000000-0000-0000-0000-0000000000d2', '00000000-0000-0000-0000-0000000000d1', 1, 'Ep 1');
insert into public.scenes (id, production_id, episode_id, number, envelope_s)
  values ('00000000-0000-0000-0000-0000000000d3', '00000000-0000-0000-0000-0000000000d1',
          '00000000-0000-0000-0000-0000000000d2', 1, 60);
insert into public.shots (id, production_id, scene_id, number, duration_s)
  values ('00000000-0000-0000-0000-0000000000d4', '00000000-0000-0000-0000-0000000000d1',
          '00000000-0000-0000-0000-0000000000d3', 1, 8);
insert into public.first_frames (id, production_id, shot_id, status, updated_at) values
  ('00000000-0000-0000-0000-00000000d101', '00000000-0000-0000-0000-0000000000d1',
   '00000000-0000-0000-0000-0000000000d4', 'running', now()),
  ('00000000-0000-0000-0000-00000000d102', '00000000-0000-0000-0000-0000000000d1',
   '00000000-0000-0000-0000-0000000000d4', 'done', now() - interval '1 hour');
insert into public.jobs (id, kind, status, production_id) values
  ('00000000-0000-0000-0000-00000000d201', 'structure_build', 'running', '00000000-0000-0000-0000-0000000000d1'),
  ('00000000-0000-0000-0000-00000000d202', 'shot_produce', 'running', '00000000-0000-0000-0000-0000000000d1'),
  ('00000000-0000-0000-0000-00000000d209', 'structure_build', 'running', '00000000-0000-0000-0000-0000000000d9');
insert into public.job_events (job_id, type, payload) values
  ('00000000-0000-0000-0000-00000000d201', 'stage', '{"stage": "read", "state": "active"}'),
  ('00000000-0000-0000-0000-00000000d201', 'agent_step', '{"text": "Read 1 file."}');

select is(
  (select count(*)::int from public.live_items('00000000-0000-0000-0000-0000000000d1')),
  3, 'without since: the running frame and the two running jobs of this production only');
select ok(
  not exists (select 1 from public.live_items('00000000-0000-0000-0000-0000000000d1')
               where id = '00000000-0000-0000-0000-00000000d102'),
  'a frame that finished long ago is not listed');
select is(
  (select seq from public.live_items('00000000-0000-0000-0000-0000000000d1')
    where id = '00000000-0000-0000-0000-00000000d201'),
  (select max(seq) from public.job_events where job_id = '00000000-0000-0000-0000-00000000d201'),
  'the build carries its newest event number');
select ok(
  (select seq is null from public.live_items('00000000-0000-0000-0000-0000000000d1')
    where id = '00000000-0000-0000-0000-00000000d202'),
  'any other job carries none');
select is(
  (select count(*)::int from public.live_items('00000000-0000-0000-0000-0000000000d1', now() - interval '2 hours')),
  4, 'with since: the frame that finished after it too');
select is(
  (select kind || '/' || shot_id::text from public.live_items('00000000-0000-0000-0000-0000000000d1')
    where id = '00000000-0000-0000-0000-00000000d101'),
  'frame/00000000-0000-0000-0000-0000000000d4', 'a frame names its shot');

set local role authenticated;
select throws_ok(
  $$select * from public.live_items('00000000-0000-0000-0000-0000000000d1')$$,
  '42501', null, 'a signed-in browser may not call it');
reset role;
set local role anon;
select throws_ok(
  $$select * from public.live_items('00000000-0000-0000-0000-0000000000d1')$$,
  '42501', null, 'nor may anyone signed out');
reset role;

select * from finish();
rollback;
