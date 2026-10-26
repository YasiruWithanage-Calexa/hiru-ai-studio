-- Phase 4: the Production panel. Frames and prompts hang off shots, one accepted frame per
-- shot, prompt versions unique per shot, private buckets, read-only for browsers.
begin;
select plan(19);

delete from public.video_prompts; delete from public.first_frames;
delete from public.memory_items; delete from public.chat_messages; delete from public.chat_threads;
delete from public.production_director_board;
delete from public.questions; delete from public.dialogue_lines; delete from public.shots;
delete from public.scenes; delete from public.episodes; delete from public.canon_versions;
delete from public.canon_entities; delete from public.jobs; delete from public.documents;
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
insert into public.shots (id, production_id, scene_id, number, duration_s) values
  ('00000000-0000-0000-0000-000000000301', '00000000-0000-0000-0000-0000000000a1', '00000000-0000-0000-0000-000000000201', 1, 8),
  ('00000000-0000-0000-0000-000000000302', '00000000-0000-0000-0000-0000000000a2', '00000000-0000-0000-0000-000000000202', 1, 4);
insert into public.first_frames (id, production_id, shot_id, status, storage_path) values
  ('00000000-0000-0000-0000-000000000401', '00000000-0000-0000-0000-0000000000a1', '00000000-0000-0000-0000-000000000301', 'done', 'a/f1.png'),
  ('00000000-0000-0000-0000-000000000402', '00000000-0000-0000-0000-0000000000a1', '00000000-0000-0000-0000-000000000301', 'done', 'a/f2.png'),
  ('00000000-0000-0000-0000-000000000403', '00000000-0000-0000-0000-0000000000a1', '00000000-0000-0000-0000-000000000301', 'queued', null),
  ('00000000-0000-0000-0000-000000000404', '00000000-0000-0000-0000-0000000000a2', '00000000-0000-0000-0000-000000000302', 'done', 'b/f1.png');
insert into public.video_prompts (production_id, shot_id, version, prose) values
  ('00000000-0000-0000-0000-0000000000a1', '00000000-0000-0000-0000-000000000301', 1, 'v1'),
  ('00000000-0000-0000-0000-0000000000a2', '00000000-0000-0000-0000-000000000302', 1, 'v1');

-- ── shots carry a design and a person's camera ───────────────────────────────────────────
select col_default_is('public', 'shots', 'design', '{}', 'a shot starts undesigned');
select col_default_is('public', 'shots', 'camera_overrides', '{}', 'and with the recommended camera');

-- ── constraints ──────────────────────────────────────────────────────────────────────────
select lives_ok($$ update public.first_frames set accepted_at = now()
                   where id = '00000000-0000-0000-0000-000000000401' $$, 'a finished frame can be accepted');
select throws_ok($$ update public.first_frames set accepted_at = now()
                    where id = '00000000-0000-0000-0000-000000000402' $$,
                 '23505', null, 'one accepted frame per shot');
select throws_ok($$ update public.first_frames set accepted_at = now()
                    where id = '00000000-0000-0000-0000-000000000403' $$,
                 '23514', null, 'a frame that is not finished cannot be accepted');
select throws_ok($$ insert into public.first_frames (production_id, shot_id, status)
                    values ('00000000-0000-0000-0000-0000000000a1', '00000000-0000-0000-0000-000000000301', 'lost') $$,
                 '23514', null, 'a frame has a known status');
select throws_ok($$ insert into public.video_prompts (production_id, shot_id, version)
                    values ('00000000-0000-0000-0000-0000000000a1', '00000000-0000-0000-0000-000000000301', 1) $$,
                 '23505', null, 'prompt versions are unique per shot');
select lives_ok($$ insert into public.video_prompts (production_id, shot_id, version, frame_id)
                   values ('00000000-0000-0000-0000-0000000000a1', '00000000-0000-0000-0000-000000000301', 2,
                           '00000000-0000-0000-0000-000000000401') $$, 'a new version records its frame');

-- a deleted frame leaves the prompt made from it, unlinked; a deleted shot takes both
delete from public.first_frames where id = '00000000-0000-0000-0000-000000000401';
select is((select frame_id from public.video_prompts where version = 2), null, 'the prompt outlives its frame');
delete from public.shots where id = '00000000-0000-0000-0000-000000000302';
select is((select count(*)::int from public.first_frames where production_id = '00000000-0000-0000-0000-0000000000a2')
          + (select count(*)::int from public.video_prompts where production_id = '00000000-0000-0000-0000-0000000000a2'),
          0, 'a deleted shot takes its frames and prompts');

-- ── storage ──────────────────────────────────────────────────────────────────────────────
select is((select count(*)::int from storage.buckets where id in ('frames', 'references') and not public), 2,
          'frames and reference sheets live in private buckets');
select is((select file_size_limit from storage.buckets where id = 'frames'), 15728640::bigint, 'frames are capped');

-- ── RLS ──────────────────────────────────────────────────────────────────────────────────
select pg_temp.as_user('00000000-0000-0000-0000-00000000000b');
select is((select count(*)::int from public.first_frames), 2, 'a member sees their production''s frames');
select is((select count(*)::int from public.video_prompts), 2, 'and prompts');
select throws_ok($$ insert into public.first_frames (production_id, shot_id)
                    values ('00000000-0000-0000-0000-0000000000a1', '00000000-0000-0000-0000-000000000301') $$,
                 '42501', null, 'browsers write nothing: frames go through the API');
select is_empty($$ update public.first_frames set accepted_at = now() returning 1 $$, 'nor acceptances');
select is_empty($$ update public.shots set camera_overrides = '{"lens":"85mm"}' returning 1 $$, 'nor camera changes');

select pg_temp.as_user('00000000-0000-0000-0000-00000000000d');
select is((select count(*)::int from public.first_frames) + (select count(*)::int from public.video_prompts), 0,
          'a non-member sees none of it');

reset role;
select ok((select count(*) from pg_publication_tables where pubname = 'supabase_realtime'
           and tablename in ('first_frames', 'video_prompts')) = 2, 'frames and prompts reach open panels');

select * from finish();
rollback;
