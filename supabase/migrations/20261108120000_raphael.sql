-- Shot Planner Raphael (plan/2026-11-08e, Phase 4): the one shared migration.
--
--   scenes.raphael   contracts.raphael.stored.StoredRaphael: the intended cut, the shoot bin (stage 1's must clips and stage 2's
--                    cinematic clips, each with its design), the editor notes and blend notes, the moment review, what is left
--                    reported, the length cap used, the seconds against the target and the cap, and a hash of what Raphael was
--                    given. `{}` for a scene Raphael never planned.
--   shots.planner    gains 'raphael': Raphael writes the same shots rows as the others, one per clip, with `ir` and `design`
--                    already current.
--   shots.role, priority, slate, handle_in_s, handle_out_s, stage, anchor, blend
--                    the clip's plan fields: what the shot is in the bin (a master, an insert ...), must / should / nice, its
--                    slate, its handles, which stage made it (1 must, 2 cinematic; 0 for another planner's shot) and, for a
--                    cinematic clip, the slates of the must clips it sits with and how post blends it.
--
-- The production's choice of planner is `productions.settings.shot_planner` ('classic' | 'adam' | 'david' | 'jonathan' |
-- 'raphael') and its default length cap `settings.raphael_length_cap` (1.5 | 2 | 2.5 | 3): keys in the existing settings JSON,
-- no column. No new table and no new policy. Deleting Raphael leaves these columns unused.

alter table public.scenes add column raphael jsonb not null default '{}'::jsonb;

alter table public.shots drop constraint shots_planner_check;
alter table public.shots add constraint shots_planner_check check (planner in ('classic', 'adam', 'david', 'jonathan', 'raphael'));

alter table public.shots
  add column role         text not null default '',
  add column priority     text not null default '' check (priority in ('', 'must', 'should', 'nice')),
  add column slate        text not null default '',
  add column handle_in_s  numeric(4, 2) not null default 0,
  add column handle_out_s numeric(4, 2) not null default 0,
  add column stage        smallint not null default 0 check (stage in (0, 1, 2)),
  add column anchor       jsonb not null default '[]'::jsonb,
  add column blend        text not null default '' check (blend in ('', 'cut_in', 'under_line', 'open', 'close', 'transition'));

comment on column public.shots.planner is
  'Which planner made this shot: classic (script_split), adam (Shot Planner Adam), david (Shot Planner David), jonathan (Shot Planner Jonathan) or raphael (Shot Planner Raphael).';
comment on column public.scenes.raphael is
  'contracts.raphael.stored.StoredRaphael: Shot Planner Raphael''s result as written (the intended cut, the must clips and the cinematic clips with their designs, the editor and blend notes, the moment review, what is left reported, the length cap used and the seconds against it). {} for a scene Raphael never planned.';
comment on column public.shots.stage is
  'Raphael: 1 = a must clip (stage 1), 2 = a cinematic clip (stage 2); 0 = not a Raphael shot.';
comment on column public.shots.anchor is
  'Raphael: for a cinematic clip, the slates of the must clips it sits with.';
