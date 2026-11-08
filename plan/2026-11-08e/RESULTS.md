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

# Phase 0d: stage 2 paid passes (2026-11-08)

From run 3's must bin (13 must, 70 s), `gpt-5` high, 48k out, turn cap 12. Stage 2 total **$0.26 of $1.50**; lab total
**$1.44 of $5.00**.

| Pass | Change (one) | Ended | Turns | Spent | Cinematic clips | Seconds | Blocking | Must clips changed |
|---|---|---|---|---|---|---|---|---|
| 4 | (the first pass) | **finish** | 6 | $0.26 | 4 (c15-c18) | 88 of 90 | 0 | none |

The four clips (`lab/raphael/runs/4-stage2_gpt_5_high_from3/bin.html`):

| Clip | Moment | Role, technique, take | Anchor, blend | Why (the model's) |
|---|---|---|---|---|
| c15 1L-1 | 1 | insert, shallow_isolation, 6 s | c01, cut_in | steam against cold rain: the stall's heartbeat |
| c16 1M-1 | 3 | insert, slow_motion, 4 s | c03, cut_in | the phone's splash: chance arriving |
| c17 1N-1 | 6 | cutaway, foreground_framing, 4 s | c06, under_line (L11) | what she notices in his stall |
| c18 1O-1 | 7 | insert, push_past_foreground, 4 s | c07, under_line (L13) | his words tied to damp notes and the cash box |

What the pass shows:

- **The shape works.** It finished in 6 of 12 turns, one clip per chosen moment (4 of 11 moments), all anchored, silent and
  different from their anchors; no must clip touched. Every clip has a blend note naming where it goes and over whose audio.
- **Repairs were all clock fits** (turns 2-5): inserts that listed action blocks did not leave room for handles. It fixed
  them by changing takes and handles, several clips per call.
- **It used the headroom almost entirely: 88 of 90 s** (the prompt says the room is allowed, not expected). One 6 s insert
  (c15) is the largest. This is the plan's first risk again, on the stage built to use the room.
- **Nothing on the big turns.** No clip on the call (moment 8), her exit (10) or the closing VO (11), the moments where the
  story turns most; no establishing, drone or transition. All four are inserts / cutaways in the first half.
- **Small additions to check:** the cash box is in the scene's objects, but "damp rupee notes" (c18) and tea steam (c15) are
  details the script does not name: within the place or a new object?

For the person's read: are these cinematic, and could post blend them? Should the next pass (one change) ask for the turning
moments first (8, 10, 11), or cap stage 2 below the whole headroom?

## Pass 5: "let it cover the scene" (the person's three changes, 2026-11-08)

Change (one, as the person set it after pass 4): stage 2's cap 2x the scene (120 s), `finish` asks for a review of every
moment (turning moments first) with a list of what moments usually earn, 3 a moment, no per-scene guide, and the
screen-text rule removed for Raphael (prompts and Raphael's checks; the shared check in `contracts.david` is unchanged).

| Pass | Ended | Turns | Spent | Cinematic clips | Seconds | Blocking | Reports | Must clips changed |
|---|---|---|---|---|---|---|---|---|
| 5 | **finish** | 4 | $0.27 | 8 (42 s) on 7 of 11 moments | 112 of 120 | 0 | 0 | none |

Stage 2 total $0.53 of $1.50; lab total $1.70 of $5.00. Page: `lab/raphael/runs/5-stage2_gpt_5_high_from3/bin.html`.

| Clip | Moment | Role, technique, take | Anchor, blend |
|---|---|---|---|
| c15 1M-1 | 8 the call | insert (the ringing phone, ECU), shallow_isolation, 4 s | c13, cut_in |
| c16 1N-1 | 8 the call | atmosphere (rain on the umbrella), slow_creep, 8 s | c08, under_line |
| c17 1P-1 | 3 the drop | insert, slow_motion splash, 4 s | c03, cut_in |
| c18 1Q-1 | 4 the grab | insert, foreground_framing, 4 s | c04, cut_in |
| c19 1R-1 | 2 the vow | atmosphere (tea steam), tilt_reveal, 6 s | c02, under_line |
| c20 1S-1 | 1 opening | atmosphere (puddle), top_down, 4 s | c01, open |
| c21 1T-1 | 10 her exit | atmosphere (empty frame), pull_back, 4 s | c11, close |
| c22 1U-1 | 11 VO close | atmosphere (dripping awning), locked_off, 8 s | c12, under_line |

What it shows:

- **The changes worked.** It reviewed the turning moments first (8, 11, 3 ...), put the phone close-up on the call, and
  covered the exit and the VO close, which pass 4 missed. Each "no" has a reason (moments 5, 6, 7, 9). 4 turns, one repair
  round (clock fits), no report left: the false screen-text reports are gone.
- **Five of eight are rain-texture atmosphere clips**, two of them 8 s. Same idea in different frames; no held reaction
  (her face on the call, his face as she leaves), no drone, no transition pair, though the list names them.
- **It again used most of the room** (112 of 120 s); 8 s atmosphere takes are where it went.
- Moment 8 got 2 of the 3 allowed; 9 (her parting line) none.
