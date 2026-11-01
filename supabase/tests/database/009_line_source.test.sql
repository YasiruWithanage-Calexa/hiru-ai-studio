-- A translated line keeps the words it was written in (plan/2026-11-01c, Phase 4): source_text and
-- source_lang are set together or not at all.
begin;
select plan(4);

delete from public.dialogue_lines; delete from public.shots;
delete from public.scenes; delete from public.episodes;
delete from public.invitations; delete from public.audit_log; delete from public.productions;

insert into public.productions (id, title, orientation) values
  ('00000000-0000-0000-0000-0000000000a1', 'One', 'horizontal');
insert into public.episodes (id, production_id, number) values
  ('00000000-0000-0000-0000-000000000101', '00000000-0000-0000-0000-0000000000a1', 1);
insert into public.scenes (id, production_id, episode_id, number, envelope_s) values
  ('00000000-0000-0000-0000-000000000201', '00000000-0000-0000-0000-0000000000a1', '00000000-0000-0000-0000-000000000101', 1, 60);

select lives_ok($$ insert into public.dialogue_lines (production_id, scene_id, ord, speaker, text)
  values ('00000000-0000-0000-0000-0000000000a1', '00000000-0000-0000-0000-000000000201', 0, 'Nimal', 'අම්මේ') $$,
  'a line nobody translated has no source');
select lives_ok($$ insert into public.dialogue_lines (production_id, scene_id, ord, speaker, text, source_text, source_lang)
  values ('00000000-0000-0000-0000-0000000000a1', '00000000-0000-0000-0000-000000000201', 1, 'Kamala', 'වාඩි වෙලා කන්න.',
          'Sit down and eat.', 'en') $$, 'a translated line keeps its original and its language');
select throws_ok($$ insert into public.dialogue_lines (production_id, scene_id, ord, speaker, text, source_text)
  values ('00000000-0000-0000-0000-0000000000a1', '00000000-0000-0000-0000-000000000201', 2, 'Nimal', 'x', 'y') $$,
  '23514', null, 'an original without its language is refused');
select throws_ok($$ insert into public.dialogue_lines (production_id, scene_id, ord, speaker, text, source_lang)
  values ('00000000-0000-0000-0000-0000000000a1', '00000000-0000-0000-0000-000000000201', 3, 'Nimal', 'x', 'en') $$,
  '23514', null, 'a language without its original is refused');

select * from finish();
rollback;
