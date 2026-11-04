-- ═══════════════════════════════════════════════════════════════════════════════════════════
-- Hiru AI Studio — upgrade a project from schema v9 to schema v10 (token_usage says which agent made a
-- model call, a hash of its prompt, how many tool calls its answer asked for and what the tool results
-- it was sent cost; plan/2026-11-04, Phase 0).
--
-- Safe to re-run: every statement skips what already exists.
--
-- HOW TO APPLY: only on a project that already has schema v9. SQL Editor → paste this whole
-- file → Run, once. It runs in one transaction: if any statement fails, nothing changes.
-- A NEW project runs schema_v10.sql instead (v9 + this file gives the same schema as v10).
-- Then set USAGE_DETAIL=true where the API and the functions run, so new rows carry the columns;
-- until then they are written without them and nothing breaks.
-- ═══════════════════════════════════════════════════════════════════════════════════════════
begin;

alter table public.token_usage
  add column if not exists component          text    not null default '',
  add column if not exists component_version  integer not null default 0,
  add column if not exists prompt_hash        text    not null default '',
  add column if not exists tool_calls         integer not null default 0,
  add column if not exists tool_result_tokens integer not null default 0;

create index if not exists token_usage_component_idx on public.token_usage (component, created_at) where component <> '';

commit;
