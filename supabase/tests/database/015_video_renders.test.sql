-- In-app video generation (plan/2026-11-06c): video_renders are scoped to the production, constrained, read-only for
-- browsers, and follow their shot; a take records where it came from; a shot carries its own video settings.
begin;
select plan(14);

delete from public.video_renders; delete from public.takes;
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
insert into public.shots (id, production_id, scene_id, number, duration_s) values
  ('00000000-0000-0000-0000-000000000301', '00000000-0000-0000-0000-0000000000a1', '00000000-0000-0000-0000-000000000201', 1, 8),
  ('00000000-0000-0000-0000-000000000302', '00000000-0000-0000-0000-0000000000a2', '00000000-0000-0000-0000-000000000202', 1, 4);
insert into public.video_renders (id, production_id, shot_id, engine, model, spec, request_hash, seed) values
  ('00000000-0000-0000-0000-000000000801', '00000000-0000-0000-0000-0000000000a1', '00000000-0000-0000-0000-000000000301',
   'veo_3_1', 'veo-3.1-generate-preview', '{}', 'h1', 1234),
  ('00000000-0000-0000-0000-000000000802', '00000000-0000-0000-0000-0000000000a2', '00000000-0000-0000-0000-000000000302',
   'omni_flash', 'gemini-omni-1.1-flash', '{}', 'h2', null);

-- ── constraints ──────────────────────────────────────────────────────────────────────────
select is((select status from public.video_renders where id = '00000000-0000-0000-0000-000000000801'), 'queued',
          'a render starts queued');
select throws_ok($$ insert into public.video_renders (production_id, shot_id, engine, model, spec, request_hash, status)
                    values ('00000000-0000-0000-0000-0000000000a1', '00000000-0000-0000-0000-000000000301',
                            'veo_3_1', 'm', '{}', 'h', 'finished') $$,
                 '23514', null, 'a render has one of five statuses');
select throws_ok($$ insert into public.video_renders (production_id, shot_id, engine, model, spec, request_hash, seed)
                    values ('00000000-0000-0000-0000-0000000000a1', '00000000-0000-0000-0000-000000000301',
                            'veo_3_1', 'm', '{}', 'h', 4294967296) $$,
                 '23514', null, 'a seed fits in 32 bits');
select lives_ok($$ update public.video_renders set status = 'running' where id = '00000000-0000-0000-0000-000000000801'
                   and status = 'queued' $$, 'a queued render can be claimed');

-- ── takes know where they came from ──────────────────────────────────────────────────────
insert into public.takes (id, production_id, shot_id, storage_path, mime, bytes, origin, render_id) values
  ('00000000-0000-0000-0000-000000000701', '00000000-0000-0000-0000-0000000000a1', '00000000-0000-0000-0000-000000000301',
   'a/t1.mp4', 'video/mp4', 10, 'generated', '00000000-0000-0000-0000-000000000801');
insert into public.takes (id, production_id, shot_id, storage_path, mime, bytes) values
  ('00000000-0000-0000-0000-000000000702', '00000000-0000-0000-0000-0000000000a1', '00000000-0000-0000-0000-000000000301',
   'a/t2.mp4', 'video/mp4', 10);
select is((select origin from public.takes where id = '00000000-0000-0000-0000-000000000702'), 'upload',
          'a take is an upload unless it says otherwise');
select throws_ok($$ update public.takes set origin = 'imported' where id = '00000000-0000-0000-0000-000000000702' $$,
                 '23514', null, 'a take is uploaded or generated');
select is((select video_settings from public.shots where id = '00000000-0000-0000-0000-000000000301'), '{}'::jsonb,
          'a shot starts with Hiru''s choice');

-- ── access: read-only, per production ────────────────────────────────────────────────────
select pg_temp.as_user('00000000-0000-0000-0000-00000000000b');
select is((select count(*)::int from public.video_renders), 1, 'a member sees their production''s renders only');
select throws_ok($$ insert into public.video_renders (production_id, shot_id, engine, model, spec, request_hash)
                    values ('00000000-0000-0000-0000-0000000000a1', '00000000-0000-0000-0000-000000000301',
                            'veo_3_1', 'm', '{}', 'h') $$,
                 '42501', null, 'a browser role cannot write one');
select pg_temp.as_user('00000000-0000-0000-0000-00000000000d');
select is((select count(*)::int from public.video_renders), 0, 'an outsider sees none');
reset role;

-- ── what goes with what ──────────────────────────────────────────────────────────────────
delete from public.takes where id = '00000000-0000-0000-0000-000000000701';
select is((select take_id from public.video_renders where id = '00000000-0000-0000-0000-000000000801'), null,
          'deleting a take leaves the render that made it');
delete from public.shots where id = '00000000-0000-0000-0000-000000000302';
select is((select count(*)::int from public.video_renders where production_id = '00000000-0000-0000-0000-0000000000a2'), 0,
          'a deleted shot takes its renders');
select is((select count(*)::int from pg_publication_tables
           where pubname = 'supabase_realtime' and tablename = 'video_renders'), 1, 'renders reach the browser live');
select is((select count(*)::int from pg_policies where tablename = 'video_renders'), 1, 'one read policy, no write policy');

select * from finish();
rollback;
