# Action-budget lab (2026-11-18)

How many actions can one clip carry before the video model breaks it? Shot 02 of Love Hour 4 "Anudi arrives" (2B-1,
the car exit) gave the wrong door in every take: she got out of the front door or opened the other back door. The
phone drop of Api Denna E01-S03 failed the same way (plan/2026-11-18b). This lab counts the actions in every Raphael
clip we have and tests a budget against the clips the person has already judged.

The person's decisions (2026-11-18):
1. **Raphael owns it.** The breakdown must respect the budget; an over-budget clip goes back to Raphael to re-plan.
2. **The budget is per clip and has no seconds in it.** The length of a clip follows from how long its action takes.

Free: no model call. `export.py` reads the database read-only.

    .venv/Scripts/python.exe lab/action_budget/export.py           every Raphael clip -> runs/corpus.json
    .venv/Scripts/python.exe lab/action_budget/count.py            the count -> runs/report.md, runs/counts.json
    .venv/Scripts/python.exe lab/action_budget/count.py --hard 1 --moves 3     (the defaults)

## What is counted

The counter reads Raphael's own beats: `intent.what_we_see` for database shots, whose `ir.beats` are the serializer's
windows and repeat a beat, and the clip's `ir.beats` for the lab plans.

| Kind | What | Examples |
|---|---|---|
| **hard** | a change of state the model has to invent | a door opens or closes, gets out or in, sits down or stands up, takes, puts, passes, drops or falls, an umbrella opens, pours, a vehicle stops or pulls away |
| **move** | a simple visible movement | walks off, turns, looks, nods, smiles, leans, reaches, raises |
| state (not counted) | something carries on | keeps, remains, holds, still in her hand, continues |
| **travelling** | a person crossing the frame or walking off | walks, strides, runs, continues right, moves out |

Rules of the count:
- One event told in several verbs is one action: catches the rim, tips, falls, lands = one drop.
- One action said twice is one action: "opens the umbrella" and "the umbrella opens".
- Weather, tears and light falling are no one's action.
- Body parts are not things: lifting the eyes or a hand, taking a breath or steps, a handshake that "takes place".

**The budget (defaults).** A clip is over budget when any of these holds:
1. it has more than **1 hard** action;
2. it has more than **3 actions in all**;
3. it has **a hard action while someone travels**. This is the compound moment: the phone slips while she walks on;
   she gets out and walks off; the umbrella opens mid-walk.

## Result (run of 2026-11-18)

- **572 clips**: 522 from the database (Hiru Short 1/3/4, Love Hour, Love Hour 2, Love Hour 4) and 50 from the lab
  plans (Api Denna v2).
- **41 over budget (7 %)**:
  - 25 with more than one hard action;
  - 18 with a hard action while someone travels, 12 of them for that reason alone;
  - 13 with more than 3 actions.
- **The person's known cases: all 5 agree.**

| Case | Verdict | Hard | All | Budget |
|---|---|---|---|---|
| Love Hour 4 2B-1: the car exit, 8 s, wrong door in every take | bad | 6 | 7 | OVER (2 hard + travel) |
| Love Hour 4 2C-1: the umbrella opens mid-walk | risky | 1 | 3 | OVER (travel) |
| Api Denna E01-S03 3A-1 (saved plan): walk, tuck, slip, walk on | bad | 2 | 3 | OVER (2 hard + travel) |
| Api Denna E01-S03 3A-1 (coverage): the slip alone | good | 1 | 1 | ok |
| Api Denna E01-S03 3B-1 (coverage): the walk-on, phone already down | good | 0 | 1 | ok |

**What the flagged clips are.** Nearly all are the same three shapes:
- **Hands doing a chain of things**: Kasun's tea making (lifts the flask, pours, sets it down, takes the cup) has 3-5
  hard actions in one clip.
- **Getting in or out**: every one of the three car-exit plans is over (Love Hour 2B-1 / 2C-1, Love Hour 2 2C-1,
  Love Hour 4 2B-1).
- **The accident in the walk**: every phone-drop plan that is not coverage, and Kasun's pick-up-and-run.

The hard actions that occur most often in the 572 clips are take/pick up (49), put/place (26), sit/stand (9),
pour/wrap/tie (8) and drop/fall (7).

## Re-plan with the budget (`replan.py`, paid, the person's yes 2026-11-18)

    .venv/Scripts/python.exe lab/action_budget/replan.py dry            free: the faults Raphael would get on the saved plans
    .venv/Scripts/python.exe lab/action_budget/replan.py budget --yes   paid: Raphael re-plans with H-91 + the blocking check

Rule `h91_action_budget.md` (topic `coverage`), with the budget added to `check_stage1` / `check_stage2` as a blocking
fault, in the lab process only. Api Denna v2 scenes from the e2e packets.

| Scene | Plan | Clips | Hard actions | Over budget | Cost |
|---|---|---|---|---|---|
| E01-S02 Anudi arrives | saved, no budget | 7 | 5 | 2 | - |
| E01-S02 | budget | 9 | 3 | **0** | $0.1863 |
| E01-S01 Kasun's tea stall | saved, no budget | 10 | 6 | 2 | - |
| E01-S01 | budget | 12 | 3 | **0** | $0.1813 |

Both finished in 8 calls, about 5 min each. Every video prompt passed the coverage lab's prompt checks.

**E01-S02, the car exit.** One 8 s clip became three:
- 2B-1: the car stops; she stays seated.
- 2C-1: she gets out "through the already-open rear passenger door".
- 2D-1: she nods and walks off.

The umbrella opens in its own clip (2E-1), with her standing; the walk past the three-wheeler is the next clip.

**E01-S01, the tea routine.**
- 1B-1: the pour alone, with the kettle already in his hand.
- The cup is taken in its own two-shot (1C-1), plus an insert (1H-1).

Things to watch:
- Nobody opens or closes the car door on screen. The cut hides it (an ellipsis); the door is left open behind her.
- The first frame of 2C-1 must show the REAR door open with her in the rear seat. That is not checked yet; a board
  would show it.
- The counter missed "arranges one short eat into the display" (1A-1), a small put.

### Run 2: nothing half done (door) + boards (paid, the person's yes 2026-11-18)

H-91 gained "leave nothing half done: a door opened when a person gets out is closed on screen before they walk away".
`replan.py` gained a check (`door_faults`): a door that is opened (or already open) in one clip and closed in none
is a blocking fault.

    replan.py budget --yes --scenes E01-S02 --out replan2           $0.1817, 7 calls
    board.py --run replan2 --scene E01-S02 --yes                     $0.0884 -> runs/replan2/E01-S02/board/sheet.png
    board.py --run replan --scene E01-S01 --yes                      $0.1108 -> runs/replan/E01-S01/board/sheet.png

**E01-S02** (9 clips, 0 over budget):

| Clip | What |
|---|---|
| 2B-1 | the car stops |
| 2C-1 | she gets out beside the already-open REAR door; the board paints her in the rear seat with the rear door open |
| 2C-2 | she closes the rear door, standing, and nods to the driver |
| 2D-1 | she opens the umbrella, standing beside the closed car |
| 2E-1 | the wide walk past the three-wheeler |

Seen on the boards:
- **E01-S02: rain in every panel.** The script starts the rain at 2D-1; the board (like the product's first frame of
  shot 02) has it raining from the car on.
- **E01-S01: two shots painted from behind.** The two close shots of Kasun (1D-1 with his line L6, and 1F-1) are both
  painted from behind, so his face is never seen while he speaks.

Spend for the action-budget lab so far: $0.3676 + $0.3809 = $0.75.

## Limits

- The counter is a word counter: it reads Raphael's English, not the picture. It is checked against 5 known cases
  and a read of the flagged list and of a sample of passing clips, not against rendered takes (the takes table records
  no verdicts).
- The budget numbers (1 hard, 3 in all) come from the person's takes of two scenes. Rendering two or three flagged
  clips after a re-plan is the way to prove them (paid, the person's call).
- Walking that is written as "takes several steps" is not counted as travelling.
