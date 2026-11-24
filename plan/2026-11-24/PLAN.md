# Location views: one sheet of named views keeps the place the same from shot to shot (plan/2026-11-24)

Revision 1 (2026-11-24). Nothing in this plan is built. The person's method, proven in `lab/location_views` (runs
001-003, $0.33 of $1). It follows plan/2026-11-23c and plan/2026-11-23d (the board's opening state, clay props, the
first frame follows the board), built offline and uncommitted. Read this file whole, then `lab/location_views/run.py`,
`docs/scene_board/README.md`, `src/libs/contracts/board.py`, `src/libs/contracts/frame_brief.py`
(`plan_references`, `reference_job`), `src/libs/contracts/canon.py` (`sheet_assets`, `face_sheet_path`) and
`src/libs/hiru_ai/systems/frame_render/graph.py` (the `reference` and `face` sheet nodes).

## 0. Rules for the chat that builds this

- **Port the lab exactly.** The sheet prompt, the board's references paragraph and "Background view" line, and the
  frame's view label and job are the lab's words (`lab/location_views/run.py`). List any change before making it.
- **Ask before every paid call**, each time. Tests run with `OPENAI__API_KEY=` blank and fakes only.
- **No enable switches.** **Never stash or reset** the person's tree. **Never edit an applied migration** (none is
  expected: the sheet is a `reference_assets` entry, the view a field of the board writer's JSON).
- Two repos: the backend (this one) and `..\hiru-ai-studio-interface` (its `CLAUDE.md` binds).

## 1. What is wrong today, and what the lab showed

The board and the first frames are painted against ONE location plate, "one view of the place; each panel has its own
camera position, so do not repeat this view". So every panel and every frame invents the rest of the place: on scene 4's
board part 1 the food three-wheeler was a white van in shots 1 and 3 and a lit shop interior behind shots 2, 4 and 5;
shot 1's frame had a blue-awning three-wheeler with a steel flask.

The lab (scene 4, "Colombo roadside" + "Food three-wheeler"):

| Run | What | Cost | Result |
|---|---|---|---|
| 001 | the sheet: 6 views, 3x2, no people, MEDIUM, from the two plates | $0.094 | the same three-wheeler (maroon, black roof, lit hatch, red tartan flask) in every view it is in; one layout (stall left, pale wall and green building right, drain at the road edge); cut clean |
| 002 | board part 1 again, LOW, the sheet instead of the plate, each panel told its view | $0.048 | shots 1-5 all show the same three-wheeler behind Kasun and the same wall and green building behind Anudi; shots 1 and 3 (one setup) keep the same spacing |
| 003 | shot 1's first frame, MEDIUM, view 1 instead of the roadside plate | $0.192 | the sheet's three-wheeler and wall; the board's blocking, umbrella and bag kept |

Not proven by the lab: a second scene at the same place; the board writer picking the views itself (the lab picked
them by hand); a shot prompt written with its view named.

## 2. The design

### 2.1 The location sheet (a new sheet of a location, like a face sheet of a person)

- **Stored** on the location's current card as a `reference_assets` entry of kind `views`, with its views:
  `{"kind": "views", "path": ..., "views": [{"n": 1, "name": "Front wide", "what": "...", "box": [x0, y0, x1, y1]},
  ...]}`. `sheet_assets` leaves it out (as it leaves out face sheets), so the plate stays the plate; a new
  `views_sheet(row)` finds it.
- **Written** by ONE small call of a new agent `views_writer` (tier `medium`, structured): from the location's card
  (`look`), its spots, the other places that stand in it (a canon location the scenes at this location also use, such
  as the food three-wheeler) and the geography the board writer wrote for scenes there, it writes six views in the
  lab's pattern: a front wide (the main view people are seen against), looking left, looking right, the reverse, and
  two details. Each view is one or two sentences of what the camera sees and on which side. A person can edit them on
  the canon page before painting (Q2).
- **Painted** by the frame_render system's sheet path (a new `views` node beside `reference` and `face`): the lab's
  sheet prompt with the views filled in, the location plate and the plates of the places in it attached, 1536x1024,
  MEDIUM. Code cuts it with `pictures.cell_boxes` (6 cells, 3x2), stores each box, and refuses a sheet that does not
  cut clean (`cut_problems`), as the board does. The model draws no text; the shot screen and the canon page draw the
  view names.
- **Asked for** on the canon page: "Make location views" on a location (one job, like "Make face sheet"), and offered
  on the Scene board card when the scene's location has none (as `missing_faces` is today).

### 2.2 The board uses the views

- The board writer gets the views (number, name, what) in its bundle and one rule: each panel names the view its
  background comes from (`Panel.view`, a number; 0 when none fits, such as an insert against a plain surface). Its
  `background` stays its own words.
- The board picture gets the sheet instead of the single plate, with the lab's references paragraph, and each PANEL
  line gains "Background view: view <n> <name>." A board whose location has no views sheet is painted as today, and the
  card says so.
- `writer_findings` reports a panel naming a view the sheet does not have.

### 2.3 The first frame uses its panel's view

- `plan_references`: when the shot's approved panel names a view and the location has a views sheet, the location
  plate is replaced by that view's crop, labelled "view <n> (<name>) of the location sheet for <place>", with the lab's
  job ("the background exactly as this view shows it ... seen from this shot's own camera"). The crop is cut on the fly
  from the stored sheet and box (no new file per view).
- Other places' plates (the three-wheeler) stay attached, as in run 003.
- The shot prompter's `<shot>` part gains "Background view: <name>: <what>" from the panel, so the shot prompt's
  background words and the picture agree (not tested by the lab; phase 0 of the live check).

## 3. Questions for the person

- Q1 **One sheet per location, or per location as a scene sets it?** The views of "Colombo roadside" include the
  food three-wheeler because scene 4 parks it there. Recommended: one sheet per location, made from the places that
  stand in it; a person makes it again (a new version) when a later scene sets the place differently.
- Q2 **Edit the views before painting?** Recommended: yes, the six views are shown on the canon page as text with a
  "Paint views" button; "Make location views" writes and paints in one go when nobody edits.
- Q3 **Gate the board on the views sheet?** Recommended: no gate; the board paints from the plate as today and the
  card offers "Make location views" (the first frames are already gated on the approved board).

## 4. Phases (offline, $0, then the person's live check)

1. **Contracts**: the `views` asset kind (`views_sheet`, `view_crop`), `sheet_assets` leaving it out; the lab's sheet
   prompt as `contracts.canon.views_sheet_prompt`; tests with the lab's run_001 sheet.
2. **`views_writer` agent** (schema, prompt, evals) and the `views` node of the frame_render system; the API route
   `POST .../canon/{id}/views-sheet` (one job) and the canon view's `views` (names, crops' URLs).
3. **Board**: `Panel.view`, the writer's bundle and rule, the board prompt's references paragraph and per-panel line
   (the lab's words), `writer_findings`.
4. **Frame**: `plan_references` with the panel's view crop, the reference job, the shot prompter's line.
5. **Interface**: the canon page (views as text, the button, the sheet with the names drawn), the board card's offer,
   the shot screen's reference list naming the view.
6. **Docs**: `docs/scene_board/README.md`, the catalog; IMPLEMENTED.md.
7. **Live check (paid, the person's)**: make the views of "Colombo roadside" in the product (about $0.10 plus a
   few cents for the writer), Update board for scene 4, then the first frames of shots 1, 3 and 11 (three frames of one
   setup, about $0.15-0.19 each). Measured: the same three-wheeler, wall and building in every panel and frame, the
   pair's spacing in shots 1, 3, 11.
