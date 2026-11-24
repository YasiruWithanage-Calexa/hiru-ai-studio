# Vehicle role lab: findings (2026-11-24)

Case: Love Hour scene 4 (de75bc31), "Colombo roadside" with Kasun's "Food three-wheeler". Budget $0.60, spent $0.359.

## Cause (read from the saved board and frame, and the product code)

1. The board picture gets only the scene location's plate (`frame_render/board.py` `image_pictures`); the
   three-wheeler's plate never reaches it, so the model invents the vehicle.
2. The board prompt says "a vehicle that is a prop is a full-size white clay vehicle", and keeps a vehicle real only
   when the plan uses its exact canon name. Panels saying "serving hatch" or "food business" fall to clay: white van.
3. The first frame attaches the three-wheeler plate as a second "location plate" with the job "the place and its
   fixtures", so its own background (and the street's blue awning) leaks in: a blue-roofed three-wheeler.
4. Nothing in the data says where the vehicle is in a scene; it is found by name in the plan text.

## Rules tested (only the vehicle words of the saved prompts changed)

1. A vehicle is never clay.
2. The scene says where its vehicles are: "Vehicles in this scene: ... parked side-on at the left of the pavement ...
   the food business, serving hatch and shelter the words mention are this three-wheeler."
3. The vehicle's own plate goes with every picture, labelled "vehicle plate", job "ONLY the vehicle itself ... ignore
   everything around it in that picture".

## Runs

| run | step | $ | result |
|---|---|---|---|
| 001 | board part 1, LOW | 0.063 | white van and invented shop gone; the same maroon, black-roofed three-wheeler with the steel hatch behind Kasun in panels 1-5; wall right; cut clean |
| 002 | shot 1 first frame, MEDIUM, panel 1 of run 001 | 0.189 | black vinyl roof (saved: blue), the plate's red tartan flask, same maroon body; wall, green building, drain, blocking and hand-over kept |
| 003 | role 2, made up: Kasun drives it home, the vehicle IS the place, MEDIUM | 0.108 | maroon dash, black roof, the food counter and tartan flask behind him, wet road and shop lights through the open sides only. Faults not about the vehicle: he looks almost into the lens; the apron does not show |

## Verdict

The three rules fix both vehicle faults of scene 4 on the board and the first frame. Role 2 (inside the vehicle)
works from the same plate with the road as words only. Not tested: a vehicle that MOVES within a scene, and a
scene where the vehicle is parked at a different place than scene 4.
