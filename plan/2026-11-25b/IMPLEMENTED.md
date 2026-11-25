# plan/2026-11-25b: what was built (phases 0-5, 2026-11-25)

Built offline in the backend; nothing committed, no schema change. Phase 6 was run on the person's yes (below). The tree still holds plan/2026-11-25's uncommitted build; this was built on top of it (no stash, no reset).

## Phase 0: found

- **The prop card's look field is `card.details`** ("colour, size, states"). Love Hour's: phone "iPhone 17 pro max -
  orange with transparent back cover. back view and front view."; umbrella "A navy folding umbrella with a short curved
  handle. Anudi carries it closed and opens it when the rain begins …"; the flask has a card but no sheet; "bag" is a
  dark-brown leather document bag.
- **Pictures**: `adapters/images.py` sets no cap of its own; OpenAI's image edit takes up to 16. The worst case here is
  13 (2 faces + 6 + 4 props + the panel); the lab sent 10.
- **Fixture**: the tests use `lab/prop_mapping/input/cases.json`'s panel props and colours and the cards above, copied
  by hand (no picture, no database).
- **Found while building**: the board v22 writer already wrote "handbag" and "tea flask". `holding.canon_match` does not
  match a two-word name ("tea flask") to "flask", so `resolve` also tries the last word.

## What was built

| phase | where | what |
|---|---|---|
| 1 | `src/libs/contracts/props.py` (new) | `scene_props` (the roster: plan names, ledger, look/condition carried), `resolve` / `bind` (against the roster, then by exact name against the production's props), `where_words`, `once_line`, `binding_text`, `image_numbers`, `prop_looks`, `canon_props`, `PROPS_SLOT`, `MAX_PANEL_PROPS = 4` |
| 2 | `hiru_ai/steps/frame_compose/logic.py` | `World.carried`, `World.roster`, `World.bound` (one roster for the board and the frame) |
| 2 | `hiru_ai/systems/frame_render/board.py` | `Board.roster`, `Board.other_props`; `Board.props` now reads the roster (its old plan-name rule moved unchanged into `scene_props`) |
| 2 | `contracts/board.py` `writer_findings` | `roster` / `others`: a panel prop that is no prop of the production → "Shot n: the kettle is not one of the scene's props; its first frame paints it from words only." A report, not a `_FAULT_MARKS` fault |
| 2 | `board_writer` | the PROPS rule's sentence and `Prop.name`'s description (the plan's §2.2 words, unchanged); `version` 1 → 2; an eval case and a prompt test |
| 3 | `contracts/frame_brief.py` `plan_references(panel_props=)`, `_panel_props` | with a bound panel: the ledger's props dropped; every bound prop's sheet in panel order after people, place and vehicles, before the same-setup frame, on top of `limit` up to 4; one a person removed is left out; one with no sheet → "No reference sheet for flask: it is painted from words only." |
| 3 | `frame_render/graph.py` | the panel is read BEFORE the references (`_board_panel` now returns `panel: {props, colours, words}`); `_references(..., panel)`; `compose` gets the panel |
| 3 | `frame_compose` `World.planned` / `reference_choices` / step ops `references`, `compose` | take `panel` |
| 4 | `contracts/board.py` `frame_sections` | a panel with `props` leaves `PROPS_SLOT` in place of `PROP_STAND_INS`; `fill_props` (slot → the paragraph, or `PROP_STAND_INS` when nothing is bound); `HELD_HEAD`, `board_hands`, `prop_stand_ins` |
| 4 | `frame_compose` `World.brief` | fills the slot with `binding_text` numbered from the attached labels; drops the ledger's `Hands:` sentence while the board's hands line is there; `prop_looks` to the brief |
| 4 | `frame_brief.reference_job` / `references_block` / `frame_brief(prop_looks=)` | a bound prop's sheet gets the lab's job "<name> exactly as shown (<look>), not its backdrop or light"; every other prop sheet is unchanged |
| 4 | `frame_compose` `World.expected` | the frame check's `hands` are the board's hands line when the frame has one (§7 Q2; not lab-proven) |
| 5 | `docs/scene_board/README.md` | "Props bound to their sheets" |

Scope held: a frame with no panel, or from a board before plan/2026-11-23c (no `props`), gets exactly today's
references and words (tests `test_without_a_panel_the_references_are_todays`, the old-board case in
`test_a_frame_from_the_panel_turns_the_clay_back_into_the_props`, and the unbound-slot case).

## Changes from the lab's words (C1-C5 of the plan, and what building added)

- **C1** `where` is built by code: "the clay phone in Anudi's right hand (the blue mannequin's), at frame right"; "the
  clay handbag Anudi carries, on Anudi's left forearm, at frame right"; "the clay tea flask resting on the rear/right
  end of the stainless-steel side serving ledge, at frame left". The lab's said "the flat clay shape …", "at chest
  height just right of centre", "its canopy above her".
- **C2** "Each prop appears once: the umbrella and the handbag on Anudi's look sheet are these same things, never a
  second umbrella or handbag." The lab ended "… umbrella or bag". Only people whose look sheet is attached and whose
  look's accessories name a bound prop are named; otherwise only "Each prop appears once."
- **C3** the look is the first sentence of `details`, a leading "A/An/The" lower-cased and any ";" made "," (the flask's
  ";" read as the next prop). So: "iPhone 17 pro max - orange with transparent back cover" (lab: "an orange iPhone
  with a transparent back cover"); "a navy folding umbrella with a short curved handle" (lab: "… black curved
  handle"); the flask "… narrow pouring spout, dull silver body with shallow dents".
- **C4** a prop with no sheet: "it has no picture: paint <its look>", or "paint the <name>" with no card.
- **C5** the state: `holding.state_in` over the ledger's thing words, the shot's words, then the panel's words; "open",
  not the lab's "open over her head".
- **C6 (added)** the name after "is" is the canon name: "is the flask" (lab: "is the tea flask"); the writer's own word
  stays in `where` ("the clay tea flask").
- **C7 (added)** a stand-in the roster does not know is matched by its exact name or last word against the
  production's other props (`canon_props`), never by a longer name ending in it: the flask only the panel named. The
  roster is still tried first, so "bag" is the handbag she carries.
- **C8 (added)** a frame with the panel as its draft (no current shot prompt) says "The approved draft shows the props
  …" and "Keep the draft's layout …".
- **C9 (said)** the plan put words-only things on the roster; they are made at `bind` instead (a panel name nothing
  resolves), the same effect.

## Checks

- `ruff check src tests scripts`: 5 errors, all E501 in files this build did not touch and identical to HEAD
  (`scripts/canon_refine_live.py`, `contracts/breakdown/checks.py`, `steps/raphael/raphael_write/logic.py`,
  `tests/api/test_production.py`, `tests/contracts/test_canon.py`).
- `mypy`: no issues (1170 files).
- `scripts/lint_imports.py`: 49 kept, 3 broken, none in this build's files (`hiru_ai.core.camera` → `hiru_ai.rag`; the
  api's `file_cache` / `media_thumbs` → `hiru_ai.core`; the david agents → `david.wire_schema`).
- `hiru_ai validate`: 203 parts, 0 errors. `hiru_ai catalog --check`: current.
- `pytest -q` (27 min): 6475 passed, 28 skipped, 69 failed. None is this build's: the 69 were run again in a clean
  worktree at HEAD (8f03132), where 44 fail as they are, and the other 25 (adam/raphael system runs, api file links,
  the reader switch) fail too once the developer's local `.env` is applied (it sets the file URL port and the engine).
  No failing traceback reaches a file this build changed. The board, frame, compose and writer tests all pass.
- New tests: `tests/contracts/test_props.py` (7), `tests/hiru_ai/test_prop_roster_frame.py` (8), two in
  `tests/contracts/test_board_state.py`, one end-to-end render in `tests/hiru_ai/test_scene_board.py`, one in
  `board_writer/tests`.
- Interface: none changed. `map-render.ts` and `map-scene.ts` pass reference labels and `frame_missing` through as
  text; nothing parses a label.

## Open (the person's)

- Q1-Q5 of the plan stand as recommended in it; nothing here decided them beyond what is built (Q2 built as
  recommended: the check's hands from the panel).
- Phase 6, paid (~$0.70): first frames of scene 4 shots 11 and 1 at medium from board v22, and one shot the lab did not
  touch, beside `lab/prop_mapping/runs/shot11/compare_shot11.jpg` and `runs/shot1/compare_shot1.jpg`. Frames painted
  before are not marked out of date. A board written before this keeps its writer words; a Rewrite and repaint makes
  the writer name props by the roster (v22 already does).

## Phase 6: the live check (2026-11-25, the person's yes for shots 11 and 1)

Run by `lab/prop_mapping/phase6.py`: the product's own code end to end on the hosted dev database, READ ONLY (the
real `Scenes.world`, `_panel_breaks_a_fact`, `_board_panel`, `_references`, the views swap, the `compose` op, the safe
depiction stop, the product painter at medium). Left out: the frame row's claim and finish, the upload, the
`token_usage` row and the frame check; nothing was written to the database or a bucket. Board v22 (parts
`9db1ba1d` / `31b47723`). Spent **$0.438** of a $0.70 cap (`runs/phase6/ledger.csv`).

- **Pictures**: both shots attached exactly the lab A list: 2 faces, 2 looks, view 1, the vehicle plate, the phone,
  umbrella and handbag sheets, the panel last (10).
- **Found by the free dry run and fixed before painting**: (1) shot 1 called the phone "open" (the writer's "palm open
  beneath the clay phone" read by `state_in`); (2) the umbrella got no state in either shot (Anudi's scene condition was
  not read). `bind` now strips an open palm / hand before reading states, and `World.bound` reads each person's carried
  words (look + condition) first, at the lowest priority. Test added (`test_props.py`).
- **Shot 11** (`runs/phase6/shot11/compare_shot11.jpg`): one navy umbrella open over her, its black curved handle in her
  left hand; the orange phone (the sheet's camera block) in her right hand at chest height; the tan handbag on the
  umbrella forearm; the steel flask on the ledge; Kasun's hands empty. The baseline's white umbrella and second folded
  one are gone. As good as lab A.
- **Shot 1** (`runs/phase6/shot1/compare_shot1.jpg`): the orange phone held out in Kasun's right hand over Anudi's
  open palm (the board's handoff); one navy umbrella in her other hand; the tan handbag on her forearm; the steel
  flask with its brown handle on the ledge. The baseline's dark phone is gone. As good as lab A.
- Close-ups: `runs/phase6/zoom_phase6.jpg`. One picture per shot; the third shot of the plan was not asked for.
