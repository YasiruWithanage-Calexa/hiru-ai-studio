# plan/2026-11-19: what is built

Built offline on 2026-11-19, both repos, **uncommitted**. No paid call was made.

| Phase | State | Where |
|---|---|---|
| 1 Take lengths rule + settings | BUILT | `contracts/take_lengths.py`; `ProductionSettings.max_take_s` / `take_lengths` / `takes`; `Shot.duration_s` 3–15; `PATCH /productions` locks both (`_locked_takes`); `shotplan.fit(lengths=)`, `timing.default_beats` any length; `PATCH /shots` retime checks `ld.takes`; `SceneView.take_lengths` |
| 2 Omni Flash 1.2 only | BUILT | `video_gen.ENGINE_CAPABILITIES` = omni_flash (model `gemini-omni-1.2-flash`, 3–15 s, no versions). Veo rows moved to `RETIRED_CAPABILITIES` (never offered; `capability()` still reads them so an in-flight Veo render finishes and old requests describe themselves). `_retired` reads a stored Veo engine as omni_flash and a stored 1.1/Veo model id as the default; `resolve` drops a Veo option (`person_generation`) unless the take is on a retired engine. `engine_label` keeps old takes named "Veo 3.1" |
| 3 Raphael | BUILT | `SceneS.takes` (+ `longest`, `legacy`); `scene_dump` drops 4/6/8 so old inputs hash as before; `shortest_take(need, takes)`, `parts_needed(s, longest)`, long actions and the listing use the scene's longest; `MenuW.take_s` is an int 3–15 and the tool schema's enum is the run's lengths (`wire_schema.stage1_specs(takes)`/`stage2_specs`); `checks.clock` refuses a length outside the scene's; `checks.long_take` (D5, report only); `<length>` says "A take here is ..." only when the lengths are not 4/6/8; one tagged prompt line `- TAKE LENGTHS (plan/2026-11-19).` in planner and cinematic (lab parity updated); `StoredRaphael.takes` for `raphael_write`; graph passes `settings.takes` to both scene builders (script and packet) |
| 4 Zora / Sable | BUILT | `Coverage.takes` + `takes_of(production row)`; `coverage_rows` and `row_trial` pass the production; kernel retime/insert refuse with the lengths in words; the coverage head says "A take here is ..."; Zora's wire names 3–15 (`RENDERABLE`), the kernel checks; quick "S04 10 seconds" path uses `cov.takes`; prompt lines in zora_author, zora_conductor, sable_agent |
| 5 Database v27 | APPLIED by the person 2026-11-19 | `Database/upgrade_v26_to_v27.sql`, `Database/schema_v27.sql`: `shots.duration_s between 3 and 15`. Until applied, saving a 3/5/7/9+ s shot fails in the database |
| 6 Probe 7 s and 13 s on 1.2 | NOT RUN | paid, the person's |
| 7 Interface | BUILT | create form: "Video model: Omni Flash 1.2" (no engine choice), "Longest take" 10/15 s, "Take lengths" Steps/Any length (sends `max_take_s`, `take_lengths`); `lib/takes/lengths.ts`; shot list length menu and chip from `scene.takeLengths`; drama page and build dialog show the production's lengths; Video card: version picker removed; `defaultBeats` any length |
| 8 Lab, one scene each mode | NOT RUN | paid, the person's |

## Option 3: old productions choose once (the person, 2026-11-19)

BUILT. A production with no `max_take_s` may set `max_take_s` + `take_lengths` ONCE (`PATCH /productions`,
`_locked_takes`). In the same request every existing shot gets `duration_locked = true` (`ShotsRepo.lock_lengths`)
BEFORE the settings change, so the scene view's re-fit re-times nothing already made; audit `production.take_lengths`
with the count. After that both are locked. A re-planned scene's new rows are unlocked and use the new lengths. Side
effect: Zora/Sable treat those fixed lengths as a person's lock (they will not retime them); a person still can, to any
length the production allows. Interface: the settings page's "Longest take" row (choose once, then read-only).
Tests: `tests/api/test_take_lengths.py::test_an_old_production_chooses_once_and_every_shot_keeps_its_length`,
`src/features/template/client.test.ts`.

## Deviations from PLAN.md

- D1/D2 (revision in PLAN.md): a production with no `max_take_s` (every one made before) keeps 4/6/8, and the take
  lengths are locked at creation too: the scene view re-fits shots with the production's lengths, so widening an old
  production would merge its unlocked shots.
- Phase 2 kept the Veo provider code and capability rows (as retired) instead of deleting them.

## Tests

- New: `tests/contracts/test_take_lengths.py`, `tests/raphael/test_take_lengths.py`, `tests/api/test_take_lengths.py`;
  interface `src/lib/takes/lengths.test.ts`, `defaultBeats` cases.
- Rewritten for Omni 1.2: video_gen, renders API, video_render worker tests. Three API tests of Veo-only behaviour (a
  recorded seed, seed from a take, a start frame OR sheets) are skipped as `VEO_RETIRED`.
- Failing before this plan and still failing (not touched): Raphael length cap `1` vs `1.5` (backend `test_api` x2,
  `test_checks[1]`, interface `raphael-panel.test`); `test_removal` allow-lists (schema_v20+); file URLs on 8001 vs 8000
  (handoff, looks, production, thumbs); `test_scene_canon` cast mark.
- Full backend suite not re-run end to end: the disk is full (179 MB free), so the HEAD worktree baseline could not be
  made. The affected folders were run: 1062 passed, 5 failed (all listed above).

## Open for the person

1. ~~Apply v27~~ done by the person 2026-11-19.
2. Phase 6 probe (two short 1.2 takes) and phase 8 lab (~$0.30): each needs a yes.
3. D3: Steps on a 15 s production are 4…14 (no 15). Say if 15 should be a step.
4. Not done: `memory_conflicts` still flags 10/15 s in documents as "not a Veo length"; director_capabilities wording;
   the Veo prompting guide and `clip_schema_veo_3_1.yaml`.
