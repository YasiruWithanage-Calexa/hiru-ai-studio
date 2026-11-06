# Origin of adam_critic

Plan: [plan/2026-11-05](../../../../../../plan/2026-11-05/PLAN.md) T4 and [plan/2026-11-04b](../../../../../../plan/2026-11-04b/PLAN.md)
§5.0 rule 5 (reuse by copy, not by import).

| | |
|---|---|
| Copied from | the system prompts of `adam_critic_audience`, `adam_critic_editor`, `adam_critic_opportunity` and `adam_critic_fidelity` |
| The old parts | unchanged; the staged planner's screening panel still runs the four |

## Changes

- **One call, four lenses.** Each note carries its `lens`, and there is one score for each lens. `CriticsWire.results`
  gives one answer per lens in the shape the four critics gave, so `adam_notes` merges them unchanged.
- **Every lens reads the code's report.** The four critics were told only the fidelity critic does; one call cannot
  hide it from three lenses, and the report only names faults.
- **The notes' high ones become problems** for the fixer ladder (`adam_problems`); the lower ones are kept in the report for
  a person, as before.
