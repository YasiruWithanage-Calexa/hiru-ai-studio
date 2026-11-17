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
3. **The image** (`contracts.board.board_prompt`): code writes the sheet, the references (the place plate and prop sheets
   only: the board has no faces) and the rules; `gpt-image-2` paints every panel at once at LOW (MEDIUM a setting, never
   HIGH, D2). People are smooth, faceless mannequins, one colour each (red, blue, yellow, green, purple, orange).
4. **After**: the picture is cut along its painted gutters into one PNG per shot; a numbered sheet is drawn by code
   (the image model never draws numbers), with black plates as black cells carrying their script line. Everything is in
   the private `frames` bucket under `<production>/boards/<board>/`.
5. **Parts** (D5): up to 16 painted shots on one picture; above that, parts of at most 12, the last panel of one part
   repeated as the first of the next (painted with that panel attached). A tall board holds up to 9, then parts of 9.
6. **Shape** (2026-11-16, `lab/portrait_board` run_001): the board has the production's shape. A horizontal production
   paints a 1536x1024 sheet of landscape panels; a vertical one a 1024x1536 sheet of tall panels ("a tall portrait 9:16
   still"), so each panel is the shape of its 9:16 first frame. An update keeps the shape the board was painted in
   (`aspect_of_board`, read from its prompt). A board in the other shape (painted before tall boards, or before the
   production's orientation changed) still feeds frames; the API says `wrong_shape` and the card asks for a whole repaint
  (Update board refuses it: a panel painted alone in the production's shape would not match its neighbours).

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
  (`keep_colours`). A whole repaint takes fresh colours.
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
| `POST .../canon/{id}/face-sheet` | a character's face sheet (job) |

Schema v26 (`Database/upgrade_v25_to_v26.sql`): `scene_boards`, `first_frames.board_id`.
