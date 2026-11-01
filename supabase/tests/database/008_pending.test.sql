-- Pending actions (plan/2026-11-01c): what "i confirm" applies. One open per thread, read-only for
-- browsers, scoped to the production.
begin;
select plan(8);

delete from public.pending_actions;
delete from public.chat_messages; delete from public.chat_threads;
delete from public.dialogue_lines; delete from public.shots;
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
  ('reviewer@hirutv.lk', '00000000-0000-0000-0000-0000000000a1', 'reviewer');
insert into auth.users (id, email) values
  ('00000000-0000-0000-0000-00000000000b', 'reviewer@hirutv.lk'),
  ('00000000-0000-0000-0000-00000000000d', 'outsider@hirutv.lk');
insert into public.episodes (id, production_id, number) values
  ('00000000-0000-0000-0000-000000000101', '00000000-0000-0000-0000-0000000000a1', 1),
  ('00000000-0000-0000-0000-000000000102', '00000000-0000-0000-0000-0000000000a2', 1);
insert into public.scenes (id, production_id, episode_id, number, envelope_s) values
  ('00000000-0000-0000-0000-000000000201', '00000000-0000-0000-0000-0000000000a1', '00000000-0000-0000-0000-000000000101', 1, 60),
  ('00000000-0000-0000-0000-000000000202', '00000000-0000-0000-0000-0000000000a2', '00000000-0000-0000-0000-000000000102', 1, 60);
insert into public.chat_threads (id, production_id, scene_id, title) values
  ('00000000-0000-0000-0000-000000000601', '00000000-0000-0000-0000-0000000000a1', '00000000-0000-0000-0000-000000000201', 'Director'),
  ('00000000-0000-0000-0000-000000000602', '00000000-0000-0000-0000-0000000000a2', '00000000-0000-0000-0000-000000000202', 'Director');
insert into public.chat_messages (id, production_id, thread_id, kind, text) values
  ('00000000-0000-0000-0000-000000000701', '00000000-0000-0000-0000-0000000000a1', '00000000-0000-0000-0000-000000000601', 'director', ''),
  ('00000000-0000-0000-0000-000000000702', '00000000-0000-0000-0000-0000000000a2', '00000000-0000-0000-0000-000000000602', 'director', '');
insert into public.pending_actions (id, production_id, thread_id, scene_id, message_id, block, option, ops, expires_at) values
  ('00000000-0000-0000-0000-000000000801', '00000000-0000-0000-0000-0000000000a1', '00000000-0000-0000-0000-000000000601',
   '00000000-0000-0000-0000-000000000201', '00000000-0000-0000-0000-000000000701', 1, 0, '[{"op": "retime"}]', now() + interval '24 hours'),
  ('00000000-0000-0000-0000-000000000802', '00000000-0000-0000-0000-0000000000a2', '00000000-0000-0000-0000-000000000602',
   '00000000-0000-0000-0000-000000000202', '00000000-0000-0000-0000-000000000702', 1, 0, '[]', now() + interval '24 hours');

-- ── constraints ──────────────────────────────────────────────────────────────────────────
select throws_ok($$ insert into public.pending_actions (production_id, thread_id, scene_id, message_id, block, option, expires_at)
                    values ('00000000-0000-0000-0000-0000000000a1', '00000000-0000-0000-0000-000000000601',
                            '00000000-0000-0000-0000-000000000201', '00000000-0000-0000-0000-000000000701', 2, 0,
                            now() + interval '1 hour') $$,
                 '23505', null, 'a thread has one open pending action');
select lives_ok($$ update public.pending_actions set status = 'superseded', closed_at = now()
                   where id = '00000000-0000-0000-0000-000000000801' $$, 'an open one can be closed');
select lives_ok($$ insert into public.pending_actions (production_id, thread_id, scene_id, message_id, block, option, expires_at)
                   values ('00000000-0000-0000-0000-0000000000a1', '00000000-0000-0000-0000-000000000601',
                           '00000000-0000-0000-0000-000000000201', '00000000-0000-0000-0000-000000000701', 2, 0,
                           now() + interval '1 hour') $$, 'and then a newer one can be opened');
select throws_ok($$ update public.pending_actions set status = 'maybe'
                    where id = '00000000-0000-0000-0000-000000000802' $$,
                 '23514', null, 'a status is one of the five');
select throws_ok($$ update public.pending_actions set block = -1
                    where id = '00000000-0000-0000-0000-000000000802' $$,
                 '23514', null, 'a block index is not negative');

-- ── access: read-only, per production ────────────────────────────────────────────────────
select pg_temp.as_user('00000000-0000-0000-0000-00000000000b');
select is((select count(*)::int from public.pending_actions), 2, 'a member sees their production''s pending actions only (the closed one and the open one)');
select throws_ok($$ insert into public.pending_actions (production_id, thread_id, scene_id, message_id, block, option, expires_at)
                    values ('00000000-0000-0000-0000-0000000000a1', '00000000-0000-0000-0000-000000000601',
                            '00000000-0000-0000-0000-000000000201', '00000000-0000-0000-0000-000000000701', 3, 0,
                            now() + interval '1 hour') $$,
                 '42501', null, 'a browser role cannot write one');
select pg_temp.as_user('00000000-0000-0000-0000-00000000000d');
select is((select count(*)::int from public.pending_actions), 0, 'an outsider sees none');

select * from finish();
rollback;
