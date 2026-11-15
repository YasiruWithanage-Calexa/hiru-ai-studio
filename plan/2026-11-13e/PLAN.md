# One board per scene: a storyboard that keeps a scene consistent (plan/2026-11-13e)

Revision 1 (2026-11-13). Status: **research done, lab built, ONE paid run done (run_001, $0.39 of a $1.00 cap)**.
Nothing under `src/` is changed and nothing is written to the database. This file is everything a new chat needs to
continue from where the first chat stopped: the problem, its cause in code and data, the research, the person's idea,
the lab, the first result, and what is waiting for the person's decision. Read it whole before doing anything.

## 0. Rules for the chat that continues this (read first)

- **Repo**: `C:\Users\witha\Documents\projects\Hiru TV\source\hiru-ai-studio` (Python 3.12: always
  `.venv/Scripts/python.exe`). The interface is `...\hiru-ai-studio-interface` (Next.js, port 3030). Read `CLAUDE.md`.
- **LAB ONLY.** All work lives in `lab/storyboard/`. Do not change `src/`, the database schema or the interface unless the
  person explicitly moves the work out of the lab. No database writes: `fetch.py` sends GET requests only.
- **Money**: the lab's OpenAI budget is **$1.00 in total** (`LAB_BUDGET_USD` in `lab/storyboard/run.py`). Booked so far:
  **$0.3948**. Left: **$0.6052**. Image tokens are booked at $10 / $40 per 1M on purpose (the repo's seed for
  `gpt-image-2` is a provisional $8 / $30), so the ledger over-states.
- **One image per run.** Before EVERY new paid run: show the person the previous run's details (board, writer output,
  cost, what worked, what failed) and **get their yes**. Only run_001 was allowed without asking; it is done.
- **OpenAI only** for text and images (CLAUDE.md "Fixed decisions").
- **Safe depiction** (CLAUDE.md, `contracts/safe_depiction.py`): no "dead/corpse/blood/kill…" in a provider prompt; the
  writer's prompt carries `PROMPT_LINE`; `run.py` scans the board prompt with `blocking()` and stops before the image call.
- **Prompt hygiene**: fix a failure with a principle plus examples from OTHER stories, never by pasting this scene's
  words into `prompt/system.md` (the principle examples there already follow this).
- Talk to the person in plain language; they think as a director. Commit only when asked.

## 1. The problem the person reported

Scene 1 (`29a9bd1c-3917-4af6-a02f-09c660a24bc8`, production `7aa4572a-f806-4ff5-bfe4-b79c7c93db75`, episode
`29cbda3a-27e3-4167-80a4-a8edb1bcc481`), "SCENE 01 - EXT. MAHAWEWA CANAL - DAWN - 1 MINUTE". Shot 1 (`a7cd886f-…`):
Aruni walks along a paddy path. Shot 2 (`a25598ed-…`): she finds Nimal lying still at the canal gate. Both first frames
came out with THE SAME background: the canal plate's view. A walk must feel like moving through one connected place
and arriving somewhere else.

## 2. Cause (verified in code and in the data)

**In code** (`src/libs/contracts/frame_brief.py`):
- `plan_references` (l.308) gives every shot of a scene the scene's ONE location (`scenes.location_id`) and its one plate.
- `references_block` (l.359) tells the image model: *"Match them exactly … the same place."*; `reference_job` (l.245)
  says the plate gives *"the place and its fixtures"*. Right for a one-room scene, wrong for a scene that travels.
- `contracts/canon_refine.py` l.45-47: place classes `set | vehicle | region | spot | unseen`; only `set`/`vehicle` are
  ever painted (`PLATED`). **A spot is never painted.**

**In the data** (read 2026-11-13):
- The breakdown already knows there are two places: canon `L04 paddy field` and `L05 canal gate`, both `class=spot`,
  `parent=L03 Mahawewa Canal` (a `set`, parent region `L02 Mahawewa village`). Their cards have look text
  (paddy: "low, waterlogged paddy plot … earthen bunds"; gate: "small rust-brown steel sluice gate in a stained concrete
  throat, vertical lifting spindle"). Neither has a plate.
- `scenes.staging.marks`: Aruni in zone `paddy field` at block 0; Nimal at `canal gate` from block 1. Shot 1's editor
  note: *"the gate lies ahead off right"*. None of this reaches the frame step.
- The L03 plate (`references` bucket, `…/4928a33b-…/2872d203-…-6ed74414.png`) is ONE one-point-perspective view down the
  canal: path + paddy left, the sluice gate right. Shot 1's accepted frame is that plate with Aruni added; shot 2's is the
  same view closer with Nimal added. **Shot 1 therefore shows the empty gate** before shot 2 reveals the body there.
- The plate also overrules the planned camera: Raphael planned shot 1 as *"crossing left to right … facing screen
  right"*; the frame shows her from behind (frame prompt even says "back-facing"); the video prompt still says
  "crossing left to right" three times over a back-facing first frame.

**Other faults found in the same two shots** (not the background, still real):
- `scene_looks.condition` is the WHOLE scene's action ("…kneels beside the canal gate and touches Nimal's hand") and is
  injected into every shot's frame prompt as "in this scene". Shot 2 came out kneeling instead of standing; the check
  flagged it ("Differs · Aruni is kneeling rather than upright") and that frame was still accepted.
- Two wardrobes: look sheet = white nurse uniform (what the frames show); the clip IR / video prompt = "rust cotton
  tunic and dark brown trousers", "phone in right trouser pocket". Shot 5's plan: "sand-coloured cuff" vs Nimal's rust
  shirt. Aruni's look sheet shows a WHITE bag; the medical-bag prop sheet says NAVY.
- `scenes.coverage.axis` is stored **cut at exactly 300 characters** ("…Keep cameras on this bank side. The bag st").
  Something truncates it on save (Raphael's write path). Not investigated further.
- `scenes.raphael`: `stage1 = "stopped"` ("A call to the model failed before Raphael finished"), `stage2 = "skipped"`,
  yet 11 clips were saved. Staging marks have no `facing` / `frame_side`.
- Shot 2's video render (`video_renders 50034721-…`, omni_flash) failed: "Google refused the request (400)". Cause not
  read (the function log was not checked).

## 3. Research (how others solve location continuity across moving shots)

- **Film craft**: a walk is often cut from different real places; the audience accepts it when light direction, time,
  screen direction (direction of travel, which side the water is on) and recurring materials/landmarks carry over. The
  usual link from walking to finding is an eyeline cut (she looks off; cut to what she sees).
  [Ron Dexter, cheating locations](https://rondexter.com/professional/pre-pro/cheating_locations.htm),
  [Videomaker, faking locations](https://www.videomaker.com/article/f12/18082-faking-locations-how-to-make-your-small-town-look-like-nyc).
- **AI practice**: a "location bible": one hero image plus multi-angle variants made FROM it, each fed to the shots it
  fits ([Oakgen](https://oakgen.ai/blog/ai-world-building-persistent-environments),
  [Atlabs, Nano Banana Pro angles](https://www.atlabs.ai/blog/master-cinematic-ai-video-how-to-control-camera-angles-consistency-with-nano-banana-pro)).
  Chain clips by last frame → next first frame, or first+last frame interpolation; big layout jumps warp
  ([Magic Hour](https://magichour.ai/blog/how-to-keep-characters-consistent-in-ai-video),
  [WaveSpeed](https://wavespeed.ai/blog/ai-guides/keep-the-same-character-across-ai-video-shots/),
  [Eachlabs Veo 3.1 first/last frame](https://www.eachlabs.ai/blog/veo-3-1-first-and-last-frame-guide)).
- **Storyboard-grid workflow (the person's idea, already in use by creators)**: generate a 3x3 storyboard of the
  sequence in one image, then re-render each panel full size and animate it
  ([RandomAI digest](https://recapio.com/digest/how-to-turn-one-image-into-a-cinematic-ai-movie-with-nano-banana-pro-by-randomai),
  [Budget Pixel](https://budgetpixel.com/blog/why-long-ai-videos-failand-how-nano-banana-pro-keeps-them-consistent),
  [AI for Real Life](https://ai-for-real-life.beehiiv.com/p/the-power-couple-of-ai-storytelling-how-nano-banana-pro-and-kling-just-leveled-up-my-workflow)).
  They recommend sending the whole grid back and asking for "panel N" rather than only cropping.
- **Research**: [CANVAS](https://arxiv.org/html/2604.13452): one stored background per location, per-shot choice of
  (previous frame | stored location picture | none, first appearance); removing location grouping / background reuse
  roughly halved background consistency (model-extracted numbers: ST-Bench background 4.94/4.73 → 2.45/3.34 without
  grouping, 2.12/2.44 without reuse). Discrete locations only, no gradual routes.
  [InfinityStory](https://arxiv.org/pdf/2603.03646): reusable people-free location library + transition shots (PDF too
  large to read; abstract only). [StoryMem](https://the-decoder.com/bytedances-storymem-gives-ai-video-models-a-memory-so-characters-stop-shapeshifting-between-scenes/),
  [VideoMemory](https://arxiv.org/html/2601.03655v1): key-frame memory per entity incl. environments.
  [Map2Video](https://arxiv.org/pdf/2512.17883): real street panoramas as spatial anchors.
- **Heavy option**: [World Labs Marble](https://www.worldlabs.ai/case-studies/magnific): a generated 3D set you move a
  camera through; static (no people), better for a recurring main location than one walk.
- Precedent in the person's other product (PromptMotion "Reconstruction"): one storyboard board for a whole build kept
  hands/object/light identical because the panels ARE one image; long pieces chain boards by sharing an overlap frame.

**Options for Hiru discussed before the idea** (cheapest first): (1) on a travelling shot the plate gives materials and
light, not layout; (2) pass the previous shot's accepted frame as a continuity reference (generalise `setup_frame`
beyond one setup); (3) paint spot plates from the parent plate (same light, new camera position) and choose the plate
per shot by staging zone; (4) hold screen direction and the water's side of frame (the staging map can check it);
(5) video: end shot 1 looking toward where shot 2 opens, or first+last frame, or an eyeline cut.

## 4. The person's idea, and the agreed view of it

**Idea**: paint ONE storyboard image holding every shot's opening picture as a panel (consistency comes free because it
is one generation), let a person approve it, then make each shot's real first frame from its panel (the panel as the
draft / composition guide).

**Agreed view**: it works, and it is a known workflow. It fixes people/clothes/light consistency for free; it fixes the
BACKGROUND only if each panel is given its own camera position (else the board repeats the plate nine times). Hiru
already has the second half: a final frame is painted from an "approved draft" (`frame_brief.references_block`:
*"keep its composition, framing, pose… paint it again as the finished frame… The sheets still decide faces, hair and the
place"*), so a panel can BE that draft.

Risks to keep in view: past ~6-9 panels boards miscount/bleed (split a long scene into boards per sequence, chained by
an overlap panel); panels are small (~480x270 for 9 on 1536x1024), so a panel steers composition/light only and the
sheets still decide faces, and a crop is NEVER sent straight to the video model; editing one shot repaints the others
(lock accepted panels, inpaint one cell, version the board, pins per final frame); inserts lose lettering on a board;
upstream data faults (section 2) get copied into every panel at once.

Open decisions for the person (not yet asked formally): board per scene or per sequence; must shots only or all; a
person approves the board before finals; final frame gets the crop, the whole board labelled "panel N", or both
(recommended: both); which image tier.

## 5. What is built (`lab/storyboard/`)

| File | What it does |
|---|---|
| `fetch.py` | Read-only. `--scene <id> --name scene1` → `input/scene1/bundle.json` + `input/scene1/refs/*.png`. Scene (heading, script, mood, `coverage.axis`, staging marks), shot PLANS (number, slate, role, size, duration, script lines, intent story/purpose, on_screen names, ir.setting, ir.first_frame composition + subjects, ir.subjects action/position, cinematography, lighting, beat actions), people (appearance from the canon card + this scene's look: outfit, hair, accessories, condition), the place + its spots' look text, props named in the shots, reference pictures (look sheets from `canon_looks.sheet_assets`, the set's plate and prop sheets from `canon_versions.reference_assets`). Black-plate shots are left out with `contracts.frame_brief.black_plate`. |
| `prompt/system.md` | The writer's instructions: one panel per shot = that shot's OPENING picture; "geography is a path, not a postcard" (camera position per panel from zones/spots/axis; different zones = different backgrounds, connected by the same ground/water/plants/weather/light); "what is revealed later is not seen earlier"; screen direction; the plate is ONE view, not every panel's; inserts described at their size, lettering never spelled; look + reference pictures win conflicts, reported in `conflicts`; no drawn text; `PROMPT_LINE` safe depiction. |
| `run.py` | `dry` = request + worst case, no call. `paid --hypothesis "…"` = (1) writer `gpt-6.1-sol`, effort high, `max_output_tokens` 16000, Responses API JSON schema `{world, geography, panels[{shot, zone, camera, background, picture}], conflicts}`, reference pictures attached at `detail: low`; (2) code builds the board prompt (sheet header, grid cols x rows read left→right top→bottom, 16:9 panels, thin white gutters; references cited in attach order with each one's job; the plate's job = "the kind of place … ONE view … do not repeat this view in every panel"; World; Geography; `PANEL i (row r, column c) — camera. Background: … picture`; no text); (3) `blocking()` scan; (4) `gpt-image-2` `images.edit`, quality high, 1536x1024, all references attached in order; (5) panels cropped by an even grid into `panels/`. Ledger guard before the run with worst cases. |
| `README.md` | How to run; file table; run list. |
| `runs/ledger.csv` | Every paid call. |
| `runs/run_001/` | `writer_input.txt`, `writer_output.json`, `board_prompt.txt`, `board.png`, `panels/panel_01..09.png`, `summary.json`. |

Commands (from the repo root, PowerShell or Git Bash; set `PYTHONIOENCODING=utf-8` for the console):
```
.venv/Scripts/python.exe lab/storyboard/fetch.py --scene 29a9bd1c-3917-4af6-a02f-09c660a24bc8 --name scene1
.venv/Scripts/python.exe lab/storyboard/run.py dry  --input scene1
.venv/Scripts/python.exe lab/storyboard/run.py paid --input scene1 --hypothesis "…"   # the person's yes first
```

Inputs of scene 1 (from `bundle.json`): 9 panels (shots 1-9; 10 = cut to black, 11 = title, left out). References in
order: 1 look sheet Nimal, 2 look sheet Aruni, 3 location plate Mahawewa Canal, 4 phone sheet, 5 C-17 (key) sheet,
6 medical bag sheet.

## 6. run_001 (2026-11-13) — the first result

Hypothesis: "one board from the shot plans keeps people/light consistent, and per-panel camera positions by zone keep
the walk and the gate as different but connected backgrounds."

Cost: writer 8,436 in / 4,341 out (1,931 reasoning), 118 s, $0.0603; image 11,498 in (9,216 image + 2,282 text) / 5,488
out, 90 s, $0.3345 (at the lab's over-stated rate). Run $0.3948.

What the writer decided: geography = one muddy bank from the paddy approach (screen left) to an apron beside the sluice
(screen right), all cameras on the landward bank; panel 1 = paddy path, "gate apron and Nimal remain beyond the right
crop"; panels 2 and 9 = same outer-apron setup; 3 = standing CU; 4 = low two-shot with a gate bar hiding the fist; 5 =
fist + key insert (marking as texture only); 6 and 8 = matching kneeling CUs; 7 = phone insert; 9 = kneeling wide with
phone.

**Read of the board** (`runs/run_001/board.png`):
- WORKED: people consistent in all 9 (Aruni's face, bun, white uniform, navy bag; Nimal's rust shirt, pose); rain, dawn
  light and grade identical; **panel 1 shows the paddy path with NO gate** (reveal protected) and **panel 2 is a
  different, angled view of the gate**, connected by the same mud, grass, water and rain; neither copies the plate's
  down-the-canal view; panel 9 returns to panel 2's setup; 6 and 8 match; clean even gutters, no drawn text.
- WEAK: panel 1 shows her walking AWAY into depth, not crossing left to right as planned (the writer chose "rear
  three-quarter"); the canal water is not visible in panel 1, so the link rests on weather and ground; the standing CU
  (3) and kneeling CUs (6, 8) look nearly the same; the key shows no C-17 and the phone shows icons only (by design).
- The writer's `conflicts` found the real data faults of section 2: trouser pocket vs dress, sand cuff vs rust shirt,
  white bag (look sheet) vs navy (prop), the axis text ending mid-sentence, and shot 6's spoken line with no words.
  The last one is a **lab gap**: the line exists in `dialogue_lines` (`dd9fbeec-…`, Aruni: "Dinu... oyata meka ahenne
  nadda?", shot `d18f36a7-…`) and `fetch.py` does not read `dialogue_lines` yet.

## 6b. run_002 (2026-11-13) — option B

Changes: `fetch.py` reads `dialogue_lines` (each plan shot carries `spoken`: speaker, text, delivery); `prompt/system.md`
gained four principles with examples from other stories (cross the frame in the planned direction, never into depth;
carry one landmark across a move on the same side of frame; camera height follows the eyes; who is speaking). Guard
caps from run_001's measurements: `WRITER_MAX_OUT` 10000, `IMAGE_WORST_OUT` 6500 (worst case $0.56).

Cost: writer 9,070 in / 4,556 out (2,070 reasoning), 180 s, $0.0637; image 11,584 in / 5,488 out, 129 s, $0.3354.
Run $0.3991. **Ledger $0.7938 of $1.00; $0.2062 left.**

Read of the board (`runs/run_002/board.png`):
- BETTER: panel 1 now shows the canal water and grass bund beside the paddy path, so the walk and the gate share a
  landmark; the gate is still out of panel 1 (reveal kept); panels 2 and 9 still match; panel 6 has parted lips for
  Aruni's line; the writer's `conflicts` listed the same data faults plus "shot 6 asks closed lips but has a line".
- NOT FIXED: panel 1 still shows Aruni mostly from behind walking into depth. The WRITER compromised ("rear
  three-quarter side view of her left-to-right travel") despite the rule, and the image leaned further to the back
  view. The landmark side flipped: the writer put the water at frame LEFT in both panels; the image put it at RIGHT in
  panel 1 and LEFT in panel 2, the very screen-direction break the rule was meant to stop.
- PARTLY: close-ups 3 vs 6/8 differ only slightly (6/8 have more gate concrete behind, a touch lower); they still read
  as similar faces in similar frames.
- NEW FAULT: Nimal's mouth is wide open in panel 2 and his eyes look half open in panel 4, against "lies still, eyes
  closed" (the writer's text said closed; the image drifted).

Lesson: a principle in the writer's prompt is not enough for camera direction; the writer softens it and the image model
drifts further. If continued, the next levers are a code check on the writer's output (planned direction vs `camera`;
landmark side named the same in consecutive panels) and a stronger board-prompt line per panel ("seen from the side,
moving toward screen right; the water is on the LEFT of this panel"). C (one full frame from a panel) does not fit the
$0.21 left at the current guard; it needs the person to raise `LAB_BUDGET_USD`.

## 6c. run_003 (2026-11-14) — numbered sheet of every shot, low quality

The person's asks: number the shots for identification; put every shot of the scene on the board, not only the painted
nine; test at low quality to stay inside the budget. Built: `all_shots` in the bundle; `run.py --quality`,
`image --from run_002` (no writer call), gutter-aware crops, `scene_sheet()` → `sheet.png` (every shot in order with a
red "SHOT N" tag drawn by code; cut-to-black / title shots as black cells carrying their script line),
`shots/shot_NN.png`, `sheet.json` (shot, slate, panel, kind, file). The image model still draws no text.

Cost: image 11,584 in / **158** out, 69 s, $0.1222 (at the lab's over-stated $10 input rate; ~$0.09 at the seed). Low
quality removes almost all output cost; the reference pictures' input is now ~95 % of the price, so fewer or smaller
references is the next lever. Ledger $0.9160; $0.0840 left.

Read: all 11 shots identifiable in order. Low quality is enough for a storyboard: faces, uniform, navy bag, rust shirt,
gate, rain and grade hold. By chance panel 1 came out side-on, walking screen right, with the canal at frame right
(the direction the plan wanted); panel 2 has the water at left/behind, so the side still flips. Shot 4 cuts off Aruni's
head and shows Nimal's eyes open; shot 5's key is unclear. Same writer text as run_002, so the differences are the
image model's own variation at low quality.

## 6d. run_004 (2026-11-14) — scene 02, all 16 shots, medium quality, one full run

Scene `8f7f085e-4eef-447b-9f64-8e5f7d2b00c2` "SCENE 02 - INT. CASH VAN - COLOMBO - NIGHT". 16 shots, all painted (4x4
grid, panels ~384x256); references: Dinu's look sheet, the Cash Van plate, the phone sheet. `LAB_BUDGET_USD` raised
1.00 → 1.30 on the person's go-ahead.

Cost: writer 9,932 in (1,592 cached) / 5,360 out (2,439 reasoning), 145 s, $0.0704; image 7,341 in (4,608 image) /
1,372 out, 49 s, $0.1283 at the lab's over-stated rate. Run $0.1987. Ledger $1.1147 of $1.30.

Read (`runs/run_004/sheet.png`):
- WORKED: Dinu identical in all 16 (face, navy shirt, red thread on the left wrist); right-hand drive; one cabin seen
  from one passenger-side axis throughout; the photograph and phone keep fixed places on the dashboard (phone left of
  the photo) in every panel that shows them; rain-on-glass night light identical; shot 15's windscreen shows the
  industrial area he steers toward. The two spoken lines are off-screen voices (Aruni's voice message, the Mudalali on
  the phone), so Dinu's closed lips are correct. 16 panels in one picture still came out cleanly separated.
- WEAK: the five close-ups (3, 7, 9, 12, 16) and the masters (1, 5, 11) are near copies; the plan repeats the same
  setups on purpose, but the change in Dinu's state shows only as small expression changes. Panels are small at 16.
- Writer `conflicts`: shot 6 vs 4 disagree on which side of the phone the photo sits (board kept shot 4's); shot 10
  asks a readable caller name (no-text rule wins); shots 1 and 15 labelled MS but described as MWS.
- Medium is cheap here because the scene has 3 references (half the image input of scene 1).

## 6e. run_005 (2026-11-14) — first frame painted from its panel (scene 02, shot 7)

Agreed with the person: a board goes "out of date" when shots change (repaint whole / repaint only changed panels with a
mask / lock approved panels / a note per panel) instead of repainting itself. For frames: the code-cut panel is the
"approved draft" (layout), the whole board is a second picture (continuity), the look sheet keeps the face.

`frame.py`: the product's `references_block` wording unchanged; labels = look/place/prop sheets + `DRAFT_LABEL` (+ "the
storyboard of this scene" with "this frame is the panel in row r, column c … paint ONE frame, never a grid"); the
board World paragraph minus its sentences about panels/grid (a preview showed it began "One painted storyboard image
with sixteen panels", which invites a grid); then the panel's camera / background / picture text. High, 1536x1024.

Cost: `panel` 5,565 in / 5,488 out, 101 s, $0.2752; `board` 7,195 in / 5,488 out, 86 s, $0.2915. Ledger $1.6814.

Read (`runs/run_005/shot07_panel.png`, `shot07_board.png`, against `runs/run_004/shots/shot_07.png`):
- WORKED (both): the frame IS the panel made final: near-frontal close-up, wet driver's window with orange rain bokeh
  at right, dark cabin and seat at left, navy shirt, closed lips, eyes toward screen left, same grade. One clean frame,
  no grid, no text. The method works.
- BOARD vs PANEL ONLY: almost no difference on a close-up (the board version is a touch darker and tighter, nearer the
  panel's mood); +$0.016. A close-up has little place in it; a wide (shot 1/11/15) is the real test of the board.
- FACE DRIFT (important): both frames show the board's Dinu (older, heavier, deeper-lined), not the look sheet's (younger,
  slimmer face, wavier hair). The draft beat the sheet on identity despite "the sheets still decide faces". The board
  already drifted his face; the frame inherits it. Levers: a stronger line ("the draft decides layout, pose and light
  only; the face comes ONLY from image 1"), sending a smaller/softer panel so it carries no facial detail, or putting
  the look sheet's face crop first.

## 6f. Why the board changes faces, and the face sheet (run_006, run_007, 2026-11-14)

Cause, checked: (1) NOT `input_fidelity`: `gpt-image-2` rejects it ("does not support the 'input_fidelity'
parameter", 400, nothing charged); the product's frame step does not set it either. (2) Every look sheet AND character
sheet in this production holds ONE face: front-on, smiling, studio light; the four body views are headless. A shot
asks for the person serious, turned three-quarter or in profile, at night, so the model invents that face and drifts
(older, heavier, more weathered: its idea of the role). (3) The writer's face words ("angular features", "stubble")
add to it. (4) Small panels (16 per board) make small faces.

Fix tested: a FACE SHEET per person: `faces.py` cuts the look sheet's portrait and paints 6 head-and-shoulders views
(front neutral, two three-quarters, two profiles, front serious) on grey, "do not age him". The board then gets the face
sheet FIRST with the job "the face comes ONLY from this sheet"; the look sheet's job becomes "clothes, shoes and
accessories, not the face"; World sentences describing that person's face are removed; a "Faces:" line says not to age
or weather them for the mood.

run_006 face sheet: 663 in / 5,488 out, $0.2261. Same man as the portrait at every angle; flaw: both three-quarter
views turn the same way. run_007 board (run_004's panels, rebuilt prompt, medium): 8,946 in / 1,372 out, $0.1443.

Read (`runs/run_007/sheet.png` vs `runs/run_004/sheet.png`): Dinu now matches his portrait in all 16 panels (younger,
slimmer face, wavy hair) instead of run_004's older, heavier man; the close-ups also vary their angle more (they copy
the face sheet's three-quarter views). Cabin, props, light and layout are as good as run_004. **The face sheet fixes
the face drift at its cause.** Cost per person: one face sheet (~$0.23 at high), made once and reused by every board
and frame. Product consequence (the person's decision): make a face sheet for each main character next to its
look/character sheet, and send it first in boards and first frames.

## 6g. Natural bodies (run_008, 2026-11-14) — LOW, image only

The person: in run_007 the way Dinu faces the camera and sits at the wheel is unnatural; fix it before going further,
medium/low images only, minimal budget. Read of run_007: in the cabin masters (1, 5, 8, 11, 13-15) his chest and
shoulders face the lens like a portrait while the wheel sits off to his left, so he reaches across to it (beside the
wheel, not behind it); in the close-ups (3, 7, 9) the face points at the lens while the eyes roll hard to the side.

Change: a general `BODIES` line in every board prompt (body faces the task, only the head turns; at a wheel: squarely
behind it, wheel centred before the chest, back on the seat, hands on the rim; a side camera sees the body side-on;
nobody faces the lens unless the panel says so; head and eyes turn together, a near-frontal face looks just past the
lens). run_008 = run_007 + that line, LOW: 9,095 in / 158 out, $0.0973. Ledger $2.1491 of $2.30.

Read: PARTLY fixed. Shots 1 and 2 now read as a real driver (arms forward to the wheel, body side-on); close-ups 12
and 16 turn the head with the eyes. Still wrong: 5, 11, 13, 14, 15 (chest to the lens, wheel at his left) and 3, 7, 9
(frontal face, eyes sideways). Cause: the WRITER's panel text asks for it ("near-frontal 85mm close-up … eyes on the
road just screen left"; masters "looking diagonally toward the driver"), and a specific panel line beats a general
rule. Fix written (not run): writer rule "CAMERA AND BODY AGREE" in `prompt/system.md`: choose the camera from the
body; side camera = profile / three-quarter with the eyeline across frame; frontal camera = through what the person
faces, eyes just past the lens; never frontal face + eyes aside, never chest to the lens with hands working beside;
each panel names where the chest faces and where the hands are. Next run = writer + LOW image (~$0.17); the cap has
$0.15 left.

## 6h. Mannequin board → real first frame (run_009, run_010, 2026-11-14)

The person's idea: the board's job is consistent places, props, camera and blocking, not faces; draw people as pose
markers (one colour per person, facing shown) and swap in the real person at the first-frame step. Chosen form:
faceless, matte, colour-coded artist's mannequins (not stick skeletons: an OpenAI image model draws mannequins with
real body volume, seat contact and hands on things; skeletons are made for ControlNet-style tools we do not use, and
their coloured lines risk leaking into a frame). A ridge on the head marks the face direction.

Built: `run.py --mannequins` (writer told to describe each person only by pose: where the body is, where the chest
faces, where the head turns, where each hand is; never face, expression, hair, skin or clothes; the board image gets
the place and prop sheets only, a "People:" line names each colour) and `frame.py --mannequins --faces Dinu
--quality medium` (the mannequin panel is the approved draft; "Dinu is the red mannequin. Replace each mannequin with
that real person, keeping exactly its place, size, pose, hands and head direction; face ONLY from the face sheet,
clothes ONLY from the look sheet; none of the mannequin's colour remains"; the writer's mannequin words are turned
back into names; World sentences about the mannequin treatment are dropped). The writer also had the new rule
CAMERA AND BODY AGREE.

run_009: writer 10,282 in / 6,154 out, $0.0821; LOW board 6,101 in / 158 out, $0.0673. Seated poses are natural: in
the masters (1, 5, 11, 15) the mannequin sits behind the wheel, arms forward to the rim; side views (2, 8, 13, 14)
side-on with hands on the wheel. Cabin, props and light consistent. Flaws: the close-ups (3, 7, 9, 12, 16) put the
head straight at the lens (the writer again chose "near-frontal … just past the lens", which a faceless head reads as
staring into camera); the dashboard photograph's people became mannequins too (a photo inside the scene should keep
real people: a later rule).

run_010: MEDIUM first frame of shot 1 from its mannequin panel: 7,198 in / 1,372 out, $0.1269. **Best frame of the
lab**: Dinu sits behind the wheel, side-on, both hands on the rim, eyes on the road; the face matches his face sheet
(young, slim, wavy hair), the navy shirt and red wrist thread match the look sheet; seat belt, cabin, rain, light and
layout match the panel; no red or mannequin left anywhere. Small: the phone sits right of the photograph (the writer
said left).

Result: the chain works at LOW board + MEDIUM frame, about $0.15 per scene board + ~$0.13 per frame: mannequin board
(place, props, camera, blocking) → person approves → face sheet + look sheet + mannequin panel → first frame.

## 6i. Close-up from a mannequin panel (run_011, 2026-11-14)

Shot 7 (CU, Dinu hears Aruni's voice message), MEDIUM, from run_009's mannequin panel + face sheet + look sheet:
7,181 in / 1,372 out, $0.1267. Ledger $2.5521 of $2.80 (cap raised 2.60 → 2.80 for it).

Read (`runs/run_011/shot07_panel.png`):
- WORKED: the face is the face sheet's Dinu even with the head filling the frame (young, slim, wavy hair, light
  stubble), navy shirt, seated in the van, rain on glass, night light; no red or mannequin left. Close-ups are safe.
- WRONG 1, eyeline: he looks straight INTO the lens. The mannequin head pointed at the lens (the writer's
  "near-frontal … just past the lens"), and a faceless head cannot show "just past"; the frame copies it. For drama a
  look into the lens is a different shot. Fix: the writer gives close-ups a three-quarter head with the eyes off the
  lens toward what the person looks at (the road); the frame prompt adds "never looks into the lens unless the panel
  says so".
- WRONG 2, screen direction: the rain-covered side window is at frame LEFT here; in shot 1's frame the driver's window
  is behind him at frame RIGHT. The board's close-ups (3, 7, 9, 12, 16) already had the glass at left, i.e. the board
  crossed the line between the master and its close-ups. Fix: the writer names, for every panel, which side the
  driver's window (or the equivalent fixed landmark) sits, kept the same as the master; a code check can compare the
  side named in consecutive panels of one setup.

## 6j. Scene 01 with two people (run_012-015, 2026-11-14)

Before the run: writer rules CLOSE-UPS DO NOT LOOK INTO THE LENS (three-quarter head, eyes off the lens toward what
the person watches) and SAME SETUP, SAME SIDE (every panel names the side of the fixed landmark; close-ups, inserts and
returns keep the master's side); frame line "Nobody looks into the lens unless this shot says so"; mannequin note:
a person inside a photograph/poster/screen stays a real photograph; `faces.py` made gender-neutral with `--quality`.
Cap 2.80 → 3.20.

- run_012 / run_013: face sheets for Aruni and Nimal at MEDIUM, $0.0616 each. Both the same person in all six views;
  the three-quarter views now turn opposite ways. Medium is enough for a face sheet.
- run_014: writer (9,674 in / 5,568 out, $0.0750) + LOW mannequin board (8,699 in / 158 out, $0.0933). Nimal red,
  Aruni blue, clearly told apart. Blocking holds in every panel: Aruni at left with the bag, Nimal lying at the gate at
  right, canal at left in 2, 4, 9. Close-ups 3, 6, 8 turn the head down toward screen right (no look into the lens);
  the standing close-up (3) and the kneeling ones (6, 8) now differ (canal and gate vs near ground). Shot 1: rear
  three-quarter walking right along the canal, gate not seen yet.
- run_015: MEDIUM frame of shot 4 (two-shot), 9 pictures in (2 face sheets, 2 look sheets, plate, 3 props, panel):
  13,833 in / 1,372 out, $0.1932. Colour mapping WORKS: blue became Aruni (her face, bun, white uniform, navy bag),
  red became Nimal (his face and moustache, rust shirt, dark trousers, sandals); place, rail in the foreground, canal
  and gate match the panel; no mannequin colour left.
  **STORY FAULT**: Nimal is propped on one elbow, eyes open, looking up at Aruni, alive and alert, where the panel and
  the plan have him lying flat and still with his eyes closed. Cause: the mannequin scheme forbids the writer to
  describe faces, so "eyes closed, lies still" (a CONDITION, not a look) was lost, and a faceless lying mannequin does
  not say "unconscious"; the frame model filled it in. Fix (not built): the writer gives each person a short
  `state` per panel (eyes open/closed, conscious or not, breathing hard, crying, asleep), never drawn on the board but
  carried into the frame prompt; the frame prompt also says "keep the body exactly as flat/upright as the mannequin".

## 6k. The state fix (run_016, 2026-11-14)

Shot 4's plan already holds the state: `ir.first_frame.subjects` = "Nimal lying entirely still with eyes closed …".
So no new field was needed for this test: in mannequin mode the frame prompt adds "Each person at the opening of this
shot, as planned: <the plan's opening picture> Keep each body exactly as flat, bent or upright as its mannequin, and
each person's eyes and state exactly as planned." (the scene-wide `scene_looks.condition` stays out: it holds the whole
scene's action, §2). run_016: same board and refs as run_015, MEDIUM, 13,902 in / 1,372 out, $0.1939.

Read (`runs/run_016/shot04_panel.png`): FIXED: Nimal lies flat on his back, still, eyes closed, head toward the gate;
Aruni upright at left looking down, bag in her left hand, right hand empty; faces, clothes, canal, gate and the
foreground rail all right. NEW FAULT: a phone and the key lie loose on the ground by his hand. The key belongs inside
his fist (masked by the bar) and the phone is Aruni's, first seen in shot 7. Cause: `frame.py` attaches EVERY prop
sheet of the scene to every frame, so the model places them. The product's frame step already picks references per
shot (`frame_brief.plan_references`); the lab must do the same: attach only the props the shot's plan names in its
opening picture / subjects, and say where an attached prop is (in a fist, in a pocket, not visible).

## 7. Next: waiting for the person's choice (ask with run_001's details first)

$0.6052 left. The current guard's worst case is $0.76 per full run (writer $0.18 + image $0.58), which would REFUSE a
second full run. Before running, lower `IMAGE_WORST_OUT` (10000) to a measured-safe value (run_001 used 5,488; e.g.
6,500) so the worst case is about $0.55, and say so to the person.

- **A. Repeat as-is, image only** (~$0.33): same `board_prompt.txt`, new image, to see whether run_001 was typical or
  lucky (judge a method by its worst run). Needs a small `run.py` mode that reuses a run's `board_prompt.txt` and skips
  the writer.
- **B. Fix and rerun** (~$0.40): add `dialogue_lines` to `fetch.py` (text, speaker, shot); push the writer to keep shot
  1 side-on with left-to-right travel and the canal water visible as the link; make standing vs kneeling CUs differ
  (camera height, background). Change the prompt by principle, not with this scene's words.
- **C. Test the second half of the idea** (~$0.25 per frame): paint ONE real full-size first frame (shot 1 or 2) from
  its panel, using Hiru's approved-draft wording, with the look sheets + plate + the crop + (optionally) the whole
  board labelled "the storyboard; this frame is panel N".

The recommendation made to the person: A first (cheapest; measures the floor), then C. Only one of these fits in the
remaining budget with margin if B is chosen; ask before each.

## 8. If the lab succeeds (not started; for later, the person decides)

The path into the product, kept here so it is not lost: a scene-level "board" artifact (image + per-panel map + pins),
painted by a system that reads the planner's shots, the staging zones and the spots; a person approves it; each shot's
first frame takes its panel as the approved draft (plus the board); a spot plate may be derived from the parent plate
for the zones (lifts the "spots are never painted" rule only for this use); fix the upstream data faults (scene-look
condition per shot, wardrobe conflict between IR and look, the 300-char axis cut) before boards copy them into every
panel. This needs its own plan revision.
