# Origin of adam_take

Plan: [plan/2026-11-05](../../../../../../plan/2026-11-05/PLAN.md) T1 and [plan/2026-11-04b](../../../../../../plan/2026-11-04b/PLAN.md)
§5.0 rule 5 (reuse by copy, not by import).

| | |
|---|---|
| Copied from | the system prompts of `adam_dramaturg`, `adam_director`, `adam_moment_writer`, `adam_blocker` and `adam_shot_designer`; `Context` and `clean_analysis` from the dramaturg (`schema.py`, `agent.py`); the staging and card cleaning from the blocker's and the designer's `finish` |
| The old parts | unchanged; the staged planner (`ADAM_MODE=staged`, the default) still uses all five |

## Changes

- **One prompt, one call.** The five prompts are in the order the stages ran (analyse, choose, imagine, stage, design), so
  the model's reasoning follows the same path. Their rules are kept; what only handed work from one stage to the next
  ("read the analysis you are given") is cut.
- **One treatment and two pitches** instead of three full treatments chosen by `adam_distinct` (plan §9 D2). A person can
  still switch: the take is asked again with the pitch as `stance` and the stored analysis as `given_analysis`.
- **No sound.** The cards carry no `sound`; `adam_sound_designer` writes it (plan §9 D3).
- **Facts in, reasoning out** (plan §6 L2): `<facts>` gives each line's word count and the shortest take that holds it, so the
  model does not work the Veo clock out in its reasoning. The designer's per-moment `<clock>` cannot exist before the moments
  do; `adam_fit` checks the clock afterwards.
- **Timeout 600 s** (the tier says 180): the answer is about 25,000 tokens.
