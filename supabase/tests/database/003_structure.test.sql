-- Phase 2: structure, canon and questions. RLS is read-only and scoped per production;
-- constraints keep shots renderable and canon codes well-formed.
begin;
select plan(20);

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
  ('writer@hirutv.lk', '00000000-0000-0000-0000-0000000000a1', 'writer');
insert into public.invitations (email, app_role) values ('admin@hirutv.lk', 'admin');
insert into auth.users (id, email) values
  ('00000000-0000-0000-0000-00000000000b', 'writer@hirutv.lk'),
  ('00000000-0000-0000-0000-00000000000c', 'admin@hirutv.lk'),
  ('00000000-0000-0000-0000-00000000000d', 'outsider@hirutv.lk');

insert into public.canon_entities (id, production_id, kind, code, name) values
  ('00000000-0000-0000-0000-0000000000e1', '00000000-0000-0000-0000-0000000000a1', 'character', 'C01', 'Kamala'),
  ('00000000-0000-0000-0000-0000000000e2', '00000000-0000-0000-0000-0000000000a1', 'location', 'L01', 'House'),
  ('00000000-0000-0000-0000-0000000000e3', '00000000-0000-0000-0000-0000000000a2', 'character', 'C01', 'Other');
insert into public.canon_versions (id, entity_id, production_id, version, card_hash) values
  ('00000000-0000-0000-0000-0000000000f1', '00000000-0000-0000-0000-0000000000e1', '00000000-0000-0000-0000-0000000000a1', 1, 'h');
update public.canon_entities set current_version_id = '00000000-0000-0000-0000-0000000000f1'
  where id = '00000000-0000-0000-0000-0000000000e1';

insert into public.episodes (id, production_id, number) values
  ('00000000-0000-0000-0000-000000000101', '00000000-0000-0000-0000-0000000000a1', 1),
  ('00000000-0000-0000-0000-000000000102', '00000000-0000-0000-0000-0000000000a2', 1);
insert into public.scenes (id, production_id, episode_id, number, envelope_s, location_id) values
  ('00000000-0000-0000-0000-000000000201', '00000000-0000-0000-0000-0000000000a1', '00000000-0000-0000-0000-000000000101', 1, 60,
   '00000000-0000-0000-0000-0000000000e2'),
  ('00000000-0000-0000-0000-000000000202', '00000000-0000-0000-0000-0000000000a2', '00000000-0000-0000-0000-000000000102', 1, 60, null);
insert into public.shots (id, production_id, scene_id, number, duration_s) values
  ('00000000-0000-0000-0000-000000000301', '00000000-0000-0000-0000-0000000000a1', '00000000-0000-0000-0000-000000000201', 1, 8),
  ('00000000-0000-0000-0000-000000000302', '00000000-0000-0000-0000-0000000000a2', '00000000-0000-0000-0000-000000000202', 1, 4);
insert into public.dialogue_lines (production_id, scene_id, ord, speaker, character_id, text, shot_id) values
  ('00000000-0000-0000-0000-0000000000a1', '00000000-0000-0000-0000-000000000201', 0, 'Kamala',
   '00000000-0000-0000-0000-0000000000e1', 'කෑම කන්න වාඩි වෙන්න.', '00000000-0000-0000-0000-000000000301');
insert into public.questions (id, production_id, key, title, body) values
  ('00000000-0000-0000-0000-000000000401', '00000000-0000-0000-0000-0000000000a1', 'loc:x', 'Q', 'Use L01?'),
  ('00000000-0000-0000-0000-000000000402', '00000000-0000-0000-0000-0000000000a2', 'loc:y', 'Q', 'Use L02?');

-- ── constraints ──────────────────────────────────────────────────────────────────────────
select throws_ok($$ insert into public.shots (production_id, scene_id, number, duration_s)
                    values ('00000000-0000-0000-0000-0000000000a1', '00000000-0000-0000-0000-000000000201', 2, 10) $$,
                 '23514', null, '10 s shots stay off (PLAN.md Q4)');
select throws_ok($$ insert into public.shots (production_id, scene_id, number, duration_s, sound_mode)
                    values ('00000000-0000-0000-0000-0000000000a1', '00000000-0000-0000-0000-000000000201', 2, 8, 'mumble') $$,
                 '23514', null, 'sound mode must be one Veo knows');
select throws_ok($$ insert into public.canon_entities (production_id, kind, code, name)
                    values ('00000000-0000-0000-0000-0000000000a1', 'prop', 'X1', 'Boat') $$,
                 '23514', null, 'canon codes look like C01 / L03 / P02');
select throws_ok($$ insert into public.canon_entities (production_id, kind, code, name)
                    values ('00000000-0000-0000-0000-0000000000a1', 'character', 'C09', 'KAMALA') $$,
                 '23505', null, 'one name per kind per production, case-insensitively');
select throws_ok($$ insert into public.canon_entities (production_id, kind, code, name)
                    values ('00000000-0000-0000-0000-0000000000a1', 'prop', 'C01', 'Boat') $$,
                 '23505', null, 'codes are unique within a production');
select lives_ok($$ insert into public.canon_entities (production_id, kind, code, name)
                   values ('00000000-0000-0000-0000-0000000000a2', 'character', 'C02', 'Kamala') $$,
                'the same name may exist in another production');
select throws_ok($$ insert into public.scenes (production_id, episode_id, number, envelope_s)
                    values ('00000000-0000-0000-0000-0000000000a1', '00000000-0000-0000-0000-000000000101', 1, 60) $$,
                 '23505', null, 'scene numbers are unique within an episode');

-- deleting a shot unbinds its lines but keeps them (lines belong to the script)
delete from public.shots where id = '00000000-0000-0000-0000-000000000301';
select is((select shot_id from public.dialogue_lines where ord = 0 and scene_id = '00000000-0000-0000-0000-000000000201'),
          null, 'deleting a shot keeps its lines, unbound');
insert into public.shots (id, production_id, scene_id, number, duration_s) values
  ('00000000-0000-0000-0000-000000000301', '00000000-0000-0000-0000-0000000000a1', '00000000-0000-0000-0000-000000000201', 1, 8);

-- deleting a canon entity unlinks scenes and lines instead of deleting them
delete from public.canon_entities where id = '00000000-0000-0000-0000-0000000000e2';
select is((select location_id from public.scenes where id = '00000000-0000-0000-0000-000000000201'), null,
          'a deleted location leaves the scene in place');

-- ── RLS ──────────────────────────────────────────────────────────────────────────────────
select pg_temp.as_user('00000000-0000-0000-0000-00000000000b');
select is((select count(*)::int from public.episodes), 1, 'a member sees only their production''s episodes');
select is((select count(*)::int from public.scenes), 1, 'scenes');
select is((select count(*)::int from public.shots), 1, 'shots');
select is((select count(*)::int from public.dialogue_lines), 1, 'dialogue lines');
select is((select count(*)::int from public.canon_entities), 1, 'canon entities');
select is((select count(*)::int from public.canon_versions), 1, 'canon versions');
select is((select count(*)::int from public.questions), 1, 'questions');
select throws_ok($$ insert into public.questions (id, production_id, key, title, body)
                    values (gen_random_uuid(), '00000000-0000-0000-0000-0000000000a1', 'k', 't', 'b') $$,
                 '42501', null, 'browsers write nothing: no insert policy');

select pg_temp.as_user('00000000-0000-0000-0000-00000000000d');
select is((select count(*)::int from public.scenes) + (select count(*)::int from public.canon_entities)
          + (select count(*)::int from public.questions), 0, 'a non-member sees nothing');

select pg_temp.as_user('00000000-0000-0000-0000-00000000000c');
select is((select count(*)::int from public.shots), 2, 'an admin sees every production');

reset role;
select ok(not has_schema_privilege('authenticated', 'graph', 'USAGE'),
          'the LangGraph checkpoint schema is closed to browsers');

select * from finish();
rollback;
