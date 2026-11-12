-- House rules and implied things (plan/2026-11-12 §3.2). Schema v22 (Database/schema_v22.sql, upgrade_v21_to_v22.sql).
--
-- A canon version may come from `inferred`: a thing the script implies but does not name (the phone a voice message
-- plays from). The scene breakdown writes it with the service role; a person can rename, change or delete it.

alter table public.canon_versions drop constraint if exists canon_versions_source_check;
alter table public.canon_versions
  add constraint canon_versions_source_check check (source in ('extract', 'user', 'inferred'));
comment on column public.canon_versions.source is
  'extract: read from a document; user: a person''s edit; inferred: implied by the script, not named in it (plan/2026-11-12)';
