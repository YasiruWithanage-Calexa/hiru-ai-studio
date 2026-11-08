# Raphael: what is built (plan/2026-11-08e)

## Phase 0a: the lab, free half (built 2026-11-08, uncommitted)

`lab/raphael/` (see its [README](../../lab/raphael/README.md)): the loop, `put_clips` (DaVinci's clip plan + `IrW` in one),
the one prompt, a scripted rehearsal on Episode 1 (edit plan, three sequences, a refused `finish`, one batch repair of two
clips, `finish` accepted in 7 turns), `dry`, the page, `pick`, 27 offline tests. DaVinci's checks, bin, money and backend are
imported (R2), so DaVinci's 44 tests still pass and nothing in `lab/davinci` changed. $0 spent.

Choices the plan left open, made in the lab (the person can change any):

- Every write's report ends with `Turns left after this one: N` (the fix DaVinci's notes asked for; no money is ever shown).
- STILL FAILING marks a fault only when the last write replaced one of its clips and it survived.
- D1: a run that stops early is saved, marked INCOMPLETE (recommended answer, not yet the person's).
- `paid` refuses a fourth run until the person's read.

## Phase 0b: paid runs

Three runs with the person's yes, $1.18 of the $5 lab budget, **all three reached `finish`** (4-7 turns). Details and the
questions for the person's read: [RESULTS.md](RESULTS.md). Two lab changes between runs, one per run:

- run 2: reports that are Raphael's (not `code`) are listed as his to fix, and the prompt says why (§3.2's two owners).
- run 3: an overrun's advice names the clip's blocks and says to split them across consecutive clips (`Raphael.advice`;
  DaVinci's check is unchanged).

`paid` now refuses a fourth run until the person's read (`--past-read`). 29 offline tests.
