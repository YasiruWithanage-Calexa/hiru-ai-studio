# lab/scene_record: findings

## Run 002 (2026-11-28): gpt-6.1-sol, high effort, one planner call + up to two repairs

| Scene | Calls | Spend | Blocking per attempt | Kept |
|---|---|---|---|---|
| canal (Ekama Sakshiya E01-S01) | 3 | $0.399 | 7 → 1 → 0 | 12 shots, 60 s, 5 explained breaks |
| deed (The Deed, scene 3) | 2 | $0.186 | 1 → 0 | 8 shots, 26 s |

Total $0.585. The repair loop worked: every fault code named was fixed or given a reason, and no repair made the plan
worse (the best record is always the one sent back).

### The canal plan against what went wrong in the demo

| Demo fault | Planner today (Raphael) | This record |
|---|---|---|
| No "notice", no POV, cut from far away straight to the body | yes | Shot 2 her look (MCU), shot 3 a POV of Nimal from where she stands, shot 4 the approach, kneel and touch in one FS |
| Nimal vanishes, then is painted standing | no mark for him | A lying mark at the waterline by the gate in every beat (M2 … M15); `frame_missing` made the model either frame him or say he is cropped below |
| Shot 1 walks across her own path | lateral move on a view whose path runs into depth | Walks west along the `path` line to the gate; travel reads "to frame left" in shots 1, 2 and 4 (no flip) |
| Close-ups painted as wides | size not tied to a camera | Each size checked against lens and distance (`size_geometry`) |
| Mustard blouse | invented by the planner | No clothes written anywhere; every prompt carries the look word for word from the look |
| Title missing | black card | Shot 12: "EKAMA SAKSHIYA" on black, the exact text |
| Clips do not chain | link "cut" + 1 s handles | 12 cut points; the phone lift is a match on action with 0.5 s overlap both sides |
| Dawn light | contradictory | "Soft eastern dawn skylight diffused through dense rain cloud", key from the sky to the east; key side per shot derived |

### Faults the first checks missed (now checks, tests 24 and 25)

- **face_hidden.** Aruni's singles (shots 2, 7, 9) are from cameras directly south of her while she looks north at
  Nimal: the plan sees the back of her head. The new check works out how her facing reads in each camera and blocks
  a single/MS/MCU/CU/ECU that faces away.
- **words:numbers.** The model wrote plan coordinates into prop places ("which rests near x 0.28, y 0.32"), which went
  into the video prompts. Both runs did it (canal 2, deed 3). The prompt now says numbers live only in number fields,
  and the check blocks it.
- Writer fixes (no model change): a prompt only describes the people and props in that shot's frame (the phone insert
  no longer describes Nimal and the key); each person's sentence at a cut point is still the same words in the clip
  before and after; the black card no longer counts as the "calm" beat for shot length.

Re-checked for free with the new rules: canal 5 blocking (3 face, 2 numbers), deed 3 blocking (numbers).

### Still open

- The planner kept the script order: the line "Dinu... oyata meka ahenne nadda?" (shot 7) comes before she takes out
  the phone (shot 8). That is the script's order; whether it is said into the phone is a director's call, not code's.
- 12 s of the 60 are black (5 s) and title (7 s): the model padded to the length. Black and title lengths should be
  set by code (or the person), not by the length target.
- A prop's place does not follow the action inside a shot: after the lift the phone's state still reads "held low"
  while her state says "at her right ear". A cut point should start a new prop state when a held prop moves.
- The phone screen was written as "no readable text"; the production's rule is to say what the text is
  (contracts/on_screen_text). The prompt carries PLANNER, the model still avoided it.
- Deed: all eight shots are static and the peak has no move (the PDF's shot 5 is a fast dolly in); allowed, but worth
  a look.

## Run 003 (2026-11-28): the same model with the face and numbers rules in the prompt and the checks

| Scene | Calls | Spend | Blocking per attempt | Kept |
|---|---|---|---|---|
| canal | 2 | $0.289 | 4 → 0 | 14 shots, 60 s, nothing explained |
| deed | 2 | $0.197 | 2 → 0 | 9 shots, 26 s, 1 advisory |

Lab total so far $1.07. Both faults the rules targeted are gone at the first attempt: no single sees the back of a
head, and no coordinates reach the prompts (0 in canal's prompts.md). The repair loop again closed every blocking
fault in one call (canal: two people listed where the lens could not see them, a size the lens could not hold, and a
false wardrobe hit; deed: a person and the deed outside an insert's lens).

Canal, what changed against run 002: the black and title cards are 3 s each (were 5 and 7), so the 60 s go to the
scene; the approach still comes as POV (shot 3) then the walk, kneel and setting down of the bag (shot 4) into a match
on action on the reach (shot 5); the phone lift is again a match on action (10 → 11); her singles now face her.

Still open after 003:

- The wardrobe check fires on "Uniform black" (an adjective, not clothing). It should look for a garment as a noun
  near a person, or ignore a word followed by a colour.
- Shot 1 now shows Nimal small in the wide before Aruni notices him (run 002 hid him behind the sluice cheek). Both
  are legitimate; the POV rule ("the audience discovers with her") prefers 002's. A person's call, or a POV check.
- Shot 5 has her thumb "ease his curled fingers slightly apart" to expose the key. The script says she touches his
  hand and the key is inside his fist; this is elaboration close to a new event. Raphael's plan kept the fist closed.
- The phone screen is again "no legible words": the planner keeps avoiding on-screen text despite PLANNER.
- The phone still has no state "at her right ear" after the lift; the line still precedes the call (script order).
- Partly seen people. Canal shot 5 is an insert of Nimal's fist that Aruni's hand reaches into, but she is not in
  `in_frame`, so her hand gets no state and no wardrobe line, while "under way" names it. `in_frame` needs a "part"
  (hand, shoulder) so a hand in an insert is described, and an insert should not say a person is "facing the camera".
- Deed: the key moment (the slam, shot 5) is a static MLS; the check only advises. Making `key_moment` blocking (or
  requiring the key moment's shots to include one at MCU or tighter, or a move) would push it to the strongest shot.

## Next

1. Free fixes to the checks: the wardrobe false hit, a blocking key-moment rule, a prop state when a held prop moves.
2. The person's video test of the chain: paint two neighbouring first frames from `runs/003_*/prompts.md` and render
   the two clips, then cut at the cut point. Best pairs: canal 4 -> 5 (match on action on the reach) and 10 -> 11
   (the phone lift); deed 6 -> 7.

## Painted boards (2026-11-28): the product's board prompt, panels written by code from the 003 records

`board_paint.py`: no board-writer model; each panel's camera, background, people (side, distance, facing, posture,
hands) and props come from the record, handed to `contracts.board.board_prompt`. gpt-image-2 at medium: canal $0.068
(12 panels, the canal views sheet attached), deed $0.051 (9 panels, words only). Image spend $0.119; lab total $1.19.

What the painter got right: the layout of both scenes (canal: the gate, Nimal lying at the gate, Aruni on the path
coming to him, then kneeling beside him; deed: red Nimal left, blue Saman right, table, cups, lamp and window in
every wide), the inserts (the reach to the fist, the key, the phone, the deed under the hand, the cups), the props as
white clay, the rain and the dusk lamp light.

Faults, and whose they are:

- **Mine (panel words):** canal panel 3 shows the key in Nimal's hand before the reveal: the hands line named it
  (`PanelPerson.right_hand` = the key) although its state is unseen. A hand must not name an unseen prop.
- **Mine:** canal panel 12 (the cutaway of the rain on the paddy) has no people in the plan, but the words did not
  say so and the painter put a kneeling Aruni in it. A panel with nobody in frame must say "nobody in this panel".
- **Mine:** "looking at the Saman": a person's name took "the".
- **The painter:** singles are painted wider than planned (canal 2, 7, 8: MCU/CU painted as full kneeling figures),
  as on the product's own board; the camera words (lens, distance) are not enough. A single's crop needs the body
  line words ("cut at the chest", "head and shoulders fill the frame").
- **The painter:** canal panel 2 (MCU, her head facing frame left) is painted from behind her; deed panels 2, 3, 7
  and 9 look straight into the lens although the words give the eyeline side ("head facing frame right, looking at
  Saman"). The words say where the head turns; the painter defaults to the lens. An eyeline needs "looks off the
  lens to frame right, never into the lens".
- **The plan (003 canal):** the dawn key light is put in the north-west; dawn is east. No check ties the key light's
  direction to the time of day (002 had it east).

## Run 004 (2026-11-28): the floor plan a crew can read

The record gained areas as polygons, `width` for paths and objects, walls, short names and a `label` on each mark;
`plan_view.py` draws `plan.html` (blocking plan, floor plan with camera icons and a camera table, a zoom on the
setups near the action). Planner re-run, gpt-6.1-sol high: canal $0.384 (7 -> 1 -> 0 blocking, 2 explained), deed
$0.191 (1 -> 0, 1 advisory). Lab total $1.77 ($1.65 planning, $0.12 painting).

What came back: the canal as water (28 x 2.8 m), both paddies and the earthen bank as areas, the 1.2 m path, the gate
(2.8 m) and its two concrete cheeks, the concrete lip Nimal lies on; the deed's tea-shop floor, the west wall and
window, the 1.1 m table. Every mark has a note ("approaches the sluice", "hidden beside the gate", "calls beside
Nimal"; "listens across the table", "takes deed and rises", "admits the concealed debt").

Still the planner's: the canal's dawn key light is in the north-west again (dawn is east; no check yet); it made a
landmark of "rain on water"; the deed's key moment (the slam) is a static MLS (advisory).

## Cameras as setups (2026-11-28, the person's review of run 004)

The person: "too much brand new cameras and positions; in the actual workflow that is not the way to do it" (their
reference: C1 establishing 24 mm, C2 side tracking 35 mm, C3 reaction/OTS 50 mm, C4 body wide/side 35 mm, C5 detail
macro/85 mm, for the whole canal scene). Run 004's canal has 9 positions for 11 shots, a new camera for almost every
shot: the record tied ONE lens and ONE target to a camera, so a new size or subject meant a new camera.

Changed (free): a camera is a SETUP with a `role` and what it `covers`; a shot takes its own `lens_mm` and `looks_at`
from its setup (`World.cam(shot)`); the planner plans the setups first and shoots each out; a new setup needs a new
angle. The `setups` check blocks more positions on the people than max(4, half the shots) (detail and insert
positions do not count: no relight), breakable only with a reason. It passes the PDF's own plan (4 for 7) and deed
004 (4 for 8), and blocks canal 003 and 004 (7 for 11-12) and deed 003 (6 for 9). The floor plan draws each setup as
a triangle with a dashed arrow to every subject it films, and a table of Setup | Role | Shots | Lens | Height | Covers.
Tests: 27.

## Run 005 (2026-11-28): planned in setups

| Scene | Spend | Blocking per attempt | Setups | Shots |
|---|---|---|---|---|
| canal | $0.274 | 3 -> 0 | 3: C1 establishing (1, 11), C2 reaction (2, 4, 5, 7, 9, 10: 28 to 135 mm), C3 POV/detail (3, 6, 8) | 11 + black + title |
| deed | $0.206 | 3 -> 0 | 4: C1 master (1, 9), C2 reverse on Saman (2, 8), C3 reaction on Nimal (3, 5, 7), C4 detail (4, 6) | 9 |

Lab total $2.25. The setups rule held at the first attempt in both: the planner planned positions first and changed
the lens per shot (C2 gives an MS, an FS, an MCU and two CUs; C3 on Nimal an MCU, an MS panned to the table and a
150 mm CU). The deed is the classic triangle (master, two singles, detail). The canal also put the line INTO the
phone (shot 9: she raises the phone, says L1, listens) and the dawn key light moved to the north-east.

New from this run: the canal's C2 stands in the canal water; `access:water` now notes it (advisory: plan waders, a
platform or the bank). The wardrobe check's false hit on "a uniform black image" is fixed (a garment only as a noun).
29 tests. The canal has no side/tracking setup for the walk (C1 covers it from the establishing position); the
person's reference had one (C2 side tracking): worth a look.

## Painted boards with the floor plan (2026-11-28, plans 005)

`board_paint.py --plan`: the floor plan as a second picture, drawn WITHOUT words (water, earth, field, concrete as
colours; each mannequin as a dot of its colour; walks dashed; camera positions as white triangles), rendered locally
by headless Chrome (`floorplan_ref.png`), with one paragraph saying what it is and "never draw the plan". Also fixed in
the panel words: a hand names a prop only once the story has shown it; a panel with nobody in it says so; no "the"
before a person's name; a scene without a views sheet says "the village tea shop behind them".

Deed (9 panels, $0.0595; lab image spend $0.178): the staging holds in every panel: red Nimal at the window side,
blue Saman across the table, the same table and cups, the lamp behind; the wide (1) and the closing FS (9) agree;
the pocket insert (4), the grab (5, from the reaction setup panned to the table) and the hand at the pocket (6) read
as one action. Faults: panel 3 puts the deed in Nimal's hands before he takes it (the words only say he looks at
it: the painter invented it); the singles still look into the lens (2, 7, 8); panel 6 shows the hand AT the pocket
because the plan's prop place still says "at the opening of Saman's chest pocket" while the movement carries it to
the table (the prop timeline does not follow a movement inside a shot: open since run 002). The prompt.txt in
`005_deed_sol/painted_plan/` was rebuilt after painting with the tea-shop wording; the painted words said "as the
location sheet shows it" in three backgrounds.

Canal (11 panels, $0.0703, after the person's `gcloud auth application-default login`; image spend $0.249, lab total
$2.38): the place holds across the board: the sluice gate stands left of the path behind Aruni in 1, 2 and 4, the path
runs into the distance the same way, the rain and the paddy are the same. The wording fixes worked: the cutaway (11)
is empty, and the key is not in Nimal's hand before the reveal (3 shows his hands empty). The setups read: 2, 4, 5, 7,
9 and 10 are all from the reaction setup in front of her (only the size changes), 3, 6 and 8 from her side. Faults:
the singles are painted wider than planned again (5 MCU and 7 CU as full kneeling figures); in 1 Nimal lies near the
camera instead of by the gate; in 10 (her CU waiting, phone at her ear) the phone is still held low (the prop place
lags the movement, as in the deed's panel 6) and Nimal lies far off down the path instead of beside her.

## One board from the MASTER floor plan (2026-11-28, the person's design; budget $0.30, spent $0.081)

`board_master.py`: ONE master floor plan for the whole scene (labelled: places, every person's positions in story
order A1..A4 / N1, the walk, the setups C1 establishing / C2 reaction / C3 POV with the shots they take) attached to
the product's board prompt; each panel's words pick its camera on the plan by name ("Seen from camera C2 ... looks
toward Aruni (pin A4) ... 100 mm ... a medium close-up: head and chest only; the frame cuts at mid-chest"), place
people by their pins, and give the eyeline ("looking at Nimal toward frame left; off the lens, never into the
camera"). Canal plan 005, 11 panels, gpt-image-2 medium.

Against the board painted from words + a text-free plan (painted_plan/), the same plan:
- Eyelines: no panel looks into the lens now (before: panels 2 and 4); heads turn toward Nimal as planned.
- Close-ups hold their framing: 7 (CU, head and shoulders), 9 (MCU with the phone), 10 (CU, phone AT her ear, from
  the front: C2) all as planned. Before: 7 a full kneeling figure, 10 painted from behind her with the phone low.
- Same setup, same world: the C2 panels (2, 4, 5, 7, 9, 10) share the channel, path and paddy behind her.
- Still wrong: 5 (MCU on the kneel) is still a full kneeling figure; in 1 Aruni carries two bags; the key in 6
  lies in an open palm rather than inside his fist.

Repaint v2 ($0.0833; this budget $0.164 of $0.30; v1 kept in `painted_master_v1/`), after the person saw that C1
stands on the west bank across the canal while panels 1 and 11 were painted from ON the path: each panel's camera
words now carry a FRAME LAYOUT worked out from the floor plan (what the camera stands on; what lies between it and
the subject and so fills the foreground; whether each path or water edge runs across the frame, straight away or
diagonally; where fixed things sit and how far; the screen direction of a walk), left out for MCU/CU/ECU/inserts
(no foreground in a close frame), and the views sheet is "how the place looks, never where the camera stands".
Result: 1 and 11 are now from across the canal (water in the foreground, the path and gate on the far bank, Aruni
walking across the frame); 3 (the POV from the path) has the path running straight away as planned; 5 is tighter
(kneeling, waist up). Still off: 2 and 4 (C2 on the concrete sluice, across the water from her) show no water in
front of her, so the C2 panels read as if from the path; 5 has a phone in her hand too early.

## 3D blocking previz, and a board painted over it (2026-11-28)

The research (WebSearch, 2026-11-28): AI storyboards hold the camera angle only when each frame starts from a rough
3D blocking render (FrameForge, Previs Pro, Storyboarder's Shot Generator, PrevizWhiz, ScreenWeaver); text prompts
alone are not followed. `previz.py` renders every shot from its camera with three.js r160 (MIT, vendored in
`vendor/`) in the local headless Chrome (SwiftShader), free: the place as flat areas, paths, blocks and a table from
the floor plan; each person as a jointed mannequin in their posture, body facing as marked and head turned to what
they look at; props as white blocks at the hand, the chest (a pocket) or on the table; the camera at its position,
height and lens (vertical FOV 2·atan(10.125 / mm)), aimed at the subject's head for a CU, the chest for an MS, the
prop for an insert. `runs/<run>/previz/` (grid.png, frame_<shot>.png, review.html).

The renders found two plan faults no text check saw: canal shot 8's camera C3 stands where Aruni's body blocks the
phone; the deed's tea shop has one wall, so the interior reads as open ground.

Board painted over the render (`board_master.py --previz`: image 1 the render grid "keep each panel's composition
exactly", image 2 the canal views sheet "only how the place looks"), $0.0870 (budget $0.251 of $0.30; lab total
about $2.63). Every panel now holds its plan: 1 and 11 from across the canal with the water in front, 3 the POV down
the path, 4 her walk toward the camera with Nimal by the water, the close-ups 7 and 10 with the head turned to frame
left, the key, the phone at her ear. Best composition of all the boards. The cost: the painter copied the render's
toy shapes (capsule bodies, ball heads, cone noses) instead of artist's mannequins. Next: a better previz figure
(neck, shoulders, tapered limbs, hands and feet, a nose ridge), or a neutral grey render the painter takes only the
layout from.

## The master floor plan sheet (2026-11-28, `sheet.py`; free)

Drawn to the practices the research found (a legend on every sheet, accurate scale with a scale bar, north; people
as circles with a facing mark and numbered positions; walks as arrows with their beat; every set-up with the field its
lens covers, its lens and height; the axis; light sources; one overhead per beat; the shot list tied to the plan):
`runs/<run>/floorplan/floorplan.html` (title block, the master drawing with its legend, the set-ups table, the
blocking table, overheads by beat) and `master.png`. Labels now avoid the drawn symbols (pins and camera icons are
obstacles to the label placer); positions on one spot read "N1–4". This sheet is now the master plan every shot
prompt and the board attach (`shot_paint.master_svg`).

## The simple camera floor plan (2026-11-28, `simple.py`; the person's reference; free)

The person: the sheet was over-done ("not lots of details but easy to work with"). `simple.py` draws only what a
crew reads at a glance, in the style of the person's reference: the main areas as clean flat blocks with one big
label (placed at the centre of the part of the area that shows, written up a tall narrow strip), the path as a band
with its name running along it beside the walk, the main objects as plain boxes, people as dots in their mannequin
colour numbered in story order (one dot per spot: "N1–4"), each walk as one orange dashed line, each camera set-up as
a blue triangle labelled C1, C2 ... with at most two dashed arrows to what it films, and a two-name key. No wedges,
lens text, legend, scale or axis. Under it one table: camera, role, shots, lens, coverage. `runs/<run>/floorplan/
simple.html` and `simple.png`. This is now the master plan every shot prompt and the board attach
(`shot_paint.master_svg`); the guide's words match it (an orange dashed line is a walk). `sheet.py` stays as the
detailed version.
