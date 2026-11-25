# The Scene board

One storyboard image per scene, painted **before any first frame**, so the frames of a scene agree on the place, the
light, the props, the camera positions and where everyone stands
([plan/2026-11-14/PLAN.md](../../plan/2026-11-14/PLAN.md); what is built and what waits for a person:
[IMPLEMENTED.md](../../plan/2026-11-14/IMPLEMENTED.md); the lab that proved it: `lab/storyboard/`, plan/2026-11-13e).

## How it works

1. **Face sheets** (D4). Every person the camera sees in the scene who has a base sheet and no face sheet gets one: six
   head-and-shoulder views cut from the base sheet's portrait, painted at MEDIUM (`contracts.canon.face_sheet_prompt`,
   stored as `kind: "face"` on the card's `reference_assets`). The canon page can redo one ("Make face sheet").
2. **The writer** (`board_writer`, tier `board`: GPT-6.1 Sol, high, 10,000 output tokens) reads the scene and every
   painted shot's PLAN (never a first-frame prompt) and the reference pictures at detail low, and writes a shared
   `world`, the `geography` as a path, one panel per shot (camera, background, picture, and each person's opening
   `state`) and the `conflicts` it found in the data. Its rules are `agents/board_writer/prompts/system.md` (the lab's,
   unchanged). People are described only by their mannequin's pose.
3. **The image** (`contracts.board.board_prompt`): code writes the sheet, the references (the place plate only: the
   board has no faces, and since plan/2026-11-23c its props are white clay stand-ins) and the rules; `gpt-image-2`
   paints every panel at once at LOW (MEDIUM a setting, never HIGH, D2). People are smooth, faceless mannequins, one colour each (red, blue, yellow, green, purple, orange).
4. **After**: the picture is cut along its painted gutters into one PNG per shot; a numbered sheet is drawn by code
   (the image model never draws numbers), with black plates as black cells carrying their script line. Everything is in
   the private `frames` bucket under `<production>/boards/<board>/`.
   **The cut reads the grid that was PAINTED** (plan/2026-11-22, `lab/board_grid`): the image model sometimes paints
   another grid than the one asked for (asked 3 across and 2 down, painted 3 and 3 with a row of empty cells).
   `pictures.cell_boxes` finds every thin white gutter on the sheet, takes the grid that explains them over the painted
   extent (white left under the grid is not part of it), cuts at the gutters (at the even split where panels touch)
   and skips empty cells. `pictures.cut_problems` then checks each crop: a crop that is empty, holds two panels (a
   gutter runs through it) or holds an empty cell **fails the part** ("Part 2 of the board came out in a different
   layout than was asked. Paint the board again."); nothing is stored as a cell and nothing repaints by itself (D1 of
   plan/2026-11-22). The board writer never names a grid: `writer_message` gives it none, its prompt forbids it, and
   `board_prompt` drops any layout sentence from `world` (`board_layout_free`), so the head sentence alone decides the
   grid. Boards cut wrongly before this are mended with no model call by `scripts/recut_boards.py` (dry run by
   default; `--apply` stores new crops at fresh paths, keeps each cell's pin, note, lock and undo history, clears an
   approval, and lists first frames painted from the part without touching them).
5. **Parts** (D5): up to 16 painted shots on one picture; above that, parts of at most 12, the last panel of one part
   repeated as the first of the next (painted with that panel attached). A tall board holds up to 6, then parts of 6
   (plan/2026-11-23c D6; it was 9).
6. **Shape** (2026-11-16, `lab/portrait_board` run_001): the board has the production's shape. A horizontal production
   paints a 1536x1024 sheet of landscape panels; a vertical one a 1024x1536 sheet of tall panels ("a tall portrait 9:16
   still"), so each panel is the shape of its 9:16 first frame. An update keeps the shape the board was painted in
   (`aspect_of_board`, read from its prompt). A board in the other shape (painted before tall boards, or before the
   production's orientation changed) still feeds frames; the API says `wrong_shape` and the card asks for a whole repaint
  (Update board refuses it: a panel painted alone in the production's shape would not match its neighbours).

## The whole opening state, clay props and the board check (plan/2026-11-23c)

([plan/2026-11-23c/PLAN.md](../../plan/2026-11-23c/PLAN.md); what is built: its IMPLEMENTED.md.) A board of
2026-11-23 floated an umbrella, gave a mannequin a third arm and stood feet over a drain. The writer had been given
only part of the plan, and the umbrella came from a look's scene condition that no shot held.

- **The writer reads everything but the look** (D1). Each painted shot's plan (`shot_plan` + `shot_context`) adds
  the opening state (`intent.opens`), who holds what as it opens (`contracts.holding.hands_for`, the words a frame
  gets), each seen person's whole stager mark (facing, side of frame, both hands, condition, wearing; read by block
  number, so a map with an empty `basis` still answers), the props set down, who is only heard, the Raphael clip's
  summary and angle, the breakdown shot it covers, and each beat's performance and camera. The scene adds the
  treatment's whole geography (it was cut to 300 letters as the axis), its colour script and key image, the zones,
  and each person's gender and age.
- **New writer rules** (`prompts/system.md`): the opening state is the truth; what is held comes from the plan, never
  the look or the scene condition (reported in `conflicts`); two hands, one thing each; everything rests on something;
  only heard is not seen; props are stand-ins. Each panel now gives every person's `left_hand` / `right_hand` and its
  `props` (who holds them in which hand, or what they rest on). Old boards without them still load.
- **Props are white clay stand-ins** (D2, D4, D5): `prop_line` says every prop is a plain matte white clay object of
  its real size and outline (a car is a full-size clay car); never grey, which is a background person. The board
  picture gets the location plate only; the writer still reads the prop sheets. `SUPPORT` and each panel's `Hands:`
  sentence (`hands_text`, in mannequin colours) go into the image prompt. A frame painted from its panel gets
  `PROP_STAND_INS` and `unprop` ("the clay phone" → "the phone"); its vision check also looks for a leftover clay
  object.
- **Props bound to their sheets** (plan/2026-11-25b, lab/prop_mapping A): one roster per scene
  (`contracts.props.scene_props`: the props the plans name, the ledger's, and what each person carries in their look or
  condition) feeds the writer and the frame. A frame painted from a panel that lists its `props` takes the sheet of
  EVERY prop the panel shows (on top of `MAX_REFERENCES`, up to `MAX_PANEL_PROPS` = 4, before the panel) and, in place
  of `PROP_STAND_INS`, the lab's paragraph: each stand-in tied to its image number by holder, hand and side ("the clay
  umbrella in Anudi's left hand (the blue mannequin's), at frame right is the umbrella: paint it exactly as image 8 shows
  it (…), open"), "white is never a prop's colour", "each prop appears once". The panel's names resolve against the
  roster only ("bag" is the handbag she carries, never a document bag). The board's hands are the frame's ONE hands
  sentence and the frame check's hands; the ledger's are dropped while they are there. A name that is no prop of the
  production is reported in `conflicts` (not a fault: the panel is still attached) and painted from words.
- **The free check** (`writer_findings`, code, before painting): more than two things in a person's hands, a held thing
  no plan of the shot gives, a prop neither held nor resting, someone only heard on the board. Into `conflicts`.
- **The board check** (`board_inspector`, tier `vision`): each new panel is looked at for a third arm, a held thing with
  no hand on it, feet on nothing and the wrong hand. A failed panel is painted again ALONE, once, told what was wrong
  (`fix_line`); the cell keeps `check: {ok, problems, fixed?, repainted?}`, a panel still wrong is named in
  `conflicts`. Without the vision model (`OPENAI__MODEL_VISION=""`) nothing is checked. The same check runs on a
  panel painted by Update board.
- **The blind count** (`board_counter`, tier `vision`, pictures at `detail: high`; plan/2026-11-25): beside the board
  check, each panel with mannequins is looked at again, told ONLY their colours (lab/board_hands: told the expected
  hands, the check copies them back and passes a third arm). It counts each mannequin's arms and hands and says
  where each held thing is; code (`count_faults`) calls more than two arms or hands, or a thing in the air, a fault,
  which goes the same way (one repaint alone). In the lab it caught about half the bad panels, with no false alarm.
- **Tall parts of 6** (D6), not 9. **Pins carry a version** (D7): a new pin is `v2:<hash>` and also reads the opening
  state and who is only heard; a cell pinned before is compared with the old hash (`pin_matches`), so painted boards
  stay current until their shot really changes.

## Location views (plan/2026-11-24)

The person's method (lab/location_views): ONE sheet of six named views of a place (front wide, looking left, looking
right, reverse, two details), made once per location on the canon page ("Make location views"; the `views_writer`
agent writes the views, or a person edits them), stored on the location's card as a `views` asset with each view's box.
When the scene's place has one, the board picture gets the sheet instead of the plate, the writer names each panel's
`view`, and each PANEL line says "Background view: view n Name". A first frame painted from its approved panel gets
that view, cut from the sheet, instead of the plate, and the shot prompter is told it. No gate: without views the board
paints from the plate, and the card says "No location views yet".

### Place views by type (plan/2026-11-24c, lab/place_views + lab/final_views)

The sheet is made at CANON time, so it covers a place's main POSSIBLE views. The views writer first answers three
questions (`sides` outside | inside | both, `moves`, `size`); code picks one of four fixed six-slot templates
(`contracts.canon.VIEW_TEMPLATES`: outside = Wide, Looking left, Looking right, Reverse from ONE anchor spot + two
details; inside = Wide from the door, Opposite wall, Left wall, Right wall + two details; both = Outside wide,
Entrance, Inside wide, Inside reverse + two details; vehicle = Front three-quarter, Side, Rear three-quarter, Inside
from the rear, Inside from the front, Detail). A person may set the three answers on the canon page first; theirs win.

- **The writer reads** the card, its spots, the plate as a picture when there is one, the scenes set there as text, the
  boards' geographies, the fixed places in it (`within`) and the vehicles named there (`comes_and_goes`), whose spaces
  it lists in `empty` and keeps bare. A vehicle card's scenes are those whose words name it.
- **Code checks** (`view_findings`): the slots are the template's in order; no quoted text or sign wording the card has
  not; each detail names a thing from the card or a scene, and a plain table, chair or wall only when a scene uses it
  ("on the table"); each empty space says where it is. On findings, ONE re-ask with them as a list; still failing, the
  views are stored with the findings, shown on the canon page.
- **The sheet** (`views_sheet_prompt`, the lab's words) is painted in soft, even, DRY light whatever the plate or the
  scenes show (the writer's `light` is kept, never painted); no vehicle is parked in a place; a vehicle stands alone on
  a grey covered-parking floor. A place without a plate is painted from its card's words; vehicles' plates are never
  attached to a place's sheet. The `views` asset gains `answers`, `template`, `empty`, `findings`, and each view's
  `camera` and `sees` (`what` = both). A built sheet stays; "Remake" makes the new kind.
- **The board keeps each panel's view** (lab/final_views fault 1): the writer names the view its camera FACES (it reads
  each view's `camera` and `sees`); each PANEL line says "Background view: view 4 (Reverse): <the view's first
  sentence>"; the board inspector gets the view's words and its crop beside the panel and answers `view_match`. A
  mismatch is repainted once with the view named; still wrong, it is a board conflict line.
- A frame's view job adds "not its light, weather or wet ground".

## Vehicles (plan/2026-11-24b, lab/vehicle_role + lab/final_views)

A vehicle is a canon place of class `vehicle`. Its card has a `make` ("BMW 520d, 2019, pearl silver"), and it is named
with it to every model. Each shot says which vehicles it shows and the ROLE of each, which can change inside one scene
(`contracts.vehicles`):

- `inside`: the vehicle IS the place of the shot; `at`: it stands in the scene's place, `where` saying where, which way
  it faces and what it stands on (the line always ends "all its wheels on <that surface>").
- Written by Raphael per clip (`ir.vehicles`, by name from the scene's vehicle cards; code maps names to ids, drops a
  stranger, keeps one `inside`); report-only checks tell it of an unknown name, two `inside`, or a `where` with no
  surface. A person changes a role on the shot screen (`PersonEdits.vehicles`, PUT/DELETE
  `.../shots/{id}/vehicles/{vehicle}`), which wins. An older shot with no `ir.vehicles` finds a named vehicle as `at`.
- **Board:** each vehicle's views sheet (else its plate) is attached after the place's, with the vehicle-only job; a
  vehicle is never clay (`CLAY_NEW`); one "Vehicles (every panel):" line before Geography says panel by panel where
  each is, with the seat-side sentence for a car a panel is inside (right-hand drive unless the card says otherwise).
  The writer reads each vehicle's card and each shot's role. A panel inside a vehicle that has a views sheet names
  that sheet's view.
- **First frame:** `inside`: the vehicle's plate is THE place (its label ends ", the place of this shot"; the location
  plate is not attached), or the inside view its panel names when the vehicle has a views sheet; `at`: the location
  (or its view) leads and the vehicle plate follows. The brief gains the lab's place sentence or "Vehicles in this
  shot", and the shot prompter gets each vehicle as a fact.
- `scripts/vehicle_make.py` moves a make out of an older look into `make` (dry by default; `--apply` writes a new
  version that keeps the plate).

## Fixed marks and the blocking plate (plan/2026-11-24d, lab/fixed_marks)

The person's rule: a person who does not walk or travel stays on ONE ground spot for every shot; only a walk, a run,
an entrance or an exit moves them. Small moves (a turn, a lean, half a step, sitting down on the spot, D1) stay within
0.5 m. Words hold a spot within one picture but not between the parts of a board (lab A_001 / A_002); a picture does
(C, T, R, W): so each run of still shots gets a **blocking plate**.

- **Stretches** (`contracts/marks.py` `stretches`): code finds them in the staging map, never a model. A shot belongs
  to the stretch of its opening block; a scene planned with line parts is mapped to the map's whole blocks
  (`whole_index`). No map: the board paints as before, with "No staging map" in its conflicts.
- **Spots**: the board writer reads `stretches` in its bundle and writes `marks` (one `GroundMark` per stretch and still
  person: what they stand on, beside which landmark, which side, how far; `apart` the gap). `marks.check` keeps one
  each; a missing one is a conflict and its stretch gets no words and no plate.
- **Words**: each part gets the "Ground marks" paragraph of its stretches after Geography (`marks.paragraph`) and a
  marks line at the head of each panel (`marks.panel_line`: still / someone leaves the mark in this shot / a new
  stretch begins); a panel painted alone (the check's repaint, Update board) gets them too.
- **The plate** (`kit.plate_prompt`): one still per stretch of two or more shots with someone still, painted BEFORE the
  parts at the panels' shape and the board's quality, from the view most of its panels face (else view 1 of an
  `outside` / `inside` sheet; a `both` or vehicle sheet without a named view gets the words only), with the stretch's
  first panel's hands. `board_inspector` looks at it like a panel and it is painted again once on a fault. It is
  attached to every part (after the place and vehicles, before the overlap panel) and every panel painted alone in its
  stretch. A plate that cannot be painted never fails the board.
- **Storage**: no schema change. The spots and plates live in the version's `writer` (`writer.marks`,
  `writer.plates`: `{n, shots, shot_ids, people, view, path, pin, check, prompt}`), which every part stores and no
  browser receives; plate files are `<production>/boards/<board>/plate_<n>-<id>.png`, written once.
- **Repaint whole board** keeps a plate whose pin (shots, people, spots, colours, pictures) is unchanged; **Repaint
  marks** (`state.repaint_plates`) paints the named plate again, then the board (a new version, D3). Rewrite and
  repaint writes new spots and new plates.
- **Internal** (the person, 2026-11-25): the plate is generated and kept on the backend, never shown. No API response
  carries it, its ticket, its spots or its prompt; the board card has no Marks row. Repaint marks stays as a route
  with no button.
- **Out of date**: the board view compares each plate's shots and people with the stretches as the staging map gives
  them now; a changed one is `stale` with "The marks of shots 1 to 14 changed: Rewrite and repaint." Never repainted by
  itself.
- First frames still get only their own panel (D4); a per-panel marks check waits for the live check (D5).

## The first frame follows the board (plan/2026-11-23d part 4)

**No approved board, no first frame** (D4, the person 2026-11-23): "Paint first frame" is refused (409) and its button
disabled, with the panel's reason, until the shot's panel is painted, current and its part approved; a black plate
needs no board.

Before this, a shot with a current shot prompt (every Raphael shot) was painted from the prompt's words alone: the
approved board never reached its first frame. Now:

- **The board paints the Camera agent's camera.** `shot_plan` gives the writer `camera_design` (`camera_of`: the
  design's picture fields with a person's changes, what the frame opens on, the composition note), the camera the
  shot prompt is written from. Pins are `v3:` and include it; `v2:` and unprefixed pins are compared in their own
  version, so painted boards stay current.
- **The shot prompter writes from the approved panel.** `World.approved_panel` (`contracts.board.approved_panel`: the
  current board's part done and approved, the panel's pin matching) gives `board_facts` (the blocking without the
  camera, both hands per person, the props) into the `<shot>` part; its prompt has one rule for it, and a check: a
  thing the board puts in a hand must be named in the frame. The record stores `board` (`<part id>:<cell path>`).
- **A later approved panel makes the shot prompt out of date** (D2): `board_reason` → "The approved scene board
  changed since this shot prompt was written.", in the frame_compose world and in the API's `scene_states` alike, so
  "Draw first frame" writes it again from the panel first.
- **The frame gets the panel for the blocking.** With a current shot prompt the approved panel is attached last as
  `BLOCKING_LABEL` ("the approved scene board panel of this shot"): where everyone stands and faces, what each hand
  holds, the props and the place; "this shot's words decide the camera". `frame_sections(blocking=True)` drops the
  panel's camera and adds the approved hands (`held_text`). Without a shot prompt the panel is the full draft, as
  before. A panel whose shot the board's own check found breaking a fact (`panel_faults`) is not attached.
- **The look sheet no longer puts a carried thing in a hand** (`frame_brief.CARRIED`): a bag or an umbrella on the look
  sheet is held or worn as the shot's words and hands say.

## Approve, out of date, update

([plan/2026-11-17/PLAN.md](../../plan/2026-11-17/PLAN.md); the lab: `lab/panel_edit/`, run_001 and run_002.)

- A person **approves** the board (each part). Only an approved board feeds first frames (D3).
- Every cell records a pin of what the writer read about its shot (`plan_pin`; a black plate's too). When a shot changes,
  is added, removed or moved (through Zora, Sable or by hand) the board says "Out of date: Shot 5 changed · shot 4 added
  · shot 7 removed"; it **never repaints by itself**. A Zora or Sable save moves only the pins of the shots it touched
  (`tests/zora/test_board_pins.py`).
- **Update board** (`POST .../scenes/{id}/board/update`, one job): an edited shot **repaints only its own panel**:

  | Out of date because | What the update does | Painted |
  |---|---|---|
  | a shot changed | its panel painted alone | 1 panel |
  | a shot was added | its panel written and painted alone, its cell inserted in shot order (in the part of the shot before it) | 1 panel |
  | a shot was removed | its cell dropped | nothing |
  | shots were reordered | the cells put in order | nothing |
  | a shot became / stopped being a black plate | a black cell drawn by code / a panel painted alone | 0 or 1 |

  **One panel alone** (§3.2): the same `board_writer`, the same system prompt (cached); the one-panel instructions
  (`contracts.board.ONE_PANEL`) go at the end of the user message, with the approved board's world, geography and
  panels as FIXED facts, the shot's plan and the board's SAVED colours. The image (`panel_prompt`) is one film still in
  the board's shape, `CAMERA_RULE` included, the sheet's layout words dropped from the world (`panel_world`); attached:
  the place, the shot's props, then the panels just before and after it. The picture is the cell, whole
  (`cell_<shot_id>-<job>.png`, `source: "panel"`); nothing is ever pasted over another panel and no mask is used: the
  image model does not honour one (run_001: cells outside the mask became a different street). Then code renumbers
  every cell and writer panel together from the shots as they stand (`renumber`: a first frame reads its panel's words
  by number), and redraws each touched part's numbered sheet from its cells (grid cuts and panels side by side, each
  fit, never stretched).
- **Colours stay** (§3.4): an update keeps the row's `colours`; a new person gets the first colour no one uses
  (`keep_colours`). A whole repaint keeps them too when it paints from the saved words; a rewrite takes fresh colours.
- **Approval** (§3.3): per part, as before. The API queues every part with its approval cleared (the schema allows an
  approval only on a done part) and carries the approval in the job; a part whose cells got a new picture is left
  unapproved ("Updated: shot 5. Look at the board and approve it again."), a part with no new picture gets the
  person's approval back. An update that only removes or moves shots keeps the approval (D2, as recommended).
- **Undo is free** (§3.6): a cell keeps its last three pictures (`previous`); when Zora's undo puts a plan back, the
  update restores that picture and panel with no model call.
- A panel that fails keeps its old cell (an added shot stays out of date); the others still update; the part says
  which shot failed. A **locked** panel is never repainted: a locked and changed shot is named ("unlock it to update
  it"). A **note** on a panel goes to the writer when that panel is painted again.
- **Repaint whole board** makes a new version: for a fresh look, a board in the wrong shape, or a board with a failed
  part; notes and locked panels carry over (a locked panel's old picture is pasted back).
- **Repaint paints, it never writes again** (the person, 2026-11-24). A whole repaint paints the pictures again from the
  panel words already written (`contracts.board.saved_board` → `reuse_writer`: the newest version with words, a failed
  part's included; the saved colours kept); the board writer does not run. Each panel is stamped by code with the shot
  it was written for and that shot's `plan_pin` (`Panel.shot_id` / `pin`, never shown to a model; older panels take
  them from their cells). A panel needs its words **written again** (`rewrite_needed`) only when its shot changed since
  (a chat or a planner moved the pin), it has none, or an unlocked panel carries a note. Then the view's `rewrite`
  names those shots, Repaint is refused (409) and the card offers **Rewrite and repaint** (`POST .../board` with
  `rewrite: true`), beside Update board. A first board is always written.
- **One board of shots 1 to N** (the person, 2026-11-24): parts are how the picture is made and are never shown. The
  card draws every part's cells as one grid in shot order, the overlap shot once (its first part's, as
  `owner_cell`); **Approve board** (`POST .../scenes/{id}/board/approve`) approves every finished part at once; a
  failed part is named by its shots ("Shots 1, 2, 3, 4, 5 and 6 came out in a different layout…", `bad_cut`).
- **The job says what it starts** (2026-11-24): a board job is a `frame_render` job, which the sweeper ends after 10
  minutes with no job event; the board writes a `stage` event before the writer, each part, each panel check, each
  single-panel repaint and each updated panel (`board._beat`). A job the sweeper ended that then finishes is `done`
  with its error cleared (`runtime/jobs.finish`).
- **A part whose picture fails the cut keeps it** (2026-11-24): `rejected.png` and `rejected-cut.png` (the cut drawn,
  red boxes the failed panels) in the part's folder, `checks[{kind: "rejected_cut", problems, boxes, path, cut_path}]`,
  shown under the part's error (`rejected_url`, `rejected_cut_url`, `rejected_problems`).

## The first frame from its panel (§3.5)

A first frame of a painted shot is made only from the shot's panel of the approved, current board (D3); the API answers
with the reason otherwise. Black plates need no board. Drafts are no longer painted. The pictures, in order: each seen
person's face sheet, their look sheets (clothes only; hair from the look when the look sets hair, D6), the place, the props
the shot names, then the panel as "the approved draft of this frame" (only its own panel, D8). The prompt gains the
mannequin paragraph (who is which colour), each person's planned opening state, the board's world and the panel's
words, all with the mannequins turned back into people, and first the stand-in rule (`STAND_INS`): every figure in the
draft, named or not, is a real person. A background figure no colour names ("two grey pedestrian mannequins") becomes
"two pedestrians" (`unmannequin`); before both, such extras were painted into the frame as grey mannequins. The
vision check also looks for a leftover mannequin and for the
planned state. These jobs run on the `hiru_ai` engine whatever `AI_ENGINE` says.

## What it costs (for the person, never the interface)

Measured in the lab: a face sheet ≈ $0.06; a board ≈ $0.15-0.18 (writer + LOW picture); a first frame ≈ $0.13-0.19. A
10-shot scene with two new characters ≈ $1.80. One panel updated (lab/panel_edit): writer ≈ $0.02-0.03 + LOW picture
≈ $0.054-0.059; a removed or moved shot, or an undo, costs nothing.

## API

| | |
|---|---|
| `GET .../scenes/{id}/board` | the current board: parts, cells, conflicts, what is out of date |
| `POST .../scenes/{id}/board` `{quality}` | paint the whole board (job, new version) |
| `POST .../scene-boards/{id}/approve` | approve one part |
| `PATCH .../scene-boards/{id}/cells/{shot_id}` `{note?, locked?}` | a panel's note or lock |
| `POST .../scenes/{id}/board/update` `{shots?}` | Update board (job): shot ids, none = everything out of date; 409 with no finished board, a wrong shape, nothing out of date, or while a plan runs |
| `POST .../scenes/{id}/board/plates/{n}/repaint` | Repaint marks (job, plan/2026-11-24d): plate `n` painted again, then the board, as a new version from the saved words; 404 with no such plate |
| `POST .../canon/{id}/face-sheet` | a character's face sheet (job) |

Schema v26 (`Database/upgrade_v25_to_v26.sql`): `scene_boards`, `first_frames.board_id`.
