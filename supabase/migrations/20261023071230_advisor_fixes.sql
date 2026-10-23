-- Fixes from `supabase db advisors` (security + performance), run after Phase 1.
--
-- 1. RLS policies call auth.uid() and the argument-free helpers through `(select ...)`, so
--    Postgres evaluates them ONCE per query (an initplan) instead of once per row. Helpers that
--    take a row value (can_view_production(production_id)) are per-row by nature and stay as is.
-- 2. Covering indexes for foreign keys: without them, deleting or nulling the parent row
--    (a production, a job, a profile) scans the whole child table.

-- ── 1. policies ──────────────────────────────────────────────────────────────────────────
drop policy profiles_read on public.profiles;
create policy profiles_read on public.profiles
  for select to authenticated using ((select public.is_active_user()));

drop policy invitations_read on public.invitations;
create policy invitations_read on public.invitations
  for select to authenticated using ((select public.is_admin()));

drop policy audit_log_read on public.audit_log;
create policy audit_log_read on public.audit_log
  for select to authenticated
  using ((select public.is_admin())
         or (production_id is not null and public.can_view_production(production_id)));

drop policy jobs_read on public.jobs;
create policy jobs_read on public.jobs
  for select to authenticated
  using ((select public.is_admin())
         or (production_id is not null and public.can_view_production(production_id))
         or (production_id is null and requested_by = (select auth.uid())));

drop policy chunks_read on public.chunks;
create policy chunks_read on public.chunks
  for select to authenticated
  using ((production_id is null and (select public.is_active_user()))
         or (production_id is not null and public.can_view_production(production_id)));

drop policy craft_techniques_read on public.craft_techniques;
create policy craft_techniques_read on public.craft_techniques
  for select to authenticated using ((select public.is_active_user()));

drop policy token_usage_read on public.token_usage;
create policy token_usage_read on public.token_usage
  for select to authenticated using ((select public.is_admin()));

-- ── 2. foreign-key indexes ───────────────────────────────────────────────────────────────
create index audit_log_actor_idx            on public.audit_log (actor_user_id);
create index documents_confirmed_by_idx     on public.documents (confirmed_by);
create index documents_uploaded_by_idx      on public.documents (uploaded_by);
create index invitations_invited_by_idx     on public.invitations (invited_by);
create index invitations_production_idx     on public.invitations (production_id);
create index production_members_added_by_idx on public.production_members (added_by);
create index productions_created_by_idx     on public.productions (created_by);
create index token_usage_actor_idx          on public.token_usage (actor_user_id);
create index token_usage_job_idx            on public.token_usage (job_id);
create index token_usage_production_idx     on public.token_usage (production_id);
