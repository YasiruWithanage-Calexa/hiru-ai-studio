-- Phase 3: the Director panel. Personas are a readable library; the board, threads, messages
-- and memory are read-only for browsers and scoped per production; edits can renumber shots
-- and reorder lines in one statement.
begin;
select plan(25);

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
  ('reviewer@hirutv.lk', '00000000-0000-0000-0000-0000000000a1', 'reviewer');
insert into public.invitations (email, app_role) values ('admin@hirutv.lk', 'admin');
insert into auth.users (id, email) values
  ('00000000-0000-0000-0000-00000000000b', 'reviewer@hirutv.lk'),
  ('00000000-0000-0000-0000-00000000000c', 'admin@hirutv.lk'),
  ('00000000-0000-0000-0000-00000000000d', 'outsider@hirutv.lk');

insert into public.episodes (id, production_id, number) values
  ('00000000-0000-0000-0000-000000000101', '00000000-0000-0000-0000-0000000000a1', 1),
  ('00000000-0000-0000-0000-000000000102', '00000000-0000-0000-0000-0000000000a2', 1);
insert into public.scenes (id, production_id, episode_id, number, envelope_s) values
  ('00000000-0000-0000-0000-000000000201', '00000000-0000-0000-0000-0000000000a1', '00000000-0000-0000-0000-000000000101', 1, 60),
  ('00000000-0000-0000-0000-000000000202', '00000000-0000-0000-0000-0000000000a2', '00000000-0000-0000-0000-000000000102', 1, 60);
insert into public.shots (id, production_id, scene_id, number, duration_s) values
  ('00000000-0000-0000-0000-000000000301', '00000000-0000-0000-0000-0000000000a1', '00000000-0000-0000-0000-000000000201', 1, 8),
  ('00000000-0000-0000-0000-000000000302', '00000000-0000-0000-0000-0000000000a1', '00000000-0000-0000-0000-000000000201', 2, 4);
insert into public.dialogue_lines (id, production_id, scene_id, ord, speaker, text) values
  ('00000000-0000-0000-0000-000000000501', '00000000-0000-0000-0000-0000000000a1', '00000000-0000-0000-0000-000000000201', 0, 'Nimal', 'අම්මේ, මම ආපහු ආවා.'),
  ('00000000-0000-0000-0000-000000000502', '00000000-0000-0000-0000-0000000000a1', '00000000-0000-0000-0000-000000000201', 1, 'Kamala', 'කෑම කන්න වාඩි වෙන්න.');

insert into public.production_director_board (production_id, persona_id, seat)
  select '00000000-0000-0000-0000-0000000000a1', id, 'lead' from public.director_personas where slug = 'grounded-realist';
insert into public.production_director_board (production_id, persona_id, seat)
  select '00000000-0000-0000-0000-0000000000a1', id, 'advisor' from public.director_personas where slug = 'lyrical-eye';
insert into public.production_director_board (production_id, persona_id, seat)
  select '00000000-0000-0000-0000-0000000000a2', id, 'lead' from public.director_personas where slug = 'tension-builder';
insert into public.chat_threads (id, production_id, scene_id, title) values
  ('00000000-0000-0000-0000-000000000601', '00000000-0000-0000-0000-0000000000a1', '00000000-0000-0000-0000-000000000201', 'Director'),
  ('00000000-0000-0000-0000-000000000602', '00000000-0000-0000-0000-0000000000a2', '00000000-0000-0000-0000-000000000202', 'Director');
insert into public.chat_messages (production_id, thread_id, kind, text) values
  ('00000000-0000-0000-0000-0000000000a1', '00000000-0000-0000-0000-000000000601', 'user', 'make shot 2 six seconds'),
  ('00000000-0000-0000-0000-0000000000a2', '00000000-0000-0000-0000-000000000602', 'user', 'tighter');
insert into public.memory_items (production_id, kind, text) values
  ('00000000-0000-0000-0000-0000000000a1', 'decision', 'Kamala never cries on screen.'),
  ('00000000-0000-0000-0000-0000000000a2', 'note', 'Other production.');

-- ── the library ──────────────────────────────────────────────────────────────────────────
select is((select count(*)::int from public.director_personas where active), 5, 'five generic personas are seeded');
select hasnt_column('public', 'director_personas', 'price', 'personas carry no price');
select col_default_is('public', 'shots', 'duration_locked', 'false', 'a shot length is the planner''s until a person sets it');

-- ── constraints ──────────────────────────────────────────────────────────────────────────
select throws_ok($$ insert into public.production_director_board (production_id, persona_id, seat)
                    select '00000000-0000-0000-0000-0000000000a1', id, 'lead' from public.director_personas
                    where slug = 'short-form' $$,
                 '23505', null, 'a board has one lead');
select throws_ok($$ insert into public.production_director_board (production_id, persona_id, seat)
                    select '00000000-0000-0000-0000-0000000000a1', id, 'critic' from public.director_personas
                    where slug = 'short-form' $$,
                 '23514', null, 'a seat is lead or advisor');
select throws_ok($$ insert into public.chat_messages (production_id, thread_id, kind)
                    values ('00000000-0000-0000-0000-0000000000a1', '00000000-0000-0000-0000-000000000601', 'system') $$,
                 '23514', null, 'messages are from a person or the director');
select throws_ok($$ insert into public.memory_items (production_id, kind, text)
                    values ('00000000-0000-0000-0000-0000000000a1', 'note', '') $$,
                 '23514', null, 'a memory item says something');
select throws_ok($$ insert into public.director_personas (slug, name, initials) values ('Bad Slug!', 'X', 'X') $$,
                 '23514', null, 'persona slugs are url-safe');

-- one statement may swap shot numbers and line order (checked at the end, not row by row)
select lives_ok($$ update public.shots set number = 3 - number
                   where scene_id = '00000000-0000-0000-0000-000000000201' $$,
                'shots can be renumbered in one statement');
select lives_ok($$ update public.dialogue_lines set ord = 1 - ord
                   where scene_id = '00000000-0000-0000-0000-000000000201' $$,
                'lines can be reordered in one statement');
select is((select speaker from public.dialogue_lines where ord = 0
           and scene_id = '00000000-0000-0000-0000-000000000201'), 'Kamala', 'the reorder landed');
set constraints public.shots_scene_id_number_key immediate;
select throws_ok($$ insert into public.shots (production_id, scene_id, number, duration_s)
                    values ('00000000-0000-0000-0000-0000000000a1', '00000000-0000-0000-0000-000000000201', 1, 4) $$,
                 '23505', null, 'shot numbers are still unique per scene');
set constraints public.shots_scene_id_number_key deferred;

-- deleting a scene takes its threads and messages; a scene's memory outlives it
insert into public.memory_items (production_id, scene_id, kind, text) values
  ('00000000-0000-0000-0000-0000000000a2', '00000000-0000-0000-0000-000000000202', 'decision', 'Scene-bound rule.');
delete from public.scenes where id = '00000000-0000-0000-0000-000000000202';
select is((select count(*)::int from public.chat_messages
           where production_id = '00000000-0000-0000-0000-0000000000a2'), 0, 'a deleted scene takes its chat');
select is((select count(*)::int from public.memory_items where text = 'Scene-bound rule.' and scene_id is null), 1,
          'a deleted scene leaves its memory, unlinked');

-- ── RLS ──────────────────────────────────────────────────────────────────────────────────
select pg_temp.as_user('00000000-0000-0000-0000-00000000000b');
select is((select count(*)::int from public.director_personas), 5, 'every active user reads the library');
select is((select count(*)::int from public.production_director_board), 2, 'a member sees their production''s board');
select is((select count(*)::int from public.chat_threads), 1, 'threads');
select is((select count(*)::int from public.chat_messages), 1, 'messages');
select is((select count(*)::int from public.memory_items), 1, 'memory');
select throws_ok($$ insert into public.chat_messages (production_id, thread_id, kind, text)
                    values ('00000000-0000-0000-0000-0000000000a1', '00000000-0000-0000-0000-000000000601', 'user', 'x') $$,
                 '42501', null, 'browsers write nothing: chat goes through the API');
select throws_ok($$ insert into public.memory_items (production_id, kind, text)
                    values ('00000000-0000-0000-0000-0000000000a1', 'note', 'x') $$,
                 '42501', null, 'nor memory');
select is_empty($$ update public.production_director_board set seat = 'advisor' returning 1 $$,
                'nor the board');

select pg_temp.as_user('00000000-0000-0000-0000-00000000000d');
select is((select count(*)::int from public.production_director_board) + (select count(*)::int from public.chat_threads)
          + (select count(*)::int from public.chat_messages) + (select count(*)::int from public.memory_items), 0,
          'a non-member sees none of it');

select pg_temp.as_user('00000000-0000-0000-0000-00000000000c');
select is((select count(*)::int from public.memory_items), 3, 'an admin sees every production''s memory');

reset role;
select ok((select count(*) from pg_publication_tables where pubname = 'supabase_realtime'
           and tablename in ('chat_messages', 'production_director_board')) = 2,
          'new messages and board changes reach open panels through Realtime');

select * from finish();
rollback;
