# Props: one roster per shot, every prop on the panel bound to its own sheet (plan/2026-11-25b)

Revision 1 (2026-11-25). Plan only: nothing is built. Proven in `lab/prop_mapping` (approach **A**, "tier 1", $1.386 of
$1.50 for the whole lab, `FINDINGS.md`). The board paints props as white clay stand-ins (plan/2026-11-23c). A first
frame painted from the panel does not turn them back into the RIGHT real props. Approach A changed only the prop words
and the prop sheets of the product's own saved prompts, and fixed every fault in shots 11 and 1 of Love Hour scene 4.
The other three approaches are not built: numbered marks (B) gained nothing, the masked props pass (C) repainted the
person under the umbrella, and coloured stand-ins (D) were equal to A with one more step.

Read this file whole, then:
- `lab/prop_mapping/FINDINGS.md` and `lab/prop_mapping/run.py` (`ROSTER`, `roster_words`, `prompt_for`: the words to
  port);
- `src/libs/contracts/board.py` (`PanelProp`, `prop_line`, `PROP_STAND_INS`, `unprop`, `frame_sections`, `held_text`,
  `writer_findings`);
- `src/libs/hiru_ai/systems/frame_render/board.py` (`Board.props`, `carried`, `writer_pictures`, `bundle`);
- `src/libs/hiru_ai/systems/frame_render/graph.py` (`_references`, `_board_panel`, `render_frame`);
- `src/libs/hiru_ai/steps/frame_compose/logic.py` (`World.planned`, `brief`, `hands`, `expected`);
- `src/libs/contracts/frame_brief.py` (`plan_references`, `reference_job`, `references_block`);
- `src/libs/contracts/holding.py` (`references_for`, `canon_match`, `state_in`);
- `src/libs/contracts/vehicles.py`, the pattern this follows.

## 0. Rules for the chat that builds this

- **Port the lab exactly.** The binding paragraph, the prop jobs and "each prop once" are the lab's words
  (`run.py` `roster_words`, `prompt_for`). §4 lists the only changes, which are the generalisations from one scene to
  any scene. List any other change of words before making it. Do not edit or re-run the lab.
- **Ask before every paid call**, each time. Tests run with `OPENAI__API_KEY=` blank and fakes only. Only phase 6 is
  paid, and it is the person's.
- **No enable switches.** **Never stash or reset** the person's tree: it holds plan/2026-11-25's uncommitted build.
  Work on top of it. **No schema change** is expected: the panel's `props` are already stored in the board's `writer`
  JSON.
- **No new agent.** Code builds the roster and the words. The board writer only names its props from the roster.
- Two repos: the backend (this one) and `..\hiru-ai-studio-interface`, whose `CLAUDE.md` binds. No interface change is
  expected (§6).
- **Scope.** Only a frame painted from a board panel that has `props` changes. A frame without a panel, or from a board
  painted before plan/2026-11-23c (no `props`), is painted exactly as today.

## 1. What is wrong today (found in code; confirmed by the lab's baseline)

| # | fault | where | seen in the baseline (scene 4, board v22) |
|---|---|---|---|
| F1 | The board and the frame pick props differently. The board matches names in the plan text; the frame takes only what the ledger says someone holds. | `Board.props` vs `holding.references_for` | Only the phone sheet was attached. The umbrella and handbag sheets exist but were not sent. |
| F2 | Things carried from a look or the scene condition are clay on the board but get no sheet in the frame. | `Board.carried` is used only by `writer_findings` | Anudi's umbrella and handbag (her look) |
| F3 | Every stand-in is the same white, and `PROP_STAND_INS` says "from its reference sheet" without naming the image, the holder or the hand. | `PROP_STAND_INS` | Shot 11: a WHITE canopy overhead (the clay's colour). The phone is dark although its sheet is orange. |
| F4 | One thing is shown twice: the stand-in, and the same thing on the look sheet. | no "each prop once" | Shot 11: a second, folded navy umbrella in her other hand. |
| F5 | Names are free text, matched again at every step against the WHOLE canon. | `PanelProp.name`, `canon_match` | The writer's "clay bag" matches the canon "bag", a dark document case, not the handbag. |
| F6 | Two hands sentences that contradict each other. | `frame_compose.brief` `hands=` (ledger) + `held_text` (board) | Shot 1: "Kasun is not holding the phone. Anudi holds the phone" beside the board's "Kasun grips the phone". |
| F7 | `MAX_REFERENCES = 6` drops props first. | `plan_references` | 2 faces are on top of the 6. The 6 are 2 looks, the view and the vehicle, which leaves room for only 2 props. |

## 2. The design

### 2.1 One roster per scene, one binding per panel: `contracts/props.py` (new, pure)

Like `contracts.vehicles`: rows in, words out, no I/O.

- `RosterProp`:
  - `key`: the canon id, or `words:<name>` for a thing with no card;
  - `name`: the ONE name used everywhere ("the phone", "the umbrella", "the tea flask");
  - `look`: what it looks like;
  - `sheet`: its sheet path, or "";
  - `source`: `prop` | `look` | `words`.
- `scene_props(scene, shots, canon, people) -> list[RosterProp]`: the props of a scene, in one place. It replaces
  `Board.props` and the props half of `references_for`. It is the union of:
  1. the canon props the shots' plans name (today's `Board.props` rule, moved here unchanged);
  2. the canon props the ledger knows (`Ledger.things` through `canon_match`);
  3. the canon props named in a person's look `accessories` or scene condition (F2: Anudi's umbrella and handbag).

  Within (3), a longer name that the words hold as a whole word beats a shorter one: "tan handbag" gives `handbag`,
  never `bag`.

  A thing a look or a plan carries that has no prop card is a `words` entry: its name and the words that name it.
- `bind(panel, roster, colours) -> list[BoundProp]`: each of the panel's `props`, resolved against the ROSTER only,
  never the whole canon (F5). Resolution is the exact name first, then `canon_match` within the roster. With the
  document case out of the roster, "bag" resolves to the handbag. A panel prop that resolves to nothing becomes a
  `words` entry under its own name, so it is never dropped.

  Each `BoundProp` carries:
  - the roster entry;
  - `holder`, `hand` and `frame_side`, taken from `PanelProp`;
  - `rests_on`;
  - `state`, from `holding.state_in(key, [panel.picture, the holder's hand words])`; the umbrella comes out "open".
- `where_words(bound, colours)`: where the stand-in is, in the image model's words. Code builds it from the panel's
  fields (the lab wrote it by hand, §4 C1):
  - held: "the clay umbrella in Anudi's left hand (the blue mannequin's), at frame right";
  - worn: "the clay handbag Anudi carries, at frame right";
  - resting: "the clay tea flask resting on the serving ledge, at frame left".
- `binding_text(bound, image_of, looks_holding)`: the lab's `roster_words` (A, no marks, no colours).
- `prop_jobs(bound, image_of)`: the lab's per-sheet jobs.
- `MAX_PANEL_PROPS = 4`: the most prop sheets one frame takes on top of `MAX_REFERENCES`. In the lab, 3 sheets made 10
  pictures in all.

### 2.2 The board (the roster in, the words out unchanged)

- `Board.props` becomes `props.scene_props(...)`, so `prop_names`, `writer_pictures` and `bundle` read the roster. The
  writer now sees the umbrella and handbag sheets and names them. `writer_pictures` stays capped at
  `MAX_WRITER_PICTURES`; people and the place stay first.
- The board IMAGE is unchanged: props stay white clay (plan/2026-11-23c D2). `prop_line(props)` names the roster's
  names.
- `board_writer/schema.py` `Prop.name`: "The prop's name, exactly as the scene's `props` name it." The prompt's PROPS
  rule gains one sentence: "Name each prop in `props` exactly as the scene's `props` name it; a thing a person carries
  that is not there keeps the name its look gives it." The chat lists these words before writing them. The agent's
  `version` goes up by one.
- `writer_findings`: a panel prop that resolves to nothing in the roster is a report line ("Shot 4: the 'bag' is not one
  of the scene's props; it is painted from words only"). It is **not** a fault mark (`_FAULT_MARKS`), so the panel is
  still attached.

### 2.3 The first frame (the lab's A)

Only when the frame is painted from a panel that has `props` (§0 Scope):

1. **The pictures** (F1, F2, F7).
   - `plan_references` gains `panel_props: Sequence[BoundProp] | None`. When it is given, the frame's props are the
     bound props that have a sheet, in panel order, each labelled "the reference sheet for <name>". They come after
     the people, the place and the vehicles, and before the same-setup frame and the panel (the panel stays LAST).
   - They sit on top of `limit`, as faces do, up to `MAX_PANEL_PROPS`.
   - The ledger's props (`references_for` step 3 and the props in `base`) are not added for such a frame, so the
     "bag" case can no longer slip in.
   - `missing_references` says "No reference sheet for the tea flask: it is painted from words only."
   - Wiring: `graph.render_frame` reads the frame's panel BEFORE `_references`, and passes it to the `references`
     compose (`World.planned(shot, panel=...)`), from the frame's own `board_id`, as `_board_panel` does now.
     `_panel_breaks_a_fact` still decides first; a panel left off means today's references.
2. **The words** (F3, F4).
   - `frame_sections` gets the bound props. In place of `PROP_STAND_INS` it emits a `props` part, the bound props as
     data. `frame_brief` turns that into the lab's binding paragraph at compose time, numbering the images from the
     same `labels` that are attached (as `references_block` does), so a number can never point at the wrong picture.
   - `reference_job` for "the reference sheet for <name>" becomes the lab's job: "<name> exactly as shown (<look>),
     not its backdrop or light".
   - The blocking paragraph (`references_block`, `BLOCKING_LABEL`) is unchanged; approach A did not change it.
3. **One hands sentence** (F6). When the attached panel has hands (`held_text` is not empty):
   - `frame_compose.brief` leaves out the ledger's `hands(shot).sentence`, so the board's hands are the only hands in
     the prompt (the lab removed `OLD_LEDGER`);
   - `opens_line` stays;
   - `expected()["hands"]` for `frame_inspector` comes from the panel's hands too, so the check does not fault a frame
     for following the board. This is not lab-proven; it is a free code change for consistency (§7 Q2).

## 3. What the lab's words were (the source to port)

From `lab/prop_mapping/run.py`, approach A:

- **Head:** "The approved scene board panel shows the props as plain white clay stand-ins. White is never a prop's
  colour: each stand-in marks only where a real prop is, its size, its angle and the hand that holds it."
- **Roster:** "These are the props, each exactly once: <where> is <name>: paint it exactly as image <n> shows it
  (<look>)<, state>; … ; <where> is <name>: it has no picture: paint <look><, state>."
- **Once:** "Each prop appears once: the umbrella and the handbag on Anudi's look sheet are these same things, never a
  second umbrella or bag."
- **Keep:** "Keep the panel's layout, proportions and perspective for every prop; add no other prop. No white clay
  shape, blank object or unfinished prop remains in the frame."
- **List:** "image <n> is the reference sheet for <name>" (no "(held by …)" note).
- **Jobs:** "image <n>: <name> exactly as shown (<look>), not its backdrop or light."
- **Removed:** the ledger's "Hands: …" sentence.

## 4. Changes from the lab (the generalisations; the build lists them again in IMPLEMENTED.md)

- **C1 `where` is built by code** from `holder`, `hand`, `frame_side` and `rests_on` (§2.1). The lab's were
  hand-written and a little richer ("at chest height just right of centre", "its canopy above her"). The panel's
  `picture` and `held_text` still carry those details in the same prompt. Phase 6 compares the two on the lab's own
  shots.
- **C2 "Each prop appears once"** is built from the people whose look sheet is attached and whose look holds a bound
  prop: "the <a> and the <b> on <person>'s look sheet are these same things, never a second <a> or <b>." When nobody's
  look holds one, the sentence is only "Each prop appears once."
- **C3 `look`** is the prop card's look words, the text its sheet was painted from. Phase 0 names the field. The lab's
  four look phrases were copied from those cards by hand.
- **C4 a `words` entry's look** is its name and the plan's words for it. The lab's flask had a hand-written description
  taken from the vehicle plate.
- **C5 the state** comes from `state_in` on the panel's words. The lab wrote "open over her head" by hand; code gives
  "open".

## 5. Phases

| phase | what | paid |
|---|---|---|
| 0 | Read the lab and the files in the header. Name the prop card's look field (C3). Confirm the image adapter and gpt-image-2 take the worst case of 13 input pictures (2 faces + 6 + 4 props + the panel; the lab sent 10). If they do not, `MAX_PANEL_PROPS` comes down to fit. Write the scene 4 fixture for the tests from `lab/prop_mapping/input/cases.json`, which holds no picture bytes. | no |
| 1 | `contracts/props.py`: `scene_props`, `bind`, `where_words`, `binding_text`, `prop_jobs`. Tests: scene 4's roster holds the umbrella and the handbag and not the document case; "bag" binds to the handbag; the flask is a `words` entry; the umbrella's state is "open"; `binding_text` for shot 11 reproduces the lab's sentences apart from C1-C5. | no |
| 2 | The board: `Board.props` → the roster; the writer schema and prompt line; the `writer_findings` report line. Writer evals and tests. | no |
| 3 | The frame's pictures: `plan_references(panel_props=)`, the wiring in `graph` and `World.planned`, `MAX_PANEL_PROPS`, `missing_references`. Tests: with a panel, the sheets are in panel order after the vehicle and before the panel; without a panel, the references are byte-for-byte today's; an old board with no `props` behaves as today. | no |
| 4 | The frame's words: the binding paragraph in `frame_brief` from the attached labels, `reference_job`, the ledger hands left out, `expected` hands from the panel. Tests: every image number in the binding paragraph names a prop sheet that is attached; `PROP_STAND_INS` is never in a prompt that has the binding paragraph; one "Hands" sentence only. | no |
| 5 | Checks: `ruff check src tests scripts`, `mypy`, `scripts/lint_imports.py`, `hiru_ai validate`, `hiru_ai catalog --check`, `pytest -q`; in the interface `npx next typegen && npm run check && npm run format:check` only if a file there changed. `IMPLEMENTED.md`. | no |
| 6 | Live check (the person's yes, about $0.70): paint first frames of scene 4 shots 11 and 1 at medium from board v22, and one shot the lab did not touch (shot 4 or 8: Anudi with all three things). Put them beside the lab's A frames (`runs/shot11/compare_shot11.jpg`, `runs/shot1/compare_shot1.jpg`). Pass: one navy umbrella, an orange phone, a tan handbag, no white prop, no second umbrella or bag, the handoff in shot 1 as on the board. | yes, the person's |

Phases 1 to 4 are built in order. Phase 2 does not wait for 3 and 4, but phase 6 needs all of them. Frames already
painted are not marked out of date; the person repaints the ones they want.

## 6. The interface

None expected. The shot screen already lists a frame's references and its "No reference sheet for …" lines from the
API. More sheets now appear there, in the same label shape ("the reference sheet for <name>"). Phase 5 greps
`features/handoff/lib/map-render.ts` and `features/scenes/lib/map-scene.ts` to confirm nothing reads the label text in
a way that breaks. No costs are shown (`CLAUDE.md`).

## 7. Questions for the person

- **Q1 C1:** accept code-built `where` words (shorter than the lab's), with phase 6 as the check? Recommended: yes. If
  phase 6 shows a prop in the wrong hand, the next step is to have the board writer write a `where` sentence per prop
  in its own words.
- **Q2 the frame check's hands:** take them from the panel when a panel is attached (§2.3.3)? Recommended: yes.
  Otherwise the check would fault the frames the lab judged right. If the ledger and the board disagree, the board wins
  for the picture. A report line on the shot screen ("the board and the ledger disagree on who holds the phone") would
  be its own small plan.
- **Q3 `MAX_PANEL_PROPS = 4`:** more than four props on one panel are painted from words. Recommended: 4, because
  quality falls as pictures are added (MultiBanana) and the lab proved 10 pictures, not more.
- **Q4 not built:** B (numbered marks), C (props pass) and D (coloured stand-ins) stay in the lab. The Gemini box finder
  (4/4, about $0.003 a picture) is kept in mind for a later frame check that counts the right prop in the right hand,
  not for painting.
- **Q5 a prop with two states** (a folded and an open umbrella): one sheet per state, as practitioners do, is not in
  this plan. Today the state is a word only ("open"), and the lab showed a word is enough for one umbrella.
