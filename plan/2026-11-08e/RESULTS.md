# Raphael phase 0b: paid runs on Episode 1 (2026-11-08)

All three runs: `gpt-5` high, `max_output` 48k, turn cap 20, Episode 1 (60 s given, cap 90 s). Folders in
`lab/raphael/runs/`, ledger `lab/raphael/runs/ledger.csv`. **Lab total $1.18 of $5.00.** Stopped after three runs for the
person's read, as the plan asks.

| Run | Change (one) | Ended | Turns | Spent | Clips | Seconds | Blocking | Reports left |
|---|---|---|---|---|---|---|---|---|
| 1 | (the first run) | **finish** | 5 | $0.32 | 11 (11 must) | 70 | 0 | 2 overruns (L16, L22 clips), 2 false screen-text |
| 2 | reports named Raphael's to fix (they were filed under "code; nothing to do", against §3.2) | **finish** | 4 | $0.40 | 14 (12 must, 2 should) | 88 | 0 | 4 overruns, 5 false feasibility |
| 3 | an overrun's advice names its blocks and says to split them across consecutive clips | **finish** | 7 | $0.46 | 13 (13 must) | 70 | 0 | 4 false screen-text only |

For comparison, DaVinci on the same scene and model: two runs, $1.74, **neither finished** (40 turns each).

## What the runs show

- **The architecture works.** Every run reached `finish` within 4-7 of 20 turns, under $0.50, with no blocking fault, and never
  over the cap. Each run wrote the whole bin in ONE `put_clips` call and repaired with batch calls (6 clips in one call in
  runs 1 and 3). The voice-only father was never in frame; heard lines were never performed.
- **Run 2: told to fix reports, Raphael filled the headroom.** It answered a multi-block overrun (c09 over b15-b17, 8.9 s in
  an 8 s take) by adding alternate angles over the same blocks, which overrun the same way, and the bin went 70 s -> 88 s.
  This is the plan's first risk (the headroom used as a goal), triggered by a vague fix sentence, not by the length prompt.
- **Run 3: the concrete advice worked.** Overruns cleared by splitting blocks across consecutive clips; it added two clips,
  then removed a should clip it no longer needed, and finished at 70 s.
- **The remaining reports are false.** The shared feasibility regex (`contracts.david.checks.FEASIBILITY`, screen text)
  matches the word "reads" ("so the drop reads without cutting", "the stall reads softly"). Product code, not changed here.

## For the person's read

1. **Coverage or a cut?** Runs 1 and 3 are 13 must clips and no alternates, inserts or B-roll: close to the length rule
   (target = the given length, "the must clips that build the intended cut, little more"), but close to a finished cut too,
   which is what Adam / David / Jonathan already make. If the post team wants more angles, the room is there (70 of 90 s);
   the prompt would have to ask for a few named extras (a reaction where a line lands, one insert, one B-roll) instead of
   "allowed, not expected". That is the person's call, not a lab fix.
2. **The screen-text regex** fires on "reads"; fixing it is a change to David's shared checks (all planners).
3. Then: the post team's sample (`run.py pick --run lab/raphael/runs/3-gpt_5_high_episode1`), D1, D7, R3.
