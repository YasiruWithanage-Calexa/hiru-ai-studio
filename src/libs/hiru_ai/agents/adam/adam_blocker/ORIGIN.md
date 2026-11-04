# Origin of adam_blocker

Plan: [plan/2026-11-04b](../../../../../../plan/2026-11-04b/PLAN.md) §5.0 rule 5 (reuse by copy, not by import) and §5.2.

| | |
|---|---|
| Copied from | `src/libs/hiru_ai/agents/stager/prompts/system.md` and `agents/stager/agent.py` (the idea of a mark that holds until the next one; the entry-by-entry validation) |
| Commit | `0f2f460` (the working tree at the time: the `stager` folder is not yet committed) |
| The old part | unchanged; `script_split` still uses `stager` |

## Changes

- **Marks belong to a moment, not a block.** Adam plans moments first (some have no block), so a mark names a `moment` id.
- **Moves are first-class** and say why (`power`, `avoidance`, `approach`, `need`, `enter`, `exit`); the stager left a
  teleport to code, which wrote a removable step (`bridges.move_block`). Adam asks the blocker for the move and
  `adam_continuity` reports a teleport that has none.
- **`holding` is a list of objects** the continuity check can follow; the stager had one string.
- **No `frame_side`.** Which side of the frame a person sits on is a decision of the shot designer (card
  `composition.frame_side`), checked by `adam_continuity` (screen direction and eyelines).
- **Zones are not returned.** The stager returned a list of zones and marks; the contract `Staging` has marks and moves,
  and a zone is a name a mark uses.
- **Input** is the moment list with the analysis and the chosen treatment (whose scene it is), not the script items.
- **`finish`** drops a mark or a move that names a moment the plan does not have or a person who is not in the scene.
- **Tier** `medium`, as the stager.
