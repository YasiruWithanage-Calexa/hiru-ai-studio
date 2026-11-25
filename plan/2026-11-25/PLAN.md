# Board hands: the side rule turned the right way, and a board check that sees a third arm (plan/2026-11-25)

Revision 1 (2026-11-25). Plan only: nothing is built. Two fixes, from the person's look at scene 4's board v21
(Love Hour, scene `de75bc31`, "A conversation that changes everything", painted 2026-11-24 at `low`): **A** the board
writer's rule for which side of the picture a hand is on is backwards; **B** the board check (`board_inspector`) passed
every panel with a third arm. It follows plan/2026-11-23c (board opening state, `board_inspector`) and 24 to 24d
(location views, vehicles, place views by type, fixed marks), built and committed.

Read this file whole, then `src/libs/hiru_ai/agents/board_writer/prompts/system.md` (the "A BODY SIDE IS ALSO A
SCREEN SIDE" rule), `src/libs/hiru_ai/agents/board_inspector/` (prompt, schema, `agent.py`, `component.yaml`),
`src/libs/hiru_ai/core/agents.py` (`_structured`: how pictures reach a model), `src/libs/hiru_ai/systems/frame_render/board.py`
(`_check_panel`, `_faults`, `_mend`, `_check_plate`) and `contracts/board.py` (`hands_text`, `fix_line`).

## 0. Rules for the chat that builds this

- **Ask before every paid call**, each time. Tests run with `OPENAI__API_KEY=` blank and fakes only. The lab (phase B0)
  is the only paid phase before the build; the live check (phase 5) is the person's.
- **Port the lab exactly** (B). The prompt words, the schema and the picture setting that win in `lab/board_hands`
  go into the product unchanged; list any change of words before making it.
- **No enable switches.** **Never stash or reset** the person's tree. No schema change is expected.
- **No new agent** (the Hiru AI pattern): the existing `board_inspector` looks better; code decides what counts as
  a fault.
- Two repos: the backend (this one) and `..\hiru-ai-studio-interface` (its `CLAUDE.md` binds). No interface change
  is expected (§4).

## 1. What the person saw (board v21)

Only Anudi (blue) is wrong. She carries three things: the umbrella, the handbag and the phone. The writer's words are
the same, and sound, in every panel: left hand the umbrella, the handbag on the left forearm, right hand the phone.

| part / panel (shot) | painted | the check said |
|---|---|---|
| 1 / 4 (**shot 4**) | three hands: umbrella at the chest, phone at the waist, a third arm hanging empty at the hip | ok, no problems |
| 1 / 5 (shot 5) | three hands, as shot 4 | ok, no problems |
| 2 / 2 (shot 7) | canopy floating with no shaft; the other hand holds a loose white stick (the cut umbrella handle) | ok, no problems |
| 2 / 3 (shot 8) | phone at the ear, plus a fist at the elbow and a hand flat on the chest: three or four hands | ok, no problems |
| 2 / 5, 2 / 6, 3 / 2, 3 / 3 | right: the umbrella hand also carries the bag on its forearm, the phone in the other hand | ok |

So the image model can paint the pose; it fails about 4 panels in 10 that show all three things, and the check
lets every failure through. A panel the check passes is never painted again.

## 2. Fix A: the side rule

### 2.1 What is wrong

`board_writer/prompts/system.md` lines 67-75 say: "someone in profile facing screen right shows their left side to
the camera, so their left-hand things are on the near side". That is backwards. A person facing screen right shows
their **right** side to the camera (turning from facing the lens to facing screen right is a turn to their own left,
which swings the right shoulder toward the lens). The postman example is wrong the same way: a satchel on the left
shoulder of a man walking screen right is on his **far** side. The last clause ("facing the camera, their left is
frame right") is right, and so is the waiter example.

The writer follows the rule faithfully, so v21's words contradict themselves. Anudi faces screen left, so her left
side is toward the camera, but every panel says "blue's **far-side left** hand grips the umbrella … **near-side
right** hand holds the phone"; Kasun, facing screen right, gets "far-side right hand". The image model cannot tell a
faceless mannequin's left from its right (the rule's own first sentence), so it reads the near/far words, and the
words and the body disagree.

What this surely breaks: every body side that matters (a canon bag on the left shoulder, a ring hand, a cast arm) is
put on the wrong side of the picture whenever the person is side-on. What it may also do, not proven: give the image
model two places to put a hand ("left" and "far side"), one more push toward a third arm. Phase 5 shows whether
fixing A alone changes the arm count.

### 2.2 The change

Words only, in `board_writer/prompts/system.md` (the chat lists the exact new words before writing them):

- The rule: "someone in profile facing screen right shows their RIGHT side to the camera, so their right-hand things
  are on the near side, toward the lens, and their left-hand things on the far side, partly hidden by the body;
  facing screen left it is the other way round; facing the camera, their left is frame right." Add one sentence the
  writer can check itself with: "a person facing screen left holds a thing in the left hand on the near side".
- The postman example turned the right way: "a postman walking screen right with the satchel on his left shoulder
  has 'the satchel on his far side, behind his body, its strap across his near shoulder only where it shows'". Keep
  the waiter example.
- One example of a person holding two things in one hand (the umbrella hand that also carries a bag on its forearm),
  said as one hand: "her near hand grips the umbrella shaft, the bag's handles over the same wrist", so the image
  model does not give the bag a hand of its own. From another story (not Anudi): a market woman with a basket and a
  parasol.

Tests and evals (free):
- `board_writer/evals/cases.yaml`: a case with a person facing screen left whose plan holds a thing in the left hand;
  the expected panel words name the near side. And one facing screen right, right hand, near side.
- `tests`: a prompt test that the old sentence is gone ("facing screen right shows their left side" never in the
  prompt), so a later edit cannot bring it back.

No code reads near/far today (`PanelPerson` has no facing field), so there is no free code check of the writer's
sides. Moving the side sum into code (the stager's `facing` plus the hand gives the picture side) is a bigger change;
it is listed as Q3 and is not in this plan.

## 3. Fix B: a board check that sees a third arm

### 3.1 Why the check misses it (found, free)

1. **It sees a thumbnail.** `core/agents.py` `_structured` sends every picture with `"detail": "low"`. OpenAI then
   shrinks the picture to fit 512 × 512. A tall panel cut from a low board is about 337 × 765, so the check sees
   about 225 × 512: a mannequin's forearm is a few pixels wide and a third one does not stand out. Every image agent
   shares this setting (`board_inspector`, `frame_inspector`, `views_writer`, `board_writer`).
2. **It answers with flags, not counts.** The schema asks `extra_limbs: bool` first; nothing makes the model count
   arms before it answers. Counting first is the usual way to get a vision model to see an extra limb.
3. **A small model with no thinking.** `model_vision` is `gpt-5-mini` with no reasoning effort (`core/settings.py`).
4. **The board is painted at `low`.** Not the check's fault, but it makes the faults more frequent; the person wants
   low and medium only, so the check has to carry it.

### 3.2 The lab (phase B0, paid, the person's yes): `lab/board_hands`

Small, fixed, on the person's own panels (as `feedback-prove-before-building`):

- **Input** (free, read-only): v21's panels exactly as the check saw them, each cell's own picture (a sheet cell
  cropped by its `box`, a repainted cell from its own path), with the same `people`, `panel`, `hands` and view crop
  `_check_panel` sends. Ten panels: the four bad ones of §1 and six good ones (shots 1, 10, 11, 12, 13 and one more
  the person picks). **The person confirms the bad/good labels by eye before any paid call**; the table in §1 is
  this chat's reading.
- **Runs**, each over all ten panels, three times (a check is not steady):
  - `R0` today's check, unchanged (`detail: low`): must reproduce the misses, or the lab is not measuring the
    product.
  - `R1` the same with `detail: high` (the panel is sent at about 768 × 1744, which it already is in substance).
  - `R2` `R1` plus count first: a new first output field, per mannequin in frame, `arms` (whole or partial arms
    seen), `hands` (hands seen), `left_hand_holds`, `right_hand_holds`, before the flags; the prompt's LIMBS rule says
    to trace each arm from its shoulder to its hand and count before answering.
  - `R3` (only if `R2` misses any bad panel) `R2` with `reasoning_effort: low`.
  - `R4` (only if `R3` still misses) `R2` on the next model up, to see whether the model is the limit.
- **Measure**: bad panels caught (the right fault named), good panels passed. **Pass**: all four bad panels caught in
  at least two of three repeats, and at most one false alarm over the 18 good checks. A false alarm costs one panel
  repaint, so a few are cheaper than a miss.
- **Cost**: a `gpt-5-mini` check at `detail: high` is about 2,000 to 3,000 input tokens: under $0.002 a call.
  `R0` to `R2` are 90 calls. **Cap $0.50** for the lab, `R4` included.
- Written up in `lab/board_hands/FINDINGS.md`, as the other labs.

### 3.3 The product change (after the lab, the winning run ported exactly)

Expected shape, if `R2` wins; the lab decides the details:

1. **A picture's detail per agent.** `component.yaml` gains `image_detail: high | low` (default `low`, so every other
   agent is unchanged); `core/agents.py` `_structured` passes it on. `board_inspector` sets `high`. `frame_inspector`
   is NOT changed here (Q2).
2. **Count first.** `board_inspector/schema.py`: `counts: list[Count]` (`mannequin` colour, `arms`, `hands`,
   `left_hand_holds`, `right_hand_holds`) as the FIRST field of `Output`; the prompt's LIMBS rule says to count before
   answering (the lab's words). The agent's `version` goes 2 → 3.
3. **Code decides, too.** `frame_render/board.py` `_faults`: a mannequin with `arms > 2` or `hands > 2` is a fault
   ("blue: three hands") even when the model set `extra_limbs` false. Fewer than two is NOT a fault from the counts
   alone (an arm cut by the frame or hidden by the body), only from the flag. Pure, tested.
4. **The repaint is told the count.** `kit.fix_line` already carries the problems; the count line ("blue: three
   hands; paint two: the umbrella hand also carries the bag on its forearm") comes from the counts and the panel's
   `hands`, so the second painting knows which hand is the extra one.
5. **The plate is checked the same way**: `_check_plate` uses the same agent, so it gets 1 to 3 for free.
6. If the lab needs `R3` or `R4`: `reasoning_effort` or the model for the `vision` tier in `core/models.yaml` /
   `core/settings.py`, said in `IMPLEMENTED.md`. That tier is shared with `frame_inspector`; Q2 decides.

Tests (fakes only): the agent sends `detail: high` and a `low` agent still sends `low`; `_faults` from counts (three
hands → fault; one arm → no fault; counts absent, an old answer → today's behaviour); `fix_line` with a count;
`board_inspector` evals gain the count field. Old saved cells keep their `check` as it was (only new checks change).

## 4. The interface

None expected. A panel's check is not shown on its own; what the check still sees after the one repaint already
reaches the board's `conflicts` ("Shot 9: the board check still sees …"). The board will simply have more panels
painted again. No costs are shown (`CLAUDE.md`).

## 5. Phases

| phase | what | paid |
|---|---|---|
| A1 | the side rule and its examples, the two-things-in-one-hand example, eval cases, the prompt test | no |
| B0 | `lab/board_hands`: export v21's ten panels (free), the person confirms the labels, then runs `R0` to `R2` (and `R3`/`R4` only if needed) | yes, cap $0.50, the person's yes |
| B1 | `image_detail` per agent in `component.yaml` / `core/agents.py` | no |
| B2 | the count-first schema and prompt (the lab's words), `_faults` from counts, `fix_line` with the count | no |
| B3 | (only if the lab needed it) the vision tier's reasoning effort or model | no |
| 4 | checks: `ruff`, `mypy`, `lint_imports`, `hiru_ai validate`, `hiru_ai catalog --check`, the board tests, the two agents' evals offline | no |
| 5 | live check (the person's): **Rewrite and repaint** scene 4 (the writer must write the sides again); look at shots 4, 5, 7, 8; count the panels painted again and what `conflicts` says | yes, the person's |

A1 does not wait for B0; the two can be built in either order. Phase 5 tests both together; if the person wants to
know what A did on its own, a Rewrite and repaint after A1 only (before B) answers it, at one more board's price.

## 6. Questions for the person

- **Q1** The lab's labels: the four bad and six good panels of §1, by eye, before B0 spends anything.
- **Q2** `frame_inspector` (the first-frame check) has the same `detail: low`. Turn it to `high` too, now or after
  this lab shows the gain? Recommended: after, as its own small step, because first frames are larger pictures and
  cost more tokens at `high`.
- **Q3** Later, not in this plan: let code work out the picture side from the stager's `facing` and the hand, so the
  writer never does the sum. Worth a plan if A1 is not enough.
- **Q4** Anudi's ground mark is still missing on v21 ("the board writer gave no ground mark for Anudi"), after the
  24d fix. Not hands; listed so it is not lost. Its own small look, or folded into phase 5's re-read?
