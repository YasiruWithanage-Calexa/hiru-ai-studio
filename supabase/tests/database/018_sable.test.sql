-- Sable (plan/2026-11-08 §4.8): a Sable thread and its messages are read only by the person who made it; a scene's chat
-- is read by everyone in the production as before; a reply's record (chat_turn_meta) is read by an admin only and is
-- written by nobody's browser; a Sable thread names no scene.
begin;
select plan(12);

delete from public.prices; delete from public.token_usage;
delete from public.scene_plan_revisions; delete from public.video_renders; delete from public.takes;
delete from public.video_prompts; delete from public.first_frames;
delete from public.memory_items; delete from public.chat_turn_meta; delete from public.chat_messages;
delete from public.chat_threads; delete from public.production_director_board;
delete from public.questions; delete from public.dialogue_lines; delete from public.shots;
delete from public.scenes; delete from public.episodes;
delete from public.invitations; delete from public.audit_log; delete from public.productions;
delete from auth.users;

create function pg_temp.as_user(uid uuid) returns void language sql as $$
  select set_config('role', 'authenticated', true),
         set_config('request.jwt.claims', json_build_object('sub', uid, 'role', 'authenticated')::text, true);
$$;

insert into public.productions (id, title, orientation) values
  ('00000000-0000-0000-0000-0000000000a1', 'One', 'horizontal');
insert into public.invitations (email, app_role) values ('admin@hirutv.lk', 'admin');
insert into public.invitations (email, production_id, production_role) values
  ('dee@hirutv.lk', '00000000-0000-0000-0000-0000000000a1', 'director'),
  ('rae@hirutv.lk', '00000000-0000-0000-0000-0000000000a1', 'reviewer');
insert into auth.users (id, email) values
  ('00000000-0000-0000-0000-00000000000a', 'admin@hirutv.lk'),
  ('00000000-0000-0000-0000-00000000000d', 'dee@hirutv.lk'),
  ('00000000-0000-0000-0000-00000000000e', 'rae@hirutv.lk');
insert into public.episodes (id, production_id, number) values
  ('00000000-0000-0000-0000-000000000101', '00000000-0000-0000-0000-0000000000a1', 1);
insert into public.scenes (id, production_id, episode_id, number, envelope_s) values
  ('00000000-0000-0000-0000-000000000201', '00000000-0000-0000-0000-0000000000a1', '00000000-0000-0000-0000-000000000101', 1, 60);
insert into public.chat_threads (id, production_id, scene_id, title, created_by) values
  ('00000000-0000-0000-0000-000000000301', '00000000-0000-0000-0000-0000000000a1',
   '00000000-0000-0000-0000-000000000201', 'Director', '00000000-0000-0000-0000-00000000000d');
insert into public.chat_threads (id, production_id, title, created_by, chat) values
  ('00000000-0000-0000-0000-000000000302', '00000000-0000-0000-0000-0000000000a1', 'Dee asks',
   '00000000-0000-0000-0000-00000000000d', 'sable');
insert into public.chat_messages (id, production_id, thread_id, kind, text) values
  ('00000000-0000-0000-0000-000000000401', '00000000-0000-0000-0000-0000000000a1',
   '00000000-0000-0000-0000-000000000301', 'user', 'scene chat'),
  ('00000000-0000-0000-0000-000000000402', '00000000-0000-0000-0000-0000000000a1',
   '00000000-0000-0000-0000-000000000302', 'director', 'sable reply');
insert into public.chat_turn_meta (message_id, production_id, meta) values
  ('00000000-0000-0000-0000-000000000402', '00000000-0000-0000-0000-0000000000a1', '{"tier_end": "sable_deep"}');

-- ── constraints ──────────────────────────────────────────────────────────────────────────
select is((select chat from public.chat_threads where id = '00000000-0000-0000-0000-000000000301'), 'scene',
          'a thread Zora or the classic chat makes is a scene''s chat by default');
select throws_ok($$ insert into public.chat_threads (production_id, title, chat) values
                    ('00000000-0000-0000-0000-0000000000a1', 'x', 'other') $$,
                 '23514', null, 'a thread is a scene''s chat or a Sable thread');
select throws_ok($$ insert into public.chat_threads (production_id, scene_id, title, chat) values
                    ('00000000-0000-0000-0000-0000000000a1', '00000000-0000-0000-0000-000000000201', 'x', 'sable') $$,
                 '23514', null, 'a Sable thread names no scene');

-- ── access ───────────────────────────────────────────────────────────────────────────────
select pg_temp.as_user('00000000-0000-0000-0000-00000000000d');
select is((select count(*)::int from public.chat_threads), 2, 'the person sees the scene chat and their own Sable thread');
select is((select count(*)::int from public.chat_messages), 2, 'and the messages of both');
select is((select count(*)::int from public.chat_turn_meta), 0, 'but never a reply''s record');
select throws_ok($$ insert into public.chat_turn_meta (message_id, production_id) values
                    ('00000000-0000-0000-0000-000000000401', '00000000-0000-0000-0000-0000000000a1') $$,
                 '42501', null, 'nobody''s browser writes a record');
select pg_temp.as_user('00000000-0000-0000-0000-00000000000e');
select is((select count(*)::int from public.chat_threads), 1, 'another member sees the scene chat only');
select is((select count(*)::int from public.chat_messages), 1, 'and not a word of someone else''s Sable thread');
select pg_temp.as_user('00000000-0000-0000-0000-00000000000a');
select is((select count(*)::int from public.chat_turn_meta), 1, 'an admin reads a reply''s record');
reset role;
select is((select count(*)::int from pg_policies where tablename = 'chat_turn_meta'), 1, 'one read policy, no write');

-- ── a reply's record goes with its message ───────────────────────────────────────────────
delete from public.chat_messages where id = '00000000-0000-0000-0000-000000000402';
select is((select count(*)::int from public.chat_turn_meta), 0, 'deleting a message deletes its record');

select * from finish();
rollback;
