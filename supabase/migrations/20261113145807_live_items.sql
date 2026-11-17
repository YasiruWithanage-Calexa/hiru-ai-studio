-- The status read in one query (plan/2026-11-13d phase 3, schema v25): what `/live` read with four queries (frames,
-- renders, documents, jobs) plus one for the build's newest event, as one union. Only the columns `/live` returns; the
-- API calls it with the service role, no browser role may.
create or replace function public.live_items(p_production uuid, p_since timestamptz default null)
returns table (kind text, id uuid, shot_id uuid, status text, job_kind text, updated_at timestamptz, seq bigint)
language sql
stable
security invoker
set search_path = ''
as $$
  select 'frame', f.id, f.shot_id, f.status, null::text, f.updated_at, null::bigint
    from public.first_frames f
   where f.production_id = p_production
     and (f.status in ('queued', 'running') or f.updated_at > p_since)
  union all
  select 'render', r.id, r.shot_id, r.status, null, r.updated_at, null
    from public.video_renders r
   where r.production_id = p_production
     and (r.status in ('queued', 'running') or r.updated_at > p_since)
  union all
  select 'document', d.id, null, d.status::text, null, d.updated_at, null
    from public.documents d
   where d.production_id = p_production
     and (d.status = 'processing' or d.updated_at > p_since)
  union all
  select 'job', j.id, null, j.status::text, j.kind, j.updated_at,
         case when j.kind = 'structure_build'
              then (select e.seq from public.job_events e where e.job_id = j.id order by e.seq desc limit 1) end
    from public.jobs j
   where j.production_id = p_production
     and (j.status in ('pending', 'running') or j.updated_at > p_since)
  order by 6, 1, 2;
$$;

comment on function public.live_items(uuid, timestamptz) is
  'plan/2026-11-13d phase 3: /live in one query. Active rows, and rows changed after p_since (null: active only). '
  'seq: the structure build''s newest event number.';

revoke all on function public.live_items(uuid, timestamptz) from public, anon, authenticated;
grant execute on function public.live_items(uuid, timestamptz) to service_role;
