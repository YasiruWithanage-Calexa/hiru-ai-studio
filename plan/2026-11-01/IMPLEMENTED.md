# Staging and second looks: what is built

Plan: [PLAN.md](PLAN.md). All twelve fixes are built and tested offline (2026-11-01). Nothing is
deployed and nothing was run against OpenAI or the hosted database.

## Who is seen (A1–A3)

- `contracts/staging.py`: `shot_cast` (everyone in the shot, seen or heard, plus who an intent
  puts on screen), `staging` (who is seen: person edits → intent → DoP `on_screen` → rules), and
  the hard rule that a line MARKED as heard (on the phone, off screen, v.o., radio, TV, intercom)
  keeps its speaker off screen unless a person added them. `HEARD_MARKS` now lives in
  `contracts/shotplan.py` and is the one list for both the split kernel and staging.
- `frame_render`: references, the People line and the vision expectation use only who is seen;
  the frame prompt adds "<name> is not in this place and not in the frame (heard through the
  phone held by Anudi…)". Pins still cover everyone (a voice's card is part of the shot).
- Video prompt: `offscreen_line` and `heard_source` in the clip schema; no wardrobe tag for a
  voice; heard people leave the Subjects section; `lip_lock` and `no_extra_people` follow who is
  seen; prompt checks say "Heard only · X (phone)".
- Camera card checks: `staging` (heard only, speaker not on screen, first frame shows someone only
  heard, DoP and intent disagree) and `coverage` (a scene of one size, the same setup twice).
  Both are in `CHECK_TOPICS`, so a person can ignore them per shot.

## Context, intent, coverage (B4–B6)

- The DoP's scene prompt carries the scene title and note, the episode title and synopsis, and the
  scenes either side (`Store.neighbours`), plus the coverage plan and, per shot, PURPOSE, WHAT WE
  SEE, EMOTIONAL BEAT, ON SCREEN and HEARD ONLY. The DoP answers `on_screen`, stored on the design.
- `engine/intent.py` (high tier, schema `shot_intent`, one call per scene) runs before a design
  that is needed. Rules fallback: the script's actions, who is heard, and for a voice over nobody
  the nearest on-camera speaker as listener. Scene plan by rules: the size progression.
- An intent is rewritten when missing or written against other material (`intent_basis`), or on
  `force`; never when `by == "person"`. The design records the intent's stamp; a change makes the
  design out of date.
- API: `PATCH /shots/{id}/intent` (only people already in the shot can be on screen; `reset`
  hands it back), `PATCH /scenes/{id}/coverage`. Views: `people`, `intent`, `design.review`,
  `coverage`, `frames[].checks`.
- Interface: "What this shot is for" and "Scene coverage" cards in step 1 of the shot page, each
  editable; frame check chips under each first frame.

## Second looks (C7–C9)

- `engine/critique.py`: free staging + coverage problems → one high-tier review (≤ 4 notes) → one
  revision of the modelled shots with the notes → each shot keeps its revision only when the free
  checks find no more problems. Notes and revised shots are stored as `design.review` and shown.
- `frame_render/engine/inspect.py`: a vision model (`OPENAI__MODEL_VISION`, default `gpt-5-mini`,
  "" = off; usage row `frame_render.vision`) counts the main people, says if someone only heard
  shows, and if the picture matches the DoP's first frame. Plus "No reference sheet · X" for
  an on-screen person painted without one. Stored in `first_frames.checks`.
- `techniques.articulate` (medium tier): 2–5 craft problems for the job's scenes; they lead the
  technique queries (max 6) and open the DoP's production block.

## Shot list (D10–D11)

- Planner rules: vary sizes in scenes of more than three shots, one physical event per 4 s shot,
  a WIDE when a scene opens on movement through space, titles that name what is seen.
- Critic on the high tier; `describe` adds `Sizes:`, `BUSY:` and `No WIDE:` lines. The plan score
  is unchanged.

## Eval (D12)

`scripts/eval_staging.py` runs `tests/eval/staging_scenes.json` (15 hard scenes) in memory through
the split and the shot producer. Rules mode: heard_kept_out 0.818, seen_shown 1.0, speaker_framed
1.0, size_variety 1.0 (floor in `tests/eval/staging_thresholds.json`, checked by
`tests/services/shot_producer/test_eval_staging.py`). The two misses are calls with no off-screen
mark, which only the intent agent can catch. Model mode has no floor yet.

## Database

`schema_v9.sql`, `upgrade_v8_to_v9.sql`, migration `20261101031324_shot_intent_and_frame_checks`:
`shots.intent`, `scenes.coverage`, `first_frames.checks` (JSON, defaults). No new table or policy.
Until v9 is applied, shot_producer and frame_render log and skip the new fields (a paid frame is
never lost); the API's intent and coverage edits fail.

## Checks run

`pytest` 735 passed; `ruff` clean; `mypy` root and per service clean. Interface: `next typegen`,
`npm run check` (lint, typecheck, 73 tests) pass; the touched files pass Prettier.

## Not done (needs the user)

- Apply `upgrade_v8_to_v9.sql` on the hosted dev DB (not verified: no Docker for `supabase test db`).
- Run `python scripts/eval_staging.py` with a key, then `--update-thresholds` to set the model floor.
- Redesign Scene 2 (force) and make new frames for S05; compare with the three old frames.
