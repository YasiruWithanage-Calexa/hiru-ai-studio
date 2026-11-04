-- Shot Planner Adam keeps a card on each shot and its plan on the scene (plan/2026-11-04b, Phase 6). A shot the classic
-- planner made keeps the defaults; a browser role reads the new columns only where it could already read the row.
begin;
select plan(8);

select has_column('public', 'shots', 'card', 'a shot has a card');
select has_column('public', 'shots', 'planner', 'and says which planner made it');
select has_column('public', 'scenes', 'adam', 'a scene keeps Adam''s plan');

insert into public.productions (id, title, orientation)
  values ('00000000-0000-0000-0000-0000000000b1', 'Adam test', 'vertical');
insert into public.episodes (id, production_id, number, title)
  values ('00000000-0000-0000-0000-0000000000c1', '00000000-0000-0000-0000-0000000000b1', 1, 'Ep 1');
insert into public.scenes (id, production_id, episode_id, number, envelope_s)
  values ('00000000-0000-0000-0000-0000000000d1', '00000000-0000-0000-0000-0000000000b1',
          '00000000-0000-0000-0000-0000000000c1', 1, 60);
insert into public.shots (production_id, scene_id, number, duration_s)
  values ('00000000-0000-0000-0000-0000000000b1', '00000000-0000-0000-0000-0000000000d1', 1, 6);
insert into public.shots (production_id, scene_id, number, duration_s, planner, card)
  values ('00000000-0000-0000-0000-0000000000b1', '00000000-0000-0000-0000-0000000000d1', 2, 4, 'adam',
          '{"number": 2, "size": "CU"}'::jsonb);

select is((select planner from public.shots where number = 1), 'classic', 'a classic shot is classic by default');
select is((select card from public.shots where number = 1), '{}'::jsonb, 'and has no card');
select is((select card ->> 'size' from public.shots where number = 2), 'CU', 'an Adam shot keeps its card');
select is((select adam from public.scenes where number = 1), '{}'::jsonb, 'a scene Adam never planned has no plan');
select throws_ok(
  $$insert into public.shots (production_id, scene_id, number, duration_s, planner)
    values ('00000000-0000-0000-0000-0000000000b1', '00000000-0000-0000-0000-0000000000d1', 3, 4, 'other')$$,
  '23514', null, 'only classic or adam may plan a shot');

select * from finish();
rollback;
