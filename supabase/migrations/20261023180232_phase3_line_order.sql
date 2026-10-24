-- Phase 3: a script edit can insert, delete and reorder lines. The API writes the scene's lines
-- in one upsert (keeping their ids, which shots and beats are bound to), so their order only
-- has to be unique again by the end of the transaction, as with shot numbers.
alter table public.dialogue_lines drop constraint dialogue_lines_scene_id_ord_key;
alter table public.dialogue_lines add constraint dialogue_lines_scene_id_ord_key
  unique (scene_id, ord) deferrable initially deferred;
