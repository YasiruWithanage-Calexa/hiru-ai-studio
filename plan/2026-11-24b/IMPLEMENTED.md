# plan/2026-11-24b: what is built

Built offline on 2026-11-24, both repos, uncommitted, after plan/2026-11-24c. No paid call. D1-D4 as the plan took
them. Phase 0: `canon_versions.card`, `shots.ir` and `shots.person_edits` are `jsonb` (no migration); 2026-11-24c is
built (its IMPLEMENTED.md); the built views code was read and built on, never over (§5).

## Built

| Plan | Where |
|---|---|
| §2.1 the card | `CanonCard.make` (max 120); `contracts.vehicles.make_of`, `named` ("Family car (BMW 520d, ...)"), `plate_label`, `sheet_label`; `canon_refine.check`: a vehicle whose parent is a set, spot or vehicle is a `parent` finding |
| §2.2 a shot's vehicles | `contracts/vehicles.py` (new): `ShotVehicle`, `VehicleEdit`, `from_wire` (names → ids, strangers dropped, one `inside`), `shot_vehicles` (ir → older-shot name fallback as `at` → a person's edits win, role `none` takes one out), `surface_of` / `where_findings` / `wheels`, `seat_sentence` (right-hand drive unless the card says left-hand), the jobs, `board_line`, `frame_lines`, `prompter_facts`; `PersonEdits.vehicles` |
| §2.2 Raphael | `wire_schema.VEHICLES_SCHEMA` as `ir.vehicles` (beside `setting`, both stages); one VEHICLES paragraph in the planner and cinematic prompts; `SceneS.vehicles` / `empty` (the vehicle cards the scene names, the place's empty spaces from its 2026-11-24c sheet) in the listing ("Vehicles:", "Kept empty:"); a scene with none hashes as before; `checks.vehicles` (report only: unknown name, two `inside`, `where` with no surface); `raphael_write.design_all` stores `ir.vehicles` by id before the design's pins |
| §2.3 the board | `Board.vehicles` per shot (also in each shot's plan for the writer), `vehicle_pictures` (the views sheet, else the plate, after the place's), `vehicle_line`, `vehicle_cards` (name, make, look, views) in the writer's bundle, `panel_views` (a panel inside a vehicle with a sheet names its view; `view_crop` and the inspector use that sheet); `contracts.board`: `prop_line` says `CLAY_NEW`, `mannequin_note` loses the clay car and gains the vehicle rule, `board_job` gives the vehicle-only job, `board_prompt` / `panel_prompt` take the vehicles line before Geography and per-panel views, `writer_findings` reads per-panel views; board writer prompt: "VEHICLES ARE REAL" |
| §2.4 the frame | `holding.references_for` no longer adds a vehicle by name; `frame_brief.plan_references` → `_with_vehicles`: `inside` replaces the scene's place (label ends `INSIDE_NOTE` ", the place of this shot"), `at` follows the place (role `vehicle`); `reference_job` (vehicle plate → vehicle-only or inside job; a vehicle sheet's view → the inside job); `frame_brief(vehicles=...)` from `frame_compose` `vehicle_lines`; `frame_render/graph.py` `_vehicle_view_picture` (§5: the inside view the panel names replaces the plate); `missing_references` "No vehicle plate"; shot prompter facts `vehicles` → "Vehicle (a fact, keep it): ..." |
| §2.5 API + interface | `ShotProductionView.vehicles` / `vehicle_choices`; `PUT /shots/{id}/vehicles/{vehicle}` (`inside` moves another inside vehicle to `at`) and `DELETE` (back to Raphael's); the card's `make` flows through the canon routes. Interface: `ShotVehicles` in the first frame's references (role select, `where` field, "Use the planner's", "Add a vehicle"; writes go through `applyShot`), the "Vehicle plate" role word, the "Make" field on a vehicle card's edit dialog, the make shown before the look |
| D2 script | `scripts/vehicle_make.py` (dry by default, `--apply`): the look's leading make words ("BMW 520d. 2019 version, ..." → "BMW 520d, 2019") into `make`; a look that opens "A/An/The ..." gets none (L03: set it on the canon page); the new version keeps `reference_assets` (plate and views) |
| docs | `docs/scene_board/README.md` (Vehicles), `docs/AI_CATALOG.md` |

## Changes from the lab's words (§0 asks to list them)

1. **The vehicle-only job** is the final lab's `VEHICLE_JOB` with "(its street, ground and light)" in place of
   "(its floor, walls and light)" / "(its street, gate, trees, ground and light)". The lab's card words for one vehicle
   (`CAR_JOB`'s "the charcoal dashboard, the right-hand steering wheel, the beige seats", `TUK_JOB`'s "its side hatch and
   serving ledge") are general on the board: ", and its inside: its dashboard, steering and seats".
2. **The inside job and place sentence** (run_bmw `FRAME`): "the car this shot happens in" is "the vehicle this shot
   happens in"; "its beige rear bench, beige door panels, the charcoal dashboard and the right-hand steering wheel" is
   "its seats, door panels, dashboard and steering"; the street is the scene's place name.
3. **The board's vehicles line** opens with the lab's sentence and names each picture; panel lines follow the lab
   ("PANEL n is INSIDE the ...: the vehicle is the place ...; the street is seen only through the windows", "PANEL n:
   the ... is <where>"), with "all its wheels on <surface>" and "the same vehicle as image n" added (§2.2).
4. **The seat-side sentence** is §2.3's own words (the lab's finding, written in the plan).
5. **"Vehicles in this shot:"** (frame `at`) is the final lab's form with the `where` and wheels of §2.2.
6. **The Raphael paragraph** is new words (the lab wrote the roles by hand); it is in BOTH Raphael prompts, not only
   the cinematic one: stage 1 writes the must clips, which are most shots, and the clip schema is shared.
7. **The `where` surface check** is report-only (told in every check report, never blocking `finish`), not a forced
   re-ask: a blocking fault would hold Raphael's whole bin on one word. The line still always ends with "all its
   wheels on <surface>" ("the ground" when `where` names none).

Not built as written: the frame's `at` vehicle uses its plate, not "the vehicle sheet's outside view the panel names"
(§5): a panel names one view, the place's. Vehicle roles are not part of a panel's pin, so a person's role change does
not mark a painted panel out of date (adding it would mark every painted board out of date); repaint by hand (D4).

## Tests

New: `tests/contracts/test_vehicles.py` (12: the two lab scenes' roles, the fallback, a person's edits, the surface
check, seat sides, the board and frame words, Raphael's listing and report checks), `tests/contracts/test_frame_vehicles.py`
(4: scene 2 shot 1 inside the BMW with no roadside plate; scene 4 shot 1 roadside then the three-wheeler with the
vehicle-only job), `tests/hiru_ai/test_board_vehicles.py` (3: the plate after the place, never clay, the line before
Geography, the writer reads make and role; a vehicle sheet; a scene with none paints as before),
`tests/contracts/test_vehicle_make.py` (2), the refine parent finding (`test_canon_refine.py`), the API route
(`test_production.py`), `tests/raphael/test_lab_parity.py` updated for the paragraph and the schema field. Interface
`shot-vehicles.test.tsx` (3).

Runs: contracts, hiru_ai, services, api and every step/system/agent suite: 4976 passed, 20 failed, every one of the 20
already failing before this build (script_split, Adam fit/score, the API handoff/looks/production/thumbs tests, the
`raphael_breakdown` eval count, the reader ingest and shot-producer hygiene tests; checked on an untouched HEAD in the
24c build). The full Raphael suite fails only as before (gold/system/api caps). `CanonCard.make` is left out of a dump
when empty, so every card without a make hashes as before (the `canon_extract` parity recordings caught it). mypy
clean on the changed `src` files, ruff clean on every changed file, `hiru-ai validate` 202 parts, catalog current.
Interface: `tsc`, lint (0 errors), tests 580 passed and 1 failed (`raphael-panel.test.tsx`, failing before), changed
files formatted.

## The person's live check (paid, ask first; phase 8)

0. `python scripts/vehicle_make.py` (dry), read it, then `--apply` (L04; L03 has no make in its look: set it on the
   canon page).
1. Love Hour scene 4: Update board, then shot 1 first frame (about $0.07 + $0.19).
2. Scene 2: plan it with Raphael again (or set the roles on the shot screen: shot 1 inside the Family car, 2-5 at the
   kerb), Update board, shot 1 first frame. Measured: the same vehicle as its plate in every panel and frame, never
   clay; shot 1 inside the BMW with no roadside plate and the driver at frame LEFT looking back; shot 2 all four wheels
   on the road; the roles Raphael wrote match the script.
