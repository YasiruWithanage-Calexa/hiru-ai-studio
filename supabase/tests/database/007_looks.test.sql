-- Looks: a character's wardrobe per stretch of episodes (read-only for browsers, API writes).
begin;
select plan(9);

delete from public.takes; delete from public.usage_budget;
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
insert into public.canon_entities (id, production_id, kind, code, name) values
  ('00000000-0000-0000-0000-000000000501', '00000000-0000-0000-0000-0000000000a1', 'character', 'C01', 'Nethmi'),
  ('00000000-0000-0000-0000-000000000502', '00000000-0000-0000-0000-0000000000a2', 'character', 'C01', 'Kamala');
insert into public.canon_looks (id, entity_id, production_id, name, ranges, outfit) values
  ('00000000-0000-0000-0000-000000000601', '00000000-0000-0000-0000-000000000501',
   '00000000-0000-0000-0000-0000000000a1', 'Village girl', '[{"from": 1, "to": 20}]', 'faded blue frock'),
  ('00000000-0000-0000-0000-000000000602', '00000000-0000-0000-0000-000000000502',
   '00000000-0000-0000-0000-0000000000a2', 'Saree', '[{"from": 1, "to": 5}]', 'blue saree');

-- ── constraints ──────────────────────────────────────────────────────────────────────────
select is((select status from public.canon_looks where id = '00000000-0000-0000-0000-000000000601'), 'draft',
          'a look starts as a draft');
select throws_ok($$ insert into public.canon_looks (entity_id, production_id, name, ranges)
                    values ('00000000-0000-0000-0000-000000000501', '00000000-0000-0000-0000-0000000000a1',
                            'village GIRL', '[]') $$,
                 '23505', null, 'a character has one look of a name, whatever the case');
select throws_ok($$ insert into public.canon_looks (entity_id, production_id, name, ranges, status)
                    values ('00000000-0000-0000-0000-000000000501', '00000000-0000-0000-0000-0000000000a1',
                            'Other', '[]', 'approved') $$,
                 '23514', null, 'a look is a draft or ready');
select throws_ok($$ insert into public.canon_looks (entity_id, production_id, name, ranges)
                    values ('00000000-0000-0000-0000-000000000501', '00000000-0000-0000-0000-0000000000a1',
                            'Other', '{"from": 1}') $$,
                 '23514', null, 'episode ranges are a list');
delete from public.canon_entities where id = '00000000-0000-0000-0000-000000000502';
select is((select count(*)::int from public.canon_looks where production_id = '00000000-0000-0000-0000-0000000000a2'), 0,
          'a deleted character takes its looks');

-- ── RLS ──────────────────────────────────────────────────────────────────────────────────
select pg_temp.as_user('00000000-0000-0000-0000-00000000000b');
select is((select count(*)::int from public.canon_looks), 1, 'a member sees their production''s looks');
select throws_ok($$ insert into public.canon_looks (entity_id, production_id, name, ranges)
                    values ('00000000-0000-0000-0000-000000000501', '00000000-0000-0000-0000-0000000000a1',
                            'Mine', '[]') $$,
                 '42501', null, 'browsers write nothing: looks go through the API');
select pg_temp.as_user('00000000-0000-0000-0000-00000000000d');
select is((select count(*)::int from public.canon_looks), 0, 'someone outside the production sees no looks');
select is((select count(*)::int from pg_policies where tablename = 'canon_looks' and cmd = 'SELECT'), 1,
          'one read policy, no write policy');

select * from finish();
rollback;
