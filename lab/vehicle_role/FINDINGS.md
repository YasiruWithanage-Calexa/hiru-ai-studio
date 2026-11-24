# Vehicle role lab: findings (2026-11-24)

Case 1: Love Hour scene 4 (de75bc31), "Colombo roadside" with Kasun's "Food three-wheeler". Budget $0.60, raised to $1.00 for case 2 (person's yes); spent $0.595 in all.

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

## Case 2: scene 2 "Anudi arrives" and the BMW 520d (`run_bmw.py`, inputs by `fetch_bmw*.py`, GET only)

Canon "L04 Family car" (class vehicle, parent the Colombo region; "BMW 520d" only inside its look text) has a good
three-part plate (exterior, right-hand-drive dashboard, beige rear bench). The approved board v3 (2026-11-16) got only
the roadside plate: a generic silver hatchback, dark interior, the driver on the rear seat beside Anudi, a GREEN
three-wheeler; the writer had written "silver-grey ... family car with a dark neutral interior". The role changes
INSIDE the scene: shot 1 inside the car, shots 2-5 the car stopped at the roadside, 6-7 no car. The product's picker
(run offline) would give shot 1's frame the roadside plate first and the BMW plate second, both "the place and its
fixtures", plus the hatchback panel.

| run | step | $ | result |
|---|---|---|---|
| 004 | board v3 again, LOW: both vehicle plates, a role per panel, the writer's two vehicle words from the cards | 0.088 | panel 1 beige BMW interior, driver in a front seat (not beside her); panel 2 a silver 5-series-shaped sedan; panel 4 the maroon three-wheeler; cut clean |
| 005 | shot 1 first frame, MEDIUM, role "inside": BMW plate is the place, NO roadside plate, panel 1 of run 004 | 0.148 | the BMW's beige seats and door panels, the driver at the wheel in front, Anudi alone on the rear seat with phone, folded umbrella and handbag; street only through the windows. Not about the car: the driver is sharp and large, not "soft at the edge" |

Extra rule from case 2: the role is per SHOT (or panel), not per scene. Extra finding: the make and model should be
a field of the vehicle card, not only words in its look (the board writer dropped "BMW 520d").

## Verdict

The three rules fix both vehicle faults of scene 4 on the board and the first frame. Role 2 (inside the vehicle)
works from the same plate with the road as words only. Not tested: a vehicle that MOVES within a scene, and a
scene where the vehicle is parked at a different place than scene 4.
