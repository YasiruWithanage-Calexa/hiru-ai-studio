# director_chat — fork record

Forked from PromptMotion `src/services/nova_chat/` at commit **1d748dc** (2026-10-19), as
PLAN.md §2.1 describes. `scripts/upstream_diff.py director_chat` lists what changed upstream
since that commit in the files below.

| Hiru file | Upstream file | What was kept |
|---|---|---|
| `engine/kernel.py` | `nova_chat/studio/ops.py` (PlanKernel) | Closed operation set; numbers resolved to handles once per batch; snapshot undo; each operation validated alone and rolled back on failure; `Change` records |
| `engine/conductor.py` | `nova_chat/studio/engine.py` (CONDUCT step) | One cheap strict-JSON call picks the lane and transcribes the user's explicit edits as operations; tasks scoped to shots |
| `engine/agents.py` | `nova_chat/studio/agents.py`, `studio/board.py` | Parallel specialists on scoped slices; `op_key` / `owner_of`; owner wins a collision and the rival is kept as a note |
| `engine/turn.py` | `nova_chat/studio/engine.py` (StudioTurnEngine) | conduct → apply → tasks → round 1 → verify → bounded round 2 → reply; reshape offered, never taken |
| `app/handler.py` | `nova_chat/app/handler.py` | Synchronous streamed turn (SSE), API proxies frames; client-safe error text |

## Intentional divergences

1. **Document.** Upstream edits a Nova production plan (shots with prose fields, cast, coverage,
   storyboard panels). Hiru edits one scene: script blocks grouped into shots, re-timed by
   `contracts.shotplan` (4/6/8 ladder, lines bound by code).
2. **Dialogue is read-only.** Upstream has `line.add / line.edit / line.drop`. Hiru's lines are
   the approved script; every `line.*` operation is refused with the reason (edit the script).
3. **New operations:** `insert` (a reaction or insert shot as a director's BEAT block, so every
   block still belongs to exactly one shot), `regroup` (move a cut), `unlock_length`,
   `set_envelope`. Upstream's `rescene`, `cast.*`, `panel.edit`, `set_runtime`, `move` are not
   carried (no Hiru equivalent).
4. **Locks.** Upstream locks cast from the Character Library and the runtime. Hiru locks a shot
   length a PERSON set (`shots.duration_locked`); the conductor (the person's words) may change
   it, specialists may not.
5. **Server-side sessions.** Upstream's sessions live in the browser and are posted every turn.
   Hiru stores threads, messages, memory and the edited plan in Supabase; the function persists
   its own result and writes `audit_log` with `actor_agent = director_chat`.
6. **Board personas.** The production's Lead persona's charter is in every specialist prompt;
   advisors review the result and are shown as a disagreement block, never applied.
7. **Read tools** (`engine/tools.py`, function calling) are new: search_production, get_canon,
   get_shot_timing, list_open_questions. Scope is fixed by the turn, never by the model.
8. **Provider.** litellm and Vertex are not used: OpenAI through the vendored `runtime/llm.py`
   (tiers from config). No credit pricing (the UI shows no costs); usage goes to `token_usage`.
9. **Absent-safe.** Without a key the conductor reads explicit edits by rules and the reply is a
   template; the plan is still edited and re-timed by code.
