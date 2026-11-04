-- token_usage learns WHICH part made a model call and what its tool loop cost (plan/2026-11-04, Phase 0).
--
-- One row per model call, as before. A call made by a hiru_ai agent now also says which agent and version it was, a
-- hash of its prompt, how many tool calls the model's answer asked for and how many tokens of tool results the call was
-- sent. That is what `hiru-ai eval --ab` and the monthly review of tool errors read. Rows written by the legacy engines
-- keep the defaults. No policy changes: the table stays service-role only.

alter table public.token_usage
  add column component          text    not null default '',
  add column component_version  integer not null default 0,
  add column prompt_hash        text    not null default '',
  add column tool_calls         integer not null default 0,
  add column tool_result_tokens integer not null default 0;

create index token_usage_component_idx on public.token_usage (component, created_at) where component <> '';
