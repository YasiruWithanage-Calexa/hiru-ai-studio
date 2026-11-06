# Zora: the new director chat, built on Nova Studio and Jonathan's plan (plan/2026-11-06e)

Status: written 2026-11-06. Nothing in this plan is built. Plain words: [human-read.md](human-read.md).
Follows: plan/2026-11-01c (director chat does what it says), plan/2026-11-06b (Shot Planner Jonathan).
Reference engine: PromptMotion Nova Studio (`PromptMotion/src/services/nova_chat/nova_chat/studio/`, design log
`docs/nova/studio.md` W1 to W8, `CLAUDE.md` "Vega Creative Studio" and "Nova").

## 1. Why a new chat

### 1.1 What the director chat is today

`systems/director_chat` (graph) and `services/director_chat` (legacy) answer one message about **one scene's shot list**:

```
read -> conduct -> [ confirm | translate | reshape | edit | follow | options ] -> settle -> remember -> advise -> reply
```

It already has good pieces, most from plan/2026-11-01c: the `scene_kernel` edit algebra (forked from Nova's `PlanKernel`
at commit `1d748dc`, before Nova Studio's W1 to W8 existed), lanes, a capability registry with a `cannot` lane, pending
actions that "do it" applies in code, the promise and claim guards, the loop breaker, the translator's staged card, the
`director_board` panel (cinematography, timing, sound, continuity) and advisors.

### 1.2 What is wrong with it now

| # | Gap | What a person sees | Where |
|---|---|---|---|
| G1 | **It does not know the planners exist.** It edits `shots` rows only. Jonathan's plan (treatment, arc, sequences, colour script, geography, key image, staging, end state, `why`, lens, angle, `use_s`) is invisible to it. | A chat edit leaves `scenes.jonathan` stale: the Jonathan tab still shows the old treatment and sequences; the end state handed to the next scene is wrong. | `steps/scene_kernel/logic.py` (no planner import), `contracts/jonathan/stored.py` |
| G2 | **It cannot talk about the treatment.** "Make the approach colder", "the key image should be her hands", "move the turn earlier" have no operation. | `cannot` or a vague `craft` that changes framings. | `contracts/director_capabilities.py`, `conductor/prompts/system.md` |
| G3 | **Ops are shot-level only.** No sequence, lens, angle, `use_s`, `why`, staging mark, colour or end-state operation. | Jonathan's vocabulary (11 sizes, lens, angle) is flattened to 7 framings. | `scene_kernel.logic.MODEL_OPS` |
| G4 | **No dependency graph.** A split re-asks framing; nothing says a changed approach makes the lenses of a sequence stale, or a changed end state breaks the next scene's seam. | Edits land, and what they contradict stays. | `turn.py` step 3 (two hard-coded rules) |
| G5 | **No change ledger.** The reply gets "Applied: …" but not "asked for and not done", "the team's work that was refused", "nothing changed". | Replies that are fluent but cannot be checked against what happened. | `turn.reply_chunks` facts |
| G6 | **No declared-vs-delivered check** (Nova W7). The seat is picked by how the message reads. | "Add a reaction" seats sound; the reply says done. | `director_board` wins table only |
| G7 | **No undo.** Every applied turn is final; the only way back is a re-split. | People are afraid to let it edit. | no revision table |
| G8 | **The craft checks are the classic fit only.** Jonathan's checks and craft measures (`jonathan_check`, `measures`, `mend`) never run after a chat edit. | A chat edit can bring back a teleport, a crossed line or a crowded take that Jonathan's stabiliser had removed. | `turn.settle` uses `kernel.fit()` |
| G9 | **Four specialists in parallel on one snapshot**, each a model call, against the Hiru AI pattern (rule 1 and 2: one author per creative unit; "another specialist's view" is not a reason). | Cost and collisions without a proof that they beat one author. | `panels/director_board` |

So the person's reading is right: Hiru's chat took Nova's kernel in October and none of what made Nova Studio work (W1 to
W8). And since then the scene's real plan moved to Jonathan, which the chat cannot see.

### 1.3 The decision this plan makes

Build a **new chat system**, its own group, named **Zora** (the person's choice, 2026-11-06; D1).
Zora is Nova Studio's turn **copied and changed for Hiru**:

- its **document** is Jonathan's stored plan of one scene (treatment → sequences → shots, staging, end state) plus the
  scene's script lines, read-only to every model;
- its **creative work** is done by **one author call per turn** (the Hiru pattern), with Nova's code machinery around it
  (operations, handles, dependency graph, ownership by effect, ledger, delivery check, re-cut offer, proposals);
- its **gate** is Jonathan's own checks, mend and repair, so a chat edit can never leave the plan worse than Jonathan left it.

The old director chat stays as it is, for scenes with no Jonathan plan, until D3 retires it.

## 2. The rules this plan follows

1. **The Hiru AI pattern** (`docs/AI_PATTERN.md`, ADR 0010). Rule 7 allows an agent loop with tools here (a person leads).
   Zora breaks rule 1 in one bounded way and says so: the conductor is a **small transcriber** (rule 2's exception: a
   small model turns free text into the format, and code checks it invented nothing, `_invented`). All creative writing is
   the one author. Nova's 12-seat board is **not** copied unless the lab (Phase 3) shows it beats one author (rule 8).
2. **Group isolation** (plan/2026-11-05e §4.0): a `zora/` group in each layer. It reaches Jonathan's parts **by id**
   (ADR 0009: `parts.step("jonathan_check")`), never by import, so `hiru-ai remove --group zora` lists everything that goes.
3. **Hiru's rules stay** (interface `CLAUDE.md`, plan 2026-11-01c §4): dialogue verbatim, changed only by a person's own
   words, staged as a card, with `can_edit_script`; the translator is the one exception, staged; Veo 4 / 6 / 8 s at
   2.2 words/s; **overruns are reported, never trimmed** (this is where Zora differs most from Nova: Nova's
   `dialogue.fit` trims lines; Zora may only retime, split or report); an approved scene is locked; no credits or costs in
   the interface.
4. **Prove before building** (the person's rule): the kernel, deps and ledger are code and free; the prompts are proven in
   a lab with a hard budget on the person's own scenes before the system is wired. **No model call without the person's
   yes, each time.**
5. **Nova's lessons are copied as tests, not rediscovered.** Each Nova W-finding that applies becomes a pinned test in
   Phase 1 or 2 (§6).

## 3. Zora in one picture

```
 READ (code)       stored Jonathan plan + script lines + canon + production memory + locks + thread + pending action
   │
 CONDUCT           small model, no creative text: lane · the person's explicit changes as OPERATIONS ·
   │               TASKS with declared EFFECTS and a scope        └ code checks the answer; one retry told what was wrong
   │
   ├─ in code, no model: confirm (pending action) · cannot · loop breaker · "nothing to apply"
   │
 KERNEL (code)     applies the person's ops on stable handles; exact undo; all-or-nothing for removals
 DEPS (code)       which nodes went STALE → tasks, each scoped; an edit that dirties > half the plan → undone, OFFERED
   │                                                                                  as "Re-plan with Jonathan"
 AUTHOR            ONE strong call (Jonathan's model and primer) for ALL of the turn's tasks: per task "YOU MAY WRITE
   │               ONLY …", "ALREADY DONE THIS TURN …"; read tools (≤ 6 calls); answers ops + notes + asks + variants
 BOARD (code)      allow-list per task, locks, verbatim lines, no-op drop; refusals kept for the ledger
 CHECK/MEND (code) jonathan_check + measures + mend on the whole plan; only faults THIS turn introduced count
 REPAIR            the same model, the exact new faults, ≤ 2 passes, a worse pass never built on (Jonathan's stabiliser)
 DELIVER (code)    declared effects vs the diff; one re-task for what is missing; the rest is "asked for, not done"
 SAVE (code)       jonathan_write path (shots, design pins, scenes.jonathan) + a REVISION for undo + audit + seams
 LEDGER (code)     what changed · nothing changed · refused · asked for and not done · reported overruns
 REPLY             mid model, written from the ledger (last thing it reads); promise and claim guards; streamed
```

Model calls per turn: `chat` 1–2 · `edit` 2 (conductor + reply) · `craft` 3–5 · worst case 7 (conductor ×2, author,
repair ×2, re-task, reply). A turn that would go over reports it and stops (the pattern's call budget).

## 4. The parts

### 4.0 Where Zora lives

```
src/libs/contracts/zora/          doc.py (ZoraDoc: a view over StoredPlan + lines), ops.py (the op grammar, addresses),
                                   effects.py (WRITES: effect → owner field set), ledger.py, events.py, render.py
src/libs/hiru_ai/steps/zora/      zora_kernel, zora_deps, zora_board, zora_deliver, zora_ledger, zora_guard,
                                   zora_save
src/libs/hiru_ai/agents/zora/     zora_conductor, zora_author, zora_reply
src/libs/hiru_ai/systems/zora/    zora_chat (the graph)
src/services/zora_chat/           the function (streamed, synchronous, like director_chat)
tests/zora/  tests/eval/zora/    tests, replay cases (tune / held-out)
lab/zora/                         the lab (Phase 3), deleted after Phase 9
docs/zora/README.md
hiru-ai-studio-interface/src/features/zora/   the chat panel (other repository)
```

Outside the group, one line each, named in `tests/zora/test_removal.py`: `api/routers/zora.py` (new) and its include in
`api/main.py`, `contracts/director_capabilities.py` (Zora's entries rendered from its own registry), `core/settings.py`
(`ZORA__*`), `.env.example`, `langgraph.json`, `pyproject.toml` (import-linter), `scripts/start-functions.ps1`,
`.github/workflows/deploy-functions.yml`, `docs/AI_CATALOG.md`, `CLAUDE.md`, and the database pair (§4.7).

### 4.1 The document and its addresses (Nova W1: the brief is an address space)

`ZoraDoc` is built from `scenes.jonathan` (`StoredPlan`) and the scene's lines. It has **two renderings**, as Nova's
`brief_to_text(addressable=True)`:

- **addressable** (conductor and author): every node printed with the address its operation uses, and a header that names
  every field and the op that writes it, and says there is no other.
  `Treatment` · `arc 1..n` · `colour A..` · `Sequence A` · `S01..` · `block [n]` · `line L4` · `mark 3` · `end.person Anudi`.
  Numbers start at 1 everywhere; an addressing error names the valid range ("there is no S09, the scene has S01–S08").
- **consumer** (reply): plain, scoped by `only=` to what the turn touched, everything else one line each (compression,
  never omission: Nova W2).

The script lines are printed with their line ids and **never** as a writable field to any model.

### 4.2 The operation grammar (`contracts/zora/ops.py`, `steps/zora/zora_kernel`)

Ported from Nova `studio/ops.py` + `brief_ops.py`, and from Hiru's `scene_kernel` for the script and marks:

| Level | Operations | Who may write |
|---|---|---|
| Treatment | `treatment.set {field: logline\|approach\|geography\|key_image}`, `arc.set/add/remove {n, beat, blocks, feeling}`, `colour.set {sequence, palette\|light\|grade}`, `advice.*` never (shown, never applied) | conductor (person's words), author |
| Sequence | `sequence.set {id, title\|purpose}`, `sequence.bounds {id, first, last}`, `sequence.add/remove` | conductor, author |
| Shot | `set {shot, field: size\|angle\|lens\|link\|why\|over}`, `retime {shot, take_s}`, `use {shot, use_s}`, `sound.set {shot, ambience\|effects\|music\|silence}`, `ir.set {shot, path}` (setting, lighting, beats, first_frame), `split`, `merge`, `insert {after, kind ∈ ADDED_KINDS, what, who, object}`, `remove`, `move`, `regroup` | conductor, author |
| Staging | `mark.set/add/remove {block, who, zone, facing, frame_side, holding}`, `zone.add` | author |
| End state | derived by code from staging and the last shots; `end.set` only by the conductor (the person said it) | conductor |
| Script | `block.set/insert/remove` | **person only**, staged as a card (today's rule) |
| Translation | `block.set {translated_to}` | translator only, staged |
| Marks | `canon.add/remove`, `check.waive/restore`, `dop_note.set` | person only |
| Locks | `lock {path}` / `unlock {path}` | the interface only (a person's click), never a model |

Kernel guarantees (Nova's, already in `scene_kernel`, kept): numbers resolve to handles once per batch; exact undo; a bad
op never corrupts the plan; partial application except **removals, which land whole or not at all** (Nova W3
`_all_or_nothing`). New: every op is re-checked with `JonathanWire`'s own validation, and lines stay bound by code
(`jonathan_write` rebinds them).

**Locks and settled** (Nova `locked` / `settled`): a field a person set or confirmed is `locked` (generalises today's
`duration_locked`): no model may write it, a lock is the person saying "not this". A choice the person handed over ("you
decide the lens") is `settled`: it may not be asked about again. Both live in `StoredPlan.person` (new, §4.7); a model can
never write either (`apply` pops them, Nova §10ad).

### 4.3 The dependency graph (`steps/zora/zora_deps`, Nova `deps.py`)

A task is **never** created from how a message reads; only from a change code can prove. Code nodes are recomputed, the
rest become author tasks, each scoped:

| Change | Stale | Who |
|---|---|---|
| `treatment.approach` | lens, angle, movement of every shot, "change only what now contradicts it" | author, scope = all shots |
| `colour.*` of sequence A | `ir.lighting` of A's shots | author, scope = A |
| `treatment.geography` | staging zones and `frame_side`; the 180° line | author + `staging_check` |
| `arc.*` moved across blocks | `sequence.bounds`, `why` of the shots at the turn | author |
| `split` / `insert` | the new shot's `ir`, `why`, size, lens | author, scope = that shot |
| `merge` | one picture for two (`shot.fuse`) | author |
| `remove` / `move` / `regroup` | joins across the gap; continuity of marks | code (`shot_joins`), author if a fault |
| `retime` / `use` | the Veo clock, the envelope | code (`fit`), overruns **reported** |
| last shots, staging | `end_state` → the next scene's seam | code (`jonathan_seams`): reported; a Jonathan re-plan of the next scene is offered, never run |
| any shot | its frame and prompt are out of date | code: today's stale marks for `shot_producer` |

**Re-cut guard** (Nova `_recut_guard` / `RESHAPE_DIRTY_RATIO`): an edit lane whose changes would rewrite more than half
the shots (min 3) is **undone** and offered as "Re-plan with Jonathan" (a `confirm_reshape` event; the answer becomes a
forced lane). `shape` and a forced lane are exempt.

### 4.4 The conductor (`agents/zora/zora_conductor`)

Strict JSON: `lane ∈ chat | clarify | edit | craft | shape | options | translate | cannot`, `ops` (the person's explicit
changes only), `tasks [{writes: effects, scope, instruction}]`, `translate`, `cannot {request, reason, route}`, `memory`,
`confidence`. Nova's conductor findings are built in from day one:

- `chat` is defined by what the message **asks for**, not what it opens with (W6); an answer with no ops and no tasks on
  any lane but `clarify` / `options` / `cannot` is re-asked once, told exactly that (`_does_nothing`).
- `clarify` writes nothing and is the default when the router fails (W-lanes).
- The retry is told **what went wrong** (`problems=`), appended last so the cached prefix is unmoved (W1); a cut answer
  is re-asked with room, not told it misunderstood (W5).
- Task numbers are post-op (Nova finding 3); `infer_op` reads an op that lost its `"op"` key (finding 5).
- `_invented(op, message, current)`: an op whose text is not the person's words (or the text it replaces) is refused
  (W4 and its regression fix).
- Tier: `medium` (D7). Lite tiers ignored the answer shape in Nova (finding 1).

### 4.5 The author (`agents/zora/zora_author`)

**One call per turn** with all the turn's tasks (from the conductor and from deps), on Jonathan's model (`jonathan` tier,
lower effort, D7) and **Jonathan's own system prompt as the primer**, so the chat's craft is the planner's craft. The
user message (static first, so it caches): the addressable plan, scoped (`plan_to_text(only=…)`: named shots in full,
the rest one line); the script block for the scope; "ALREADY DONE THIS TURN" (finding 2); per task "YOU MAY WRITE ONLY: …"
(finding 6); production memory through the middleware (plan/2026-11-05d); the transcript's last 4 messages, before the
plan (Nova cache order).

It may call read tools (catalog, `director` group): `scene_read`, `shot_read`, `canon_read`, `memory_search`,
`staging_check`, `continuity_check`, `plan_try`; at most 6 calls (pattern). It answers `{notes, ops, asks, variants}`;
`variants` (≤ 3) only when the conductor asked for options; each variant is an op set tried on a copy (§4.8).

Waves (Nova W8): when a task changes the arc or sequences and another task writes shots in the same scope, the author is
told to do the arc first; with one author this is ordering inside one answer, checked by the kernel applying the arc ops
first.

### 4.6 Check, mend, repair, deliver (`zora_board`, `zora_deliver`, Jonathan's checks by id)

1. **Board** (code): drops ops outside the task's allow-list, on a locked path, re-sending a value already there (Nova
   `is_noop`, `_drop_stale_resends`), or putting words in a line. Every refusal is kept with the seat the person would
   recognise ("the director's lens change on S04 was refused: you set S04's lens").
2. **Check**: `jonathan_check` + `measures` on the whole plan. Only problems whose `key` is new since the turn began count
   as this turn's; old ones are left alone (repair, don't redo).
3. **Mend**: `jonathan_mend` (a longer take, a crowded shot cut at a block boundary, numbering). Never trims a line.
4. **Repair**: if a new fault or craft gap remains, the same author model gets the exact sentences and the shots, answers
   a patch of ops; at most 2 passes; a pass that is worse is dropped and the best kept (Jonathan's stabiliser scoring:
   faults, then craft gaps).
5. **Deliver** (Nova W7): `effects.WRITES` maps each effect (`treatment.approach`, `shot.lens`, `sequence.bounds`,
   `shot.sound.music`, …) to the fields that show it. Declared effects that did not change in the diff are re-tasked
   once; a locked effect is never re-tasked but is reported. What is still missing rides the `ops` event as `undelivered`
   and reaches the reply as "ASKED FOR THIS TURN BUT NOT CHANGED".
6. **Overruns**: lines longer than their take after the turn are reported per shot with the way out (retime to 8 s,
   split at a block). **Never trimmed.** A test pins that no Zora path writes a line's text except the staged paths.

### 4.7 Save, undo, seams (`steps/zora/zora_save`) and the database pair

- Writes through Jonathan's `jonathan_write` path (by id): shots with their card, intent, IR and current design pins; the
  lines rebound; `scenes.jonathan` with the new plan, `mended`, `problems`, and `previous` set to the last plan.
- **Revisions** (G7, Nova checkpoints, server-side because the plan lives in the database): a `scene_plan_revisions` row
  per applied turn `{scene_id, revision, stored_plan, shots, made_by, message_id, created_at}`. Undo restores a revision
  in code (no model) and is itself a revision, so redo is undo of the undo. Keep the last 30 per scene (D4).
- `StoredPlan` gains `person: {locked: [paths], settled: [paths]}` (JSONB, no column change: `scenes.jonathan` is JSONB).
- Seams: the new end state is compared with the next scene's start (`jonathan_seams`); a broken seam is reported in the
  ledger with an offer to re-plan the next scene.
- Migration: `Database/upgrade_v13_to_v14.sql` + `schema_v14.sql` (`scene_plan_revisions`, RLS read via
  `can_view_production()`, write through the API only), a pgTAP test. **Applied by the person.**

### 4.8 Proposals, pending actions and the old guards

- **Options lane** → the author's `variants`, each tried on a copy, kept only if it passes check and its label's
  post-condition (plan 2026-11-01c Phase 3 verified cards). "Use this" applies with no model and writes a revision first.
- Carried over as they are, re-homed into `steps/zora/zora_guard`: the capability registry and `cannot` lane, pending
  actions ("i confirm", "do it" in code), the promise guard, the claim guard (now also reads the ledger), the loop
  breaker, the translator card. They are **copied**, not imported, so the old chat can be removed later without touching
  Zora.

### 4.9 Treatment mode (Nova brief mode) and "Plan shots from this treatment"

When a scene has **no shots yet** (or the person says they want to work on the treatment), Zora edits only the treatment
and sequences, like Nova's brief mode before "Send to the director":

- Gaps (Nova `brief_gaps` / `is_hard`): hard = an arc that covers every script block; soft = approach, colour script,
  geography, key image. "You decide" settles soft gaps (Nova §10ad), and the reply may never ask about a settled gap.
- **"Plan shots from this treatment"** = a Jonathan job with the treatment **pinned**: `jonathan_pack` prints it as
  fixed, and a new `jonathan_check` code `treatment` reports a plan whose sequences or arc drift from it. This is the one
  change inside the `jonathan` group (§4.0 exception list) and is D5.

### 4.10 The API and events (`api/routers/zora.py`)

`POST …/scenes/{scene_id}/zora/turn` (streamed), `POST …/zora/undo`, `POST …/zora/redo`,
`POST …/messages/{id}/use` (a proposal), `GET …/zora/revisions`. Events: today's `status | plan | delta | message | done
| error`, plus Nova's `ops {changes, refused, undelivered, nothing_changed}`, `proposals`, `confirm_reshape`, `gate
{problems, overruns, seams}`. `nothing_changed` is explicit (the client reads only `true`, Nova W2).

Routing: a scene whose `scenes.jonathan` holds a plan goes to Zora when `ZORA__ENABLED`; any other scene keeps the old
chat (D3).

### 4.11 The interface (`hiru-ai-studio-interface/src/features/zora/`)

The middle column of the Director page, same three-column workspace. From Nova's Creative Studio:

- **What changed**, uncollapsed, under each reply: by treatment / sequence / shot; "Nothing in the plan changed";
  "Asked for, not done yet"; "Couldn't apply" with the reason (W2).
- **Undo / Redo** in the chat header (revisions).
- **Re-plan offer card** (`confirm_reshape`): "This would change most of the scene. Re-plan with Jonathan?" Yes / Keep.
- **Proposal cards**: "Use this" (the existing `OptionsCard`, re-themed), and the verified card rules.
- **Lock** a field from the Jonathan tab or shot details (a person's click writes `lock`).
- **Suggestions** above the composer (Nova `replySuggestions`): "Draft the arc" when only the arc is missing, "You decide
  the rest" when soft gaps are open. A suggestion is a button, so the router is skipped.
- `@` mentions shots **and** sequences.
- Gate warnings (overruns, seams) under the panel header, amber.
- Lines render with `spoken()`; no credits or costs anywhere.
- Figma frames for the new pieces before Phase 8 (D8).

## 5. What is copied from Nova, what is changed, what is left

| Nova Studio | Zora | Why |
|---|---|---|
| `ops.py` / `brief_ops.py` kernels | copied as one kernel over Jonathan's plan | one document, three levels |
| 12 agent seats + conductor + reply | conductor + **one author** + reply | Hiru pattern rules 1, 2, 8; the seats are a lab arm (Phase 3) |
| `deps.py` change → task | copied, rules rewritten for treatment / sequence / shot / staging / seams | Hiru's plan shape |
| `board.py` ownership | kept as per-task allow-lists and per-effect owners; no seat collisions to settle | one author |
| W1 addressable rendering | copied | — |
| W2 change ledger, `nothing_changed` | copied | — |
| W3 `repair_brief`/`validate_brief`, all-or-nothing removal, re-cut guard | `jonathan_check`/`mend`/repair stand in for repair/validate; the rest copied | Jonathan's gate is stronger |
| W4 ownership, staleness, `_invented` | copied | — |
| W5 rate-limit retry, cut-answer retry | copied | — |
| W6 a turn that changes nothing is re-asked | copied (today's chat has half of it) | — |
| W7 effects declared vs delivered | copied | — |
| W8 words keep their order, `words.shift` | **not needed as an op**: lines are bound by code in script order; `jonathan_check` "lines" (every line once, in order) is the guard | Hiru lines are verbatim |
| `dialogue.fit` trims lines | **replaced** by retime / split / report | Hiru never trims |
| fit loop | kept as a check, its action is report | same |
| `settled` / `locked` | copied | — |
| proposals, "Use this" + checkpoint | copied, checkpoint = server revision | the plan is in the database |
| credits per turn, quote | **left out** | no costs in the interface |
| RAG craft notes / `craft_techniques` | left out for now; the author reads `search_kb` and production memory | D9 |
| prompt hygiene (`CHARTER_BUDGETS`, incident words) | copied into `test_prompt_hygiene.py` | — |
| replay harness `nova_studio_replay.py` | folded into `scripts/replay_director.py --engine zora` | one harness |

## 6. Phases

Each phase ends with `IMPLEMENTED.md` updated and the checks green: `ruff check src tests scripts`, `mypy`,
`scripts/lint_imports.py`, `hiru_ai validate`, `hiru_ai catalog --check`, `pytest -q` (with `OPENAI__API_KEY=` blank);
in the interface `npx next typegen && npm run check && npm run format:check`.

### Phase 0: evidence (free)

1. Ten real requests on three scenes the cinematic lab already planned (Episode 1's reading, `arrival`,
   `father_refuses`: saved answers in `lab/cinematic/runs`, so no model call):
   "make the approach colder", "her reaction before his line", "S03 on an 85", "the key image is her hands", "make it
   tenser", "two ways to open", "all in Sinhala", "add a reaction and keep 60 s", "undo that", "the next scene starts in
   the rain". Run each through today's chat in rules mode with recorded answers; record what lands, what is lost (G1–G9).
2. Turn them into replay cases (`tests/eval/zora/cases.json`, split tune / held-out) with expectations: `end_state`,
   `effects_delivered`, `claims_match_state`, `no_unbacked_promise`, `lines_verbatim`, `jonathan_problems_not_worse`.
3. Read (read-only, **ask first**) two stored director threads from the dev database to add real phrasing.

### Phase 1: the document and the kernel (free, offline)

`contracts/zora/{doc,ops,render}.py`, `steps/zora/zora_kernel`. Handles, exact undo, all-or-nothing removals, locks,
per-op validation against `JonathanWire`, the two renderings with the address header. Tests port Nova's: addressing from 1
with named ranges (W1), post-op numbers, `infer_op`, a removal batch lands whole or not at all (W3), a re-timed shot is
protected, a lock refuses a model op and accepts a person's, no op path writes a line's text.

### Phase 2: deps, board, ledger, delivery (free, offline)

`zora_deps`, `zora_board`, `zora_deliver`, `zora_ledger`, `contracts/zora/effects.py`. The stale table (§4.3), the
re-cut guard, the `WRITES` map with the build-time test that every effect has an owner that can reach it (Nova W4/W7),
`changed_effects` from the diff, the ledger lines matched by handle (W5), `nothing_changed`. Jonathan's check, mend and
the "only new problems" filter, called by id, with the saved lab plans as fixtures.

### Phase 3: the lab (paid, needs the person's yes and a budget)

`lab/zora/`: the conductor and author prompts, run on the Phase 0 cases with a **hard budget of $3** (D10), never paying
twice for a call (answers cached by input hash), one change per paid run, stop when the held-out cases pass at k=3.

Two arms, same cases:
- **A, one author** (this plan's design);
- **B, Nova seats**: the four `director_board` crafts as separate calls with ownership settling.

The person reads the end plans blind (which plan would you shoot?). B is built into the product only if it wins clearly
(rule 8); otherwise A. Results in `lab/zora/RESULTS.md`.

### Phase 4: the system `zora_chat` (free to build; tests use recorded answers)

`agents/zora/*` (the lab's winning prompts), `systems/zora/zora_chat` as a graph:
`read → conduct → [confirm | cannot | translate | options | offer | edit | craft | shape | chat] → kernel → deps → author
→ board → check/mend/repair → deliver → save → ledger → reply`. The guards of §4.8 copied in. Kill switch
`ZORA__ENABLED` (default false). Settings: `MAX_REPAIRS` (2), `DELIVERY_PASSES` (1), `RESHAPE_DIRTY_RATIO` (0.5),
`RESHAPE_MIN_SHOTS` (3), `VARIANTS_MAX` (3), `AUTHOR_TOOL_CALLS` (6), `TRANSCRIPT_MESSAGES` (4). Langfuse traces come
from the global hook.

### Phase 5: save, undo, seams (free; the migration is the person's)

`zora_save`, the revisions table pair and its pgTAP test, undo/redo, seams in the ledger, stale marks for frames and
prompts. Before the migration is applied, Zora runs without undo and says so in the panel (absent-safe).

### Phase 6: treatment mode and the pinned-treatment Jonathan run (needs D5)

Gaps, settled, "Plan shots from this treatment", the `treatment` check in `jonathan_check`.

### Phase 7: the API

`api/routers/zora.py`, events, permissions (direct / edit_script as today), the routing rule of §4.10, API tests.

### Phase 8: the interface (needs D8 frames)

`features/zora/`: chat panel, ledger, undo/redo, re-plan card, proposal cards, suggestions, locks, `@` sequences.
`client.ts` dispatches the new events. Tests for the ledger rendering, `nothing_changed`, undo and the mapper.

### Phase 9: evals and the live check (the person's)

`scripts/replay_director.py --engine zora --model --k 4` on the held-out cases: pass^4, honesty score (share of replies
whose claims all have receipts), `effects_delivered` rate, refusal rate. A director uses Zora on five real scenes and
compares with today's chat. Then D3 (default, retirement).

## 7. Decisions for the person

| # | Question | Recommendation |
|---|---|---|
| D1 | Name | **Decided 2026-11-06: Zora.** `group = zora`, settings `ZORA__*`. |
| D2 | One author or Nova's seats? | One author (pattern rules 1, 2, 8); the lab (Phase 3) decides. |
| D3 | Which scenes use Zora? | Scenes with a Jonathan plan; the old chat stays for the rest until Jonathan is the default, then retire it. |
| D4 | Undo storage | A `scene_plan_revisions` table, last 30 per scene. |
| D5 | Treatment mode and the pinned-treatment Jonathan run in v1? | Yes, but after Phase 5; it touches the `jonathan` group once. |
| D6 | Advisors (board personas) | Keep the persona as the reply's voice; advisors' views off in Zora v1 (each is a model call with no proof it helps). |
| D7 | Models | Conductor `medium`; author on the `jonathan` model at lower effort (a new `zora` tier, set by the lab); reply `medium`. |
| D8 | Figma | Frames for the ledger, undo, re-plan card and suggestions before Phase 8. |
| D9 | Craft notes (RAG) | Not in v1; the author has `search_kb` and production memory. |
| D10 | Lab budget | $3 hard cap, asked before each paid run. |

## 8. Risks

| Risk | Answer |
|---|---|
| One author is slower than four small seats | One call with scoped context; `edit` lanes need no author at all. Measured in the lab. |
| Jonathan's check is too strict for small edits and blocks them | Only problems new this turn count; repair ≤ 2, then reported, never blocking. |
| The chat and a Jonathan re-run write the same scene at once | `zora_save` refuses a write whose `previous` is not the current plan (optimistic check), and the panel re-reads. |
| Two chats to maintain until D3 | Zora copies, never imports, the old chat's guards; the old one is removed whole later. |
| Prompt overfitting to the Phase 0 requests | Held-out split, incident-word test, charter budgets (Nova prompt hygiene). |
