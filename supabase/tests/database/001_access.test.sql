-- Access model tests (PLAN.md §9): visibility per role, invitations applied on sign-up, and
-- no direct writes from browser roles. Run: npx supabase test db
begin;
select plan(27);

-- Start from empty tables INSIDE this transaction, so the counts below are exact even on a
-- local database full of dev data. The final rollback restores everything.
delete from public.chunks; delete from public.craft_techniques; delete from public.token_usage;
delete from public.jobs; delete from public.documents; delete from public.invitations;
delete from public.audit_log; delete from public.productions; delete from auth.users;

-- ── fixtures ─────────────────────────────────────────────────────────────────────────────
insert into public.productions (id, title, orientation) values
  ('00000000-0000-0000-0000-0000000000a1', 'Production One', 'horizontal'),
  ('00000000-0000-0000-0000-0000000000a2', 'Production Two', 'vertical');

-- Invitations BEFORE the users exist: the auth trigger must apply them.
insert into public.invitations (email, app_role) values ('admin@hiru.test', 'admin');
insert into public.invitations (email, production_id, production_role) values
  ('producer@hiru.test', '00000000-0000-0000-0000-0000000000a1', 'producer'),
  ('writer@hiru.test',   '00000000-0000-0000-0000-0000000000a1', 'writer'),
  ('writer@hiru.test',   '00000000-0000-0000-0000-0000000000a2', 'reviewer'),
  ('gone@hiru.test',     '00000000-0000-0000-0000-0000000000a1', 'director');

insert into auth.users (id, email, raw_user_meta_data) values
  ('00000000-0000-0000-0000-00000000000a', 'Admin@Hiru.test',    '{"display_name": "Ada Admin"}'),
  ('00000000-0000-0000-0000-00000000000b', 'producer@hiru.test', '{}'),
  ('00000000-0000-0000-0000-00000000000c', 'writer@hiru.test',   '{}'),
  ('00000000-0000-0000-0000-00000000000d', 'outsider@hiru.test', '{}'),
  ('00000000-0000-0000-0000-00000000000e', 'gone@hiru.test',     '{}');

update public.profiles set active = false where id = '00000000-0000-0000-0000-00000000000e';

insert into public.jobs (id, kind, production_id, requested_by) values
  ('00000000-0000-0000-0000-0000000000b1', 'echo', '00000000-0000-0000-0000-0000000000a1', '00000000-0000-0000-0000-00000000000b'),
  ('00000000-0000-0000-0000-0000000000b2', 'echo', '00000000-0000-0000-0000-0000000000a2', '00000000-0000-0000-0000-00000000000a');
insert into public.job_events (job_id, type) values
  ('00000000-0000-0000-0000-0000000000b1', 'status'),
  ('00000000-0000-0000-0000-0000000000b2', 'status');

create function pg_temp.as_user(uid uuid) returns void language sql as $$
  select set_config('role', 'authenticated', true),
         set_config('request.jwt.claims', json_build_object('sub', uid, 'role', 'authenticated')::text, true);
$$;
create function pg_temp.as_postgres() returns void language sql as $$
  select set_config('role', 'postgres', true), set_config('request.jwt.claims', '', true);
$$;

-- ── sign-up applies invitations ──────────────────────────────────────────────────────────
select is((select app_role::text from public.profiles where id = '00000000-0000-0000-0000-00000000000a'),
          'admin', 'admin invitation grants the workspace admin role');
select is((select email from public.profiles where id = '00000000-0000-0000-0000-00000000000a'),
          'admin@hiru.test', 'profile email is lower-cased');
select is((select display_name from public.profiles where id = '00000000-0000-0000-0000-00000000000a'),
          'Ada Admin', 'display name taken from sign-up metadata');
select is((select app_role::text from public.profiles where id = '00000000-0000-0000-0000-00000000000b'),
          'member', 'a production invitation does not make anyone an admin');
select is((select role::text from public.production_members
           where user_id = '00000000-0000-0000-0000-00000000000b'
             and production_id = '00000000-0000-0000-0000-0000000000a1'),
          'producer', 'production invitation creates the membership');
select is((select count(*)::int from public.production_members where user_id = '00000000-0000-0000-0000-00000000000c'),
          2, 'every pending invitation for an email is applied');
select is((select count(*)::int from public.invitations where accepted_at is null), 0,
          'applied invitations are marked accepted');

-- ── admin ────────────────────────────────────────────────────────────────────────────────
select pg_temp.as_user('00000000-0000-0000-0000-00000000000a');
select is((select count(*)::int from public.productions), 2, 'admin sees every production');
select is((select count(*)::int from public.invitations), 5, 'admin sees invitations');
select is((select count(*)::int from public.jobs), 2, 'admin sees every job');

-- ── producer (member of one production) ──────────────────────────────────────────────────
select pg_temp.as_user('00000000-0000-0000-0000-00000000000b');
select is((select count(*)::int from public.productions), 1, 'producer sees only their production');
select is((select count(*)::int from public.production_members
           where production_id = '00000000-0000-0000-0000-0000000000a2'), 0,
          'producer cannot see members of a production they are not on');
select is((select count(*)::int from public.invitations), 0, 'producer cannot see invitations');
select is((select count(*)::int from public.jobs), 1, 'producer sees jobs of their production only');
select is((select count(*)::int from public.job_events), 1, 'job events follow job visibility');
select is((select count(*)::int from public.profiles), 5, 'active users see the staff directory');

-- writes from the browser are denied
select throws_ok($$ insert into public.productions (title, orientation) values ('x', 'vertical') $$,
                 '42501', null, 'browser roles cannot insert productions');
select throws_ok($$ insert into public.production_members (production_id, user_id, role)
                    values ('00000000-0000-0000-0000-0000000000a2', '00000000-0000-0000-0000-00000000000b', 'producer') $$,
                 '42501', null, 'a producer cannot add members, even themselves');
update public.productions set title = 'hacked' where id = '00000000-0000-0000-0000-0000000000a1';
update public.profiles set app_role = 'admin' where id = '00000000-0000-0000-0000-00000000000b';
select pg_temp.as_postgres();
select is((select title from public.productions where id = '00000000-0000-0000-0000-0000000000a1'),
          'Production One', 'browser updates to productions change nothing');
select is((select app_role::text from public.profiles where id = '00000000-0000-0000-0000-00000000000b'),
          'member', 'a member cannot promote themselves');

-- ── writer (two productions, two roles) ──────────────────────────────────────────────────
select pg_temp.as_user('00000000-0000-0000-0000-00000000000c');
select is((select count(*)::int from public.productions), 2, 'writer sees both productions they are on');
select is(public.my_production_role('00000000-0000-0000-0000-0000000000a2')::text, 'reviewer',
          'my_production_role() returns the role on that production');

-- ── outsider (no memberships) ────────────────────────────────────────────────────────────
select pg_temp.as_user('00000000-0000-0000-0000-00000000000d');
select is((select count(*)::int from public.productions), 0, 'a user with no role sees no productions');
select is((select count(*)::int from public.jobs), 0, 'and no jobs');

-- ── deactivated user ─────────────────────────────────────────────────────────────────────
select pg_temp.as_user('00000000-0000-0000-0000-00000000000e');
select is((select count(*)::int from public.productions), 0, 'a deactivated member loses access');
select is((select count(*)::int from public.profiles), 0, 'and cannot read the directory');

-- ── anonymous ────────────────────────────────────────────────────────────────────────────
select set_config('role', 'anon', true), set_config('request.jwt.claims', '', true);
select is((select count(*)::int from public.productions), 0, 'anon sees nothing');

select * from finish();
rollback;
