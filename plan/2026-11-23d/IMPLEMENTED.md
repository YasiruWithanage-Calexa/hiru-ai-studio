# plan/2026-11-23d: what is built

Part 4 (the first frame follows the board) is built offline on 2026-11-23, uncommitted. **Part 3 (what a person
carries continues across scenes) is not built.** No paid call was made. The person asked to build part 4 directly, so
phase 4-0's free read was the one done in the conversation of 2026-11-23 (scene 4, shots 1, 7, 11: no shot was painted
from its panel; the shot prompt held the umbrella folded with the bag in her hand, the panel had it open over her and
the bag on her shoulder; the shot prompt's camera came from the Camera agent, the panel's from the planner) and the
lab is the live check below.

## Built (§2.2)

| Item | Where |
|---|---|
| 1. the board paints the Camera agent's camera; pins v3 | `contracts/board.py` `camera_of`, `shot_plan["camera_design"]`, `PIN_VERSION = "v3"`, `pin_matches` (v3, v2, unprefixed) |
| 2. the frame gets the panel for the blocking with a shot prompt | `contracts/producer.py` `BLOCKING_LABEL`; `contracts/frame_brief.py` its paragraph in `references_block`; `contracts/board.py` `frame_sections(blocking=True)`, `blocking_text`, `held_text`; `systems/frame_render/graph.py` `render_frame`, `_board_panel(blocking=)` |
| 2a. D2, by cause | camera changed → the panel's v3 pin moves, `approved_panel` is None, nothing attached; shot prompt older than the approved panel → `board_reason` / `BOARD_CHANGED` in `frame_compose` `World.shot_prompt_reasons` and the API's `scene_states` (the same function), so "Draw first frame" rewrites it from the panel; the panel breaks a fact → `panel_faults` (the board's code-found conflicts) and it is not attached; the shot prompt breaks a fact → its own checks, plus the new one: a thing the board puts in a hand must be named in the frame; both fit and differ → the panel is attached and the vision check's hands chip shows a difference (no new chip) |
| 3. the hands agree | the approved hands go into the frame's board paragraphs (`held_text`) and into the shot prompter's facts (`panel_facts`) |
| 4. the look sheet | `frame_brief.CARRIED`: a carried thing on the look sheet is held or worn as the shot's words and hands say |
| 5. the shot prompter reads the panel | `core/shot_prompts.py` `board_facts`; `systems/shot_prompts/graph.py` (facts + `record["board"]` stamp); `steps/shot_prompt/logic.py` (`shot_brief` board lines, the held-thing check); `agents/shot_prompter/prompts/system.md` (one rule); `World.boards` fed by frame_render's and shot_prompts' worlds |
| docs | `docs/scene_board/README.md` "The first frame follows the board" |

## Tests

New: `tests/contracts/test_board_follows.py` (6), in `tests/contracts/test_board_state.py` the v2/v3 pin test, in
`steps/shot_prompt/tests` the board brief and check test. Changed: `tests/hiru_ai/test_scene_board.py` (a shot with a
current shot prompt now gets the panel as `BLOCKING_LABEL`, the camera from the prompt). mypy clean, `hiru_ai validate`
0 errors, catalog current; ruff errors only in other plans' files. Three `tests/api/test_production.py` tests fail on
this machine because `.env` sets the API on port 8001 (they expect 8000); not this plan's.

## The person's

- **Live check (paid, ask first):** approve the board of scene 4 (each part), then "Draw first frame" for shots 1, 7
  and 11. Their shot prompts are out of date ("The approved scene board changed…") and are written again from the
  panels first (one shot prompter call each), then painted with the panel attached. Look for: the umbrella open in
  her left hand, the bag on her shoulder, positions as on the board, the camera as the shot prompt says, no clay or
  mannequin left.
- Part 3 (carry across scenes, the breakdown map's empty basis) is still to build.

## Follow-up of 2026-11-23 (the first live try of shot 1)

- The person's three frames of scene 4 shot 1 were painted with NO panel: board version 12 was never approved, so the
  old shot prompt (2026-11-22: "her left hand holds her tan structured handbag and navy folding umbrella low at her
  side") painted them.
- **D4 (the person): first frame generation is disabled while the scene board is not approved.** The API's
  `request_frames` and `request_scene_frames` refuse (409, the panel's reason) unless the shot's panel is ready
  (painted, current, its part approved) or the shot is a black plate; `frame_board` reports the panel's real state and
  reason, so the interface's existing "Paint first frame" button is disabled with that reason as its title. This
  reverses "the board is no gate" of the audit of 2026-11-21 (`PROMPT_STATE` is kept only for old views).
- A free preview found the board's World leaking into the frame ("Render them without human surface details or
  clothing", "every portable object is its actual size and outline, without marking"): `_BOARD_WORDS` now drops
  sentences about clay, stand-ins, outlines, faceless, surface details and "without human/clothing/markings";
  `PROP_STAND_INS` names the board panel in the blocking variant.
- `tests/services/frame_render/conftest.py` `FakeStore.boards()` (the frame world reads it; 12 frame tests and 5
  parity cases had broken on its absence). `tests/api/test_boards.py`: the gate assertions turned round.
- Remaining full-suite failures are not this plan's: port 8001 in `.env` (API tests expecting 8000), Adam, Jonathan,
  David, script_split, parity (canon_extract, structure_build), `raphael_breakdown` eval cases.
