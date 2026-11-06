-- token_usage keeps a call's hidden reasoning apart from its answer (plan/2026-11-05, Phase 0). A row that names none
-- keeps 0, and browser roles still read nothing.
begin;
select plan(3);

delete from public.token_usage;

insert into public.token_usage (phase, model, input_tokens, output_tokens) values ('legacy.phase', 'gpt-5', 10, 5);
insert into public.token_usage (phase, model, input_tokens, output_tokens, reasoning_tokens, component)
  values ('agent.planner', 'gpt-5', 9000, 21000, 14000, 'agent:planner');

select is((select reasoning_tokens from public.token_usage where phase = 'legacy.phase'), 0,
  'a row that names no reasoning keeps 0');
select is((select reasoning_tokens from public.token_usage where component = 'agent:planner'), 14000,
  'a row keeps the reasoning of its output');

set local role authenticated;
select is((select count(*)::int from public.token_usage), 0, 'a signed-in person reads no usage rows');

select * from finish();
rollback;
