-- Phase 5: takes (one accepted per shot, private bucket, read-only for browsers) and the
-- monthly usage budget (the API's alone).
begin;
select plan(13);

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
insert into public.episodes (id, production_id, number) values
  ('00000000-0000-0000-0000-000000000101', '00000000-0000-0000-0000-0000000000a1', 1),
  ('00000000-0000-0000-0000-000000000102', '00000000-0000-0000-0000-0000000000a2', 1);
insert into public.scenes (id, production_id, episode_id, number, envelope_s) values
  ('00000000-0000-0000-0000-000000000201', '00000000-0000-0000-0000-0000000000a1', '00000000-0000-0000-0000-000000000101', 1, 60),
  ('00000000-0000-0000-0000-000000000202', '00000000-0000-0000-0000-0000000000a2', '00000000-0000-0000-0000-000000000102', 1, 60);
insert into public.shots (id, production_id, scene_id, number, duration_s) values
  ('00000000-0000-0000-0000-000000000301', '00000000-0000-0000-0000-0000000000a1', '00000000-0000-0000-0000-000000000201', 1, 8),
  ('00000000-0000-0000-0000-000000000302', '00000000-0000-0000-0000-0000000000a2', '00000000-0000-0000-0000-000000000202', 1, 4);
insert into public.takes (id, production_id, shot_id, storage_path, mime, bytes) values
  ('00000000-0000-0000-0000-000000000701', '00000000-0000-0000-0000-0000000000a1', '00000000-0000-0000-0000-000000000301', 'a/t1.mp4', 'video/mp4', 10),
  ('00000000-0000-0000-0000-000000000702', '00000000-0000-0000-0000-0000000000a1', '00000000-0000-0000-0000-000000000301', 'a/t2.mp4', 'video/mp4', 10),
  ('00000000-0000-0000-0000-000000000703', '00000000-0000-0000-0000-0000000000a2', '00000000-0000-0000-0000-000000000302', 'b/t1.mp4', 'video/mp4', 10);
insert into public.usage_budget (month, budget_tokens) values ('2026-10-01', 5000000);

-- ── constraints ──────────────────────────────────────────────────────────────────────────
select lives_ok($$ update public.takes set status = 'accepted', accepted_at = now()
                   where id = '00000000-0000-0000-0000-000000000701' $$, 'a take can be accepted');
select throws_ok($$ update public.takes set status = 'accepted', accepted_at = now()
                    where id = '00000000-0000-0000-0000-000000000702' $$,
                 '23505', null, 'one accepted take per shot');
select throws_ok($$ update public.takes set status = 'accepted' where id = '00000000-0000-0000-0000-000000000702' $$,
                 '23514', null, 'an accepted take says when');
select throws_ok($$ insert into public.takes (production_id, shot_id, storage_path, mime, bytes)
                    values ('00000000-0000-0000-0000-0000000000a1', '00000000-0000-0000-0000-000000000301', 'x', 'image/gif', 1) $$,
                 '23514', null, 'takes are video');
select throws_ok($$ insert into public.usage_budget (month, budget_tokens) values ('2026-10-15', 1) $$,
                 '23514', null, 'a budget is per calendar month');
delete from public.shots where id = '00000000-0000-0000-0000-000000000302';
select is((select count(*)::int from public.takes where production_id = '00000000-0000-0000-0000-0000000000a2'), 0,
          'a deleted shot takes its takes');
select is((select count(*)::int from storage.buckets where id = 'takes' and not public), 1, 'takes are private');
select is((select file_size_limit from storage.buckets where id = 'takes'), 31457280::bigint,
          'takes fit under Cloud Run''s request limit');

-- ── RLS ──────────────────────────────────────────────────────────────────────────────────
select pg_temp.as_user('00000000-0000-0000-0000-00000000000b');
select is((select count(*)::int from public.takes), 2, 'a member sees their production''s takes');
select is((select count(*)::int from public.usage_budget), 0, 'nobody reads the budget directly');
select throws_ok($$ insert into public.takes (production_id, shot_id, storage_path, mime, bytes)
                    values ('00000000-0000-0000-0000-0000000000a1', '00000000-0000-0000-0000-000000000301', 'x', 'video/mp4', 1) $$,
                 '42501', null, 'browsers write nothing: takes go through the API');

select pg_temp.as_user('00000000-0000-0000-0000-00000000000d');
select is((select count(*)::int from public.takes), 0, 'a non-member sees none');

reset role;
select ok(exists (select 1 from pg_publication_tables where pubname = 'supabase_realtime' and tablename = 'takes'),
          'takes reach open screens');

select * from finish();
rollback;
