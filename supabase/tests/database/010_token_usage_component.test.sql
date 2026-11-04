-- token_usage says which part made a call and what its tool loop cost (plan/2026-11-04, Phase 0). A row that names
-- none of it (a legacy engine) keeps the defaults, and browser roles still read nothing.
begin;
select plan(5);

delete from public.token_usage;

insert into public.token_usage (phase, model, input_tokens) values ('legacy.phase', 'gpt-5', 10);
insert into public.token_usage (phase, model, input_tokens, cached_input_tokens, output_tokens, component,
                                component_version, prompt_hash, tool_calls, tool_result_tokens)
  values ('agent.chat_answerer', 'gpt-5', 900, 700, 40, 'agent:chat_answerer', 2, 'a1b2c3d4e5f6', 2, 640);

select is((select component from public.token_usage where phase = 'legacy.phase'), '',
  'a legacy row names no component');
select is((select tool_calls + tool_result_tokens + component_version from public.token_usage
           where phase = 'legacy.phase'), 0, 'and no tool loop');
select is((select tool_result_tokens from public.token_usage where component = 'agent:chat_answerer'), 640,
  'an agent row keeps what its tool results cost');
select is((select count(*)::int from public.token_usage where component <> ''), 1,
  'the component index covers only rows that name one');

set local role authenticated;
select is((select count(*)::int from public.token_usage), 0, 'a signed-in person reads no usage rows');

select * from finish();
rollback;
