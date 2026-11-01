# director_chat — fork record

Forked from PromptMotion `src/services/nova_chat/` at commit **1d748dc** (2026-10-19), as
PLAN.md §2.1 describes. `scripts/upstream_diff.py director_chat` lists what changed upstream
since that commit in the files below.

| Hiru file | Upstream file | What was kept |
|---|---|---|
| `engine/kernel.py` | `nova_chat/studio/ops.py` (PlanKernel) | Closed operation set; numbers resolved to handles once per batch; snapshot undo; each operation validated alone and rolled back on failure; `Change` records |
| `engine/conductor.py` | `nova_chat/studio/engine.py` (CONDUCT step) | One cheap strict-JSON call picks the lane and transcribes the user's explicit edits as operations; tasks scoped to shots |
| `engine/agents.py` | `nova_chat/studio/agents.py`, `nova_chat/studio/board.py` | Parallel specialists on scoped slices; `op_key` / `owner_of`; owner wins a collision and the rival is kept as a note |
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
10. **The kernel adopts the timing kernel's splits.** A shot whose speech cannot fit the longest
    rung is split by `contracts.shotplan` into a continuous follow-on; `ScenePlanKernel._absorb`
    takes that split in after loading and after every operation, so the shot numbers a model
    reads are the numbers its operations address. Upstream's plan has no such kernel.
11. **Write-back is shared with the API.** Fitted shots go back to rows through
    `contracts.sceneplan.rows_after_fit` (ids kept, the follow-on part of a split is a new shot,
    `version` bumped only when something a prompt depends on changed), the same code the API
    uses when a person edits a shot or the script.
12. **The `done` event carries the lane** (`chat | edit | craft | reshape`), used by the replay
    harness (`scripts/replay_director.py`) to score turns.
13. **Guards from the first real-model replay (2026-10-24):** framing and sound names are
    normalised in the kernel; specialists are held to their task's shots and at most 6 operations;
    the reply runs on `medium` and is told explicitly when nothing changed; a standing rule the
    production already holds is not stored again.
14. **The chat changes the Script column (2026-10-26).** Upstream's plan has no script a person
    edits. Hiru's kernel now has `block.set | block.insert | block.remove` (script blocks, named by
    their number at the START of a batch, like shots), `canon.add | canon.remove`,
    `check.waive | check.restore` and `dop_note.set` (a shot's `person_edits`). All are
    PERSON-ONLY (`by="you"`): a specialist, the conductor's tasks and an options card cannot use
    them. Dialogue words must be copied from what the person wrote (here or earlier), are staged
    as an options card (Apply / Keep) and applied only by `engine/choice.py`, with
    `Permission.EDIT_SCRIPT` (`TurnPayload.can_edit_script`); shot-list edits keep
    `Permission.DIRECT`. `persist` saves the script, its lines and a new `script_version` (and
    refuses a script someone saved meanwhile). This also fixes `insert`, which used to shift
    block numbers without saving the script block it added.
15. **`engine/ripple.py` is new.** After a script edit it names the impact set (touched shots,
    their neighbours, shots joined by a continuous or matched cut) and notes what it found in
    code; the continuity specialist is tasked on that set (beats and joins only; it cannot touch
    dialogue). For a staged change the specialist's fixes ride in the card's operations.
16. **`describe()` numbers blocks** (`[n]`) and shows who is in each shot and what a person set
    on it; the conductor prompt grew from 2.4k to 2.9k characters (the hygiene budget is 3000).

17. **Director Chat v2, Phase 0 (2026-10-26, plan/2026-10-26).** `engine/refusals.py` filters every
    refusal the kernel records, so a validation message ("text takes text") or an operation name
    never reaches a reply or a card. `engine/proposals.py` resolves "do that / yes / update S02
    with that" from the stored thread (an open options card, or the last piece of advice, which
    becomes one Apply / Keep card), and removes any sentence in a reply that points at a card the
    message does not carry. A model answer that is an edit or craft with no operations and no tasks
    is asked once more (Nova W6, `conductor.AGAIN`, appended after the message so the system prompt
    stays cacheable). The reply model reads the turn ledger after the message (Nova W2).

18. **Director chat does what it says (2026-11-01, plan/2026-11-01c, Phases 0 to 3).**
    `contracts/director_capabilities.py` is one registry of what the chat can do (operations,
    permission, staged or not) and cannot (`NOT_HERE`, each with a route), rendered into the static
    part of the conductor, options and reply prompts instead of three hand-written lists. The
    conductor has a lane `cannot` {request, reason, route}; a plain `chat` answer to a request the
    registry names (dialogue in another language) is turned into `cannot` in code (`conductor.backstop`).
    `engine/pending.py` + the `pending_actions` table: a card that offers one edit leaves a pending
    action, and "i confirm / do it / apply it" applies it through `choice.apply_choice` or says
    "There is nothing waiting to apply." plus the last route; no model decides it. A reply message's
    text block carries `advice: false` and `route` so a refusal is never "advice" for a later "do it".
    `proposals.guard_reply` also drops offers to do something later when no card or pending action
    waits, and replaces a sentence that says a change was made when no receipt, chosen-card effect or
    scene state shows it. `options.propose` drops an option whose label claims a goal its operations do
    not reach (`dialogue.si`, `shot.framing`) and relabels one that lost operations; `choice` writes the
    card's EFFECT as its outcome ("Changed director notes on 5 shots. Dialogue words unchanged.") and
    whether the goal was reached. The conductor prompt grew to 3.7k characters (budget 4.2k).

19. **The translator, the loop breaker and the evals (2026-11-01, plan/2026-11-01c, Phases 4 to 6; decision D1
    accepted).** The script stays in the language it was written in. Only when the person asks for the
    dialogue in another language (any language: the request names it, `conductor.asks_for_language` /
    `target_language` read it without a key, the model's `translate {language, code, style, shots}` reads
    it with one) is the conductor's lane `translate`. `engine/translate.py` is the translator agent: one
    `high`-tier strict-JSON call per 30 lines, `{line_id, text}` out, with the speaker, delivery, style and
    the production's rules in the prompt. Code decides the rest: lines already in the language are left
    alone, lines that have a stored source in that language go back to it with no model call, and a line
    that did not come back in the language's script (`contracts.director_capabilities.LANGUAGES`) is left
    out. Its output is `block.set` operations marked `translated_to`, tried on a copy of the scene
    (`turn._stage(by="translator")`; `kernel.is_translation` is the only script write an agent may make,
    and only there), shown as a card with every line before and after (`ChatOption.lines`), and applied
    only by a person with EDIT_SCRIPT (button, or "i confirm it" through the pending action). Applying keeps
    each line's first original in `dialogue_lines.source_text` / `source_lang`. `engine/loop.py`: every
    reply records its `goal` and `met` (`TextBlock`); the same unmet goal twice in a row is answered in code
    ("the card above is waiting", or the refusal and its route, "Asking again will not change that.").
    `proposals.guard_reply` no longer treats a negated sentence ("nothing has been applied") as a claim.
    `scripts/replay_director.py` gained `--k` (pass@1 and pass^k), an honesty score and ten more
    conversations. The conductor prompt is 4.4k characters (budget 5k).
