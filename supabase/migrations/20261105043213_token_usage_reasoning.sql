-- token_usage learns how much of a call's output was hidden reasoning (plan/2026-11-05, Phase 0).
--
-- A reasoning model bills its thinking as output tokens, and the 2026-11-04 build showed that is most of the bill (about
-- 93 % of the cost was gpt-5 output, mostly reasoning). The column keeps it apart from the answer, so a cost per scene
-- can be read from the table. A row that does not name it (a legacy engine, a model that does not reason) keeps 0.
-- No policy changes: the table stays service-role only.

alter table public.token_usage
  add column reasoning_tokens integer not null default 0;

comment on column public.token_usage.reasoning_tokens is
  'Of output_tokens, the part that was hidden reasoning (a reasoning model bills it as output). 0 for a legacy row.';
