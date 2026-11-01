-- A translated line keeps the words it was written in (plan/2026-11-01c, Phase 4). The script stays in its own
-- language by default; when a person asks for the dialogue in another language the director chat's translator
-- writes `text`, and these two columns hold what the line said before: the first original, however many times
-- it is translated after. `source_lang` is the script the original was in ('en', 'si', 'ta', 'hi' or 'mixed').
-- Both are null for a line nobody has translated.

alter table public.dialogue_lines
  add column source_text text,
  add column source_lang text,
  add constraint dialogue_lines_source_pair check ((source_text is null) = (source_lang is null));
