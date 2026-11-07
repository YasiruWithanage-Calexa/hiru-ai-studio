-- Zora's undo history (plan/2026-11-06e §4.7): scene_plan_revisions are scoped to the production, constrained, one
-- number per scene, read-only for browsers, and follow their scene.
begin;
select plan(9);

delete from public.scene_plan_revisions; delete from public.video_renders; delete from public.takes;
delete from public.video_prompts; delete from public.first_frames;
delete from public.memory_items; delete from public.chat_messages; delete from public.chat_threads;
delete from public.production_director_board;
delete from public.questions; delete from public.dialogue_lines; delete from public.shots;
delete from public.scenes; delete from public.episodes;
delete from public.invitations; delete from public.audit_log; delete from public.productions;
delete from auth.users;

create function pg_temp.as_user(uid uuid) returns void language sql as $$
  select set_config('role', 'authenticated', true),
         set_config('request.jwt.claims', json_build_object('sub', uid, 'role', 'authenticated')::text, true);
$$;

insert into public.productions (id, title, orientation) values
  ('00000000-0000-0000-0000-0000000000a1', 'One', 'horizontal'),
  ('00000000-0000-0000-0000-0000000000a2', 'Two', 'vertical');
insert into public.invitations (email, production_id, production_role) values
  ('crew@hirutv.lk', '00000000-0000-0000-0000-0000000000a1', 'production');
insert into auth.users (id, email) values
  ('00000000-0000-0000-0000-00000000000b', 'crew@hirutv.lk'),
  ('00000000-0000-0000-0000-00000000000d', 'outsider@hirutv.lk');
insert into public.episodes (id, production_id, number) values
  ('00000000-0000-0000-0000-000000000101', '00000000-0000-0000-0000-0000000000a1', 1),
  ('00000000-0000-0000-0000-000000000102', '00000000-0000-0000-0000-0000000000a2', 1);
insert into public.scenes (id, production_id, episode_id, number, envelope_s) values
  ('00000000-0000-0000-0000-000000000201', '00000000-0000-0000-0000-0000000000a1', '00000000-0000-0000-0000-000000000101', 1, 60),
  ('00000000-0000-0000-0000-000000000202', '00000000-0000-0000-0000-0000000000a2', '00000000-0000-0000-0000-000000000102', 1, 60);
insert into public.scene_plan_revisions (production_id, scene_id, revision, kind, stored) values
  ('00000000-0000-0000-0000-0000000000a1', '00000000-0000-0000-0000-000000000201', 1, 'base', '{"planner":"jonathan"}'),
  ('00000000-0000-0000-0000-0000000000a1', '00000000-0000-0000-0000-000000000201', 2, 'turn', '{"planner":"jonathan"}'),
  ('00000000-0000-0000-0000-0000000000a2', '00000000-0000-0000-0000-000000000202', 1, 'base', '{"planner":"jonathan"}');

-- ── constraints ──────────────────────────────────────────────────────────────────────────
select throws_ok($$ insert into public.scene_plan_revisions (production_id, scene_id, revision, kind, stored)
                    values ('00000000-0000-0000-0000-0000000000a1', '00000000-0000-0000-0000-000000000201', 2,
                            'turn', '{}') $$,
                 '23505', null, 'a revision number is used once per scene');
select throws_ok($$ insert into public.scene_plan_revisions (production_id, scene_id, revision, kind, stored)
                    values ('00000000-0000-0000-0000-0000000000a1', '00000000-0000-0000-0000-000000000201', 3,
                            'rewrite', '{}') $$,
                 '23514', null, 'a revision is a base, turn, use, undo or redo');
select throws_ok($$ insert into public.scene_plan_revisions (production_id, scene_id, revision, kind, stored)
                    values ('00000000-0000-0000-0000-0000000000a1', '00000000-0000-0000-0000-000000000201', 0,
                            'turn', '{}') $$,
                 '23514', null, 'revisions count from 1');
select is((select shot_ids from public.scene_plan_revisions where revision = 2), '[]'::jsonb,
          'shot ids default to none');

-- ── read-only for browsers, scoped to the production ─────────────────────────────────────
select pg_temp.as_user('00000000-0000-0000-0000-00000000000b');
select is((select count(*)::int from public.scene_plan_revisions), 2, 'a member reads their production''s revisions');
select throws_ok($$ insert into public.scene_plan_revisions (production_id, scene_id, revision, kind, stored)
                    values ('00000000-0000-0000-0000-0000000000a1', '00000000-0000-0000-0000-000000000201', 9,
                            'turn', '{}') $$,
                 '42501', null, 'a browser cannot write a revision');
select pg_temp.as_user('00000000-0000-0000-0000-00000000000d');
select is((select count(*)::int from public.scene_plan_revisions), 0, 'an outsider reads none');
reset role;

-- ── follows its scene ────────────────────────────────────────────────────────────────────
delete from public.scenes where id = '00000000-0000-0000-0000-000000000202';
select is((select count(*)::int from public.scene_plan_revisions
           where scene_id = '00000000-0000-0000-0000-000000000202'), 0, 'a scene''s revisions go with it');
select ok((select relrowsecurity from pg_class where oid = 'public.scene_plan_revisions'::regclass),
          'row level security is on');

select * from finish();
rollback;
