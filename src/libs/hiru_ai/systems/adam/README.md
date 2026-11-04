# Adam: Shot Planner Adam

A second, separate shot planner (plan: `plan/2026-11-04b/PLAN.md`). `script_split` is not changed; a production or a
scene chooses which one plans its shots, and both write the same `shots` rows.

**Adam imagines first, then cuts.** The stage order (§4):

```
① ANALYSE   adam_dramaturg        what the scene is about, beats, wants, whose scene it is, baseline → break → aftermath
② CONCEIVE  adam_director ×3      three treatments that differ on purpose; a person or the score picks one
③ IMAGINE   adam_moment_writer    the viewer's experience as ordered MOMENTS (script / implied / elaboration)
④ STAGE     adam_blocker          where everyone is, how movement shows power
⑤ DESIGN    adam_shot_designer    moments → shot cards;  adam_sound_designer → the sound map
⑥ SCREEN    adam_screening        four critics, one revision; code scores both and keeps the better one
⑦ WRITE     adam_write            shots rows (+ card), lines bound, the plan stored on the scene
```

**Where it lives.** One `adam/` folder in each layer of this package (`systems/adam/`, `panels/adam/`, `agents/adam/`,
`steps/adam/`, `tools/adam/`, `knowledge_bases/adam/`), plus `src/libs/contracts/adam/`, `src/services/shot_planner_adam/`,
`tests/adam/`, `tests/eval/adam/` and `docs/adam/`. Deleting those folders removes Adam: `hiru-ai remove --group adam`
lists them, and everything outside the group that still names it.

**The rules** (enforced by `hiru-ai validate`, import-linter and `tests/adam/test_isolation.py`):

1. Ids in an `adam/` folder start with `adam_`, and an `adam_` id outside one is refused.
2. A part of the group names only parts of the group, and nothing outside the group names one inside it.
3. Adam's parts import only their own `adam` folder, a lower layer's `adam` folder, `hiru_ai.core`, `hiru_ai.rag` and `contracts`.
4. Reuse is by copy, not by import: a part that starts from an existing one keeps an `ORIGIN.md` (source path, commit, every change).

**Status.** See `plan/2026-11-04b/IMPLEMENTED.md`.
