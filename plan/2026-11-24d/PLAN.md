# Fixed marks: a person who does not travel stays on one ground spot, held by a blocking plate (plan/2026-11-24d)

Revision 2 (2026-11-24). Phases 0 to 5 are BUILT offline (`IMPLEMENTED.md`); phase 6, the live check, is the person's. Built with two deviations, both said in `IMPLEMENTED.md`: no schema v31 (the plates live in the version's `writer`, §3.5), and `plate_prompt` is in `contracts/board.py`. Revision 1 was the design below. The person's rule, proven in `lab/fixed_marks` (7 boards and
two plates, $0.611 of $0.75, `FINDINGS.md`). It follows plan/2026-11-24 (location views), 24b (vehicles) and 24c
(place views by type), built and committed. Read this file whole, then `lab/fixed_marks/FINDINGS.md` and
`lab/fixed_marks/run.py` (the words to port: `MARKS`, `PLATE_WORDS`, `plate_prompt`), `docs/scene_board/README.md`,
`src/libs/contracts/board.py` (`board_shots`, `shot_context`, `marks_at`, `board_prompt`, `panel_prompt`, `Writer`),
`src/libs/contracts/stagemap.py` (`Mark`, `POSTURES`, `OFF`), `src/libs/contracts/bridges.py` (`move_block`),
`src/libs/hiru_ai/systems/frame_render/board.py` (the paint loop, `_mend`, `image_pictures`) and
`src/libs/hiru_ai/agents/board_writer/` (prompt and schema).

## 0. Rules for the chat that builds this

- **Port the lab exactly.** The "Ground marks" paragraph, the radius sentence, the plate words and the plate prompt
  are the lab's (`MARKS`, `PLATE_WORDS`, `plate_prompt` with `tall=True`), with the scene's names and spots filled in
  by code. List any change of words before making it.
- **Ask before every paid call**, each time. Tests run with `OPENAI__API_KEY=` blank and fakes only. Phase 0 is the
  only paid phase before the build; the live check (phase 6) is the person's.
- **No enable switches** (the person's way since plan/2026-11-24): the feature is on when the scene has a staging map.
- **Never stash or reset** the person's tree. **Never edit an applied migration.** Schema v31 is the person's to apply.
- **No new agent** (the Hiru AI pattern, rule 8): the board writer writes the spots; code finds the stretches, builds
  the words and paints the plates; the existing `board_inspector` checks a plate.
- Two repos: the backend (this one) and `..\hiru-ai-studio-interface` (its `CLAUDE.md` binds).

## 1. The person's rule

> If people do not walk, they stay in the same position for all the shots. Only when they walk, travel or otherwise
> change position does their position change. The position is the GROUND position: the spot in the place, the
> landmarks around it and the gap to the other person, not the side of the picture. Small steps keep the mark, within
> a small radius. (2026-11-24)

The radius is **0.5 m**: a turn of the head or body, a lean, a shift of weight or half a step stays inside it.

## 2. What is wrong today, and what the lab showed

The staging map's mark (`stagemap.Mark`) holds `zone` ("roadside") and `frame_side` / `facing` (relative to the
camera). Nothing says where on the ground a person stands, so every panel re-decides it and the image model fills it
in. On scene 4's board v18 part 1 the three-wheeler was behind Kasun in panels 1 and 3, became a counter with a flask
in 2, 4 and 5, and the gap between Kasun and Anudi changed, although nobody moves in shots 1-6. The prompt already said
"the vending bay left, the wall right" in every panel: the words about sides were there, the spot was not.

| run | adds | result |
|---|---|---|
| A_001, A_002 | ground marks in words | each sheet steady within itself, but the two runs chose DIFFERENT spots (beside the three-wheeler / against its hatch; 1.5 m / 1 m apart) |
| B_001 | words + a floor plan drawn by code | as A; the plan added nothing visible; no dot or ring painted |
| C_001, C_002 | words + a wide (16:9) blocking plate | both put the people where the plate does; C_002's grid BROKE (the board copied the plate's wide shape) |
| T_001 | words + a TALL (9:16) blocking plate | the grid holds; the plate's spots in all five panels; but the board took the plate's handbag-on-forearm, against "on her left shoulder" |

So: **words hold a mark within one picture; a picture holds it between pictures.** A board is painted in parts (scene
4: three), each its own picture, so only a plate keeps part 2's Kasun where part 1 put him. The plate must be painted
at the panels' shape and must itself be right, because the board copies more than the spots.

## 3. The design

### 3.1 Stretches (code, `contracts/marks.py`, new, pure)

A **stretch** is a run of the scene's blocks in which nobody moves. Code finds the boundaries from the staging map,
never a model:

- a **move** of person P at block b: P's mark at b has a different `zone` from P's mark before it, or `posture`
  `walking` or `running`, or the block is an implied step `bridge: "move:<P>"` (`bridges.move_block`);
- an **entrance or exit**: P's zone changes from or to `off` (the people on the plate change);
- a posture change alone (standing → sitting, kneeling) is NOT a move: it happens on the spot, inside the radius
  (D1).

A shot belongs to the stretch that holds its OPENING block (`block_start`): its panel and first frame show the shot's
first picture. A shot whose blocks contain a move starts on the old spot (its panel shows where the walk begins).
`stretches(staging, items, shots) -> list[Stretch]` with `Stretch(n, blocks, shot_ids, people)`; `people` = everyone
on the map in a zone other than `off` during it. A stretch with fewer than TWO painted shots showing people gets no
plate (one panel is its own truth); it still gets the ground-marks words.

A scene without a staging map (or one that is stale) has no stretches: the board is painted as today, and the board
view says so in `conflicts` ("No staging map: the people's spots are not held between shots"). Absent-safe.

### 3.2 Ground marks (the board writer, one more output)

The writer's bundle gains `stretches` (code's: `n`, the shot numbers, the people, and what ends it: "Anudi walks off
at shot 15"). Its schema gains:

```python
class GroundMark(BaseModel):
    stretch: int
    who: str
    spot: str  # on what ground, beside which landmark of the place's views (its layout and `empty`), on which side,
               # how far from it: "on the concrete pavement half a metre in from the kerb drain, one step to the
               # right of the rear of the food three-wheeler"
    apart: str = ""  # the gap to the next person on this stretch: "about 1.2 metres to Kasun's right"
class Output(BaseModel):
    ...
    marks: list[GroundMark]
```

A new rule in `prompts/system.md`, GROUND MARKS (the lab's words): each person stands on ONE spot per stretch; the
spot names the place's landmarks as the views sheet's `layout`, `empty` and views show them (lab fault 1: never as the
writer imagines them, the hatch was on the side of the three-wheeler, not its rear); a panel never moves a person off
it; its `background` follows from the spot and the camera; when a shot's plan shows someone travelling inside a stretch
the map keeps still, it says so in `conflicts` (the stager missed a walk) and keeps the spot.

Code checks (`marks.check`): one spot per person per stretch; every person of the stretch has one; a mark for an
unknown stretch or person is dropped. A stretch left without spots gets no marks paragraph and no plate, and a
`conflicts` line; the board still paints (never fails a board).

### 3.3 The words on every picture (code)

`marks.paragraph(writer, stretch)` builds the lab's paragraph for a stretch from the writer's spots (phase 0's
`stretch_marks`, word for word): "Ground marks (shots 1 to 15): nobody walks in these shots, so each person stands on
ONE spot ... within half a metre of the mark ... a closer camera makes them larger, never closer together." A
one-person or one-shot stretch leaves out the gap sentence. `marks.panel_line(shot)` is one of three, by code from the
stretches (phase 0: the generic line alone would contradict a walk):

- a shot inside a stretch: "Marks: on the ground marks of shots 1 to 15, the same gap as in every panel of them."
- a shot whose blocks hold a move: "Marks: Kasun stays on his ground mark of shots 1 to 15; Anudi leaves hers in this
  shot." (who stays and who moves, from the map; the way they go is the panel's own words);
- the first shot of a new stretch: "Marks: the ground marks of shot 16; nobody stands on the marks of shots 1 to 15."

`board_prompt` and `panel_prompt` take the paragraphs and the line. A part that holds two stretches carries both
paragraphs, each naming its shots.

Stretches are found through the map's anchors (`SceneStaging.placed`, `reading.resolve`) against the shots' items,
never by raw block numbers: on scene 4 the script has blocks 0-18 but shots 11-14 open at 19-22 (phase 0).

### 3.4 The blocking plate (one per stretch)

ONE still per stretch, painted by the board job BEFORE the parts, at the production's shape (`kit.board_aspect`
panel shape: 9:16 for a vertical production, lab T), at the board's quality (LOW default, MEDIUM as a setting, never
HIGH). Its prompt is the lab's `plate_prompt(tall=True)` built by code from the board's own paragraphs (`board_world`,
`mannequin_paragraph`, `prop_line`, the vehicles line), the stretch's marks paragraph, and:

- the camera: the views-sheet view most of the stretch's panels name (`panel.view`); when none names one, view 1
  only for the `outside` ("Wide", the anchor spot) and `inside` ("Wide from the door") templates. A `both` sheet's
  view 1 is the outside and a `vehicle` sheet's is the vehicle from outside, so there the stretch keeps the words
  and gets no plate. Full length, every person of the stretch and the landmarks their spots name;
- the people's hands as the stretch's FIRST panel has them (`hands_text`), so the plate shows what the panels will
  (lab T fault: the plate's bag on the forearm went into every panel);
- its references: the place's views sheet (or plate) and the stretch's vehicle sheets, as the parts get them.

The plate is then checked by `board_inspector` with HANDS (limbs, floating, ground, hands), and painted again ALONE
once when it finds a fault, exactly as `_mend` does for a panel. A plate whose faults remain is kept and its problems
shown; a plate that cannot be painted leaves its stretch with the words only and a `conflicts` line.

Each part is then painted with the plates of the stretches it holds attached after the place and vehicle pictures and
before the overlap panel, labelled "the blocking plate for shots 1 to 14", told by the lab's `PLATE_WORDS` ("Take
from image n only where each person stands on the ground, what stands behind each of them and the gap between them
... Not its framing, its light or its poses."). A panel painted alone (`_mend`, a panel edit of plan/2026-11-17)
gets its stretch's plate too.

### 3.5 Storage (as designed; BUILT WITHOUT v31: see `IMPLEMENTED.md` phase 4)

`scene_boards.plates jsonb not null default '[]'`: on each part row, the plates THAT part was painted against:
`[{n, shot_ids, numbers, people, path, view, prompt, check, pin}]`. One plate file is shared by every part of its
stretch (`<production>/boards/<first part id>/plate_<n>-<id>.png`, written once, never overwritten, with its
`.thumb.webp`). The spots stay in `writer.marks` (already jsonb). `pin` = a hash of the stretch's shot ids, its spots,
the colours, the place's views asset and the vehicles: a plate whose pin no longer matches is out of date (§3.6). No
new table; the column needs no new policy (the table's read policy covers it); `supabase/tests/database/` gets a row
check. Migration `npx supabase migration new board_plates` + `Database/schema_v31.sql` and
`upgrade_v30_to_v31.sql`, verified by the three dumps.

### 3.6 What a person does with it

- **Paint / Update / Rewrite and repaint** (a new writer): new spots, new plates, new parts.
- **Repaint whole board** (images only, saved words, the person's rule "repaint never rewrites"): the parts are
  painted again against the SAME plates. The people stay where they were; only the painting is new.
- **Repaint marks** (new, per plate): the plate painted again from its saved prompt, then the parts of its stretch
  with it, in one job (D3). A locked panel is still never repainted.
- **Out of date, never repainted by itself**: when a plan or staging edit changes a stretch (someone now walks, a
  shot moves to another stretch), its plate's pin fails and `stale_reasons` says "The marks of shots 1 to 14 changed";
  Update board rewrites and repaints what changed.
- **Approve part** stays as it is; approving a part approves the plates it was painted against. A first frame still
  needs an approved, current board (D3 of plan/2026-11-14).

### 3.7 The API and the interface

`SceneBoardView` gains `plates: list[BoardPlateView]` (deduplicated across parts): `n`, `shots` ("Shots 1-14"),
`people_marks` (each person's spot, in words), `url` / `thumb_url` / `file_key` (tickets, never a path), `problems`
(the inspector's), `stale`. `POST .../board/plates/{n}/repaint` (the same permission as Repaint whole board) runs
§3.6's Repaint marks. The live store needs nothing new (the job's events say "Painting the blocking plate 1 of 2").

In the interface (`features/production/components/scene-board-card.tsx`): a **Marks** row above the parts, one tile
per plate: its thumbnail (opens large), "Shots 1-14", the spots in words, its problems, Repaint marks. No costs.

### 3.8 Not in this plan

- **First frames** keep getting only their own panel (D8 of plan/2026-11-14). Whether the plate should go to a first
  frame too is a lab question (D4).
- **A marks check of each panel** by the inspector (the plate as the second picture, `marks_match`) waits for the
  live check to show drift the words and plate leave (D5).

## 4. Phases

0. **Lab, paid (the person's yes)**: DONE 2026-11-24, $0.188 (`lab/fixed_marks` R_001, W_001, FINDINGS.md "Phase
   0"). Scene 4's parts 2 and 3 against the same tall plate: the spots held across all three parts; the oblique
   singles kept her spot; a walk and a new one-shot stretch left the old marks. It changed §3.3 (three panel lines,
   anchors not raw block numbers). Not tested: a true reverse across the line (scene 4's cameras all stay on the road
   side) and a stretch with two plates; the live check (phase 6) covers both.
1. **`contracts/marks.py`**: stretches, checks, the paragraph and the panel line (the lab's words), the plate prompt,
   the pin. Tests: moves (zone, walking, bridge), entrance and exit, posture change keeps the stretch, a shot opening
   before a move, no map, a stale map, one-shot stretch has no plate, the words byte for byte against the lab.
2. **The board writer**: the bundle's `stretches`, the `GroundMark` schema, the GROUND MARKS rule, `marks.check`; the
   agent's tests and eval cases (scene 4, a reverse-shot scene).
3. **The paint loop** (`systems/frame_render/board.py`): plates before parts, the inspector on each plate, the plates
   attached to the parts and to `_mend`, `plates` saved per part, Repaint whole board keeps them, Repaint marks.
   Tests with the fake painter: order of pictures, which part gets which plate, a failed plate still paints the
   parts, a locked panel untouched, no staging map paints as today.
4. **Schema v31 and the API**: the migration and the version pair, the repository, `BoardPlateView`, the repaint
   route, `stale_reasons` for a plate; `tests/api/test_boards.py` (no path in any response).
5. **The interface**: the Marks row and Repaint marks; its tests.
6. **Live check (the person's)**: apply v31, paint scene 4's board and one scene with a walk; compare with v18 the
   way the lab did. Update `docs/scene_board/README.md` and this plan's `IMPLEMENTED.md`.

Cost in use: one plate and one inspector look per stretch with two or more shots of people, at the board's quality
(about $0.05 a plate at LOW in the lab). Scene 4's map has marks at blocks 0 and 18 only (both stand, then both walk
off), so the shots that open before block 18 make one stretch and one plate.

## 5. Decisions for the person

- **D1 Posture changes.** Recommended: sitting down, standing up or kneeling on the spot keeps the mark (it is inside
  the radius); only walking, running, a zone change, an implied move, an entrance or an exit ends a stretch.
- **D2 Plates before the parts, no stop.** Recommended: the job paints the plates, checks them, then the parts, and
  the person judges it all at once (approving a part approves its plates). The other way, a stop after the plates for
  approval before any part is painted, costs a wait each time.
- **D3 Repaint marks repaints the stretch's parts too.** Recommended: yes, in one job, since parts painted against an
  old plate no longer match it. Repaint whole board keeps the plates.
- **D4 First frames.** Recommended: not now; a lab of three frames from one stretch, with and without the plate, first.
- **D5 A marks check per panel.** Recommended: not now; after the live check.

## 6. Risks

- **The stager misses a walk** (the map is coarse: scene 4 has marks at blocks 0 and 18 only). The writer reports it
  in `conflicts`; a person fixes the staging map, and the board's pin then reports the marks out of date.
- **A reverse across the line is untested.** Phase 0's oblique singles held, but every scene-4 camera stays on the
  road side; no board in the production has a shot / reverse across the two people yet. The live check (phase 6)
  paints one.
- **The plate carries what it shows.** Its hands come from the first panel and the inspector checks them; anything
  else it gets wrong (a prop, a wall) goes into every panel of its stretch, so its tile shows it beside the parts.
