# What people carry continues; the first frame follows the board (plan/2026-11-23d)

Revision 2 (2026-11-23: the person answered Q1-Q3 as D1-D3, §5). Nothing in this plan is built. It follows plan/2026-11-23c (the Scene board's opening state,
clay props, board check), which is built offline and uncommitted, and its follow-up of the same day (below). Read this
file whole, then `plan/2026-11-23c/PLAN.md` §3.6 and IMPLEMENTED.md, `docs/scene_board/README.md`,
`src/libs/contracts/holding.py`, `src/libs/contracts/stagemap.py`, `src/libs/contracts/breakdown/fill.py`,
`src/libs/hiru_ai/systems/raphael/raphael_shot_planner/graph.py` (`ledger_of`) and
`src/libs/hiru_ai/systems/frame_render/graph.py` (`render_frame`, `_board_panel`).

## 0. Rules for the chat that builds this

- **Prove before building.** Phase 0 of each part is a free read or a small lab on the person's scene (production
  b89f79a3, episode ffc308a3, scenes 2-4) with a hard budget. Ask before every paid call (image or model), each time.
- **No enable switches.** **Never stash or reset** the person's tree; compare in a separate worktree.
- **Never edit an applied migration.** Neither part expects a schema change (staging, intent and cells are JSON).
- Two repos: the backend (this one) and `..\hiru-ai-studio-interface` (its `CLAUDE.md` binds).

## 1. What is wrong (found 2026-11-23, scene 4 "A conversation that changes everything")

The story: scene 2, Anudi "gets out, carrying her handbag and umbrella… Rain begins to fall. She opens her umbrella";
scene 3, she "walks past Kasun's three-wheeler while holding her umbrella" and tries to slip her phone into "the side
pocket of her handbag". Scene 4's script never names them, but she is still in the rain, straight after scene 3.

| Part | Carries the umbrella and the handbag into scene 4? |
|---|---|
| Her look ("office-day separates") | yes: accessories "a tan structured handbag and a navy folding umbrella" |
| Scene 4's `scene_looks.condition` (`breakdown_looks`) | yes: "Holding the open umbrella" |
| Canon props | fixed on 2026-11-23: "and" renamed "handbag" (P04), "umbrella" added (P16); neither has a sheet yet |
| Scene 4's staging map (`by: "model"`, the breakdown's) | no: only the phone; `basis: ""` |
| Raphael's plan (IR, every shot) | no: only the phone in her right hand |
| Each shot's `intent.opens` | missing on all 14 shots (the empty basis places no mark) |
| The Scene board (plan/2026-11-23c follow-up) | yes: the writer now keeps what the condition carries, in the free hand |
| The first frame of shot 1 | the bag, from the look sheet; no umbrella; not the board's blocking |

Two separate faults:

- **A. Nothing carries what a person holds from one scene to the next.** Raphael's stager call (`ledger_of`) reads
  only this scene: its items, the speaker names, the reading and the place. The breakdown's map (`fill.staging`)
  likewise. So the ledger, the IR, `opens`, the hands sentence (`holding.hands_for`) and the video prompt all lose
  the umbrella. The scene condition is the only part that kept it, and it is free text.
- **B. The first frame does not follow the board.** `render_frame` attaches the approved panel only when the shot has
  NO current shot prompt (`from_prompt`, the audit of 2026-11-21: the panel was painted before the Camera agent and
  would override its angle). Every Raphael shot now has a shot prompt, so no Raphael frame is painted from its panel:
  the board and the frames are two separate tracks. Shot 1's frame (`board_id = None`) shows a close two-shot of
  both looking at the phone, the handbag in her hand from the look sheet, no umbrella.

Also found: **C. `basis: ""`.** `contracts/breakdown/fill.py` `staging(..., basis="")` stores the breakdown's map with
an empty basis; `SceneStaging.placed` resolves marks through the basis, so the ledger places nothing and `opens` is
never written (plan/2026-11-23c F3).

## 2. The design

### 2.1 Part 3: what a person carries continues (fault A, C)

1. **A carried-state ledger across scenes** (`contracts/holding.py` or a new `contracts/carry.py`, pure): for each
   person, what they hold or carry as a scene ENDS (the last marks' `holding`, `left_hand`, `right_hand`, `wearing`,
   plus the props set down and not picked up), and, for the next scene in story order of the same episode, what they
   ENTER with (D1). A scene is one place over a short time, so nothing jumps inside it; between two scenes the story's
   own data decides whether the moment continues: the person wears the same look in both (`scene_looks`, written by
   `breakdown_looks` from story time) and the breakdown's continuity puts them next to each other in story order. A
   person in a new look, or a scene that is not next in story order, enters with what the new scene and its look
   say, nothing carried. Scene 3 → scene 4 (same look, next in order, rain in both) carries the open umbrella and
   the handbag.
2. **The stager reads it.** `ledger_of` and the breakdown's stager step pass `entering: {person: [things, hand]}`
   to the stager (a new input field, the agent's prompt gains one rule: a person enters holding what they held at
   the end of the scene before, unless the script has them put it down, and the first mark says so). The scene
   condition is read too, as a second witness ("Holding the open umbrella").
3. **The planner reads it.** Raphael's listing already shows `At the start:` from the map, so a map that starts with
   the umbrella reaches the IR and `opens` with no prompt change. Phase 0 checks this on scene 4.
4. **Fix the empty basis** (fault C): the breakdown writes the basis of the items it placed (`rd.basis`), and a stored
   map with `basis: ""` is read by block number (as `contracts.board.marks_at` does), so `opens` is written for maps
   already stored. A re-plan of the scene is the person's (it costs a Raphael run).
5. **Props:** a carried thing that matches no canon prop is reported once on the scene ("Anudi carries an umbrella;
   the canon has no umbrella"), the way the 2026-11-23 fix had to be done by hand.

### 2.2 Part 4: the first frame follows the board (fault B)

1. **The board paints the Camera agent's camera.** `shot_plan` reads `design.camera` (the Camera agent's design, the
   one the shot prompt is written from) when it is current, and the planner's `ir.cinematography` otherwise; the pin
   (`plan_pin`, v3) includes it, so a camera change marks the panel out of date (the board's Update repaints it
   alone).
2. **The frame gets the panel as the blocking draft, with a shot prompt too.** When the shot has a current shot
   prompt AND a current, approved panel whose pin matches, `render_frame` attaches the panel last, as today's
   `DRAFT_LABEL`, but its job is narrower: "where each person stands and faces, what each hand holds, the props and
   the place; the camera, lens and framing come from this shot's words". `frame_sections` gains that variant; the
   shot prompt's words stay the picture's words. A stale or unapproved panel is not attached (as now, the frame is
   painted from its words).
2a. **When the shot prompt and the panel disagree, the cause decides (D2).** Both are written from the same facts
   after this plan (the Camera agent's camera, the ledger's hands, the panel's hands into the shot prompter), so a
   disagreement has a cause, and code finds it before the frame is painted (a free check, words only):

   | Why they disagree | Which wins | Said where |
   |---|---|---|
   | the camera changed after the panel was painted (its pin moved) | the shot prompt; the panel is stale and not attached | "Panel out of date" on the board, as today |
   | the shot prompt was written before the board was approved, or before its panel changed | the panel (a person approved it); the shot prompt is marked out of date ("Recommend settings" writes it again from the panel) | the shot's prompt chip |
   | the panel breaks a fact (a hand holds what the ledger gives someone else, a person only heard is on it) | the fact; the panel is reported in its conflicts and not attached | the board's conflicts |
   | the shot prompt breaks a fact | the fact; the shot prompt's own checks already refuse it | the shot prompt's checks |
   | none of these: both fit the facts and still differ (two readings of the same plan) | the panel, and the shot names the difference so a person can look | an advisory chip on the frame |
3. **The hands agree.** The frame's hands sentence takes the panel's structured hands (`PanelPerson.left_hand`,
   `right_hand`, `props`) when the ledger has none, so a carried umbrella reaches the frame even before part 3.
4. **The look sheet stops putting a carried thing in a hand.** "Dress them exactly as their look sheet shows, the
   same clothes and accessories" stays for clothes; a carried accessory (a bag, an umbrella) is placed by the hands
   sentence, never by the look sheet.
5. **The shot prompter reads the panel.** `shot_prompter` gets the panel's hands, props and positions as facts, so
   the shot prompt and the board agree (and the video prompt with them).

## 3. Phase 0 (free reads, then a small lab; the person's)

- 3-0 (free): read scenes 2-4's staging, the breakdown's continuity order and scene 3's last marks; list what the
  ledger would give scene 4. Confirm `rd.basis` of scene 4's items and that reading by block number gives `opens`.
- 4-0 (free): list which shots of the production have a current shot prompt and a current approved panel; read the
  Camera agent's design against the panel's camera for scene 4.
- Lab (paid, ask first, cap $1.50): repaint scene 4's board with the Camera agent's camera, then paint the first frames
  of shots 1, 7 and 11 with the panel attached as the blocking draft (MEDIUM). Measured by the person: positions and
  hands match the panel, the umbrella in her left hand and the bag on her shoulder, the camera matches the shot
  prompt, no clay left.

## 4. Phases after phase 0 (offline, $0)

1. Part 3: the carry ledger (pure) + tests on scenes 2-4's rows; the stager input and its one rule; the breakdown's
   basis and the by-block reading of an empty basis.
2. Part 4: `shot_plan` reads `design.camera`, pin v3; `render_frame` attaches the panel with a shot prompt;
   `frame_sections` blocking variant; hands from the panel; the look-sheet line for carried accessories;
   `shot_prompter` reads the panel.
3. Docs (`docs/scene_board/README.md`, the catalog), IMPLEMENTED.md.
4. Live check (paid, the person's): re-plan scene 4 (Raphael), Update board, paint its first frames.

## 5. What the person decided (2026-11-23)

- D1 A scene is one place over a short time: nothing jumps inside a scene. Whether a thing carries from one scene to
  the next is read from the story's data (same look, next in story order), §2.1 item 1; never a question.
- D2 Which wins when the shot prompt and the panel disagree depends on why they disagree: §2.2 item 2a.
- D3 Yes: paint the umbrella and handbag reference sheets (the canon page's sheet button, the person's session).
