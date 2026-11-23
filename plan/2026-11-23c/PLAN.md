# Scene board: the whole opening state, and props as stand-ins (plan/2026-11-23c)

Revision 2 (2026-11-23: the person answered Q1-Q5 as D4-D8). Nothing in this plan is built. It changes the Scene board (plan/2026-11-14, -17, -22;
`docs/scene_board/README.md`). Read this file whole, then that README, `src/libs/contracts/board.py`,
`src/libs/hiru_ai/systems/frame_render/board.py` and `src/libs/hiru_ai/agents/board_writer/prompts/system.md`.

## 0. Rules for the chat that builds this (read before anything)

- **Prove before building** (the person's rule). Phase 0 is a lab on the person's own scene with a hard budget. No
  product phase starts before the person has read the lab and said yes.
- **Ask before every paid call** (image or model), each time. Tests run with `OPENAI__API_KEY=` blank and fakes only.
- **Port the lab exactly.** What the lab proves (bundle, writer rules, stand-in wording) goes into the product
  unchanged. List any change before making it.
- **No enable switches.** The new board runs whenever a model can be called.
- **Never stash or reset** the person's tree (other plans' work is uncommitted); compare in a separate worktree.
- **Never edit an applied migration.** This plan expects no schema change (cells and the writer live in JSON columns);
  if one turns out to be needed, it is the next version.
- Two repos: the backend (this one) and `..\hiru-ai-studio-interface` (its `CLAUDE.md` binds).

## 1. What is wrong today

A tall board (part 1 of 2, 9 panels) of a rainy-lane scene: Red hands Blue a phone; Blue holds an umbrella and a
handbag.

| Shot | Fault |
|---|---|
| 2, 3, 4, 5 | The umbrella floats: its shaft stands with no hand on it |
| 7, 8 | Blue reads as having three arms: phone in one hand, a hand at the waist, the bag on a third arm, the umbrella still overhead |
| 1, 3 | Red's feet sit on the edge of the drain grate, which reads as floating over a step |
| 1 → 7 → 8 | The bag changes arm and the umbrella comes and goes between panels |

**Cause: the board writer is not given most of what the plan already knows, so it guesses.** The stager writes each
person's hands, facing and props set down block by block. Code turns that into each shot's opening state. The
planner writes each shot's performance and props. Then `writer_bundle()` and `shot_plan()` (`contracts/board.py`)
pass on only a part of it:

| Source | What exists | Reaches the board writer today |
|---|---|---|
| `stager` → `scenes.staging.marks` | who, zone, block, posture, holding | ✅ |
| | `facing`, `frame_side`, `left_hand`, `right_hand`, `condition`, `wearing` | ❌ |
| `stager` → `scenes.staging.props` | props in no hand: prop, `where`, `state`, from which block | ❌ |
| code (ledger) → shot `intent` | `opens` (the opening state: place, posture, hands, condition, props), `ends` | ❌ |
| | `what_we_see`, `emotional_beat`, `heard_only`, `voice_source` | ❌ |
| | story, purpose, on_screen | ✅ |
| `raphael_planner` → shot `ir` | setting, lighting, cinematography, first_frame composition and subjects, subjects' action and position, beats' action | ✅ |
| | beats' `performance` (face and hands) and camera sentence | ❌ |
| `raphael_breakdown` → `scenes.raphael.breakdown.shots[]` | `blocking`, `performance`, **`props`** (what is held, worn, wet, in the way), `light`, `must_read` | ❌ |
| `raphael_planner` → `scenes.raphael.clips[]` | `summary`, `over` (who is shown while a line plays), angle | ❌ |
| `raphael_planner` → `scenes.raphael.edit.treatment` | `geography` | ⚠️ cut to 300 characters, as "axis" |
| | `colour_script` (light and grade per sequence), `key_image`, the moments | ❌ |
| `breakdown_canon` → canon card | person gender, age (height and build for the mannequin) | ❌ (phase 0 confirms the keys) |

It also matters that:
- The board's tall part held 9 panels; the lab measured only 6 tall panels as clean (`lab/portrait_board` run_001).
- Props are matched to canon by name in the plan text: "smartphone" against a canon "phone" is missed (frame refs
  audit, 2026-11-18).
- Nothing checks the writer's panels against the ledger, and nothing looks at the painted board.

## 2. What the person decided (2026-11-23)

- **D1 Only the canon look is left out.** People are mannequins, so a person's face, hair, look and outfit stay out of
  the board (correct today). **Everything else the plan knows reaches the board writer.**
- **D2 Props are stand-ins, like the mannequins.** A phone, a car or an umbrella is not painted as the real object on
  the board. It is painted as a plain representing item that keeps the prop's place, size, shape and the hand that
  holds it. The first frame turns it back into the real prop from its sheet, as it does for people.
- **D3 The location stays real.** The location plate is attached and the place is painted for real, as today.

Answered by the person (2026-11-23, revision 2):

- **D4 The stand-in's look: matte white clay**, the prop's real size and outline, no screen, buttons, logo, text,
  pattern or colour. Not grey: grey is how the board paints unnamed background people (`STAND_INS` turns grey figures
  into pedestrians).
- **D5 Vehicles too:** a car is a full-size white clay car. A vehicle someone sits in keeps its doors, windows and
  seats as shapes, so the seated mannequin still reads.
- **D6 Tall parts of at most 6 panels** (the measured size), not 9: `ONE_IMAGE_TALL = PART_SIZE_TALL = 6`. A 9-shot
  scene paints 2 pictures.
- **D7 A pin version.** The pin (`plan_pin`) gains what the writer now reads, under a new version; a cell pinned with
  the old version is compared with the old hash, so painted boards stay current until their shot really changes.
- **D8 The lab cap is $1.50** (§4).

## 3. The design

### 3.1 What the writer reads (the bundle)

The writer still reads the scene once (one call, same tier). For each **painted shot** the plan gains:

| New field | From | Note |
|---|---|---|
| `opening_state` | shot `intent.opens` | the truth for the panel: posture, each hand, condition, props set down |
| `marks` | `scenes.staging.marks` on the shot's first block, whole | facing, frame_side, left_hand, right_hand, holding, posture, condition, wearing |
| `props_down` | `scenes.staging.props` in force at the shot's first block | where each prop not held is, and its state |
| `beats[]` | `ir.beats` | action **and** performance and the camera sentence (today: action only) |
| `breakdown` | the `raphael_breakdown` shot whose blocks overlap the clip | blocking, performance, props, light, must_read |
| `summary`, `over`, `angle` | the Raphael clip with the shot's slate | |
| `heard_only` | `intent.heard_only` | people only heard (the caller on the phone): never drawn |

For the **scene** the bundle gains the treatment's whole `geography` (no 300-character cut), its `colour_script` and
`key_image`, the staging `zones`, and for each person their gender and age (no look, no outfit, D1).

`ends` is not sent: a panel is the shot's first frame. The writer's input grows; phase 0 measures it against
`WRITER_MAX_OUTPUT` and the tier's input limit.

### 3.2 What the writer must do (new rules in `system.md`)

- **THE OPENING STATE IS THE TRUTH.** `opening_state` and `marks` decide where everyone is, how they stand and what
  each hand holds. The plan's prose may not move a thing to another hand. A disagreement goes in `conflicts`.
- **TWO HANDS.** Every person has two arms and two hands. Each panel names, for every person shown, what the left hand
  and the right hand hold (or "empty", or where the hand rests), and which side of the picture each is on (the rule
  already there: a body side is also a screen side). One thing per hand. A bag hangs from a named shoulder or forearm.
  A person given more than they can hold: the ledger's choice is kept, and the rest goes in `conflicts`.
- **EVERYTHING RESTS ON SOMETHING.** Feet stand on a named surface ("on the wet pavement, a step from the drain
  grate"). A set-down prop sits on a named surface. A held prop's grip is said ("the umbrella's handle in her right
  fist, the shaft rising past her shoulder"). Nothing floats.
- **ONLY HEARD IS NOT SEEN.** A person in `heard_only` is never in a panel.
- **PROPS ARE STAND-INS** (D2): each prop is written as "the clay <prop name>" with its size, outline, hand and side.
- New panel fields, so code can check them and the first frame can use them: each `people[]` entry gains
  `left_hand`, `right_hand`; each panel gains `props[]` (`name`, `held_by` + hand, or `rests_on`, `frame_side`).

### 3.3 Props as stand-ins (board image and first frame)

- `board_prompt` / `panel_prompt` gain a `prop_line` beside `mannequin_line`: "Every prop is a plain matte white clay
  stand-in of the real object's size and outline: <names>. No screens, buttons, logos, text, patterns or colours on
  them. The place, the light and the weather are a real photorealistic film still."
- The board picture no longer gets the prop sheets (the writer still reads them, for shape and size). The location
  plate stays (D3). The freed picture slots stay empty.
- The first frame from its panel (`frame_sections`) gains `PROP_STAND_INS`, the props' twin of `STAND_INS`: every
  white clay shape is the real prop from its sheet, kept in exactly its place, size, hand and angle; no clay remains.
  `unprop()` turns "the clay umbrella" back into "the umbrella", as `unmannequin()` does for people. The frame's
  vision check also looks for a leftover clay prop.
- The prop name match is widened so "smartphone" finds the canon "phone" (the canon's names and aliases).

### 3.4 A free code check after the writer

Before anything is painted, code compares the writer's answer with the ledger (no model call): a hand holding what the
ledger does not give it, a person with more than two held things, a prop with no hand and no surface, a `heard_only`
person in a panel. Each finding is added to the board's `conflicts` (shown on the board card as today). Phase 0 says
whether a one-panel repair is worth it; this plan does not add one.

### 3.5 Not in this plan

A vision check of the painted board (extra limbs, floating things), repainting a failed panel alone. If the lab shows
the painter still breaks grips it is given, that is the next plan.

## 3.6 Phase 0 findings: the free read (2026-11-23, scene de75bc31, board version 8)

Read-only reads of the scene, its 14 shots, its boards and its scene looks. What they show changes this plan:

1. **The plan is clean.** Raphael's IR names the hands in every shot: "handset in her right hand", "empty hands at his
   sides". **No shot mentions an umbrella or a bag.**
2. **The umbrella comes from the scene look, not the plan.** `scene_looks.condition` for Anudi (`breakdown_looks`)
   is "Holding the open umbrella; shoe toes remain lightly damp." The tan handbag comes from her look (the look table
   was not read; phase 1 confirms). The board passes the condition to the writer as `scene_condition`. The writer then
   put both into `world` "throughout" and into all 14 panels. A held thing is an action, not a condition: the same
   fault as plan/2026-11-13e §2, which keeps the condition out of the first frame but not out of the board.
3. **This breaks continuity downstream.** The board shows an open umbrella in every shot. The plan, the video prompts
   and the frames' own text have none. `world` also says "no rain is falling", yet the umbrella is open.
4. **The writer DID assign the hands, and the painter ignored them.** Every panel says: umbrella in the near-side left
   hand, bag over that left forearm, phone in the far-side right hand. The picture still floats the umbrella and
   adds an arm. So better text alone is not enough. Loading one arm with an open umbrella and a bag is also hard for
   the image model.
5. **The ledger is empty here.** The stager's `left_hand` / `right_hand` are "" on all 4 marks, it lists no props set
   down, and `intent.opens` is missing on all 14 shots. Passing those fields through (§3.1) would add nothing for this
   scene; the hands come from the IR, which already reaches the writer. Why `opens` was never written (staging made
   before plan/2026-11-09, or the ledger path skipped) is for phase 1 to find out.
6. The tall part held 9 panels (D6 now makes it 6). The board was painted at LOW.

What follows for the design:

- **F1 What a person holds comes from the plan.** A held thing that comes only from the scene condition or the look
  (an umbrella, a bag carried in a hand) is not painted. The writer reports it in `conflicts` ("the look holds an
  open umbrella; no shot does"). Worn things (a bag on the shoulder, a watch) stay part of the look. This needs the
  person's decision (Q6).
- **F2 The vision check comes into this plan** (it was §3.5, "not in this plan"). The painter ignored grips it was
  given, so a cheap check per cut panel (extra or missing limbs, a held prop with no hand on it, nothing underfoot)
  repaints a failed panel alone, once, through `_paint_panel`. The lab measures whether it is needed after stand-ins.
- **F3 The ledger is fixed at its source.** When the stager leaves the hands empty or `opens` is missing, the board
  reads the IR's `first_frame.subjects` and `subjects[].position`, as it does today. Phase 1 finds why this scene has
  no `opens`.

### Q6 for the person

The script never mentions an umbrella. `breakdown_looks` decided Anudi holds an open umbrella in this scene. Should a
held thing from the look or condition be **left out of the board** unless a shot's plan holds it (recommended: the
plan decides what is in a hand), or should the planner be made to carry it into every shot?

## 4. Phase 0: the lab (paid, the person's)

`lab/board_state/`, built from `lab/storyboard/fetch.py` and `run.py`, on the rainy-lane scene above. Read-only reads
of its data first ($0): staging, every shot's `intent.opens`, `scenes.raphael`, the stored board's `prompt` and
`writer`. That answers whether the stager filled the hands and whether the board lost them.

| Run | Bundle | Writer rules | Props | Pictures |
|---|---|---|---|---|
| A | today | today | real | none: the stored board is the baseline ($0) |
| B | §3.1 | §3.2 | real | the board (2 parts, LOW) |
| C | §3.1 | §3.2 | stand-ins §3.3 | the board (2 parts, LOW) + first frames of 2 shots with a prop in hand (MEDIUM) |
| D | as C, plus F1 (no umbrella, plan decides the hands) | §3.2 | stand-ins | the board (parts of 6, LOW) + the vision check of F2 on its panels |

Measured per panel, by the person reading it: floating things, extra or missing limbs, hands against the ledger, feet
on a surface, the bag and umbrella across panels; for C, whether the frames turn the clay back into the real phone and
umbrella. Expected cost: about $0.15-0.18 a board part, about $0.13-0.19 a frame. B + C come to about $1.10. D (3
parts of 6, plus about 14 vision checks) is about $0.55 more, which goes over the **$1.50 cap** (D8). Recommended
order: C, then D, and B only if money is left (the phase 0 findings make B the least informative). Each run is asked
for before it is made.

## 5. Phases after the lab (offline, $0)

1. **Bundle**: `shot_plan`, `writer_bundle` and `Board` read the fields of §3.1 (shot → clip by slate, clip →
   breakdown shot by blocks). Tests with stored rows of the lab scene.
2. **Writer**: the rules of §3.2 in `system.md` (the lab's words), the new panel fields in `schema.py` and
   `contracts.board.Panel` (old boards without them still load).
3. **Stand-ins**: §3.3 in `board_prompt`, `panel_prompt`, `frame_sections`, `unprop`, the vision check's words, the
   widened prop match.
4. **Check**: §3.4, into `conflicts`.
5. **Parts and pins**: D6 (tall parts of 6) and D7 (the pin version).
6. **Docs**: `docs/scene_board/README.md`, `docs/AI_CATALOG.md`; the interface needs no change unless the person wants
   the hands shown on a cell.
7. **Live check** (paid, the person's): one whole board and two frames of the lab scene in the product.
