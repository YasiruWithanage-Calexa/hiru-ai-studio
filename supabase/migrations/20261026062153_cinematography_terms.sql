-- Cinematography terms: a richer craft_techniques (see src/knowledge_base/cinematography).

-- The cinematography terms database (src/knowledge_base/cinematography) is richer than the
-- camera_shots table: what a technique FEELS like (`effect`), the phrase that makes an AI video
-- model render it (`prompt_phrase`), whether it renders reliably (`ai_supported`), mood / scene
-- tags, and the terms it pairs with (`related`: [{type, name}]). Existing rows keep working: every
-- new column has a default. `domain` now also takes light, post, story, format and animation.
alter table public.craft_techniques
  add column slug          text    not null default '',
  add column subcategory   text    not null default '',
  add column effect        text    not null default '',
  add column example_scene text    not null default '',
  add column prompt_phrase text    not null default '',
  add column aliases       text    not null default '',
  add column complexity    text    not null default '' check (complexity in ('', 'basic', 'intermediate', 'advanced')),
  add column ai_supported  boolean not null default true,
  add column tags          text[]  not null default '{}',
  add column related       jsonb   not null default '[]'::jsonb;

-- The result type grows, which `create or replace` cannot do.
drop function public.match_craft_techniques(text, extensions.vector, text, text[], integer, integer);

create or replace function public.match_craft_techniques(
  query_text       text,
  query_embedding  extensions.vector(1536) default null,
  match_domain     text default '',
  match_categories text[] default null,
  match_count      integer default 5,
  rrf_k            integer default 60
)
returns table (
  id bigint, domain text, category text, name text, abbreviation text, definition text,
  use_case text, example_film text, score double precision,
  slug text, subcategory text, effect text, example_scene text, prompt_phrase text,
  aliases text, complexity text, ai_supported boolean, tags text[], related jsonb
)
language sql stable
set search_path = ''
as $$
  with filtered as (
    select t.* from public.craft_techniques t
    where (match_domain = '' or t.domain = match_domain)
      and (match_categories is null or cardinality(match_categories) = 0
           or t.category = any (match_categories)
           or not exists (select 1 from public.craft_techniques c where c.category = any (match_categories)))
  ),
  q as (select public.or_tsquery(query_text) as tsq),
  vec as (
    select f.id, row_number() over (order by f.embedding operator(extensions.<=>) query_embedding, f.id) as r
    from filtered f where query_embedding is not null and f.embedding is not null
  ),
  txt as (
    select f.id, row_number() over (order by ts_rank_cd(f.fts, q.tsq) desc, f.id) as r
    from filtered f, q where q.tsq is not null and f.fts @@ q.tsq
  ),
  fused as (
    select coalesce(v.id, t.id) as id,
           coalesce(1.0 / (rrf_k + v.r), 0) + coalesce(1.0 / (rrf_k + t.r), 0) as score
    from vec v full outer join txt t on v.id = t.id
  )
  select t.id, t.domain, t.category, t.name, t.abbreviation, t.definition, t.use_case,
         t.example_film, f.score::double precision,
         t.slug, t.subcategory, t.effect, t.example_scene, t.prompt_phrase,
         t.aliases, t.complexity, t.ai_supported, t.tags, t.related
  from fused f join public.craft_techniques t on t.id = f.id
  order by f.score desc, t.id
  limit greatest(match_count, 1);
$$;

grant execute on function public.match_craft_techniques(text, extensions.vector, text, text[], integer, integer)
  to authenticated, service_role;
revoke execute on function public.match_craft_techniques(text, extensions.vector, text, text[], integer, integer) from anon;
