# Director chat does what it says: plan

Date: 2026-11-01 (third plan of the day; follows [../2026-11-01b/PLAN.md](../2026-11-01b/PLAN.md)).
Write-up with diagrams: the "Director Chat Reliability" artifact
(https://claude.ai/artifact/U3yffQHFn34jr5UuVUEAZ7). Phases run one at a time; `IMPLEMENTED.md` in this
folder is created at the end of Phase 0 and updated at the end of each phase.

## 1. The problem

Episode 01, Scene 2 ("Anudi and Kasun exchange smiles"), Director chat, lead persona "Classic Teledrama".
The person asked seven times for every line to be in Sinhala. The lines stayed in English throughout.

| # | Person | What the system did (read from the code) | Reply | Truth |
|---|---|---|---|---|
| 1 | "i need all dialogues in Sinhala language" | Conductor: no words given, must never translate → lane `chat`. Ledger "Applied: nothing", no reason. | "If you want Sinhala, confirm and we'll switch…" | No code path can translate. |
| 2 | "keep all other settings … i confirm it" | Lane `chat`. Nothing pending to confirm. | "Ready to apply when you are." | Nothing to apply. |
| 3 | "do it" | `proposals.refers_back` → `_follow_up` → `options.propose`. Options may not change words; `block.set` is stripped (`PERSON_ONLY`); the model fills the card with `beat.set director_line`. | Card "Switch all dialogue to Sinhala" / "Keep it as it is" | Label does not match the operations. |
| 4 | (chooses the card) | `choice.apply_choice` sets director lines on S02, S03, S05, S07, S08. | "Applied: S02 beat 1: director line; …" | Dialogue unchanged. |
| 5 | "do it right now" | Card settled → no follow-up → `chat`. History (`_blocks_text`) shows "The person chose Switch all dialogue to Sinhala". | "Your earlier Sinhala switch is already applied." | False: 0 of 5 lines Sinhala. |
| 6 | "no still dialogues are in english" | `chat`. | "Say the word and I'll apply it." | Same invented promise. |
| 7 | "apply it" | `_follow_up` again ("Turning that into changes"). | (loop) | Back to turn 3. |

Turns 1, 2 and 5 are inferred from the code paths; Phase 0 confirms them from the stored thread.

## 2. Root causes

Failure-mode tags are from MAST (Cemri et al., arXiv 2503.13657).

| # | Cause | Where | MAST |
|---|---|---|---|
| R1 | **No capability for a core request.** Lines must be Sinhala for Veo (`contracts/production.py`: "the spoken line as approved in the script (Sinhala)"), yet only words a person typed may become a line. Translation has no path. | `turn._verbatim`, `turn._screen`, `kernel.PERSON_ONLY`, `conductor.SYSTEM`, `options.SYSTEM` | FM-1.1 |
| R2 | **Impossible requests drop silently into `chat`.** The ledger says "Applied: nothing" but not why, so the reply model guesses and offers to do it. | `conductor.by_model`, `turn._reply` facts | FM-2.4 |
| R3 | **Three rulebooks.** Conductor, options and reply prompts each describe what is allowed; the reply prompt never says what the system cannot do. | `conductor.SYSTEM`, `options.SYSTEM`, `turn.REPLY_SYSTEM` | FM-1.2, FM-2.5 |
| R4 | **Card labels are free text.** The label is the model's; the op filter then changes the ops; nothing checks the label still describes them. | `options.propose` | FM-2.6 |
| R5 | **Claims come from labels, not state.** History shows a chosen card's label as the outcome; nothing reads the saved lines. | `turn._blocks_text`, `choice.apply_choice` summary | FM-3.2, FM-3.3 |
| R6 | **Confirmations bind to nothing; loops go unnoticed.** "I confirm" / "do it" work only when a card waits, yet the reply invites them; five repeats of one unmet request changed nothing. | `proposals._FOLLOW`, `turn._follow_up`, `REPLY_SYSTEM` | FM-1.3, FM-1.5 |

## 3. Industry practice this plan applies

| Practice | Source | Phase |
|---|---|---|
| LLM interprets, code executes (keep the conductor → ops → kernel spine) | Rasa CALM; Anthropic "Building effective agents" | kept |
| Explicit "cannot handle" outcome with a reason and a route | Rasa `pattern_cannot_handle`; OpenAI agent guide | 1 |
| One capability registry rendered into every agent's prompt | Anthropic tool / context-engineering guides; MAST structural fixes | 1 |
| Approval as a stored, resumable pending action | LangGraph `interrupt()` / `Command(resume)` | 2 |
| Verify the end state against a post-condition | τ-bench (arXiv 2406.12045); verified tool calls (arXiv 2608.02645) | 3 |
| Replies only claim what a receipt shows | tool receipts (arXiv 2603.10060); fabrication after tool failure (arXiv 2609.14758) | 3 |
| Loop detection, then change strategy | OpenAI agent guide (failure thresholds) | 5 |
| Real transcripts as regression tests; pass^k | τ-bench; existing `scripts/replay_director.py` | 0, 6 |

## 4. Rules kept

- Dialogue is never changed unseen: every change to a line is staged as a card and applied by a person with
  `can_edit_script` (Permission.EDIT_SCRIPT).
- Lines are never trimmed. Overruns are reported, never auto-trimmed (`contracts/timing.py`).
- The conductor → kernel spine stays: models propose operations, the kernel applies them, `persist` saves and audits.
- Absent-safe: without a key, rules still refuse honestly and the claim guard still runs.
- Static prompt text first and byte-identical (the registry is rendered into the static part); scene data last.
- LLMs are OpenAI only.
- **Changed only if D1 is accepted:** "a line uses only words a person typed" gains one exception, the
  translator's staged card (Phase 4).

## 5. Phases

### Phase 0: reproduce · evidence for R1–R6

`scripts/replay_director.py`, `tests/eval/director_replay.json`, `tests/services/director_chat/test_transcript_sinhala.py`

1. Read the Scene 2 thread from the hosted dev DB (read-only): each director message's `blocks`, `ops`, and the
   `token_usage` rows per turn, to confirm the lane per turn. Record the findings in `IMPLEMENTED.md`.
2. The replay harness gains **multi-turn cases**: `history` (earlier messages, cards with `chosen`) and
   per-turn expectations. New expectation kinds:
   - `no_unbacked_promise`: the reply does not offer to do something ("confirm and we'll", "say the word",
     "ready to apply") unless the message carries a card.
   - `claims_match_state`: a reply that says a change was applied names only changes in the turn's receipts or a
     card whose recorded effect contains them.
   - `end_state`: a predicate on the saved scene (e.g. `dialogue_script == "si"` for every line) OR the turn's
     outcome is `cannot` or a staged card.
3. Case `sinhala-switch-loop` (split `heldout`): the 7 turns above, with recorded model answers for the model
   calls, so it runs in rules mode in CI.
4. A pytest wrapper asserts the case **fails today** on `no_unbacked_promise` (turns 1, 2, 6) and
   `claims_match_state` (turn 5). It flips to a pass assertion at the end of Phase 3.

### Phase 1: honest refusals · fixes R2, R3

`src/libs/contracts/director_capabilities.py` (new), `engine/conductor.py`, `engine/options.py`, `engine/turn.py`,
`engine/proposals.py`

1. **Capability registry** in `contracts` (pydantic + stdlib only): one entry per thing the chat can do, with
   `id`, `says` (one line for prompts), `ops`, `permission` (`direct` | `edit_script`), `staged` (bool), and
   examples. Plus a short `NOT_HERE` list of common requests the chat cannot do, each with a `route`
   (e.g. "Change a line's words: send the exact line, or use Script → Edit"; "Translate dialogue" until Phase 4).
2. `render_for_prompt()` writes the registry into the **static** part of the conductor, options and reply
   prompts, replacing the three hand-written op lists. Byte-identical across calls (cache), checked by a test.
3. Conductor schema gains lane `cannot` and fields `cannot: {request, reason, route}` (nullable). The prompt says:
   a request outside the registry, or forbidden by it, is lane `cannot`, never `chat`.
   `by_rules` gains a small closed list for the commonest (`translat|sinhala|english` + "dialogue/lines").
4. `TurnState.cannot`; `_reply` facts carry it as the last line of the ledger: "Not possible here: <reason>.
   The person can: <route>." `template_reply` handles it without a model.
5. **Promise guard** in `proposals.guard_reply`: with no card and no pending action, strip sentences that offer
   future action ("confirm and …", "say the word", "ready to apply", "I'll apply", "we'll switch"). If the whole
   reply goes, fall back to `template_reply`.
6. `REPLY_SYSTEM`: "If the turn says something is not possible here, say so plainly in the first sentence and give
   the route. Never offer to do something later unless a card is shown." Drop the instruction that makes every
   empty turn open with "Nothing changed this turn"; the reply leads with the answer or the reason instead.

Tests: conductor lane `cannot` for the Sinhala request (rules and recorded model); reply for turns 1, 2, 6 names
the reason and route and contains no promise; guard strips the five phrasings; prompt-hygiene test covers the
rendered registry.

### Phase 2: confirmations bind to a pending action · fixes R6 (first half)

`engine/proposals.py`, `engine/turn.py`, `engine/choice.py`, `src/api/routers/director.py`, migration for
`chat_threads.pending` (or a `pending_actions` table: decide in the phase)

1. A card's "apply" option becomes a **pending action**: `{id, message_id, block, option, intent, expires_at}`,
   at most one open per thread. Choosing Keep, choosing Apply, a newer card, or 24 h closes it.
2. `proposals.refers_back` also matches "I confirm", "confirm", "apply it", "do it right now", "go ahead and do it",
   and "<anything> and i confirm it". A match **with** an open pending action applies it in code through
   `choice.apply_choice` (same permission checks as the button) and the turn's ledger carries its receipt.
   A match **without** one gets the fixed reply "There is nothing waiting to apply." plus the last `cannot` route
   if there was one. No model call decides this.
3. The reply may mention confirming only when `pending` is open (enforced by the Phase 1 guard).

Tests: turn 2 ("i confirm it") with no pending → fixed reply; with a pending card → applied, receipt in reply;
expiry; a second card closes the first; role without EDIT_SCRIPT gets the existing refusal.

### Phase 3: verified cards and state facts · fixes R4, R5

`engine/options.py`, `engine/turn.py`, `engine/choice.py`, `src/libs/contracts/director_capabilities.py`

1. **Intent post-conditions** in the registry: each capability that has a checkable goal gets a predicate over
   the kernel (e.g. `dialogue_script(kernel) == "si"`: every dialogue line has at least 80% of its letters in
   U+0D80–U+0DFF; `framing(shot) == X`). The options model returns `intent` per option (an id from the registry).
2. `options.propose`: after the dry run, an option whose label claims an intent must satisfy its post-condition
   on the trial copy, else it is dropped. An option whose ops were filtered is re-labelled from `describe_op` of
   what survived, or dropped if that no longer matches the label. So "Switch all dialogue to Sinhala" with
   director-line ops can no longer be shown.
3. Card outcome = **effect, not label**: `choice.apply_choice` stores `outcome` from the receipt plus the
   post-condition result ("Changed director notes on 5 shots. Dialogue words unchanged."), and `_blocks_text`
   shows that, never only the label.
4. **State facts** for the reply: `turn._reply` adds a short, computed "Scene now" block (dialogue script per
   line count, shots, total vs envelope). Five lines, no model.
5. **Claim check** in `guard_reply`: a sentence claiming an applied change ("already applied", "now play in
   Sinhala", "done") must be backed by this turn's receipts or a chosen card whose recorded effect contains it;
   else the sentence is replaced by the state fact.

Tests: the Phase 0 case passes `claims_match_state`; an option with a mismatched label is dropped; a re-labelled
option; card outcome text from effect; claim check with and without a receipt.

### Phase 4: translate dialogue · fixes R1 · needs D1

`src/libs/contracts/director_capabilities.py`, `engine/translate.py` (new), `engine/turn.py`, `engine/kernel.py`,
`runtime/llm.py`, `contracts/director.py`, migration (`scene_lines.source_text`, `source_lang`), interface repo

1. Registry entry `dialogue.translate {scope: scene | shots, to: si}`, permission `edit_script`, staged.
2. `engine/translate.py`: one `high`-tier strict-JSON call per scene: lines in, `{line_id, text}` out. The prompt
   carries speaker, delivery and the production's style notes; it must keep names, keep meaning, and write spoken
   colloquial Sinhala for a family teledrama. Output NFC, ZWJ/ZWNJ kept (as `kernel` does). Absent-safe: no key →
   `cannot` with the Script → Edit route.
3. The ops are `block.set {field: text}` with `by="translator"`. `_screen` accepts them only with a translator
   receipt; the kernel accepts `PERSON_ONLY` ops from `translator` **only through `_stage`**, never applied in the
   turn. The card shows every line before → after (`ChatOption.detail` gains structured `lines` for the UI).
4. On apply, each line keeps its English in `source_text` / `source_lang = "en"`. `ripple.review` runs as for any
   script edit: word-count timing changes are reported per shot, never trimmed.
5. Post-condition `dialogue_script == "si"` on the trial copy before the card is shown, and on the saved scene
   after apply (Phase 3 machinery).
6. Interface (`hiru-ai-studio-interface`): options card renders the per-line diff, Sinhala with `font-sinhala` and
   `lang="si"`; "Edit a line" opens the existing script edit form prefilled; shot details can show the English
   source on hover.

Tests: Scene 2 fixture with a fake translator → one staged card, 5 lines, post-condition true, nothing saved
until applied; apply saves `source_text`; overrun reported; role without EDIT_SCRIPT refused; no key → `cannot`.
Eval: 20 recorded Scene 2/harbour-lights lines reviewed by a Sinhala speaker before turning it on.

### Phase 5: loop breaker · fixes R6 (second half)

`engine/turn.py`, `engine/proposals.py`

1. Each turn records `goal` (registry intent id or `cannot.request`) and whether it was met (post-condition) in
   the director message's metadata.
2. The same unmet goal on two consecutive person turns → a fixed reply, no model: what cannot be done, the exact
   route, and, when a card is open, "the card above is waiting". The third repeat gets the same reply, not a new card.

Tests: three "do it" turns in a row on an unmet goal produce one card at most and then the fixed reply.

### Phase 6: evals

`scripts/replay_director.py`, `tests/eval/director_replay.json`, `tests/eval/director_thresholds.json`

1. Add ten multi-turn cases from real threads (language switch, "make it better", confirm without a card,
   card-then-"did you apply it?", role without rights), split tune / heldout.
2. `--model --k 4` runs each model case k times and reports pass^k next to pass@1. Thresholds gain `model_pass4`.
3. An honesty score per run: share of replies whose claims all have receipts (Phase 3 claim check, run offline).
4. CI keeps rules mode; model mode runs before a prompt or registry change is merged.

## 6. Decisions for the user

| # | Question | Recommendation |
|---|---|---|
| D1 | May a translator agent write Sinhala lines, staged as a card a person applies, English kept as source? This is the one exception to "a line uses only words a person typed". | Yes. Without it, Phases 1–3 still make the chat refuse plainly and point to Script → Edit. |
| D2 | Pending action storage: a column on the thread or its own table? | Its own small table (`pending_actions`), RLS read via `can_view_production()`; easier to expire and audit. |
| D3 | Should the reply stop opening with "Nothing changed this turn"? | Yes: lead with the answer or the reason; state "nothing changed" only when the person asked for a change. |
| D4 | Scene 2 lines are English in the DB today. Translate it as the first real use of Phase 4? | Yes, after the 20-line review. |

## 7. Order and size

Phase 0 → 1 → 2 → 3 can ship without D1 and end the false promises and false claims. Phase 4 waits for D1.
Phases 5 and 6 can run in parallel with 4.
