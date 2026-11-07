-- The document reader (plan/2026-11-06f): the model reads a whole document (its text, or its page images when the text
-- layer is scrambled) once at ingest, and the reading is kept beside the text. A scene read from page images waits for a
-- person to confirm its dialogue (decision 6). Schema v16 (Database/schema_v16.sql, upgrade_v15_to_v16.sql).

-- documents.reading_path: the stored reading (contracts.doc_read.Reading) in the documents bucket; null = not read.
-- documents.read_from: how it was read: 'text' (checked word for word) or 'pages' (from the page images).
alter table public.documents add column if not exists reading_path text;
alter table public.documents add column if not exists read_from text check (read_from in ('text', 'pages'));

-- scenes.read_from: how the scene's script was read; null = the rules read it (as before the reader).
-- scenes.read_confirmed_by / _at: the person who checked a 'pages' scene's dialogue against the page; cleared when a
-- build writes the scene again.
alter table public.scenes add column if not exists read_from text check (read_from in ('text', 'pages'));
alter table public.scenes add column if not exists read_confirmed_by uuid references public.profiles (id) on delete set null;
alter table public.scenes add column if not exists read_confirmed_at timestamptz;
create index if not exists scenes_read_confirmed_by_idx on public.scenes (read_confirmed_by);
