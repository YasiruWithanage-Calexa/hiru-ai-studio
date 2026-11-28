# lab/scene_record: one scene record, code checks that block, clips that chain without the last frame

Started 2026-11-28 after the canal demo (Ekama Sakshiya E01-S01) and "Shot Breakdown: The Deed, Scene 3". Nothing in
`src/` or the database changes; the only database access is `fetch_canal.py`, which reads.

## What it tests

1. **The scene record** (`schema.py`): the spine (goal, objectives, subtext, POV, key moment), beats with intensity
   1-10 and who holds power, and a **floor plan in metres**: landmarks (a gate, a path as a line, the key light's
   source), a mark per person per beat (lying people too; a walk is a mark with `moves_to` and the path it follows),
   the axis per beat and the side cameras keep, and named cameras with a position, height, target and lens.
2. **Cut points instead of "link: cut" + handles**: between every two shots one record of where everyone is (a mark
   and how far along a walk or rise), posture, what each hand holds, what they look at, and the movement under way. A
   shot ENDS on it and the next OPENS on it. A cut inside a movement is `match_on_action` with overlap on both sides.
3. **Code checks that block** (`checks.py`); a shot may break a rule only with a `breaks` entry and a reason, which
   turns the fault into "explained". What code decides from the plan:
   - story: no person, prop or line the scene does not have; every block in one beat, in order; every line said;
   - chain: one cut point between every two shots; marks exist and are the person's own; the cut lists everyone on
     screen; match on action has the movement written and at least 0.5 s of overlap on both clips;
   - props: one timeline (holder, hand, place, on, seen); the hands at every cut agree with it; one hand at a time;
     never in frame before the story shows it;
   - space: **180** (camera on the axis's stated side), **30 degrees or a size step** between cuts on the same
     subject, **size vs geometry** (what that lens holds from that distance), **frame:out** (listed but not in the
     lens's view), **frame_missing** (on a mark inside the view but left out: the canal's vanishing body),
     **unmarked** (on screen without a mark), **eyelines** (two singles of A at B and B at A look opposite ways),
     **screen direction** of a walk across cuts, and a walk **off its path** (the canal's shot 1);
   - intensity: the peak beat has a shot at MCU or tighter; no CU in a calm beat; peak shots average shorter than
     calm ones; no leap of five sizes; the scene opens on the space; the key moment's shots exist;
   - wardrobe: a garment, or a colour on a garment, that no look in the scene has (the mustard blouse).
4. **Chaining through the video prompt, no last frame** (`chain.py`). Each clip's prompt is:
   `CAMERA` (size, lens, height, move and its reason, key light side) · `OPENS ON` (the start cut point) · a timed
   action · `ENDS ON` (the end cut point, held still for 0.5 s before a plain cut) or, before a match on action, the
   movement still going at the last frame and the instant of the cut · `KEEP THE SAME` (each person's look, word for
   word, from the look, never the planner).
   The world facts of a cut point (posture, hands, the prop's state, what is under way) come from ONE function, so
   shot N's ENDS ON and shot N+1's OPENS ON are the same words. The frame facts (frame left or right, facing which
   way on screen, distance) are worked out per camera from the floor plan, so a reverse angle is right by
   construction. The first-frame brief is written from the same OPENS ON record, so the picture and the clip start
   from one source.

## Run it

```
.venv/Scripts/python.exe -m pytest lab/scene_record/tests -q                    free: 23 tests
.venv/Scripts/python.exe lab/scene_record/run.py check --scene deed --record lab/scene_record/input/deed_gold.json
                                                                                free: the PDF's plan, checked
.venv/Scripts/python.exe lab/scene_record/run.py plan --scene canal             free: the brief only
.venv/Scripts/python.exe lab/scene_record/run.py plan --scene canal --yes       PAID: planner + up to 2 repairs
.venv/Scripts/python.exe lab/scene_record/run.py plan --scene deed --yes        PAID
.venv/Scripts/python.exe lab/scene_record/fetch_canal.py                        reads the hosted DB (GET only)
```

Each run writes `runs/<run>/`: `brief.md`, `attempts/`, `record.json`, `report.md` (faults, the spine, and per shot
what the floor plan says: sides, eyeline, key light side, travel, frame width, size the lens holds),
`prompts.md` (first frame + video prompt per shot), `floorplan.svg` (open in a browser), `spend.json`.
Default model `gpt-6.1-sol` at high effort (Jonathan's tier), `--model gpt-5` to compare. Cap $1.50 per run.

## Inputs

- `input/canal.json`: the demo scene (7 blocks, Aruni and Nimal with their looks and scene conditions, the canal and
  its six views, the bag, the key, the phone). Planner sees people WITHOUT their looks; code adds them.
- `input/deed.json`: "The Deed" scene 3 from the PDF. The PDF gives the story, not the script's words, so its four
  blocks are the story's sentences and it has no line ids.
- `input/deed_gold.json`: the PDF's own seven-shot plan as a record (positions read off its floor-plan figure; our
  shot 6 is its insert 7 and our 7 its close-up 6, in edit order). It passes every check. The floor plan also settles
  a contradiction inside the PDF: its shot 5 record says Nimal's eyeline is "frame left", its eyeline figure says
  "screen right"; from the cameras' positions it is screen right.

## What the person runs (paid)

1. `plan --scene canal --yes` and `plan --scene deed --yes` (about $0.3 to $0.8 each): read `report.md` and
   `floorplan.svg`. Does the canal plan have the notice, the approach, Nimal marked lying at the gate in every beat,
   a walk along the path, the line after the call?
2. Paint first frames from two neighbouring shots' **First frame** briefs and render the two clips from their
   **Video** prompts (dashboard or Flow; this lab never paints or renders). The test of the chain: cut at the cut
   point (the ENDS ON second, or inside the movement for a match on action) and see whether the cut holds.
   Best pairs: canal approach then kneel; Deed shot 4 into shot 5 (match on action on the rise).

## Floor plan and blocking plan (2026-11-28)

Every run also writes `plan.html` (`plan_view.py`, free): the BLOCKING PLAN (each person's positions numbered in story
order, START to END, dashed arrows for walks, a dotted line to what they look at, a short note at each position, and
a list), the FLOOR PLAN with every camera as an icon pointing where it looks and a table of the cameras (shots, size,
lens, height, purpose), and a zoom on the setups near the action. The record now carries what such a plan needs:
areas (water, fields, a room's floor) as polygons, a `width` for paths and objects, walls, and a `label` on each mark;
plans written before this (runs 002, 003) are drawn with defaults (a water band beside an edge, a 1.2 m path).
