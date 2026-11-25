# lab/board_hands: does the board check see a third arm? (plan/2026-11-25 B0)

2026-11-25. Paid with the person's yes ("run lab B0"), cap $0.50. **Spent $0.451** (booked; $0.06 of it is an
estimate for an R3 run cut off by a session end that saved no results, counted so the cap stays safe).

## The case

Scene 4 (Love Hour, `de75bc31`), Scene board v21, painted at `low`. Ten panels exactly as `_check_panel` sent them
(`export.py`: the cell's own picture, `people`, `panel`, `hands`, the view crop). Labels by eye (2026-11-25):

- bad: shot 4 (three hands), 5 (three hands), 7 (canopy with no shaft into a hand, loose white stick), 8 (three or
  four hands)
- good: shots 1, 3, 10, 11, 12, 13

## Runs (gpt-5-mini unless said; three repeats unless said)

| run | what | bad caught (limb / floating) | good sent to repaint | $ |
|---|---|---|---|---|
| R0 | today's check (`detail: low`) | 1/4, 0/4, 0/4 (shot 8 once) | 0/6, 0/6, 0/6 | 0.087 |
| R1 | `detail: high` | 0/4, 0/4, 0/4 | 1/6 (11), 1/6 (12), 0/6 | 0.080 |
| R2 | R1 + count first (`counts` before the flags; LIMBS told to trace and count) | 0/4, 0/4, 0/4 | 0/6 ×3 | 0.118 |
| R3 | R2 + `reasoning_effort: high`, once | 0/4 | 0/6 | 0.106 |
| R4 | R2 on gpt-5 | not run: about $0.09 on the four bad panels alone would pass the cap | | |

**No run passes** (pass = all four bad caught in two of three repeats). R0 reproduces the product's misses, so the lab
measures the product.

## What the lab shows

1. **The check reads the answer, not the picture.** In R2 and R3 every bad panel is counted "arms 2, hands 2", and
   the words of each hand are the expected HANDS line copied back: "left hand gripping the umbrella shaft (the
   handbag hangs from the left forearm) | right hand gripping the phone at waist height" on shot 4, which has a third
   arm hanging empty at the hip. Shot 7's canopy with no shaft becomes "far-side left hand gripping the clay umbrella
   shaft". The `<expected>` block (THE PANEL SHOULD SHOW and HANDS) tells the model what is there, and it agrees.
2. **More pixels did not help** (R1): the same misses at `detail: high`, plus two false alarms. The thumbnail
   (`detail: low`) is real but is not the cause.
3. **Counting did not help** while the expected words are in front of it (R2), nor did more thinking (R3).
4. Cost is higher than the plan's guess: about $0.003 a check at `low`/`high` and $0.004 with counts (the reasoning
   tokens: 1,200-2,700 out), $0.01 at effort high; not $0.002.

## What this means for plan B

B1-B3 as written (high detail, count first, effort) would not fix the misses: do not build them as they are.

The next test the results point to (not run, a new paid step; the person's yes and a new cap):

- **R5 blind count**: the same panel with NO expected words: the model is told only the mannequins' colours and asked
  to count each one's arms and hands and say what each hand holds. Code then compares: more than two arms or hands is
  a fault, and a thing in HANDS that no counted hand holds is a fault. The expected words go only to a second step (or
  to code), never to the counting look.
- **R6** R5 on the next model up, only if R5 misses.
- About $0.03-0.04 a run of ten panels on gpt-5-mini; three repeats of R5 about $0.12; R6 on gpt-5 about $0.20 for
  ten panels once. A cap of $0.40 covers both.

## R5 and R6: the blind count (2026-11-25, the person's yes, a new cap of $0.40; spent $0.344 of it)

The model sees only the panel (no view crop) and is told only the mannequins' colours (`BLIND_SYSTEM`, the `Blind`
schema: `counts` per mannequin, `things` with `hand` / `surface` / `air`). Code calls a fault: more than two arms or
hands, or a thing in the `air`.

| run | bad caught | good sent to repaint | $ | $ a check |
|---|---|---|---|---|
| R5 blind, gpt-5-mini ×3 | 1/4 (8), 2/4 (7, 8), 3/4 (5, 7, 8) | 0/6, 0/6, 0/6 | 0.114 | 0.004 |
| R6 blind, gpt-5 ×1 | 3/4 (4, 7, 8) | **3/6** (3, 11, 13) | 0.230 | 0.023 |

- **Taking the expected words away works**: R5 catches 6 of 12 bad looks against 1 of 12 for R0, with no false alarm in
  18 good looks. Shot 8's third hand and shot 7's floating canopy are seen; shot 4's hanging third arm never is by
  gpt-5-mini.
- **No form passes** (all four bad, two of three repeats). The models do not count arms well: even gpt-5 counts
  "2 arms" on every bad panel and catches them only by an umbrella "in the air". The same rule fires on good panels
  (R6: an umbrella shaft partly hidden reads as "not gripped"), so R6 is dear AND noisy.
- **Two looks** (free, from R5's saved answers): a fault when either of two R5 looks sees one catches 2/4 (#1 + #2) or
  3/4 (#2 + #3, #1 + #3), still with no false alarm, at $0.008 a panel.

## What this means for plan B (2026-11-25)

- Worth building: **the blind count on gpt-5-mini** (R5) as the board check's limb-and-floating look, with the expected
  words kept away from it (the hands and view checks stay as today, as a separate look). About half the bad panels go
  back to be painted again, none of the good ones, at $0.004 a panel. A second look doubles the cost for a little more.
- Not worth building: R1-R3 (detail, counting with the expected words, effort) and R6 (gpt-5: 6× the cost, half the
  good panels repainted).
- The check can only catch, not prevent: A1 (the one-arm wording, the sides turned right) is what should paint fewer
  third arms; the live repaint (phase 5) shows whether it does.

Lab total: **$0.794** ($0.451 for R0-R3, $0.344 for R5-R6).

Files: `export.py` (free), `run.py` (R0-R4, `--once`, `--bad`), `input/` (the ten panels, their view crops,
`cases.json`), `runs/` (each run's answers, usage and score; `spend.json`).
