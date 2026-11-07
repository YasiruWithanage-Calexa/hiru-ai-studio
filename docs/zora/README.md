# Zora

The new director chat (plan/2026-11-06e). It edits the plan Shot Planner Jonathan stores on a scene (`scenes.jonathan`:
treatment, sequences, shots, staging, end state), the way PromptMotion's Nova Studio edits a production: code does the
bookkeeping, one strong model does the creative work, and every turn says exactly what changed.

**Built (2026-11-07): phases 0 to 8 offline, except the lab's paid run (phase 3) and the live check (phase 9), which
are a person's.** Off until `ZORA__ENABLED=true`; undo needs schema v14 on the database. No model has been called: the
prompts are the lab's, unproven. Status: `plan/2026-11-06e/IMPLEMENTED.md`.

A turn: `systems/zora/zora_chat` (function `hiru-zora-chat`, port 8213; API `api/routers/zora.py`; panel
`hiru-ai-studio-interface/src/features/zora/`). Conductor (`zora_conductor`, medium) → kernel → deps → ONE author
(`zora_author`, the `zora` tier: Jonathan's model and prompt) → board → Jonathan's mend and checks, at most two repairs →
delivery check → save through Jonathan's write path with a revision → ledger → reply (`zora_reply`, from the ledger).
Undo, redo, a confirmation and a suggestion button are answered in code.

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
| guards | `steps/zora/zora_guard` | the old chat's guards, copied: confirmations and undo in code, the loop breaker, the reply guard |
| save | `steps/zora/zora_save` | Jonathan's write path by id, shot ids kept, the revisions behind undo and redo |
| wire, events, treatment | `contracts/zora/{wire,events,treatment}.py` | the answer shapes, the events and actions, treatment mode's gaps and suggestions |
| agents | `agents/zora/zora_{conductor,author,reply}` | the three model calls of a turn |
| system | `systems/zora/zora_chat` | the graph, the turn, the actions (use, undo, redo, lock), the save |

## The rules it keeps

- Dialogue is the script's: no operation writes a line's words; lines follow their blocks. Overruns are reported with
  the way out, never trimmed (Nova trims; Zora does not).
- A lock is the person saying "not this": the author cannot write a locked field; what the person sets becomes locked.
- Zora reaches the planner only by id (`core.parts`), from four files: `zora_kernel/step.py`, `zora_board/gate.py`,
  `zora_save/step.py` and `systems/zora/zora_chat/scene.py`. `hiru-ai remove --group zora` lists every folder.
- A turn that changed nothing says so (`nothing_changed`); a declared effect that did not change is "asked for, not
  done", never claimed; a save over a plan someone changed meanwhile is refused.

## Tests

`tests/zora` (the kernel's properties on three plans the cinematic lab wrote, the deps, board, gate, delivery, ledger,
the replay cases, isolation and removal), each step's own `tests/`, and `lab/zora/tests`.
