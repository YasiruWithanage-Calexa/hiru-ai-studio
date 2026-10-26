-- After Phase 5: what a PERSON sets on a shot by hand or in the director chat, and that no agent writes:
-- who is in it (canon chips added or taken out), which advisory checks to ignore, and the DoP's
-- note. Kept apart from `design` (shot_producer rewrites it on every re-design) and from
-- `camera_overrides` (camera fields only), so a re-design or a re-split of the script never
-- undoes it silently. Shape: contracts.producer.PersonEdits.
-- Same access model as before: RLS is read-only for browser roles; the API and the
-- director_chat function (service role) write.
alter table public.shots
  add column person_edits jsonb not null default '{}'::jsonb;
