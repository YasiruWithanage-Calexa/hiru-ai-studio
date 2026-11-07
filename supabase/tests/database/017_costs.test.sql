-- A scene's production cost (plan/2026-11-06d): `prices` is RLS-protected (an admin reads, a member sees nothing, nobody
-- writes from a browser) and seeded; token_usage.scene_id is indexed and cleared when its scene is deleted.
begin;
select plan(11);

delete from public.prices; delete from public.token_usage;
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
  ('00000000-0000-0000-0000-0000000000a1', 'One', 'horizontal');
insert into public.invitations (email, app_role) values ('admin@hirutv.lk', 'admin');
insert into public.invitations (email, production_id, production_role) values
  ('crew@hirutv.lk', '00000000-0000-0000-0000-0000000000a1', 'producer');
insert into auth.users (id, email) values
  ('00000000-0000-0000-0000-00000000000a', 'admin@hirutv.lk'),
  ('00000000-0000-0000-0000-00000000000b', 'crew@hirutv.lk');
insert into public.episodes (id, production_id, number) values
  ('00000000-0000-0000-0000-000000000101', '00000000-0000-0000-0000-0000000000a1', 1);
insert into public.scenes (id, production_id, episode_id, number, envelope_s) values
  ('00000000-0000-0000-0000-000000000201', '00000000-0000-0000-0000-0000000000a1', '00000000-0000-0000-0000-000000000101', 1, 60);
insert into public.prices (kind, model_prefix, input_micros, cached_input_micros, output_micros) values
  ('tokens', 'gpt-5', 1250000, 125000, 10000000);
insert into public.token_usage (production_id, phase, model, input_tokens, scene_id) values
  ('00000000-0000-0000-0000-0000000000a1', 'shot_producer.craft', 'gpt-5', 10,
   '00000000-0000-0000-0000-000000000201');

-- ── constraints ──────────────────────────────────────────────────────────────────────────
select throws_ok($$ insert into public.prices (kind) values ('credits') $$,
                 '23514', null, 'a price is for tokens, video seconds or an estimate');
select throws_ok($$ insert into public.prices (kind, input_micros) values ('tokens', -1) $$,
                 '23514', null, 'a price is never negative');
select is((select valid_from <= now() from public.prices where model_prefix = 'gpt-5'), true,
          'a price is valid from now unless it says when');

-- ── access: an admin reads, a member does not, nobody writes from a browser ──────────────
select pg_temp.as_user('00000000-0000-0000-0000-00000000000a');
select is((select count(*)::int from public.prices), 1, 'an admin reads the price list');
select throws_ok($$ insert into public.prices (kind, model_prefix) values ('tokens', 'x') $$,
                 '42501', null, 'an admin''s browser cannot write a price either');
select pg_temp.as_user('00000000-0000-0000-0000-00000000000b');
select is((select count(*)::int from public.prices), 0, 'a producer sees no price list');
reset role;
select is((select count(*)::int from pg_policies where tablename = 'prices'), 1, 'one read policy, no write policy');

-- ── the scene a call was for ─────────────────────────────────────────────────────────────
select is((select count(*)::int from pg_indexes where tablename = 'token_usage' and indexname = 'token_usage_scene_idx'),
          1, 'a scene''s calls are found by an index');
select is((select scene_id from public.token_usage where phase = 'shot_producer.craft'), '00000000-0000-0000-0000-000000000201'::uuid,
          'a call names its scene');
delete from public.scenes where id = '00000000-0000-0000-0000-000000000201';
select is((select scene_id from public.token_usage where phase = 'shot_producer.craft'), null,
          'deleting a scene keeps its calls, tied to no scene');
select is((select count(*)::int from public.token_usage where phase = 'shot_producer.craft'), 1, 'the usage row stays');

select * from finish();
rollback;
