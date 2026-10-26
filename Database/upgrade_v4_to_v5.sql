-- ═══════════════════════════════════════════════════════════════════════════════════════════
-- Hiru AI Studio — upgrade a project from schema v4 to schema v5 (the director chat edits the
-- Script column: a shot's own marks, set by a person, are `shots.person_edits`).
--
-- HOW TO APPLY: only on a project that already has schema v4. SQL Editor → paste this whole
-- file → Run, once. It runs in one transaction: if any statement fails, nothing changes.
-- A NEW project runs schema_v5.sql instead (v4 + this file gives the same schema as v5).
-- ═══════════════════════════════════════════════════════════════════════════════════════════

begin;

-- Who is in the shot (canon chips added or taken out), which advisory checks to ignore, and the
-- DoP's note (contracts.producer.PersonEdits). Written by the API and director_chat, never by an
-- agent, so a re-design or a re-split of the script does not undo it. Read-only for browsers.
alter table public.shots
  add column person_edits jsonb not null default '{}'::jsonb;

commit;
