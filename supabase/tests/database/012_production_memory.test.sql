-- Production memory (plan/2026-11-05d): entries are scoped to the production, constrained to the plan's forms, read-only
-- for browsers, and follow their document and their production when those are deleted.
begin;
select plan(11);

delete from public.production_memory;
delete from public.documents;
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
insert into public.documents (id, production_id, filename, mime_type, size_bytes, sha256, storage_path) values
  ('00000000-0000-0000-0000-000000000301', '00000000-0000-0000-0000-0000000000a1', 'bible.txt', 'text/plain', 10, 'abc', 'a1/bible.txt');
insert into public.production_memory (id, production_id, document_id, topic, applies_to, says, quote, strength) values
  ('00000000-0000-0000-0000-000000000901', '00000000-0000-0000-0000-0000000000a1', '00000000-0000-0000-0000-000000000301',
   'camera', 'when:love scenes', 'Use 50mm and 85mm lenses.', 'Love scenes 50mm and 85mm lenses', 'prefer'),
  ('00000000-0000-0000-0000-000000000902', '00000000-0000-0000-0000-0000000000a2', null,
   'sound', 'production', 'Rain first.', '', 'prefer');

-- ── constraints ──────────────────────────────────────────────────────────────────────────
select throws_ok($$ insert into public.production_memory (production_id, topic, says)
                    values ('00000000-0000-0000-0000-0000000000a1', 'Camera', 'x') $$,
                 '23514', null, 'a topic is lower case');
select throws_ok($$ insert into public.production_memory (production_id, topic, says, applies_to)
                    values ('00000000-0000-0000-0000-0000000000a1', 'camera', 'x', 'somewhere nice') $$,
                 '23514', null, 'a target is one of the five forms');
select throws_ok($$ insert into public.production_memory (production_id, topic, says, applies_to)
                    values ('00000000-0000-0000-0000-0000000000a1', 'camera', 'x', 'episode:two') $$,
                 '23514', null, 'an episode target is a number');
select throws_ok($$ insert into public.production_memory (production_id, topic, says, strength)
                    values ('00000000-0000-0000-0000-0000000000a1', 'camera', 'x', 'should') $$,
                 '23514', null, 'a strength is must, prefer or fact');
select lives_ok($$ insert into public.production_memory (production_id, topic, says, applies_to, status, source)
                   values ('00000000-0000-0000-0000-0000000000a1', 'sound', 'No music in village scenes.', 'place:Mahawewa',
                           'approved', 'person') $$, 'a person can add an entry with no document');

-- ── access: read-only, per production ────────────────────────────────────────────────────
select pg_temp.as_user('00000000-0000-0000-0000-00000000000b');
select is((select count(*)::int from public.production_memory), 2, 'a member sees their production''s entries only');
select throws_ok($$ insert into public.production_memory (production_id, topic, says)
                    values ('00000000-0000-0000-0000-0000000000a1', 'camera', 'x') $$,
                 '42501', null, 'a browser role cannot write one');
select pg_temp.as_user('00000000-0000-0000-0000-00000000000d');
select is((select count(*)::int from public.production_memory), 0, 'an outsider sees none');
reset role;

-- ── what goes with what ──────────────────────────────────────────────────────────────────
delete from public.documents where id = '00000000-0000-0000-0000-000000000301';
select is((select count(*)::int from public.production_memory where document_id is not null), 0,
          'an entry goes with its document');
select is((select count(*)::int from public.production_memory where production_id = '00000000-0000-0000-0000-0000000000a1'), 1,
          'a person''s entry stays');
delete from public.productions where id = '00000000-0000-0000-0000-0000000000a2';
select is((select count(*)::int from public.production_memory where production_id = '00000000-0000-0000-0000-0000000000a2'), 0,
          'an entry goes with its production');

select * from finish();
rollback;
