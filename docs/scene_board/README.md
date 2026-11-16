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
   still"), so each panel is the shape of its 9:16 first frame. A repaint keeps the shape the board was painted in
   (`aspect_of_board`, read from its prompt). A board in the other shape (painted before tall boards, or before the
   production's orientation changed) still feeds frames; the API says `wrong_shape` and the card asks for a whole repaint.

## Approve, out of date, repaint

- A person **approves** the board (each part). Only an approved board feeds first frames (D3).
- Each panel records a pin of what the writer read about its shot (`plan_pin`). When a shot changes the board says
  "Out of date: shot 4 changed"; it **never repaints by itself**.
- **Repaint changed panels** (D7, method A): a masked `images.edit` of that part's picture, transparent over the changed
  cells only, so every other panel stays pixel for pixel. Its approval is cleared. **Repaint whole board** makes a new
  version (needed when shots are added, removed or reordered); notes and locked panels carry over.
- A **locked** panel is never repainted (in a whole repaint its old picture is pasted back). A **note** on a panel goes to
  the writer only when that panel is repainted.

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
10-shot scene with two new characters ≈ $1.80.

## API

| | |
|---|---|
| `GET .../scenes/{id}/board` | the current board: parts, cells, conflicts, what is out of date |
| `POST .../scenes/{id}/board` `{quality}` | paint the whole board (job, new version) |
| `POST .../scene-boards/{id}/approve` | approve one part |
| `PATCH .../scene-boards/{id}/cells/{shot_id}` `{note?, locked?}` | a panel's note or lock |
| `POST .../scene-boards/{id}/repaint` `{shots}` | repaint some panels in place (job); none named = the changed ones |
| `POST .../canon/{id}/face-sheet` | a character's face sheet (job) |

Schema v25 (`Database/upgrade_v24_to_v25.sql`): `scene_boards`, `first_frames.board_id`.
