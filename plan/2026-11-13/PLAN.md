# Zora on the shot rows: the build (plan/2026-11-13)

Revision 1 (2026-11-13). Nothing in this plan is built. Phases 1 to 8 are offline ($0); phase 9 is a paid live check
(the person's yes first). This plan BUILDS what plan/2026-11-12d designed and its lab proved; read this file first, then
`plan/2026-11-12d/PLAN.md` (§1, §2a, §3, §5) and `lab/zora_rows/RESULTS.md`. Everything a new chat needs is written here
or named here by path.

Pages drawn for the person (read-only context): how Zora works today https://claude.ai/artifact/ThSZuW7FCgBnuZRnUEnDU2;
the agreed shape https://claude.ai/artifact/HpE9khgRjCkiBkUFkverX4; the lab's last run (the target behaviour)
https://claude.ai/artifact/ThPDx6u6RtT45rdtxkAE57.

## 0. Rules for the chat that builds this (read before anything)

- **Two repos.** Backend: `C:\Users\witha\Documents\projects\Hiru TV\source\hiru-ai-studio` (Python 3.12, run everything
  with `.venv/Scripts/python.exe`; the system `python` is 3.9 and must not be used). Interface:
  `...\hiru-ai-studio-interface` (Next.js 16; read its `CLAUDE.md` and `AGENTS.md` first, they are binding).
- **No model call, image or paid run without the person's yes, each time.** Tests run with `OPENAI__API_KEY=` blank
  (the `.env` holds a real key). The hosted Supabase is the one dev database: no SQL and no writes against it without
  asking; reads only inside `set transaction read only`.
- **The database was replaced on 2026-11-13** (the person removed the old one and put the new one in `.env`). Hiru
  Short Combined 2, the lab's scene, is NOT in it; the lab keeps its own copy (`lab/zora_rows/input/…json`), so every
  offline test and the recorded-answer replay use that file, never the database. Read on 2026-11-13: one production,
  "test" (`shot_planner` raphael), 12 scenes (4 per episode, 3 episodes), 6 shots and 6 lines each, every shot planned
  by **classic**; `scene_plan_revisions` and `chat_messages` empty; no shot performs a line while stored silent. The
  schema has the Raphael columns on `shots`.
- **Files are CRLF.** Rewrite a backend file with `open(p, "w", encoding="utf-8", newline="")` keeping its endings. In
  this harness a Bash heredoc turns `\n` inside the text into a real newline: write any code that contains escapes with
  the Write tool, never through a heredoc.
- **Someone else's uncommitted work:** on 2026-11-12 `steps/raphael/raphael_write/logic.py` and its test had uncommitted
  changes that are not ours (heard lines written `voiceover`, see §3.7). Do not overwrite them; read `git diff` first.
- **Baseline before any change** (`ADAM_MODE=staged OPENAI__API_KEY= .venv/Scripts/python.exe -m pytest -q -p
  no:logging tests/raphael tests/zora`, 2026-11-12): 5 failures that are not ours: two in `tests/raphael/test_api.py`
  (cap refused / result whole), `tests/raphael/test_checks.py::test_the_bin_over_each_cap_fails_and_at_the_cap_passes[1]`,
  and the removal-list tests `tests/raphael/test_removal.py` and `tests/zora/test_removal.py`. Run the baseline again
  before phase 1 and report only failures that are new.
- **Commit only when the person asks.** Work stays uncommitted; write `IMPLEMENTED.md` in this folder as phases land.
- Checks before finishing (backend): `ruff check src tests scripts`, `mypy`, `.venv/Scripts/python.exe
  scripts/lint_imports.py`, `.venv/Scripts/python.exe -m hiru_ai validate`, `... -m hiru_ai catalog --check`, `pytest -q`
  (with `ADAM_MODE=staged OPENAI__API_KEY=`). Interface: `npx next typegen && npm run check && npm run format:check`.

## 1. What and why, in short

Zora is the director chat beside one scene. Today (plan/2026-11-06e) it edits Shot Planner Jonathan's stored plan
(`scenes.jonathan`): it adopts any other planner's scene into Jonathan's shape, checks with `jonathan_check` /
`jonathan_mend`, saves through `jonathan_write` (which rewrites the rows and makes the planner "jonathan"), and its author
prompt starts with Jonathan's. The person is deprecating every planner except Raphael, and new planners will come, so
(their words, 2026-11-12) **"the planner plans, Zora edits": Zora must have no dependency on any planner.**

The new Zora edits the **shot rows** (`shots` + `dialogue_lines.shot_id`) directly, as **coverage** (clips may overlap;
each line is performed by exactly one clip). Risky edits are not refused: Zora shows what will happen on a card and the
person presses **Accept** or **Reject** (the person: "he knows what he is doing"). Replies talk like a colleague, not a
report. A turn costs **under $0.001 for a plain command or a click and at most $0.02** (the person's targets; measured in
the lab, §2). The planner is used only for "Re-plan the scene", through the production's `shot_planner` setting.

Also in this plan (the person, 2026-11-13): **a clip that performs a line but is stored silent** (Veo was told "nobody
speaks" over a spoken line) is found by code and fixed by Zora (§3.7).

## 2. What the lab proved (lab/zora_rows, $1.03 in six paid runs, 2026-11-13)

Scene: Hiru Short Combined 2, Scene 03 (Colombo garage flashback), planned by Raphael: 7 blocks, 20 overlapping clips,
lines L2 / L3 / L4 performed by S05 / S08 / S11 (`lab/zora_rows/input/0f4ba0fd-db0b-4722-8feb-e89586b06f24.json`). Twelve
turns: a question, an exact change, a craft note, a risky removal accepted then undone, a risky removal rejected, a
script change, an insert, options, "Use this". Run 6 did all twelve right.

Final model choice (plan/2026-11-12d D9):

| Role | Model, effort | Measured |
|---|---|---|
| plain commands (size, take, remove) | **code, no model** | $0 |
| conductor (reads the message) | gpt-5-mini, minimal | ≈ $0.0007-0.0011 |
| author (the craft) | **gpt-6.1-terra, low** | ≈ $0.002-0.012 |
| reply (every turn) | gpt-5-mini, minimal | ≈ $0.0007-0.0017 |

Per turn (uncached): command $0.0009; Accept / Undo / Reject $0.0007-0.0010; "Use this" $0.0015; a question $0.0017;
"not possible here" $0.0019; "Drop S08" with its card $0.0033; insert $0.0073; two endings $0.0114; "make it tenser"
≈ $0.015. Whole session ≈ $0.05 (run 3 on gpt-6.1-sol + gpt-5: $0.29).

Rejected in the lab: **gpt-5-nano** (misread 5 of 7 messages as conductor, unreliable replies); gpt-5-mini at *low* as the
reply (pasted its fact sheet back); gpt-6.1-terra as the reply (dry); gpt-5 as the reply (warm, but $0.006-0.014 does
not fit beside the author inside $0.02).

## 3. The design (port the lab, not import it)

The lab code is the reference implementation. Port each file into the product's structure (contracts are pure
standard library + pydantic; steps and systems follow the repo's ADRs: a step is reached by id through `core.parts`,
never imported across groups; `scripts/lint_imports.py` enforces it). Keep the lab folder as it is (it is the evidence).

| Lab file | Becomes | Notes |
|---|---|---|
| `lab/zora_rows/coverage.py` | `src/libs/contracts/coverage/scene.py` (+ `__init__.py`) | `Coverage`, `Clip`, `Line`, `Block`, `render`, `fingerprint`, `to_rows`; load from rows the ports return, not from a file |
| `lab/zora_rows/kernel.py` | `src/libs/hiru_ai/steps/coverage/coverage_kernel/` (`logic.py`, `step.py`, `component.yaml`, `tests/`) | + the `sound_mode` operation (§3.7) |
| `lab/zora_rows/checks.py` | `src/libs/contracts/coverage/checks.py` | + `line_unvoiced` (§3.7) |
| `lab/zora_rows/risk.py` | `src/libs/contracts/coverage/risk.py` | |
| `lab/zora_rows/turn.py` | `src/libs/hiru_ai/systems/zora/zora_chat/turn.py` (rewrite) | the graph in `graph.py` keeps its shape |
| `lab/zora_rows/agents.py` (schemas, budget) | `src/libs/contracts/zora/wire.py` (schemas) + `systems/zora/zora_chat/budget.py` | |
| `lab/zora_rows/prompts/{conductor,author,reply}.md` | `agents/zora/zora_{conductor,author,reply}/prompts/system.md` | the author's `{SAFE}` is `contracts.safe_depiction.PROMPT_LINE` |
| `lab/zora_rows/tests/test_lab.py` | `tests/zora/test_rows_*.py` | all 18 cases, adapted |

### 3.1 The shot contract (`contracts/coverage`)

Read from the rows (`scenes.lines(scene_id)`, `scenes.shots(scene_id)`, the scene row with `script` and `staging`, the
production's characters for names). A `Clip` is one shot row:

| Clip field | Row field |
|---|---|
| `h` (stable handle for the turn), `row_id` | `id` |
| `slate`, `role`, `priority`, `stage`, `anchor`, `blend`, `handle_in_s/out_s` | same columns (Raphael's; "" / 0 / [] for other planners) |
| `size` | `framing` (the database's list only: WIDE, MS, MCU, CU, TWO, OTS, INSERT) |
| `take_s` | `duration_s` (4, 6, 8) |
| `link`, `sound_mode` | `camera_link`, `sound_mode` |
| `first`, `last` (blocks `[first, last)`) | `block_start`, `block_end` |
| `why`, `sees`, `on_screen` (names) | `intent.purpose`, `intent.what_we_see`, `intent.on_screen` (character ids → names) |
| `sound` (ambience, effects, music, silence) | `card.sound` |
| `heard` (line ids heard on the clip) | `card.lines[].line_id` |
| `ir` | `ir` (camera design; `ir.cinematography.angle/lens/movement`, `setting`, `lighting`, `audio`, `beats`, `subjects`, `first_frame`) |
| `locks` | §3.5 |

Blocks come from the scene's `script` (a dialogue block is bound to its `dialogue_lines` row by `line_id`, else by order);
a line's id for the models is `L<block index>` (as Raphael's cards write it). A line is performed by the clip in
`dialogue_lines.shot_id`. Never read `scenes.raphael`, `scenes.jonathan`, `scenes.david`, `scenes.adam` or
`scenes.coverage`: they are planners' and Zora must not depend on them. Fields a planner adds that the contract does not
name are carried through untouched. **Field gap (plan/2026-11-12d §3.1 audit):** rows do not carry Raphael's `technique`
or `moment`; Zora does not need them (its checks are per clip and per line), so nothing is added for them in this plan.

### 3.2 The row kernel (`steps/coverage/coverage_kernel`)

Operations (flat objects, unused fields null; shots named `S01..` as numbered AT THE START of the batch):
`set` (shot, field ∈ size | link | why | sees | angle | lens | movement | setting | lighting | audio | beats | subjects |
first_frame; the last three a JSON string, whole), `retime` (take_s 4/6/8), `sound` (field ∈ ambience | effects | music |
silence), `sound_mode` (§3.7), `role` (role, priority), `insert` (after, role, size, take_s, first_block, last_block,
who, what), `remove`, `split` (at_block, inside the clip), `merge` (to_shot), `move` (after), `line` (line, to_shot).

Guarantees (port the lab's and keep its tests): numbers read at the batch's start and resolved to handles once; each
operation rolled back alone if it fails; removals land all or none; a model (`author`, `repair`) never writes a locked
field, the person's own words (`conductor`, `person`) may, and what they set becomes locked; no operation writes a line's
words. Coverage rules: a removed / split / merged clip's lines move in code to the clip that best keeps them (covers the
block, speaker on screen, a master / two-shot / single before a reaction or insert, must before should); no such clip
leaves the line unbound (the checks report it, the risk rule asks). An insert with no size is an INSERT; only a size or
words the person gave are locked (lab run 2 bug: a default was locked). A priority written in the role field
("must") moves to `priority`.

### 3.3 The checks (`contracts/coverage/checks.py`, code, no model)

`find(cov)` and `new(before, after)` (keys use handles, so renumbering is not "new"): `block_unshown`, `line_unbound`,
`line_outside`, `speaker_unseen` (report), `overrun` (`contracts.timing.speech_seconds` against the take: **repair** when a
model made the take, **report** when a person set it; never trimmed), `picture_empty` (a new or re-cut clip with no why or
IR), `anchor_gone` (report), `unsafe` (`contracts.safe_depiction.blocking` over the clip's text), `length` (takes over
1.5x the scene's `envelope_s`, report), and `line_unvoiced` (§3.7). Only problems the turn introduced count. At most
one repair pass per turn inside the budget (D11 in 2026-11-12d said three author calls; the budget decides now).
Extracting Raphael's own coverage checks (`contracts/raphael/checks.py`) into shared code (2026-11-12d D3) is NOT in
this plan; the lab worked without them.

### 3.4 The risk rule and the Accept / Reject card (`contracts/coverage/risk.py`)

From the operations that landed (never a model), a turn ASKS FIRST when it: removes a must clip or the clip that performs
a line; splits or merges; changes a role; moves a line; changes more than half the clips; changes a field a person locked;
or leaves a new problem the repair could not fix. A risky turn saves nothing: its message carries a `confirm` block
`{ops: [{op, by}], made_on: <fingerprint of the rows read>, reasons, lines (consequences)}`. **Accept** is an action, no
model: refused when the rows' fingerprint changed; else the ops are replayed **in the batches they landed in** (lab run 1
bug: one at a time shifted the numbers), checked, saved, a revision of kind `use`. **Reject** changes nothing; the thread
remembers it and the conductor is told not to offer it again. Options keep their cards ("Use this" = the same replay).

### 3.5 Save in place, locks, undo

- **Save** with `scenes.save_plan(scene_id, shots, removed, lines, scene_fields={})` (ports.py; the adapter upserts shots,
  deletes removed ones, upserts lines): changed clips only, ids kept, `version + 1`, `number` renumbered in row order; a
  new clip gets `uuid4`, `production_id`, `scene_id`, `planner` = the scene's existing planner value (the column's check
  list), `status = draft`. A clip whose IR changed is finished with `steps/serialize/shots.finish(entry, ShotInput,
  SceneInput, ProductionInput)` (reached by id) and its design saved (`scenes.save_design`). Bump `version` on every
  touched clip so prompts and frames read as out of date (as `api/services/sable.mark_out_of_date` does). Never write
  `scenes.<planner>` or a row's `planner` for an existing clip. The optimistic check stays: rows changed since the turn
  read them → nothing saved, "ask again".
- **Locks** (D-A below): `duration_locked` for the take; the other fields in `shots.person_edits` under a new
  `PersonEdits.zora_locks: list[str]` (contracts/producer.py; `extra="ignore"`, so add the field and its `dump`).
- **Undo**: `scene_plan_revisions` stays; `stored` = `{"rows": [...the scene's clip rows as Zora wrote them...], "lines":
  [{id, shot_id}]}`; kinds `base | turn | use | undo | redo` (the table's check; Accept is `use`, no migration). A
  revision written before this plan holds a Jonathan JSON: the stack starts after it (say so in the reply when undo
  reaches it).

### 3.6 The turn (`systems/zora/zora_chat/turn.py`)

```
read rows → in code ─┬─ undo · redo · [Accept] · [Reject] · [Use N] (actions, no model) ─────────────────┐
                     ├─ quick(): a plain command code reads itself (no model) ──┐                         │
                     └─ conductor (gpt-5-mini minimal) ─┬─ chat | clarify | cannot ──────────────────────┤
                                                        └─ edit | craft | options ─┴→ kernel → code tasks │
                        → author (terra low) → board → delivery → checks → repair ≤1 → risk ─┬─ save     │
                                                                                             └─ card ─ reply
```

- **quick()** (lab `turn.quick`): `(please) drop|remove|delete|cut S05(, any reason)` → remove; `(please)(make) S01
  (a|an|to|into) <parts>` where every part (split on `,` / `and`) is a take `4|6|8 s/sec/seconds` or a size word
  (wide, medium, ms, mcu, medium close-up, close-up, cu, two-shot, ots, over the shoulder, insert) → set / retime. The shot
  must exist. Anything else → the conductor. Also add the §3.7 command.
- **Conductor**: lanes chat, clarify, edit, craft, options, cannot; confidence < 0.5 on a writing lane → clarify; one retry
  told what was wrong (a writing lane with nothing, words the person did not say); **task shots are the numbers as
  printed, before the turn's ops** (lab run 2 bug: it counted post-op numbers wrong); on an insert its tasks are dropped
  (code tasks the new clip). Its scene view is clip heads only.
- **Code's tasks** (never from how a message reads): a new or re-cut clip needs its picture (with the person's own words
  and size, locked); a clip that now performs a line must show its speaker saying it (skip when its `sees` already
  says so: saves ≈ $0.002 on "Drop S08", lab run 6).
- **Author**: one call for all tasks (variants on options, at most 6 operations each, short values); scoped tasks see
  their clips in full; a whole-scene task sees every clip as head + why + camera, no IR (lab run 5: the options author
  was cut off reading the whole scene); the board keeps it to its tasks (kind ∈ picture, camera, timing, sound, light,
  order; shots in scope; no locks); delivery reports a task that changed none of its shots; its note goes to the reply
  only when none of its work was refused.
- **Reply** (gpt-5-mini minimal, every turn and every click): persona "Zora, the director's creative partner: a seasoned
  Sri Lankan TV drama director who loves this scene and talks to the team like a colleague on set"; last 6 messages (12
  when the author worked); the scene as heads plus the clips touched and the shots the message names; the facts LAST as
  plain sentences (`plain()`: "S01's size went from MS to WIDE"), under headers WHAT CHANGED / WAITING FOR THEIR OK /
  COULD NOT BE DONE / ASKED FOR BUT NOT DONE / HEADS-UP / OPTIONS / NO OPTIONS ARE SHOWN / NOT POSSIBLE HERE (with "every
  clip is generated by Veo: never suggest ADR, a reshoot, a recorded take"). A card is a proposal ("dropping S08
  would…"), never done. **Code guard** after it: cut from the first pasted header (`(?i:what happened this turn)` and the
  upper-case headers), and cut card / Accept / Reject / "Use this" sentences when no card is shown ("the script card" is a
  route, kept). If no model reply fits the budget: `plain_reply` from the facts.

### 3.7 A clip that performs a line but is stored silent (new, the person 2026-11-13)

The bug: Raphael's writer stored a clip bound to a line whose speaker is not seen (a voice message, a call) as `silent` /
`ambient` / `music_only`, so its prompt said "nobody speaks" over a spoken line. The writer is fixed (uncommitted, not
ours) and `scripts/repair_heard_shots.py` repairs old rows once. Zora must also catch and fix it, for any planner:

- **Check `line_unvoiced`** (code): a clip that performs a line (`dialogue_lines.shot_id`) with `sound_mode` not in
  `dialogue | voiceover | sung`. The right mode is unambiguous: the speaker on screen in that clip → `dialogue`, else
  `voiceover` (as `raphael_write.sound_mode_of`). Its fix is **code**: no model.
- **Operation `sound_mode`** (shot, value ∈ dialogue | voiceover | sung | ambient | music_only | silent) in the kernel;
  the `line` operation sets `dialogue` or `voiceover` by whether the speaker is on screen (the lab always set dialogue:
  a bug to fix in the port). After a change, `word_target` follows (`contracts.timing.shot_word_target(take)` for
  dialogue / voiceover, else 0) and `version + 1` marks the prompt out of date (the person presses Regenerate).
- **How the person meets it:** on every turn the check runs on the scene as read. Found ones are NOT fixed silently: the
  reply mentions them and the message carries a one-click card "Fix the sound on S07 (Aruni's line is heard, not seen:
  voiced off screen)" (Accept: code only, a revision of kind `use`). Asked directly ("S07 has a line but it's silent,
  fix it", "fix the silent shots") → quick() or the conductor gives `sound_mode` ops; safe, so it saves at once.
- **The picture text** (its `ir.audio` or beats may still say "no dialogue" / "silent hold"): when the person asks for the
  fix, code adds an author task on that clip (picture + sound: "it now carries {speaker}'s line {L}, heard off screen:
  make its audio and beats say so"). From the card alone, only the sound mode changes.
- **Cost:** found and fixed from the card ≈ $0.001 (the reply); asked by message ≈ $0.002 (+ conductor) or ≈ $0.004-0.005
  with the author's picture rewrite; all silent shots of a scene in one message ≈ $0.005-0.01. Regenerating the prompt
  and the video is separate (not Zora's cost).

### 3.8 The turn budget (code)

`TURN_CAP_USD = 0.02`, `REPLY_RESERVE = 0.003`, `MIN_OUT = 400`. Before each call: price the input (all uncached) with
`contracts/costs.py`'s token prices, and cap `max_output_tokens` at what the turn can still afford (the author and the
repair leave `REPLY_RESERVE` for the reply); a call that cannot afford `MIN_OUT` is not sent (`OverBudget`); an answer cut
off at the cap is not used (`CutOff`): the author's work is reported "did not fit this turn", the reply falls back to
`plain_reply`, the conductor to clarify. Spent is read from the usage rows of this turn (core/usage.py writes one per
call; price them with `contracts.costs.cost_tokens`).

Product changes this needs: `Agent.run` and `Agent.stream` (core/agents.py) take `max_output: int | None` and bind
`max_tokens` as `converse` already does; `contracts/costs.py` gets `gpt-6.1-terra` ($1.00 in, $0.05 cached, $5.00 out,
as `contracts/raphael/money.py`); a way to read the turn's spend (a small sink wrapper on `RunContext` that sums the rows it
forwards, or the usage rows the turn's context collected).

### 3.9 Agents and settings

- `agents/zora/zora_conductor`: prompt = lab `prompts/conductor.md`; schema = lab `conductor_schema()` (lanes without
  `shape` and `translate`; tasks with `writes` ∈ the six kinds and `shots`); tier `zora_chat`.
- `agents/zora/zora_author`: prompt = lab `prompts/author.md` with the safe-depiction line; NOT Jonathan's prompt (delete
  the test that compares its head with Jonathan's file); `memory: ["*"]` and the `production_memory` middleware stay; tier
  `zora_author`; timeout 120 s.
- `agents/zora/zora_reply`: prompt = lab `prompts/reply.md`; shape text; tier `zora_chat`.
- `core/models.yaml`: `zora_chat: { model: model_zora_chat, effort: effort_zora_chat, timeout_s: 60, retries: 1 }`,
  `zora_author: { model: model_zora_author, effort: effort_zora_author, timeout_s: 120, retries: 1 }`; remove `zora`.
- `core/settings.py` (OpenAISettings): `model_zora_chat = "gpt-5-mini"`, `effort_zora_chat = "minimal"`,
  `model_zora_author = "gpt-6.1-terra"`, `effort_zora_author = "low"`; remove `effort_zora`. `ZoraSettings`: drop
  `max_repairs`, `delivery_passes`, `reshape_*`; add `turn_cap_usd = 0.02`; keep `enabled`, `variants_max = 2`,
  `revisions_kept`, `transcript_messages`.
- "Remember this" (2026-11-12d D12): the conductor's `memory` becomes a production memory entry the middleware gives the
  author and the conductor (add `production_memory` to the conductor's middleware); never written and left unread.

### 3.10 API and interface

- API (`src/api/routers/zora.py`, `src/api/services/zora.py`): `PLANNER = "jonathan"` and `has_plan` go; status no longer
  needs a stored plan (a scene with shot rows is editable); `POST /scenes/{id}/zora/accept` and `/reject` (CanDirect,
  approved scene → 409) carry the message id and block index, through the function as actions (`ZoraAction.kind`
  gains `accept` / `reject`); `plan-shots` dispatches the job of the production's `shot_planner`
  (`ProductionSettings.shot_planner`, as `api/routers/build.py` does), not `PLAN_SCENE_JONATHAN`; lock / unlock write §3.5.
- Interface (`hiru-ai-studio-interface/src/features/zora/`: `api.ts`, `client.ts`, `types.ts`,
  `components/zora-chat.tsx`, `components/what-changed.tsx`): render the `confirm` block with its lines and **Accept** /
  **Reject** (the look of Sable's cards: `features/sable/components/sable-blocks.tsx`) and its settled state
  ("Accepted · revision N", "Rejected"); an option that needs the person's OK says so on its card; drop the treatment
  chips ("Draft the arc", "You decide the rest", "Plan shots from this treatment") and the `confirm_reshape` card; keep
  the changes block. Follow the interface rules: TanStack Query cache (`useSceneActions().applyShot`), no
  `router.refresh()`, keys in `src/lib/query/keys.ts`, **no costs or credits anywhere in the UI**.

### 3.11 What goes away

`zora_chat/scene.py` `adopt` and `planner_scene`; `steps/zora/zora_board/gate.py` (Jonathan's mend and check);
`steps/zora/zora_save` through `jonathan_write`; `zora_kernel/step.kernel_for` (Jonathan's check); `contracts/zora/
treatment.py` and the treatment lane and suggestions; the `shape` and `translate` lanes; Jonathan's prompt in the author;
the Zora entries in `tests/jonathan/test_removal.py`; tests that pin Jonathan-shaped behaviour. `tests/zora/
test_isolation.py` gains: no Zora file imports or names a planner (`jonathan`, `raphael`, `david`, `adam`, `classic`
as code identifiers). Keep `contracts/zora/ops.py` only if the kernel still uses it; otherwise remove it with its tests.

## 4. Phases

| Phase | What | Done when |
|---|---|---|
| 1 | `contracts/coverage` (scene, checks incl. `line_unvoiced`, risk), `contracts/costs.py` + terra, `PersonEdits.zora_locks` | the lab's coverage / checks / risk tests pass on the product modules, using the lab's input file as fixture |
| 2 | `steps/coverage/coverage_kernel` + the `sound_mode` op + `line` voiced by sight | the lab's kernel tests + new ones for §3.7 |
| 3 | Agents and settings (§3.9), `Agent.run/stream(max_output)`, the budget (§3.8) | `hiru_ai validate`, `catalog --check`; budget tests (a call capped, one refused, a cut-off handled) |
| 4 | The turn (§3.6) + save / locks / undo (§3.5) + quick() + the silent-shot card (§3.7) | the twelve-turn scenario replays offline with the lab's recorded answers (below) |
| 5 | Removal (§3.11) + the isolation rule | no planner named in Zora; `pytest` green apart from the baseline |
| 6 | API (§3.10) | `tests/zora/test_api.py` updated: accept / reject / stale card / approved scene |
| 7 | Interface (§3.10) | component tests for the confirm block; `npm run check` |
| 8 | Sable's change cards through the row kernel (2026-11-12d D4) instead of the classic director function | Sable's tests; can be split into its own plan if it grows |
| 9 | Live check, the person's yes: in the new database, one scene of "test" planned with Raphael first (the person starts the re-plan; the classic scenes work too, as single-cut coverage), the twelve lab turns adapted to that scene's shot numbers, + "fix the silent shot": no scene has one today, so the person chooses whether to set one shot's `sound_mode` to `silent` by hand for the test | each turn's cost within §2's numbers, ≤ $0.02; cap $0.50 |

**Recorded answers for phase 4:** `lab/zora_rows/runs/run6/turns.json` holds every turn's conductor answer, author
answers and replies; `lab/zora_rows/runs/cache/*.json` holds every model answer by request hash. Write a fake model
backend that returns them by turn and role, and assert the product's turn makes the same lanes, saves, cards and changes
as run 6 (exact replies may differ: assert facts, not wording).

## 5. Decisions

- **D-A Locks.** Recommended: take → `duration_locked`; every other field → `person_edits.zora_locks` (no migration).
- **D-B The silent-shot fix (§3.7).** Recommended: found by code each turn, offered as a one-click card, never applied
  silently; asked by message, applied at once (safe).
- **D-C Old Jonathan-shaped revisions.** Recommended: not restorable; undo stops at them and says why.
- **D-D Sable (phase 8).** Recommended: in this plan, last; split out if it grows past a day.
- **D-E Re-plan.** Taken (2026-11-12d D2): "Re-plan the scene" runs the production's `shot_planner`.
- Taken in 2026-11-12d and by the lab: no planner dependency (D1); risk list (D5); Accept = revision `use` (D8);
  translate dropped (D10); models and the $0.02 cap (D9, §2).

## 6. Not in this plan

Deprecating Adam, David, Jonathan and the classic planner (the person's own work); moving Raphael's coverage checks into
shared code (2026-11-12d D3); regenerating prompts, frames or videos after an edit (they are marked out of date); a
treatment, arc or colour script in Zora; translation; editing a line's words (the script card).
