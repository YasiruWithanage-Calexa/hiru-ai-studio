# Origin of adam_fixer

Plan: [plan/2026-11-05](../../../../../../plan/2026-11-05/PLAN.md) T3 and [plan/2026-11-04b](../../../../../../plan/2026-11-04b/PLAN.md)
§5.0 rule 5 (reuse by copy, not by import).

| | |
|---|---|
| Copied from | the system prompt of `adam_reviser` (the operations, the rules) |
| The old part | unchanged; the staged planner's screening panel still revises with `adam_reviser` |

## Changes

- **One problem, not a list of notes.** The prompt answers one problem by its id; its one disposition says done (the
  operations) or declined (why).
- **The part of the plan around the problem**, not all of it: the cards within two of the problem's card (all of them when it
  is about the scene as a whole) and the moments those cards show.
- **A tier chosen per call.** The manifest's `medium` is the bottom rung; `systems/adam/adam_shot_planner/fixer.yaml` says
  which tier each rung of each kind of problem runs on, and the system passes it to `Agent.run(tier=...)`.
- **A second rung is told why the first failed** (`<earlier>`): what code refused in the smaller model's fix.
