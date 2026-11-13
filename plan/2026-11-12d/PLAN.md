# Zora without a planner: the director chat edits the shot rows (plan/2026-11-12d)

**The build is plan/2026-11-13/PLAN.md** (2026-11-13): it carries this design, the lab's final choices and the silent-shot fix; a new chat implements from it.

Revision 3 (2026-11-13): phase 0 (the lab) DONE, $0.80 of $2.00 in three paid runs on Hiru Short Combined 2 Scene 03; results in lab/zora_rows/RESULTS.md and section 2a. Revision 2 (2026-11-12): every decision taken as recommended. Nothing built in src/ yet. Phase 0 is a small paid lab (the person's yes first); phases 1 to 6 are offline;
phase 7 is a paid live check (the person's yes first).

**Read §1 and §3 first if you are a new chat picking this up.** Two pages were drawn for the person before this plan:
[How Zora Works](https://claude.ai/artifact/ThSZuW7FCgBnuZRnUEnDU2) (Zora as it is, its agents, memories and the six
problems found) and [Zora Without a Planner](https://claude.ai/artifact/HpE9khgRjCkiBkUFkverX4) (the shape agreed here,
with the Accept / Reject card).

## 1. Why

Zora (plan/2026-11-06e) edits Shot Planner Jonathan's stored plan, not the scene's shots. It takes six things from
Jonathan: the plan's shape (treatment → sequences → shots), his scene builder, `jonathan_check` after every operation,
`jonathan_mend` + `jonathan_check` as the gate, `jonathan_write` as the save, and his author prompt as the head of
Zora's. A scene another planner made is adopted into Jonathan's shape (`zora_chat/scene.adopt`), and the first Zora save
rewrites its rows through `jonathan_write`: the planner becomes `jonathan`, titles and intents are rewritten, Raphael's
coverage roles are lost.

The person's direction (2026-11-12):

1. **All planners except Raphael will be deprecated, and new planners will come.** Zora must not be bound to any
   planner.
2. **The planner plans, Zora edits.** Zora has no dependency on a planner.
3. **The director knows what they are doing.** Zora does not refuse a risky edit (removing a must clip, a split, a
   merge); it shows what will happen and asks in the chat, and the person presses Accept or Reject.

Also found while reading Zora (the first page above), and settled here where they touch the same code:

- The conductor's "remember this" is written to `memory_items` and never read by Zora (only the dropped classic chat
  read it, `systems/director_chat/view.py:67`).
- The translate lane sends the person to the classic chat, which the interface no longer shows (`turn.py:63`).
- A turn has 300 s (`task_manager.ZORA_CHAT`) but one author call may take 600 s and a turn may make four.
- The author's `effort_zora` ("low", gpt-6.1-sol) was never tried: the Zora lab of 2026-11-06e was not run.

## 2. What is already there to build on

- **The rows are already the common ground.** Every planner writes `shots` rows and binds `dialogue_lines.shot_id`.
  Raphael's rows carry `role`, `priority` (must / should / nice), `slate`, `handle_in_s`, `handle_out_s`, `stage`,
  `anchor`, `blend` next to `block_start`, `block_end`, `framing`, `duration_s`, `camera_link`, `sound_mode`, `ir`,
  `card`, `intent`, `design` (`raphael_write`, schema v23).
- **A line is performed by one clip.** `dialogue_lines.shot_id` is a single id; Raphael binds a line to the must clip
  that performs it, and the other clips over that line play silent or under it.
- **Locks already have homes on the row:** `duration_locked`, `camera_overrides` (what a person changed on the camera),
  `person_edits` (`contracts.producer.PersonEdits`: who is in the shot, advisories to ignore, the DoP's note).
- **The checks that understand coverage are Raphael's** (`contracts/raphael/checks.py`: coverage, length, clock,
  long action, feasibility, designs, consistency, device unseen, the state ledger of plan/2026-11-09). The general
  checks do not: `stage_check` and `scene_kernel` go through `contracts.shotplan.fit`, whose rule is "every block in
  exactly one shot" (the rule that collapsed a 14-shot coverage plan to S01–S03 on 2026-11-09).
- **The camera is finished by shared code:** `steps/serialize/shots.finish` (IR coerced, subjects pruned, names over
  codes, spoken words stripped, beats fitted). No planner owns it.
- **Speech timing is shared:** `contracts/timing.py` (2.2 words/s, overruns reported, never trimmed), mirrored by the
  interface's `src/lib/veo/timing.ts`.
- **Marking frames and prompts stale is shared:** `api/services/sable.mark_out_of_date` (version + 1 on touched shots).
- **Zora's machinery that does not know Jonathan stays:** the graph, the conductor's checks and retry, the kernel's
  guarantees (stable handles, exact undo, a bad operation rolled back, removals all or nothing, locks, no line words),
  the board, the delivery check, the ledger, the reply guard, Stop finishing the turn, Edit / Ask again, the revisions
  table and its stack.

## 2a. What the lab taught (phase 0, done 2026-11-13)

Full table in `lab/zora_rows/RESULTS.md`; pages: run 1 https://claude.ai/artifact/E8KgPVitgzwhUcm9XYZUDz, run 2 (two
reply voices) https://claude.ai/artifact/N7TUHS7xWUTdp8DuRYcanc, run 3 https://claude.ai/artifact/RdpxZCvW6TGjXndnoWdpBs.
The design of section 3 held: no planner, coverage edits, lines following their clip, Accept / Reject. Phase 3 takes
these from the lab (the lab's `coverage.py`, `kernel.py`, `checks.py`, `risk.py`, `turn.py` and prompts are the starting
point, ported, not imported):

- **The reply is a colleague, not a reporter** (the person, 2026-11-13: "Sable is natural, Zora is structured and not
  friendly"). A persona, the last 12 messages, the facts in plain sentences (`plain()`), no list read back (the panel
  shows the changes block), one optional suggestion; a card is talked about as a proposal; never ADR or a reshoot (every
  clip is generated). Model gpt-5.
- **A code guard on the reply**: cut from a pasted fact-sheet header, and cut card or button words when no card is
  shown ("the script card" is a route, kept).
- **Task shots are the numbers as printed, before the turn's ops**; code alone tasks the author with a new clip's picture
  and with a clip that takes over a removed clip's line.
- **An insert with no size is an INSERT**; only a value the person said is locked.
- **A new overrun a model caused is repaired**; one on a take a person set is reported.
- **Accept and "Use this" replay the operations in the batches they landed in.**
- The author's note goes to the reply only when none of the team's work was refused.

## 3. The design

### 3.1 The shot contract

One document, `contracts/coverage/` (pure standard library + pydantic), read from rows and written back to rows:

    Coverage.of(scene_row, shot_rows, line_rows, staging)   the scene as clips, in row order
    Clip                                                     one shot row as Zora sees it (below)
    Coverage.rows(old_rows)                                  the changed clips as row updates, ids kept

A `Clip` is: its handle and number, `blocks` (`block_start` to `block_end`, may overlap other clips), `lines` (the
`dialogue_lines` it performs, read-only words), `role`, `priority`, `slate`, `anchor`, `blend`, `handles`, `size`
(`framing`, the database's list: WIDE, MS, MCU, CU, TWO, OTS, INSERT), `take_s` (`duration_s`: 4 / 6 / 8), `link`,
`sound_mode`, `ir`, `intent`, and its `locks` (from `duration_locked`, `camera_overrides`, `person_edits`).

Fields Zora never writes: a line's words, `planner`, `stage`, `card`, `design` (re-derived when the IR changes),
`slate` (renumbered by code when clips are added or removed, D6). A field a future planner adds that is not in the
contract is carried through untouched.

**Field audit (phase 1, done 2026-11-12).** Raphael's checks read, per clip: `id`, `blocks`, `take_s`, `ir`, `lines`,
`speaks`, `handle_in_s` / `handle_out_s`, `priority`, `role`, `sound`, `why`, `angle`, `lens`, **`technique`** and
**`moment`**; per scene: the blocks (kind, speaker, line id, delivery, screen time, holds, the ledger's `now`,
`device`), the staging map, the edit plan's moments and the target length (`guide_s`). What the rows Raphael writes
(`raphael_write.rows_for`) give:

| Check input | On the row | Missing |
|---|---|---|
| blocks, take, role, priority, slate, handles, anchor, blend, stage | columns | |
| lines heard, on the speaker or over whom; sound design; size | `card` (`lines`, `sound`, `size`) | |
| performs a line (`speaks`) | `dialogue_lines.shot_id` + `card.lines[].on_speaker` | |
| why | `intent.purpose` | |
| angle, lens, movement | `ir.cinematography` | |
| setup letter | the slate (`12B-3` → B) | |
| **technique** (feasibility: what Veo can do) | | only in `scenes.raphael` |
| **moment** (which moment of the intended cut) | | only in `scenes.raphael` |
| the edit plan's moments, target length | | `scenes.raphael`, the scene's reading |

Decision for the gap (recommended, no migration): **Raphael's `card_of` also writes `technique` and `moment`** into
`card`, so the rows carry every per-clip fact. A row without them (planned before this change) reads technique as
unknown (the feasibility check skips that clip) and moment as none. The moment-level checks (every moment covered, the
moment review) stay Raphael's: Zora checks clips and lines, not moments. The target length comes from the scene
(`envelope_s`), which every planner has. `raphael_write` had uncommitted changes by someone else on 2026-11-12, so this
edit waits for them to land.

**Coverage, not a cut.** Clips may overlap. Row order (`number`) is the intended cut order the planner wrote. A single
cut is coverage with no overlap, so a scene from any planner fits.

### 3.2 The row kernel (`steps/coverage_kernel`)

Zora's kernel (`steps/zora/zora_kernel`) moved onto `Coverage`, with the same six guarantees, plus:

- **Operations:** `set` (size, angle, lens, link, why), `retime`, `sound.set`, `ir.set`, `insert` (a new clip over a
  block range, with role and who), `remove`, `split`, `merge`, `move`, `role.set`, `line.move` (perform a line in
  another clip). The names, the flat wire shape and `to_op` stay as in `contracts/zora/ops.py`; the treatment, arc,
  colour, sequence and staging-mark operations go.
- **Lines follow the clip that performs them.** Removing, splitting or merging a clip that performs a line moves the
  line, in code, to the clip that best keeps it: the overlapping clip that shows the speaker, else the clip that
  takes the line's blocks after a split. When no clip can take it, the operation is still tried, and the risk rule
  (§3.4) puts the question to the person (D7).
- **Validation is the shared checks' blocking faults** (§3.3), never a planner's.

### 3.3 The checks (`contracts/coverage/checks.py`)

The planner-free parts of `contracts/raphael/checks.py` are moved here and read a `Coverage`, not Raphael's `Bin`:
coverage (every line performed once, every block shown), clock and length (`contracts/timing`), long action,
feasibility, designs, consistency, device unseen, and the state ledger (plan/2026-11-09: hands, handovers, posture,
condition, presence, place). **Raphael then calls the shared checks** through a small `Bin → Coverage` adapter, so a
planner depends on the shared contract and Zora depends on nothing of Raphael's (D3). Raphael's stage-2 craft checks
(variety, blend notes, the moment review) stay Raphael's.

`shot_joins` and `prompt_lint` stay as they are (they read rows already); `stage_check` is not used by Zora (single-cut
`fit`). As today: only problems THIS turn introduced count, at most two repair passes, a worse pass is dropped, an
overrun is reported and never trimmed, a take the person set is kept.

### 3.4 The risk rule and the Accept / Reject card

After the checks and repairs, code reads the turn's operations (never a model) and decides:

**Asks first** (D5, the person's list to change):

- remove a must clip, or any clip that is the only one performing a line;
- split or merge;
- change a clip's role;
- move a line to another clip;
- an edit that changes more than half the clips (replaces today's re-cut guard and its re-plan offer);
- change a field a person locked (only the conductor, from the person's own words, may try it);
- an edit that leaves a new problem the repairs could not fix.

**Applies straight away** (Undo available): size, angle, lens, movement, take length while the line still fits,
sound, IR fields, adding a cinematic clip, removing a cinematic or slate clip that performs no line.

A risky turn saves nothing. Its reply carries a `confirm` block: the exact operations, the consequences in plain lines
(which line moves where, take changes, scene length before → after, checks after the change), and the fingerprint of
the rows the turn read. The person's click is an action, as "Use this" is today (`zora_chat/actions.py`):

- **Accept** (no model): refused when the rows changed since the card was made; else the operations are applied on
  the current rows, checked once more, saved (§3.5) as a revision of kind `use` (D8), and the card says
  "Accepted · revision N".
- **Reject**: nothing changes; the card says "Rejected". The ledger of the next turn knows it, so Zora does not offer
  the same thing again in this thread (`zora_guard.repeated`).

The options lane keeps its cards: each variant is tried on a copy and checked; a variant that is risky is labelled
"needs your OK" and its "Use this" is the Accept.

### 3.5 Save in place, undo, stale marks

- **Save:** only changed clips are written, ids kept, `version` + 1; new clips get new rows; removed clips are deleted;
  `dialogue_lines.shot_id` follows the kernel. A clip whose IR changed is finished by `serialize.shots.finish` and its
  `design` re-derived; frames and prompts of touched clips are marked out of date (the `mark_out_of_date` path). The
  optimistic check stays: rows changed since the turn read them → nothing saved, "ask again".
- **Never written by Zora:** `scenes.<planner>` (Raphael's stored result is "as planned" history), `planner`.
- **Undo:** `scene_plan_revisions` stays; `stored` holds the row snapshot of the scene's clips and line bindings instead
  of `scenes.jonathan` (the column is `jsonb`; only its comment changes). Restore writes the snapshot back with the
  original ids. A revision made before this plan (a Jonathan JSON) is not restorable and the stack starts after it.
- **Locks:** a person's lock and unlock write the row fields of §2 (D6); no lock lives in a planner's JSON.

### 3.6 The turn after the change

    read rows → in code (undo · redo · confirm) ─┬─ conduct → chat | clarify | cannot ─────────────┐
                                                 └─ conduct → edit | craft | options → kernel →    │
                                                    author → board → delivery → checks → repair →  │
                                                    risk ─┬─ safe: save                            │
                                                          └─ risky: card (nothing saved) ── reply ←┘

- **Lanes:** `chat`, `clarify`, `edit`, `craft`, `options`, `cannot`. `shape` becomes the risky "changes most of the
  scene" card or, for a request no edit can express, a "Re-plan the scene" offer (D2). `translate` goes (D10).
- **Dependencies (`zora_deps`)** keep only the clip rules: a new or split clip needs its picture and reason, a merge
  needs one picture, any touched clip is stale. The treatment rules go.
- **Agents:** the conductor and the reply stay (`gpt-5-mini`), with the plan rendered as coverage (each clip with its
  blocks, role, size, take, who performs which line, locks). The author gets **Zora's own craft prompt**, written for
  coverage (phase 0), not Jonathan's. Its model and effort come from the lab (D9).
- **Time:** the author's timeout and the turn's budget are set so a turn fits the function's deadline (D11).
- **Memory:** the conductor's `memory` either feeds back (D12) or is removed; it is never written and left unread.

### 3.7 What goes away

`zora_chat/scene.adopt` and `planner_scene`, `zora_board/gate.py` (Jonathan's mend and check), `zora_save` through
`jonathan_write`, `zora_kernel/step.kernel_for` (Jonathan's check), the treatment mode and its suggestions ("Draft the
arc", "You decide the rest", "Plan shots from this treatment"), `contracts/zora/treatment.py`, the `translate` lane,
Jonathan's prompt at the head of `zora_author`, `PLANNER = "jonathan"` in `api/services/zora.py` and `scene.py`, and the
Zora entries in `tests/jonathan/test_removal.py`. `tests/zora/test_isolation.py` gains a rule: no Zora file imports or
names a planner.

### 3.8 The interface

- Zora panel: a `confirm` block with the consequences and **Accept** / **Reject** (the Sable card's look:
  `features/sable/components/sable-blocks.tsx`), and its settled state; a risky option card says "needs your OK".
- The treatment chips above the composer go. The changes block and "What changed" stay.
- Locks are set on the shot (size, lens, take) as today's lock buttons, written to the row fields.
- The panel title says which planner made the scene, as information only.

## 4. Phases

| Phase | What | Cost | State |
|---|---|---|---|
| 0 | Lab (`lab/zora_rows/`), the person's yes first: on one Raphael scene the person picks, the conductor and a new coverage author prompt over recorded turns (exact change, craft note, options, a risky remove); the planner-free checks on each answer; the author's model and effort compared on the same turns | cap $2.00 | done 2026-11-13, $0.80 (§2a) |
| 1 | `contracts/coverage/`: `Coverage`, `Clip`, rows in and out; a field audit (does every field the checks read survive in the rows Raphael writes? what is missing is listed, not guessed); the shared checks moved out of `contracts/raphael/checks.py`; Raphael's checks call them through `Bin → Coverage` with its existing tests green and a parity test (same faults on Raphael's fixtures) | $0 | |
| 2 | `steps/coverage_kernel`: the operations of §3.2 with the zora kernel's guarantees and tests (overlap allowed, lines follow their clip, locks from row fields, removals all or nothing); the risk rule (§3.4) as pure code with its own tests | $0 | |
| 3 | Zora on rows: `zora_chat` read and save on `Coverage`; revisions as row snapshots; the `confirm` block and the accept / reject actions; lanes, deps and agents of §3.6 (prompts from phase 0); the time budget; §3.7 removed; the isolation test | $0 | |
| 4 | API: `POST /scenes/{id}/zora/accept`, `/reject` (CanDirect, approved scene → 409); lock / unlock write row fields; re-plan per D2; status no longer asks for a Jonathan plan | $0 | |
| 5 | Interface: §3.8, with tests; `npx next typegen && npm run check && npm run format:check` | $0 | |
| 6 | Sable's change cards through the row editor instead of the classic director function (D4) | $0 | |
| 7 | Live check, the person's yes: one Raphael scene, scripted turns: exact change, craft note, two options + Use this, a risky remove → Accept, the same → Reject, undo, redo, a Stop mid-turn | cap $1.50 | |

Checks before finishing (backend): `ruff check src tests scripts`, `mypy`, `.venv/Scripts/python.exe
scripts/lint_imports.py`, `hiru_ai validate`, `hiru_ai catalog --check`, `pytest -q` (with `ADAM_MODE=staged
OPENAI__API_KEY=`). Interface: `npx next typegen && npm run check && npm run format:check`.

## 5. Decisions

- **D1 (taken, 2026-11-12):** Zora has no dependency on any planner; it edits the shot rows. Planners plan from nothing.
- **D2 (taken, 2026-11-12, as recommended). The "Re-plan the scene" offer.** Recommended: **keep it, calling the production's `shot_planner`** (the job kind
  chosen by the setting, never a planner's name in Zora's code). Alternative: drop it from Zora; re-plans start from
  the build screen only.
- **D3 (taken, 2026-11-12, as recommended). Where the coverage checks live.** Recommended: **move them to `contracts/coverage/` and make Raphael call
  them.** Alternatives: Zora calls Raphael's checks by id (a planner dependency again), or Zora writes its own copy (two
  lists that drift).
- **D4 (taken, 2026-11-12, as recommended). Sable.** Recommended: **phase 6 of this plan**: Sable's change cards are applied today by the classic director
  function and its single-cut kernel, the same coverage problem. Alternative: a later plan.
- **D5 (taken, 2026-11-12). The risk list (§3.4)** as drafted; the person may change it later.
- **D6 (taken, 2026-11-12, as recommended). Locks and slates.** Recommended: locks in `duration_locked`, `camera_overrides`, `person_edits` (no migration);
  slates renumbered by code after an insert or removal, the letters of the setups kept.
- **D7 (taken, 2026-11-12, as recommended). A line with no clip to take it** (removing the only clip that shows its speaker). Recommended: **the card offers
  to add a single on the speaker** as part of the same Accept. Alternative: refuse the removal with the reason.
- **D8 (taken, 2026-11-12, as recommended). Accept as a revision kind.** Recommended: **`use`** (no migration). Alternative: schema v24 adds `accept` and
  `reject` so the history reads plainly.
- **D9 (answered by the lab, 2026-11-13, runs 1-6).** The person's targets: a small request under $0.001, at most $0.02 a turn. Conductor gpt-5-mini at minimal; author **gpt-6.1-terra** at low; every reply gpt-5-mini at minimal; plain commands (size, take, remove) read by code with no model; a hard $0.02 cap per turn in code (each call's output capped to what the turn can afford). Measured: a plain command $0.0009, a click $0.0007-0.001, a question $0.0017, a craft note about $0.015 (lab/zora_rows/RESULTS.md).
- **D10 (taken, 2026-11-12, as recommended). Translation.** Recommended: **drop the lane**; a request to translate is answered as `cannot` with "ask Sable"
  if Sable can stage it, else "not available in the chat".
- **D11 (taken, 2026-11-12, as recommended). Time.** Recommended: author timeout 120 s, at most three author calls per turn (first, one re-task, one
  repair), function deadline 300 s kept; a turn that runs out saves nothing and says so.
- **D12 (taken, 2026-11-12, as recommended). "Remember this."** Recommended: **the production memory reads it**: a Zora decision is stored as a production
  memory entry, so the middleware gives it to the author (and the conductor gains `production_memory`). Alternative:
  remove the conductor's `memory` field.

## 6. Not in this plan

- Deprecating Adam, David, Jonathan and the classic planner (the person's own work); this plan only stops Zora
  depending on any of them.
- Changing what Raphael plans, or its stage-2 craft checks.
- Regenerating frames or prompts after an edit (they are marked out of date, as today).
- Editing a line's words (the script card) or translating dialogue.
- A treatment, arc or colour script in Zora.
