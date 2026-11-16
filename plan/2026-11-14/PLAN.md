# Scene board: consistent first frames from one mannequin board per scene (plan/2026-11-14)

Revision 2 (2026-11-14): the person's decisions D1-D5, D7, D8 recorded in §5 and applied below (D6 added the same day). Nothing in this plan is built. It brings into the product what the storyboard lab proved
(plan/2026-11-13e, `lab/storyboard/`, $3.23 in 16 paid runs). Phase 0 and phase 7 are paid and need the person's yes,
each call; phases 1 to 6 are offline ($0). Read this file whole, then `plan/2026-11-13e/PLAN.md` §1-2 (the problem)
and §6c-6k (every run and what it taught). Everything a new chat needs is written here or named here by path.

## 0. Rules for the chat that builds this (read before anything)

- **Two repos.** Backend: `C:\Users\witha\Documents\projects\Hiru TV\source\hiru-ai-studio` (Python 3.12, run everything
  with `.venv/Scripts/python.exe`; the system `python` is 3.9 and must not be used). Interface:
  `...\hiru-ai-studio-interface` (Next.js 16; read its `CLAUDE.md` and `AGENTS.md` first, they are binding: data
  through `features/*/api.ts`, routes from `src/config/routes.ts`, shadcn/ui, TanStack Query "quiet by default", files
  through `<Media>`, **no costs or credits in the UI**).
- **No model call, image or paid run without the person's yes, each time.** Tests run with `OPENAI__API_KEY=` blank
  (the `.env` holds a real key). The hosted Supabase is the one dev database: no SQL and no writes against it without
  asking; reads only inside `set transaction read only` or GET requests.
- **The person's image rule (2026-11-14): no high-quality images.** Boards paint at LOW (the setting may allow medium),
  face sheets and first frames at MEDIUM. `high` is not offered by this feature.
- **OpenAI only** for text and images (backend `CLAUDE.md` "Fixed decisions"). Image model `gpt-image-2`
  (`images.edit`); it does NOT accept `input_fidelity` (400, measured 2026-11-14).
- **Safe depiction** (`contracts/safe_depiction.py`): every board and frame prompt is scanned with `blocking()` before
  the image call; the board writer's prompt carries `PROMPT_LINE`.
- **Prompt hygiene**: a writer failure is fixed by a principle plus examples from OTHER stories, never by pasting a
  scene's words into a prompt (the lab's `prompt/system.md` follows this; keep it so).
- **Files are CRLF.** Rewrite a backend file with `open(p, "w", encoding="utf-8", newline="")` keeping its endings. A
  Bash heredoc in this harness turns `\n` / `\b` inside the text into real control characters: write code that
  contains escapes with the Write or Edit tool, never through a heredoc (the lab hit this four times).
- **Uncommitted work of other plans is everywhere** (see the memory index). Read `git status` / `git diff` of a file
  before editing it; never overwrite someone else's change.
- **Commit only when the person asks.** Write `IMPLEMENTED.md` in this folder as phases land.
- Checks before finishing (backend): `ruff check src tests scripts`, `mypy`, `.venv/Scripts/python.exe
  scripts/lint_imports.py`, `.venv/Scripts/python.exe -m hiru_ai validate`, `... -m hiru_ai catalog --check`, `pytest -q`
  (with `ADAM_MODE=staged OPENAI__API_KEY=`). Run the test baseline BEFORE phase 1 and report only new failures.
  Interface: `npx next typegen && npm run check && npm run format:check`.

## 1. What and why

**The problem** (plan/2026-11-13e §1-2): first frames of one scene are painted one shot at a time, each from the same
single location plate, so they disagree. In scene 01 (Mahawewa canal) the walk and the discovery got the SAME
background, the walk already showed the gate where the body is revealed later, and people's faces, poses and clothes
drifted from frame to frame.

**The fix the lab proved**: before any first frame, paint ONE image per scene, the **Scene board**: every painted shot's
opening picture as a numbered panel, in one generation, so place, light, props, camera positions and blocking are
consistent by construction. People on the board are **faceless, colour-coded mannequins** (one colour per person), so
the board fixes WHERE everyone is and HOW they sit or stand, but never their faces. A person approves the board. Then
each shot's first frame is painted from **its panel** (the layout) + **the person's face sheet** (the face) + **the
look sheet** (the clothes) + **the plan's state for this shot** (eyes closed, still …) + **only the props the shot
names**.

**Why mannequins** (the person's idea, 2026-11-14, refined): with real people on the board, the board invented faces
(older, heavier) and every frame copied them; with mannequins there is no face to copy. Coloured mannequins, not
pose-detector skeletons: an OpenAI image model draws mannequins with real body volume, seat contact and hands on
things; skeletons are for ControlNet-style tools we do not use, and coloured lines leak into frames.

**Why face sheets**: every look sheet and character sheet today holds ONE face (front, smiling, studio light; the four
body views are headless). A shot needs that person serious, turned, at night, so the model invents the face. A face
sheet (6 head-and-shoulder views: front neutral, two three-quarters, two profiles, front serious) gives it the angles.
This also helps today's first frames, board or not.

## 2. What the lab proved (plan/2026-11-13e, read §6c-6k for the detail)

| Run | What | Result |
|---|---|---|
| run_003 | numbered sheet of every shot, LOW | numbers drawn by code; black plates as black cells; LOW is enough for a board ($0.12) |
| run_004 | scene 02, 16 shots, one image | 16 panels hold; cabin, props, light consistent ($0.20 at medium) |
| run_005 | first frame from its panel (draft wording) | layout kept, but the board's drifted FACE copied |
| run_006/007 | face sheet for Dinu → board | faces match the portrait in all 16 panels |
| run_008 | a general "bodies" rule only | partly: the writer's own camera text overrides a general rule |
| run_009 | mannequin board, writer describes poses only | natural seated poses; nothing to drift |
| run_010 | MEDIUM frame from a mannequin panel | best frame of the lab: natural driver, right face and clothes, no mannequin left ($0.13) |
| run_011 | close-up from a mannequin panel | face right; stared into the lens; window side flipped → two writer rules |
| run_012-014 | scene 01, two people (red Nimal, blue Aruni), MEDIUM face sheets | colours told apart; blocking and screen side held; close-ups no longer face the lens |
| run_015 | two-person MEDIUM frame | colour → person mapping right; but Nimal awake (state lost) |
| run_016 | + the plan's opening picture per person | Nimal still, eyes closed; but loose phone/key (lab attached every prop) |

Measured costs (lab ledger, over-stated image rates): face sheet MEDIUM **$0.06**; board = writer **$0.07-0.08** + LOW
image **$0.07-0.10**; first frame MEDIUM **$0.13** (one person) to **$0.19** (two people, 9 pictures in).

## 3. The design

### 3.1 Face sheets (per character)

- **Where**: `canon_versions.reference_assets` already holds `[{kind, path, job_id, version, created_at}]`. Add
  `kind: "face"` next to `"sheet"`. No schema change.
- **Made from**: the portrait in the character's current sheet (the look sheet when one is in force is NOT used: the
  face does not change with a look). Code crops the right-hand portrait (the lab's `faces.py`: right 26.5 % of a
  5-view sheet) and paints 6 views at MEDIUM with the lab's gender-neutral prompt (`lab/storyboard/faces.py PROMPT`).
  Move the prompt to `contracts/canon.py` (`face_sheet_prompt()`), next to `look_sheet_prompt`.
- **Job**: the existing `frame_render` reference-sheet path (`state.reference_entity_id`) gains `state.reference_kind =
  "face"`. A vision check (`frame_render.engine.inspect.sheet_checks`) confirms six views of one person.
- **When (D4: automatic)**: when a Scene board is painted, the job first makes the face sheet of every person who
  appears on screen in the scene and lacks one (MEDIUM, ~$0.06 each), then paints the board; a first frame does the
  same for its on-screen people. The character's canon page also has "Make face sheet" to redo one.
- **Use**: whenever a face sheet exists it is attached FIRST for that person, in boards' frame step AND in today's
  frame path. Its label `the face sheet for <name>`; its job (`frame_brief.reference_job`): "<name>'s face, age and
  hair at every angle and expression: <name>'s face comes ONLY from this sheet". When a face sheet is attached the
  look sheet's job becomes "<name>'s clothes, shoes and accessories in this scene, not the face, light or backdrop"
  (lab `run.py _job`). Hair (D6, decided): from the look sheet when the look sets hair (`canon_looks.hair` not empty), else the face sheet; the face-sheet job then says "face and age" without hair, and the look-sheet job adds "and hair".

### 3.2 The Scene board (per scene)

- **One board per scene, versioned.** New table `scene_boards` (schema v25, §3.8). A board holds: the writer's output
  (world, geography, panels, conflicts), the colour of each person, the image, the panel map (shot → cell box), the
  pins of every shot it drew, its status, and approval. One approved board per scene (unique index, like
  `first_frames_one_accepted`).
- **Which shots**: every shot of the scene in order. Black plates (`contracts.frame_brief.black_plate`: cut to black,
  title cards) are NOT painted; they appear on the sheet as black cells carrying their script line.
- **Size limit**: up to 16 painted shots in one image (4x4 measured clean, run_004). More than 16 → the board is split
  into parts of at most 12, each its own image, the last panel of one part repeated as the first of the next (D5).
  Grid: `ceil(sqrt(n))` columns.
- **The writer** (new agent `board_writer`, Hiru AI pattern of plan/2026-11-05e; model `gpt-6.1-sol`, effort high,
  `max_output_tokens` 10000, Responses JSON schema): input = scene (heading, script, mood, axis, staging marks),
  every painted shot's plan (lab `fetch.py` fields: size, role, script lines, `spoken` lines from `dialogue_lines`,
  story, purpose, on-screen names, setting, `ir.first_frame` composition + subjects, `ir.subjects`, cinematography,
  lighting, beats), the people (appearance, look fields), the place and its spots' look text, the props, and the
  reference pictures at `detail: low`. Its instructions = the lab's `prompt/system.md` (all rules, §3.4) + the
  mannequin note (lab `run.py mannequin_note`). Output schema = the lab's `SCHEMA` plus, per panel, `people:
  [{name, state}]` where `state` is the person's condition at the opening (eyes open/closed, still, asleep, crying,
  breathing hard); never drawn on the board, carried to the frame (§3.5).
- **The image** (code-built prompt, lab `run.py board_prompt` with `mannequins=True`): sheet header (grid, read order,
  16:9 panels, thin white gutters); references = the PLACE plate and the PROP sheets only (no face or look sheet: the
  board has no faces); the "People:" line (each person = a smooth, matte, faceless mannequin in one colour, a ridge on
  the head shows the face direction, real height and build); World (writer, minus sentences describing a face); the
  Geography; one line per panel; the `BODIES` line; "Draw NO text". `gpt-image-2` `images.edit`, **LOW**, 1536x1024.
  Colours in person order: red, blue, yellow, green, purple, orange.
- **Code after the image** (lab `run.py`): gutter-aware crop (`_gutters`, `crop_panels`) → one PNG per shot; the
  numbered sheet (`scene_sheet`: a red "SHOT N" tag drawn by code per cell, black-plate cells) → both stored in the
  private `frames` bucket under `boards/<board_id>/`. The image model never draws numbers.
- **The conflicts list** the writer returns is shown to the person beside the board (it found real data faults every
  run: wardrobe vs plan, bag colour, a cut axis note, a line without words). It is advice, not a block.

### 3.3 Approve, out of date, repaint, lock, notes

- **Approve**: a person approves the board (or one part). Only an approved board feeds first frames.
- **Pins**: each panel records the pins of its shot at paint time (`contracts.producer.Pins` of the shot's plan fields
  the writer read). When a shot changes, the board shows **"Out of date: shots 4 and 7 changed"**; it never repaints
  by itself (the person, 2026-11-13).
- **Repaint** (person's choice): the whole board (shots added, removed or reordered), or **only the changed panels**:
  `images.edit` with a mask that is transparent over those cells and opaque elsewhere, so the other panels stay
  pixel-identical (D7: method A). Phase 0 must prove `gpt-image-2` honours a mask on a board; if it does not, stop
  and ask the person (method B, a whole repaint with locked panels pasted back by code, is the fallback they have
  not yet chosen).
- **Lock** a panel: a locked panel is never repainted.
- **Note per panel** ("shot 1: side-on, walking right"): stored on the board; on a repaint the writer receives the
  notes of the panels being repainted, for those panels only.

### 3.4 Writer rules (all in the lab's `prompt/system.md`, keep them as written)

Geography is a path, not a postcard; what is revealed later is not seen earlier; screen direction (cross the frame in
the planned direction, never walk into depth); carry one landmark across a move; same size, different moment,
different picture (camera height follows the eyes); camera and body agree (the body faces the task, only the head
turns; never a frontal face with eyes aside, never a chest to the lens while the hands work beside); close-ups do
not look into the lens (three-quarter, eyes toward what is watched); same setup, same side (name the landmark's side;
close-ups keep the master's side); who is speaking; inserts at their size, lettering never spelled; look and reference
pictures win conflicts, reported; a person inside a photograph or screen stays a real photograph; safe depiction.

### 3.5 First frame from a board panel

- `first_frames` gains `board_id` (the approved board it was painted from) next to `draft_id`; a final has one or the
  other (check constraint).
- **An approved board is REQUIRED (D3).** A first frame of a painted shot can only be made from the scene's approved,
  current board panel. Without one, the API refuses the frame request with a plain reason ("Approve the scene board
  first") and the interface shows "Paint scene board" instead of the frame buttons; the scene batch action
  "Generate frames for all shots" needs it too. A shot whose panel is out of date cannot get a new frame until its
  panel is repainted and the board approved again. Black plates are unaffected (made by code). Frames painted before
  this feature stay as they are. Today's draft-to-final path (`draft_id`) is no longer offered for new frames.
- **Pictures, in order** (`frame_render.engine.pipeline` `references()` + the board panel): the face sheet of each
  person the camera SEES (someone only heard is never attached, existing rule) → their look sheets (clothes only) →
  the place plate → **only the props this shot's plan names** (opening picture / subjects / beats; the lab attached
  every prop and the frame painted a loose phone and key, run_016) → the panel, labelled `DRAFT_LABEL` ("the approved
  draft of this frame").
- **Prompt additions** (`contracts/frame_brief.py`, lab `frame.py`): the existing draft paragraph; the mannequin
  paragraph ("The approved draft shows every person as a coloured, faceless mannequin: Nimal is the red mannequin;
  Aruni is the blue mannequin. Replace each mannequin with that real person, keeping exactly its place, size, pose,
  hand positions and head direction; face ONLY from the face sheet, clothes ONLY from the look sheet; none of the
  mannequin's colour remains … Nobody looks into the lens unless this shot says so"); **the state** ("Each person at
  the opening of this shot, as planned: <the plan's `ir.first_frame.subjects` + the writer's panel `state`> Keep each
  body exactly as flat, bent or upright as its mannequin"). The scene-wide `scene_looks.condition` stays OUT (it holds
  the whole scene's action, plan/2026-11-13e §2). The writer's mannequin words are turned back into names
  (`unmannequin`); World sentences about the mannequin treatment are dropped.
- **Quality**: MEDIUM. **Only the shot's own panel is sent, never the whole board (D8)** (run_005: the whole board
  added little; it costs more and is one more picture to confuse).
- **Checks** (existing `inspect.vision_checks`) gain: "no mannequin or solid-colour figure in the frame", "the eyes /
  state match the plan".

### 3.6 Interface (hiru-ai-studio-interface)

- **Name**: the interface already calls the strip of accepted first frames "Storyboard"
  (`features/production/components/storyboard.tsx`, `features/workspace/components/storyboard-dialog.tsx`). The new
  thing is the **Scene board** (D1).
- **Scene production page** (`production-workspace.tsx`, `scene-batch-actions.tsx`): a "Scene board" card: "Paint
  scene board" (job, polled through the one shared status poll `useOnActivity`), the numbered sheet through `<Media>`
  with `thumbSrc`, the conflicts list, **Approve**, the out-of-date banner with "Repaint changed panels" / "Repaint
  whole board", and per panel (click a cell): note, lock, open the shot. Query keys in `src/lib/query/keys.ts`;
  writes put the returned board into the cache, never `router.refresh()`.
- **Shot first-frame panel** (`first-frame-panel.tsx`): "Paint first frame" paints from the board panel and shows the
  panel beside the result. With no approved, current board the panel says why and links to the Scene board card
  (D3); the old draft buttons are removed for new frames.
- **Canon character page**: the face sheet next to the look sheets, "Make face sheet".
- **No costs** anywhere in this UI (interface `CLAUDE.md`).

### 3.7 Costs (for the person, never the UI)

Per scene: board $0.15-0.18 (writer + LOW); per new character: face sheet $0.06; per shot: first frame $0.13-0.19.
A 10-shot scene with 2 new characters ≈ $0.15 + $0.12 + 10 × $0.15 ≈ **$1.80**, about the same as painting ten frames
today with drafts, but consistent.

### 3.8 Data (schema v25: `Database/upgrade_v24_to_v25.sql`, `schema_v25.sql`, a `supabase/migrations` file)

```
scene_boards (
  id uuid pk, production_id fk, scene_id fk, version int, part int default 1, parts int default 1,
  status text check in ('queued','running','done','failed','refused'), job_id fk jobs,
  quality text check in ('low','medium'), storage_path text, sheet_path text,
  writer jsonb   -- {world, geography, panels:[{shot_id, number, zone, camera, background, picture,
                 --   people:[{name, state}]}], conflicts:[...]}
  colours jsonb  -- {entity_id: "red", ...}
  cells jsonb    -- [{shot_id, number, box:[x0,y0,x1,y1], path, pins, locked bool, note text}]
  prompt text, checks jsonb, error text,
  approved_at, approved_by, created_by, created_at, updated_at
)
unique (scene_id, version, part); one approved board per (scene_id, part).
first_frames.board_id uuid references scene_boards(id) on delete set null
  + check (draft_id is null or board_id is null)
```
RLS as `first_frames` (production members read; editors write through the API only).

## 4. Phases

**Phase 0 (paid, the person's yes; ~$0.25)**: (a) mask repaint: on the lab's run_014 board, repaint panel 1 with a
mask at LOW, check the other 8 panels are unchanged; (b) one MEDIUM frame of scene 01 shot 2 (wide, both people) with
props attached per shot only (lab `frame.py` gains that filter first). Record both in `IMPLEMENTED.md`.

**Phase 1 (offline): contracts.** `contracts/board.py`: the panel/writer schema, colours, `board_prompt`, `BODIES`,
mannequin lines, `crop_panels`/`_gutters`, `scene_sheet`, pins per cell, `stale_cells(board, shots)`, split into
parts. `contracts/frame_brief.py`: face-sheet label + job, look job when a face sheet is attached, mannequin
paragraph, the state line, props-per-shot selection, `unmannequin`. `contracts/canon.py`: `face_sheet_prompt`. Unit
tests for each, including: a black plate is never a panel; 17 shots → 2 parts with an overlap panel; a locked cell is
never in a repaint; `blocking()` on the board prompt; the face sheet goes first; an unseen (heard) person never gets a
face sheet.

**Phase 2 (offline): face sheets.** `reference_kind="face"` in the frame_render reference path, the portrait crop,
`kind:"face"` stored in `reference_assets`, the API endpoint (`POST .../canon/{entity_id}/face-sheet`), the vision
check. Today's frame path attaches face sheets first (§3.1). Tests with the fake image adapter.

**Phase 3 (offline): the board.** Schema v25 (file only; the person applies it). Agent `board_writer` (prompt =
`lab/storyboard/prompt/system.md` moved under the agent, plus the mannequin note; recorded-answer test from the lab's
run_014 `writer_output.json`). A `scene_board` job in the frame_render service (writer → prompt → `blocking()` →
image LOW → crop → sheet → store). API: paint, get, approve, note, lock, repaint (`cells` list or whole). Stale
detection from pins.

**Phase 4 (offline): first frame from the board.** `first_frames.board_id`; the pipeline attaches the panel as the
draft and adds the mannequin paragraph and the state; props per shot; vision checks for leftover mannequins and the
planned state.

**Phase 5 (offline): interface.** §3.6, with tests like `first-frame-panel.test.tsx`.

**Phase 6 (offline): docs.** `docs/` page for the Scene board (how it works, what it costs, its rules); the lab
README points at the product.

**Phase 7 (paid, the person's yes; ~$1.20)**: after the person applies v25: face sheets for Aruni, Nimal, Dinu
(MEDIUM, $0.18); boards for scenes 01 and 02 ($0.35); frames for 4 shots (01 shot 2 and 4, 02 shot 1 and 7, ~$0.65).
Compare with the lab's runs; the person reads the result.

## 5. Decisions (the person, 2026-11-14)

- **D1 Name: "Scene board".** The existing "Storyboard" strip of accepted frames keeps its name.
- **D2 Board quality: LOW by default, MEDIUM as a setting, never HIGH.**
- **D3 An approved board is REQUIRED before first frames** (§3.5): no frame of a painted shot without the scene's
  approved, current board panel.
- **D4 Face sheets are made automatically** for on-screen people who lack one, when a board or frame is painted.
- **D5 Split: up to 16 shots on one board; above that, parts of up to 12 with one overlap panel.**
- **D6 Hair: from the look when the look sets hair** (the look's `hair` field is not empty), else from the face sheet.
- **D7 Repaint changed panels: method A**, a masked edit of only those cells. Phase 0 proves it; if it fails, ask.
- **D8 Each first frame gets only its own panel**, never the whole board.

## 6. Known data faults the board will surface (not fixed by this plan)

From plan/2026-11-13e §2 and every writer's `conflicts`: the clip IR's wardrobe vs the look sheet (Aruni's trouser
pocket vs a nurse dress); a prop colour that differs between a look sheet and a prop sheet (white vs navy bag);
`scenes.coverage.axis` cut at exactly 300 characters on save; `scene_looks.condition` holding the whole scene's action;
shot size labels that disagree with the camera text (MS vs MWS); shots that place a prop on different sides. The board
shows them as conflicts; fixing them upstream is separate work.
