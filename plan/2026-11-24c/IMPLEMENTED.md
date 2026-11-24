# plan/2026-11-24c: what is built

Built offline on 2026-11-24, both repos, uncommitted. No paid call. The person said "implement 2026-11-24c" without
answering D1-D3, so the recommendations were taken: **D1** the writer answers, a person may set the three answers first
on the canon page (theirs win); **D2** one re-ask on findings, then stored with the findings shown; **D3** the roadside
sheet with the three-wheeler in it stays until the person remakes it (paid, about $0.09). No migration (§2.6): every new
field lives in the `views` reference asset's JSON.

## Built

| Plan | Where |
|---|---|
| §2.1 answers + templates | `contracts/canon.py`: `VIEW_TEMPLATES` (the lab's `TEMPLATES`, word for word), `VIEW_SIDES`, `VIEW_SIZES`, `view_template` (lab `template_of`), `template_slots`, `view_words`, `view_key_words`; API `ViewAnswers`, `LocationView` gains `camera`/`sees` (`what` optional, max 1400) |
| §2.2 the writer | `agents/views_writer` v2: schema = the lab's `Written` (`answers`, `layout`, `empty`, `views[{slot, camera, sees}]`) + the built `light`; prompt = the lab's `SYSTEM` (r2) rendered; message = the lab's `user_message`; the plate goes to the writer as a 1024 px JPEG (`images` hook); `within` / `comes_and_goes` / `geographies` / `answers` / `findings` inputs |
| §2.3 code checks | `contracts.canon.view_findings(written, card_look, scenes)`: slots in order; quoted text or sign wording the card has not; a detail naming nothing from the card or a scene; a plain table/chair/stool/wall/floor/ceiling no scene uses; an empty space that says not where it is. `render_views`: one re-ask with the findings, then stored with what is left (`findings` on the asset and the job result) |
| §2.4 the sheet | `contracts.canon.views_sheet_prompt` replaced by the lab's `sheet_prompt` (place / vehicle head, take-from, no-plate words, `empty`, no vehicle parked, vehicle alone on grey concrete) with the dry light line; the writer's `light` is stored, never painted; `VIEW_JOB` + "not its light, weather or wet ground"; `render_views` paints a place with no plate from its card's words, attaches only the place's own plate (never other places' or vehicles' plates); the asset gains `answers`, `template`, `empty`, `findings` and each view's `camera`/`sees` (`what` = both, so the frame and shot prompter read it as before) |
| §2.2/§3 API | `POST .../canon/{id}/views-sheet`: no plate needed (409 only without a card), optional `answers`; `_views_context` gives the scenes as the lab's text, splits vehicles named there into `comes_and_goes`, and finds a vehicle card's scenes by its name or aliases; `CanonEntity.views_answers/template/empty/findings`; the board's "No location views yet" note no longer needs a plate |
| §2.7 the board | writer rule "a panel names the view its camera FACES" (board_writer prompt); the bundle gives each view's `camera` and `sees`; PANEL line "Background view: view 4 (Reverse): <first sentence of sees>" (`board.view_named`, `view_line`); `board_inspector` v2 gets `view` + `view_b64` (the crop, second picture) and answers `view_match`; `frame_render/board.py` `Board.view_crop` (the sheet read once), `_faults` adds the view mismatch, `_mend` repaints once with `fix_line(..., view)` naming the view; still wrong → the built conflict line on the board card |
| §2.5 interface | `LocationViewsSection`: three answer selects ("the writer decides" by default; sent only when all three are set), template chip, slot names over the views (sees shown), findings (amber status), "Kept bare" spaces, "Make/Remake vehicle views" on a vehicle card, no plate needed; edits send `camera` + `sees`; `lib/view-templates.ts` (slot names); types, mapper, client |
| §6 docs | `docs/scene_board/README.md` (Place views by type), `docs/AI_CATALOG.md` regenerated |

## Changes from the lab's words (§0 asks to list them)

1. **Sheet light line**: the lab's "soft, even daylight that shows the {what} clearly; the same light in every view" is
   "soft, even, dry daylight that shows the {what} clearly; dry ground, no rain, no puddles, no reflections; the same
   light in every view" (§2.4).
2. **Writer prompt**: the lab's `SYSTEM` (r2) unchanged, plus four lines after its rules: follow the storyboards'
   geography and name the same things with the same words (the built prompt's two good lines, §2.2); a detail's `sees`
   starts with the thing's name (§2.1); write the place dry, the scenes' weather goes in `light`, never painted (§2.4);
   use the person's answers when given (D1).
3. **Writer message**: the lab's `user_message` word for word, then (only when present) the fixed places in it, the
   vehicles that come and go, the boards' geographies, the person's answers and the re-ask's findings.
4. **Check 4** tests "where it is" in code (the entry, or the layout sentence that names it). "What its ground looks
   like" is asked for in the writer's field and in the finding's words but not checked: the r2 roadside, which the
   plan's phase 1 test accepts, never says its bay's ground.
5. **Check 3**: a plain thing counts as used when a scene puts something or someone on, at or beside it ("documents on
   the table"); the restaurant's scene names "wooden tables" only as setting, so its table detail is found. The detail's
   thing is read from its `camera` line.
6. **The board writer's example** for §2.7 is a jetty, not the roadside: that prompt's rule is examples from other
   stories, never one scene's words (plan/2026-11-14 §0).
7. **Panel key words** are the first sentence of the view's `sees` (cut at 220 characters); an older sheet's `what`.

## Tests

New: `tests/contracts/test_place_views.py` (12: templates, the r2 restaurant's sign text and table found, the r2
roadside's bay accepted, the prep room's used table fine, dry sheet, no-plate words, vehicle sheet, key words);
`views_writer` tests from the four lab places as eval fixtures (6); `tests/hiru_ai/test_location_views.py` (no plate,
re-ask, findings stored, the person's answers win); `tests/hiru_ai/test_board_check.py` (the final lab's panels named
Reverse but painted the frontage: the inspector gets the view's words and crop, the repaint names the view); API
(`views-sheet` without a plate, answers, the new entity fields, `_views_context` splitting the vehicle out). Interface
`location-views.test.tsx` (4).

Full backend run: 6351 passed, 75 failed. After this build's fixes, the suites it touches all pass (920: contracts,
board check, location views, API boards and canon, systems contract, board_inspector / views_writer / board_writer
agents, agents contract). The `frame_render` wiring snapshot (`tests/graph.mmd`) was refreshed: it lacked the `views`
node that plan/2026-11-24 added. The rest fail the same way on an untouched HEAD worktree or sit in retired-planner
suites this plan does not touch (Adam, David, Jonathan, Raphael gold/system, parity recordings, script_split, the API
production/handoff/looks/thumbs tests, `raphael_breakdown` eval count). mypy clean on `src`, ruff clean on every
changed file, `hiru-ai validate` 202 parts, catalog regenerated. Interface: lint has 0 errors, `tsc` passes, tests show
577 passed and 1 failed (`raphael-panel.test.tsx`, which already failed before), and every changed file is formatted
(the 66 unformatted files are not this plan's).

## The person's live check (paid, ask first; phase 7)

1. Canon → Colombo roadside, KASUN'S Restaurant, Kasun's small food preparation workspace, Family car → **Remake** the
   views (about $0.08 each and a cent per writer call). Check: the right template, one connected place, the roadside
   bay empty, no invented text, details from the card or scenes, every sheet dry; findings (if any) shown.
2. Love Hour scene 2 → **Update board** (LOW, about $0.07): panels 2 and 3 show view 4 (Reverse), or the inspector
   finds it and repaints once.
