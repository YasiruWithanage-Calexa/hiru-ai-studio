# Jonathan length modes, in plain words (plan/2026-11-08b)

## The problem

Scene 01 of *Ekama Sakshiya* is written as 1 minute with one short line, but Jonathan planned about 90 s.

Why:

- Every shot has two times: what Veo **makes** (4, 6 or 8 s) and what the edit **keeps** (as little as 2 s). The 90 s is
  mostly what Veo makes. A 2 s cutaway still needs a 4 s clip.
- Jonathan is told to cover a minute with 15 to 22 short shots and may go about 20 % over.
- **Nothing checks the length.** Jonathan fixes the mistakes code finds, and length is not one of them.

## What we will build

A choice per production:

- **Guide**: exactly what happens today.
- **Strict**: the edit may keep **at most 10 % more** than the scene's length (a 1-minute scene: 66 s at most). Code
  checks it. If the plan is over, Jonathan is sent back to fix it, up to two times, and told which shots have time to
  give.

In both modes a line is never cut short and nothing in the script is dropped.

## The careful parts

- **Some scenes cannot fit.** Before planning, code works out the least time the scene needs with every line said in
  full. If that is already over the limit, you are told ("needs at least 71 s; the limit is 66 s") and the plan is still
  made.
- **No cheating.** Jonathan could make every shot 2 s and pass. A second check stops a plan that is mostly 2 s shots or
  that rushes the scene's turning points.
- **Nothing else gets worse.** A shorter plan that breaks something else (a prop in the wrong hand, a missing line) is
  not kept.

## What you will see

In production settings (admin): **Jonathan length: Guide / Strict.** On the Jonathan tab, next to "X s kept of Y s": the
mode and the limit, in red if the scene is over. Seconds only, never costs.

## Before we build it

A small test on this screenplay's three scenes and two old test scenes, Guide against Strict, **$5 at most, only when
you say yes**. You read the plans without knowing which is which. If Strict keeps the quality and lands inside 10 %, we
build it.

## Your decisions

1. Cap the **kept** time (recommended) or the **made** time.
2. Setting per production (recommended), or per scene too (needs a database change).
3. Default stays Guide until the test says otherwise.
4. The no-cheating numbers (half the shots at 2 s at most): tuned in the test.
5. Admin only changes it.
