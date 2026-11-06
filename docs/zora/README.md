# Zora

The new director chat (plan/2026-11-06e). It edits the plan Shot Planner Jonathan stores on a scene (`scenes.jonathan`:
treatment, sequences, shots, staging, end state), the way PromptMotion's Nova Studio edits a production: code does the
bookkeeping, one strong model does the creative work, and every turn says exactly what changed.

**Built so far (2026-11-06): phases 0 to 2 and the lab harness of phase 3, offline.** No chat system, API or screen
yet; nothing is wired into the product and no model has been called. Status: `plan/2026-11-06e/IMPLEMENTED.md`.

## The parts

| Part | Where | What it does |
|---|---|---|
| document | `contracts/zora/doc.py` | `ZoraDoc`: the stored plan + the scene's script (read-only) + the person's locks and settled choices; the planner's wire validation in pure code |
| grammar | `contracts/zora/ops.py` | the operations, who may use each, the address each writes, the conductor's invention guard |
| renderings | `contracts/zora/render.py` | the addressable plan (conductor, author) and the plain one (reply) |
| effects | `contracts/zora/effects.py` | what a turn can change, who can change it, and code's reading of the diff (paired by shot handle) |
| tasks | `contracts/zora/tasks.py` | a piece of the author's work: effects it must deliver, effects it may write, its scope |
| ledger | `contracts/zora/ledger.py` | the turn's one account: changes, refused, asked for and not done, nothing changed, overruns |
| kernel | `steps/zora/zora_kernel` | applies operations on stable handles; exact undo; removals whole or not at all; locks; lines bound by code |
| deps | `steps/zora/zora_deps` | which parts an edit made stale, the author tasks that follow, the re-cut guard |
| board + gate | `steps/zora/zora_board` | keeps the author to its tasks; the planner's mend and checks by id, only new problems count |
| deliver | `steps/zora/zora_deliver` | declared effects against the diff: one re-task, then reported |
| ledger | `steps/zora/zora_ledger` | the diff as lines by treatment, sequence and shot; the `ops` and `gate` events |

## The rules it keeps

- Dialogue is the script's: no operation writes a line's words; lines follow their blocks. Overruns are reported with
  the way out, never trimmed (Nova trims; Zora does not).
- A lock is the person saying "not this": the author cannot write a locked field; what the person sets becomes locked.
- Zora reaches the planner only by id (`parts.step(...)`), from two files: `zora_kernel/step.py` and
  `zora_board/gate.py`. `hiru-ai remove --group zora` lists every folder.

## Tests

`tests/zora` (the kernel's properties on three plans the cinematic lab wrote, the deps, board, gate, delivery, ledger,
the replay cases, isolation and removal), each step's own `tests/`, and `lab/zora/tests`.
