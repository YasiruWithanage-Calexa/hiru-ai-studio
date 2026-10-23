-- Monthly model-token total for GET /v1/usage (the UI shows a percentage only).
-- Called by the API with the service role; browser roles have no use for it.
create or replace function public.token_usage_since(since timestamptz)
returns bigint
language sql stable
set search_path = ''
as $$
  select coalesce(sum(input_tokens::bigint + output_tokens::bigint), 0)::bigint
  from public.token_usage
  where created_at >= since;
$$;

revoke all on function public.token_usage_since(timestamptz) from public, anon, authenticated;
grant execute on function public.token_usage_since(timestamptz) to service_role;
