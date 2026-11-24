# Vehicles: a role in each shot, never clay, always their own plate (plan/2026-11-24b)

Revision 3 (2026-11-24). Nothing in this plan is built. Proven in `lab/vehicle_role` (runs 001-005, $0.595 of $1.00,
`FINDINGS.md`) and, with plan/2026-11-24c, in `lab/final_views` (Love Hour scene 2: a board and shots 1, 2, 4, 7 with
the new sheets, $0.674, `FINDINGS.md`). Revision 2: plan/2026-11-24 (location views) is now BUILT and committed
(2d4a986), and plan/2026-11-24c (place views by type, `lab/place_views`) changes it; build 2026-11-24c FIRST, then
this; §3 D3 and §5 were rewritten for that. Revision 3 adds what the final lab found: `where` says what the vehicle
stands on (§2.2), the seat side rule for inside shots (§2.3, §2.4), the vehicle sheet's inside view as the place (§5,
now proven), and the lab-before-ship of §5 is done. Read §5 before touching `board.py`, `frame_brief.py`,
`shot_prompts.py` or `frame_render/views.py`. Read this file whole, then
`lab/vehicle_role/FINDINGS.md`, `lab/vehicle_role/run.py` and `run_bmw.py` (the words to port), `src/libs/contracts/
board.py` (`prop_line`, `mannequin_note`), `src/libs/hiru_ai/systems/frame_render/board.py` (`place`, `place_names`,
`writer_pictures`, `image_pictures`), `src/libs/contracts/frame_brief.py` (`plan_references`, `reference_job`),
`src/libs/contracts/holding.py` (`references_for`), `src/libs/contracts/canon.py` (`CanonCard`) and
`src/libs/hiru_ai/agents/raphael/wire_schema.py`.

## 0. Rules for the chat that builds this

- **Port the lab exactly.** The vehicle-only job, the "never clay" sentence and the vehicles line are the lab's words
  (`lab/vehicle_role/run.py` `VEHICLE_JOB`, `CLAY_NEW`, `WHERE`; `run_bmw.py` `CAR_JOB`, `VEHICLES`, `FRAME`). List
  any change of words before making it. Do not edit or re-run the lab.
- **Ask before every paid call**, each time. Tests run with `OPENAI__API_KEY=` blank and fakes only.
- **No enable switches.** **Never stash or reset** the person's tree. **Never edit an applied migration** (none is
  expected: the make is a field of the card JSON, the vehicles record a field of the shot's `ir` and `person_edits`;
  phase 0 confirms the columns are JSON).
- Two repos: the backend (this one) and `..\hiru-ai-studio-interface` (its `CLAUDE.md` binds).

## 1. What is wrong today, and what the lab showed

Vehicles (`canon_class = "vehicle"`: Love Hour's "Food three-wheeler" L03 and "Family car" L04, a BMW 520d) are canon
locations with a reference plate, a parent (the Colombo region) and nothing that says where they are in a scene. So:

1. **The board never sees a vehicle.** The board picture gets only the scene location's plate (`image_pictures`); the
   board writer gets the same (`writer_pictures`). The writer invents the vehicle ("silver-grey family car with a dark
   neutral interior", "muted-green food three-wheeler") and the image model paints its own.
2. **The board's rules make a vehicle clay.** `prop_line`: "A vehicle that is a prop is a full-size white clay vehicle".
   The 2026-11-23 patch keeps a place real only when the plan uses its exact canon name; "the serving hatch", "the food
   business" or "the car" fall to clay: scene 4's three-wheeler came out a white van.
3. **The first frame makes a vehicle a second place.** `references_for` adds a vehicle by its name in the shot's words,
   labelled "the location plate for ..." with the job "the place and its fixtures", AFTER the scene's location plate.
   Its plate's own background leaks in (scene 4: a blue-roofed three-wheeler); for a shot INSIDE a car the roadside plate
   leads (scene 2 shot 1, worked out offline: roadside plate first, BMW second).
4. **The role changes inside one scene.** Scene 2 "Anudi arrives": shot 1 inside the moving car (the car IS the place),
   shots 2-5 the car stopped at the roadside (it STANDS IN the place), shots 6-7 no car. The scene stores one location.
5. **The make lives only in the look text.** "BMW 520d" is the first words of L04's `look`; the board writer dropped it.

The lab (only the vehicle words of the saved prompts changed):

| Run | What | Cost | Result |
|---|---|---|---|
| 001 | scene 4 board part 1, LOW: three-wheeler plate attached with the vehicle-only job, "never clay", vehicles line | $0.063 | white van and invented shop gone; the same maroon, black-roofed three-wheeler in panels 1-5 |
| 002 | scene 4 shot 1 frame, MEDIUM, vehicle plate with the vehicle-only job, panel 1 of run 001 | $0.189 | black roof (saved: blue), the plate's flask; wall, building, blocking kept |
| 003 | made up: Kasun drives the three-wheeler home; the vehicle IS the place, the road only words | $0.108 | the same three-wheeler from inside; road only through the open sides |
| 004 | scene 2 board v3, LOW: both vehicle plates, a role per panel, the writer's two vehicle words from the cards | $0.088 | a silver 5-series sedan (saved: a hatchback), the beige interior, the driver in front (saved: beside her), the maroon three-wheeler (saved: green) |
| 005 | scene 2 shot 1 frame, MEDIUM, role inside: BMW plate is the place, NO roadside plate | $0.148 | the BMW's beige seats and door panels, the driver at the wheel, Anudi alone on the rear seat; street only through the windows |

Not proven by the lab: Raphael writing the roles itself (the lab wrote them by hand); the board writer reading the
vehicle plates itself (run 004 replaced its two vehicle words by hand); a vehicle moving through a shot seen from
outside; a vehicle together with a location views sheet (§5).

## 2. The design

### 2.1 The vehicle card

- `CanonCard` gains `make: str` (max 120): "BMW 520d, 2019, pearl silver"; "older maroon Bajaj three-wheeler". Shown
  and edited on the canon page for a vehicle only; empty for every other class.
- A vehicle's `parent_id` may be a region or nothing, never a set or a spot (`canon_refine` finding, as the spot rule).
- Everywhere a vehicle is named to a model, it is named with its make: "the Family car (BMW 520d, 2019, pearl silver)".

### 2.2 The vehicles of a shot

- Each shot holds `vehicles: [{id, role, where}]` in its `ir` (written by Raphael) with a person's change in
  `person_edits.vehicles` (the person's wins, as `cast.add/remove`):
  - `role = "inside"`: the vehicle IS the place of this shot (people sit in or on it, the camera is in or on it).
  - `role = "at"`: the vehicle stands in the scene's place; `where` says where, which way it faces AND what it stands
    on ("stopped on the asphalt beside the kerb drain, all four wheels on the road, nose toward screen right"; "parked
    side-on in the vending bay at the left of the pavement, its wheels on the bay's concrete"). In `lab/final_views`
    the car "stopped at the kerb" straddled the kerb drain with a front wheel on its slab (fault 2). Code checks that a
    `where` names a surface (road, asphalt, kerb side, bay, drive, ground, floor, sand ...) and Raphael is re-asked
    once when it does not; the vehicles line (§2.3) always ends with "all its wheels on <that surface>".
- **Written by Raphael's cinematic step** (`wire_schema.py`, beside `setting`): one list per clip, by canon NAME from
  the scene's vehicle cards it is given (name, make, look); code maps names to ids and drops a name that is not a vehicle
  card. At most one `inside` per shot.
- **Read from older shots** with no `vehicles`: code fills `at` for a vehicle card named in the shot's words or zones
  (today's `names_place`), `where` empty; never `inside`. So nothing old breaks, and a person can set `inside` by hand.
- `contracts.vehicles` (new, small): `shot_vehicles(shot, canon) -> list[ShotVehicle]` (ir + person edits + the
  fallback), `vehicle_line(vehicles)` (the lab's words), `VEHICLE_JOB`.

### 2.3 The board

- `image_pictures` and `writer_pictures`: after the location plate, the plate of every vehicle any painted panel has,
  labelled "the vehicle plate for <name> (<make>)".
- The references paragraph gives each vehicle plate the lab's job (`CAR_JOB` / `VEHICLE_JOB`: "ONLY the vehicle
  itself, exactly as shown ... Ignore everything around the vehicle in that picture").
- `prop_line`: the clay-vehicle sentence becomes the lab's `CLAY_NEW` ("A vehicle is never a clay stand-in: every vehicle
  is painted real, exactly as its vehicle plate shows it, with its real colours"); `mannequin_note` loses "a car" from
  its clay examples and gains the same rule for the writer.
- One "Vehicles (every panel):" line before Geography, in the lab's words: which plate is which vehicle, then panel by
  panel each vehicle's role (`inside`: "PANEL n is INSIDE the <vehicle>: the vehicle is the place ... the street is seen
  only through the windows"; `at`: "PANEL n: the <vehicle> is <where>").
- The board writer's bundle gains the vehicles (name, make, look, role and where per shot) and it sees their plates, so
  its own words describe the real vehicle (in run 004 this was done by hand).
- **Seat sides for an `inside` panel** (`lab/final_views` fault 4: the right-hand-drive driver came out at frame right
  with the camera looking back from the front passenger seat, on the board AND the frame). The vehicles line adds the
  lab's sentence for a car with a driving seat: "The driver's seat is on the car's RIGHT (right-hand drive): with the
  camera looking BACK from the front, the driver is at frame LEFT; looking FORWARD from the rear, at frame RIGHT."
  Right-hand drive is the default in the Sri Lankan market; a card whose `make` or look says left-hand drive flips it.

### 2.4 The first frame

- `plan_references`: vehicles come from `shot_vehicles`, not from `names_place`.
  - `inside`: the vehicle plate is THE place ("the vehicle plate for <name> (<make>)", job: the lab's frame wording "the
    car this shot happens in: ..." with its inside); the scene's location plate is NOT attached.
  - `at`: the location plate leads; the vehicle plate follows with the vehicle-only job.
- `reference_job` gains the prefix "the vehicle plate for ".
- The frame brief's scene words gain the lab's place sentence for `inside` ("The place: this shot happens INSIDE ... The
  street is NOT a place of its own here: ... seen only through the windows") and the vehicles line for `at`; an
  `inside` shot also gets the seat-side sentence of §2.3.
- The shot prompter (`core/shot_prompts.py`) gets the same facts (`vehicles` in its facts), so the shot prompt's words
  and the pictures agree.

### 2.5 The interface

- Canon page: the `make` field on a vehicle card.
- Shot workspace: a "Vehicles" row in the references list: each vehicle, "inside" or "at <where>", changeable by a
  person (one small client form; the write returns the shot view into the TanStack cache, `applyShot`).
- Scene board card: no change (the board names its vehicles in its own reference list).

## 3. Decisions (the person's, 2026-11-24: taken as recommended)

- D1 **Who writes the role:** Raphael's cinematic step, per shot; a person can change it on the shot screen.
- D2 **Existing cards:** the make moves out of the look text into `make` once, by a script the person runs after
  reading its dry list (Love Hour: L03, L04). The region parent stays.
- D3 **With location views:** settled by plan/2026-11-24c: a place's views sheet paints only what is always there,
  keeps the space where a vehicle stands EMPTY, and never attaches a vehicle's plate; vehicles always come from their
  own plate (or, later, their own vehicle views sheet, §5). Not proven together: one small lab run before this ships
  (§5).
- D4 **Old approved boards** (Love Hour scenes 2 and 4) stay; the person repaints them in the live check.

## 4. Phases (offline, $0, then the person's live check)

0. **Check** the columns (`canon_versions.card`, `shots.ir`, `shots.person_edits` are JSON: no migration), that
   plan/2026-11-24c is built (its IMPLEMENTED.md), and the built views code in the files of §5; write down in
   IMPLEMENTED.md where each change of §2 goes beside it.
1. **Contracts:** `CanonCard.make`; `contracts.vehicles` (`ShotVehicle`, `shot_vehicles`, `vehicle_line`, the lab's
   jobs); `PersonEdits.vehicles`; the `canon_refine` parent finding. Tests from the lab's two cases (scene 4 shots 1-6
   all `at`; scene 2 shot 1 `inside`, shots 2-5 `at`, 6-7 the three-wheeler `at`), the old-shot fallback, the
   `where` surface check and the seat-side sentence (right-hand drive by default, flipped by a left-hand-drive card).
2. **Raphael:** `vehicles` in `wire_schema.py` and the cinematic prompt (one paragraph: what a vehicle is, the two
   roles, one `inside` at most), the scene's vehicle cards in its input; code maps names → ids. Evals: scene 2 and 4
   cases (offline fixtures from `lab/vehicle_role/input*`).
3. **Board:** pictures, references paragraph, `prop_line` / `mannequin_note`, the vehicles line, the writer's bundle.
   Tests: the lab's run 001 and 004 prompts come out of the product code from the lab's inputs, word for word in the
   vehicle parts (a golden-file test).
4. **Frame + shot prompter:** `plan_references`, `reference_job`, the scene words, the shot prompter's facts. Tests:
   scene 2 shot 1 gets no roadside plate and the BMW plate first; scene 4 shot 1 gets the roadside plate then the
   three-wheeler plate with the vehicle-only job.
5. **API + interface:** the card's `make` through the canon routes; `vehicles` in the shot view and a write route for a
   person's change; the canon field and the workspace row. `npx next typegen && npm run check && npm run format:check`.
6. **Make script** (D2): `scripts/vehicle_make.py --dry` lists each vehicle card's proposed `make` (the look's leading
   make words) and new look; `--apply` writes a new card version. The person runs `--apply`.
7. **Docs:** `docs/scene_board/README.md` (vehicles), the catalog, IMPLEMENTED.md.
8. **Live check (paid, the person's):** Love Hour scene 4 Update board + shot 1 first frame; scene 2 Update board + shot
   1 first frame (about $0.07 + $0.19 each scene, as the lab). Measured: the same vehicle as its plate in every panel and
   frame, never clay; scene 2 shot 1 inside the BMW with no roadside plate and the driver at frame LEFT looking back;
   scene 2 shot 2 the car with all four wheels on the road, not over the drain; the roles Raphael wrote match the
   script.

## 5. With the location views (plan/2026-11-24, built) and place views by type (plan/2026-11-24c)

The built views code already changed the files this plan touches: `Board.image_pictures` attaches the views sheet
instead of the plate when the place has one; `frame_render/graph.py` `_view_picture` replaces the location plate by
the panel's view crop; `board_facts` gives the shot prompter "Background view". Build on that, never over it:

- **Board:** the vehicle plates of §2.3 go AFTER the views sheet (or the plate, when there is no sheet); the vehicles
  line goes after the built `views_paragraph`. A panel whose vehicle is `inside` names a view of the VEHICLE's sheet
  when the vehicle has one (2026-11-24c, template `vehicle`), else none, and its background is the vehicle.
- **Frame:** `at`: the panel's view crop of the place leads (as built), the vehicle plate follows with the vehicle-only
  job (or the vehicle sheet's outside view the panel names: "Side", "Front three-quarter", as `lab/final_views` shots 2
  and 4). `inside`: no place view and no location plate. When the vehicle has a views sheet (2026-11-24c, template
  `vehicle`), the panel's inside view ("Inside from the rear" / "Inside from the front") is the place, PROVEN by
  `lab/final_views` shot 1 (the BMW's beige bench, console and door from view 5); without a sheet, the plate is the
  place (runs 003, 005).
- **The empty space:** 2026-11-24c's `empty` names where a vehicle stands ("the vending bay at the left of the
  pavement"); the vehicles line's `where` should use the same words, so the board and frame put the vehicle in the
  bare space the sheet shows. `contracts.vehicles.vehicle_line` takes the place's `empty` list and the writer of the
  `where` (Raphael) is given it.
- `views_context.within` no longer carries vehicles (2026-11-24c §2.2): this plan adds nothing there.
- **The lab before ship is DONE** (`lab/final_views`, 2026-11-24): the 2026-11-24c roadside sheet with the empty bay,
  the BMW vehicle sheet and the three-wheeler plate, on a scene 2 board and shots 1, 2, 4, 7. The three-wheeler stood
  in the bay (not a stall), the BMW was right in every picture, never clay; the same building, awning and wall across
  shots 2, 4 and 7. Its four faults are in this plan (§2.2 surface, §2.3 seat sides) and 2026-11-24c (§2.4 dry
  sheets, §2.7 the board's view check).
