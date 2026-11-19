# plan/2026-11-18b: what is built

Phases 1 to 3 built offline on 2026-11-18, backend only, uncommitted. Paid calls, all with the person's yes: the lab's
Raphael re-plan ($0.1678) and the Scene board at LOW ($0.0892). Phases 4 to 9 are open ([PLAN.md](PLAN.md) section 5).

## Built, file by file

**Ledger (`src/libs/contracts/holding.py`)**
- `HOW_HELD`: words that say how a thing is held ("held", "out", "raised", "extended" ...) are never the thing;
  "toward(s)", "beside", "behind" split a holding like the other prepositions. "smartphone, held out toward Anudi" is
  the smartphone only.
- `Hands.moves`: true when a thing leaves or changes hands during the shot (video).
- `shot_hands(..., after=False)`: a person who lets go during the shot is no longer told "each hand keeps its own,
  neither is put down"; with `after`, the shot opens once its blocks have played and nothing changes hands in it.
- `hands_for` reads `after` from the shot's `card` (jsonb: no schema change). `frame_compose` uses `hands_for`, so the
  first frame gets the same state as the video prompt.

**Raphael write (`src/libs/hiru_ai/steps/raphael/raphael_write/logic.py`)**
- `mark_after(shots, scene)`, called at the end of `rows_for`: the walk-on half of a split moment gets
  `card.after = true`.
- `sound_mode_of`: `silence` with ambience or effects is `ambient` (nobody speaks, the rain stays); `silence` alone is
  still `silent`.

**Serializer, both copies (`src/libs/hiru_ai/steps/serialize/` and `src/services/shot_producer/shot_producer/engine/`)**
- `schemas/clip_schema_veo_3_1.yaml`: `stay_put` (the sentence of `physics` a moving shot drops, word for word) and
  `tripod`.
- `model.py`: `ShotInput.moves`, set with `hands` in `scene_input` and `restage`.
- `logic.py` / `serialize.py`: `_guard` drops `stay_put` when `shot.moves`; `_camera_text` adds `tripod` on a static
  camera, and the grade and lens no longer end in ".."; `_beats_section` drops the beat's camera note on a static
  camera and skips an empty window that carries no line.
- `shots.py`: `_sentence`, `_placed` (each timed beat ONCE, in the window it overlaps most; several in one window in
  order, each action with its own performance); `fit_beats` uses it, untimed beats are mapped as before.
- `card.py`: `_sound_bit` / `sound_text`: no closing stop inside the line, and a part that says "None ..." is left out.

**Camera words (`src/libs/contracts/camera_words.py`)**
- `lighting_words`: when the person has not changed the lighting and the planner wrote its light, the preset gives only
  its time ("Day: <the planner's light>").

**House rule**
- `src/libs/hiru_ai/house_rules/accidents_as_coverage.md`: H-15 v1, `default`, topic `coverage` (the lab's H-90
  text).
- `agents/raphael/raphael_planner/component.yaml` and `raphael_cinematic/component.yaml`: `house_rules` gains
  `coverage`. The breakdown agents (topic `objects`) do not get it.

**Lab**: `lab/coverage/` (`run.py`, `board.py`, `h90_coverage.md`, `runs/`, `README.md`).

## Tests

- New: `tests/raphael/test_accident_coverage.py` (11 tests, the stager's real E01-S03 marks).
- Changed on purpose:
  - `tests/contracts/test_frame_brief.py`: "Lighting: Dawn: ...".
  - `tests/raphael/test_implied_packet.py`: H-15 at the end of both Raphael prompts.
  - `raphael_write/tests/test_step_raphael_write.py`: a no-words carrier may be `ambient`.
  - `tests/services/shot_producer/test_pictures.py`: a long beat is not repeated, so ["first", "", "second"].
- Parity re-recorded:
  - `tests/parity/fixtures/shot_producer/{prompts,model_design}.json`. The beat diff is the fix: "He says softly"
    used to fill both windows of a 4 s shot, and the model's "She keeps stirring" was dropped.
  - `frame_render/*` for the legacy engine only, after restoring them from git (the graph frame_render cases were
    failing before and are left as they were).

**Whole suite.** It already had 50 failures before this work (Adam, api, graph parity for canon_extract,
frame_render and structure_build, raphael api/isolation/removal, `test_prompt_hygiene`). After this work: no new
failure. The files of this plan pass ruff and mypy; the mypy errors left in `shot_producer/engine/feeling.py` and
`intent.py` are older.

## Phases 4 to 8 (built offline 2026-11-18, second session, $0)

**Phase 4, shot order** (`steps/raphael/raphael_write/logic.py`)
- `order(clips, notes)`: a cinematic clip whose blend note says it plays `before c01` is cut just ahead of that clip;
  one whose note only says it `opens moment N` goes ahead of the moment's first clip. Any other clip keeps
  (moment, stage, id).
- `rows_for` and `design_all` pass `stored.blend_notes`, so the shot numbers and the designs agree.
- E01-S03: c08 (3H-1, the establishing wide) is now shot 1, before the insert. It used to be shot 3, between the
  walk-on and the pickup.
- Tests: `raphael_write/tests/test_cut_order.py` (4), on the lab's real plan.

**Phase 5, the two-shot painted walking: found, not a fault.**
- The board writer paints each shot's OPENING picture by design (its system prompt: the panel becomes the shot's first
  frame).
- Raphael's own editor note for 3E-1 says "Start with Anudi still facing right. Turn first, then offer."
- So panel 6 (her mid-step, facing right) is the plan's first frame. The turn is the shot's action, which the video
  model plays. Nothing to change.

**Phase 6, the handbag side: found in the picture model.**
- Raphael's plan, the writer's panels (`writer.json`) and the board prompt all say "left shoulder / left hip".
- The image model cannot tell a faceless mannequin's left from its right.
- Fix: a writer rule, "A BODY SIDE IS ALSO A SCREEN SIDE" (`agents/board_writer/prompts/system.md`). When a thing is
  on one side of a body, the panel also says which side of the PICTURE it is on, worked out from the facing (profile
  facing screen right: left side toward the lens).
- Proving it needs a paid board run: the person's call.

**Phase 7**: covered by plan/2026-11-18c phase 2 (`checks.action_budget`). It is blocking, not report-only.

**Phase 8, Sable and Zora keep the split**
- `contracts/holding.after_ids(scene, shots)` is now the one rule for `card.after`. `raphael_write.mark_after` uses it.
- `core/coverage_rows.remark_after(scene_row, plan, before)` runs in `Saver.save`, so every Zora turn, Zora click and
  Sable Accept goes through it:
  - when an edit changes the shape of the cut (a clip's blocks or stage, the order, a clip added or removed), each
    clip's `after` is set again from the rows as they will be saved;
  - a clip whose mark changes is written with its version bumped (its hands, frame and video prompt change with it);
  - an edit that leaves the shape alone (a size, a sound) changes no mark.
- Tests: `tests/raphael/test_accident_coverage.py` (+2: a moved walk-on loses its mark; a new walk-on gains one; a
  merged-away insert clears it).
