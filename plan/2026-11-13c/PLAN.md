# Plan C: Sable, the lightweight shot editor (plan/2026-11-13c)

Revision 1 (2026-11-13). Nothing in this plan is built. Phase 0 is a $0 read; phases 1 to 7 are offline ($0); phase 8 is
a paid live check (the person's yes first). This plan BUILDS what the Sable lab (`lab/sable_rows`, six paid runs,
$0.75 of a $1.00 cap) proved. A new chat implements it from this file alone; everything it needs is written here or
named here by path.

The person's words (2026-11-13), the three rules of this plan:

1. **"Sable is our lightweight shot editor."** Quick, cheap, exact shot work; craft ("make it tenser") is Zora's.
2. **"Sable works within the scene only. It is aware of other things in the production but does operations within the
   scene."** Reads everything, changes only the open scene.
3. **"Sable must warn on a change that does not match the story, and the user can override it"** (their example: episode 1
   says she went to medical school, a new clip in episode 2 shows her going to engineering school).

Pages for the person (context only): the lab's scene run https://claude.ai/artifact/RtRC67sjLcca1enS2TAuYy, the
production run before the fixes https://claude.ai/artifact/Yc2GaAwQXrFegt1VxXTeZv, prod3
https://claude.ai/artifact/ScQheW5SKfPTNP1F7Ux5hG. The final run: prod5 https://claude.ai/artifact/6Zy3GMthCeytU3HzrAr9ps (files in `lab/sable_rows/runs/prod5/`).

## 0. Rules for the chat that builds this (read before anything)

- **Two repos.** Backend `C:\Users\witha\Documents\projects\Hiru TV\source\hiru-ai-studio` (Python 3.12: always
  `.venv/Scripts/python.exe`; the system `python` is 3.9 and breaks). Interface `...\hiru-ai-studio-interface` (Next.js 16;
  its `CLAUDE.md` and `AGENTS.md` are binding: no costs in the UI, TanStack Query cache, no `router.refresh()`, no raw
  hex, shadcn/ui, `spoken()` for dialogue).
- **No model call, image or paid run without the person's yes, each time** (they review every paid iteration; a paid run
  without it is refused by the harness). Tests run with `OPENAI__API_KEY=` blank.
- **The database was replaced on 2026-11-13.** The new one holds one production, "test" (12 classic-planned scenes of
  filler, a traffic seed). No writes and no SQL against it without asking; reads only inside `set transaction read only`.
  Offline tests use the lab's files, never the database.
- **Files are CRLF.** Rewrite with `open(p, "w", encoding="utf-8", newline="")`. A Bash heredoc in this harness turns
  `\n` inside the text into a real newline: write code that contains escapes with the Write tool.
- **Plan/2026-11-13 (the Zora build) is built** (uncommitted, see its `IMPLEMENTED.md`): this plan REUSES its parts.
  Do not change Zora's behaviour except where §3.1 says the part becomes shared; Zora's tests must stay green.
- **Baseline before any change:** `ADAM_MODE=staged OPENAI__API_KEY= .venv/Scripts/python.exe -m pytest -q -p no:logging`.
  The Zora build recorded 28 failed + 3 errors that are pre-existing (port 8001 files URL in `.env`, David's agents,
  media thumbs, …). Run it again first; report only failures that are new.
- **Commit only when the person asks.** Write `IMPLEMENTED.md` in this folder as phases land.
- Checks before finishing (backend): `ruff check src tests scripts`, `mypy`, `.venv/Scripts/python.exe
  scripts/lint_imports.py`, `... -m hiru_ai validate`, `... -m hiru_ai catalog --check`, `pytest -q` (with `ADAM_MODE=staged
  OPENAI__API_KEY=`). Interface: `npx next typegen && npm run check && npm run format:check`.

## 1. Why: what the lab found

The lab (`lab/sable_rows/RESULTS.md`) ran today's Sable (its real code, on the repo's test fakes, no database) and a
lightweight editor on the same messages.

**Today's Sable cannot edit a coverage scene, and costs 30x more.** It is one react agent (`agents/sable/sable_agent`,
25 tools, tiers `sable` gpt-5-mini low → `sable_deep` gpt-5 medium, up to 10 model calls). Its change cards go through
`change_propose` → `core/trial.py` → the classic `scene_kernel` and its `timing_check` through `contracts.shotplan.fit`,
whose rule is "every block in exactly one shot": on a Raphael scene (20 overlapping clips) it sees 7 ("there is no shot
8"; 42 s instead of 120 s). On the classic "test" scenes it refused even "make S01 a wide" and every insert ("would not
cover the script exactly once"). It checks nothing against the story. Average $0.031 a message; "make it tenser" $0.205
(9 calls, 10 minutes); an insert attempt $0.16-0.18.

**The lightweight editor, after five iterations, did every message right** (prod5, twelve messages on episode 2 scene 2
of a lab story written into a copy of "test": production questions, a scene lookup, plain edits, three story conflicts,
override, reject, undo, "change another scene"):

| Message | Result | Cost |
|---|---|---|
| "What do we know about Dilini?" / "Which scenes is Sahan in?" | right, from the production card | $0.0005-0.0013 |
| "How many shots does E1S3 have, and who speaks?" | right (6, by shot): code read E1S3 in | $0.0009 |
| "Make S01 a wide." | saved; code read it | $0.0006 |
| "Add a 4-second insert after S02 of Dilini's ENGINEERING faculty admission letter." | **warning** (E1S2: medical faculty); Accept overrode it; Undo removed it | $0.0004 |
| "Add a 4-second insert after S03 of Dilini's anatomy textbook." | saved, no warning (it fits) | $0.0010 |
| "In S05, show Dilini wearing jeans and a t-shirt." | **warning** (her card: saree); Reject left the scene | $0.0005 |
| "Add a shot after S06 of Sahan handing Dilini a stethoscope." | **warning** (E2S4 says he gives it later) | $0.0008 |
| "Change the tea shop in E2S4 to a bus stop." | refused: open E2S4 to change it | $0.0008 |

On the Raphael scene (run 1): twelve messages $0.013 in all (today's Sable $0.338), every edit landed, risky ones carded,
craft handed to Zora.

**What the iterations taught** (each one is a rule of this plan):

| Run | Failure | Rule |
|---|---|---|
| run 1 | a card's reply said "I removed S08" while nothing was saved | a waiting card's reply is written by code from the card |
| run 1 | "Move S15 before S14" was asked back | code reads moves (before / after) |
| prod1 | one call doing everything at minimal effort caught 1 of 3 conflicts | a separate, focused **story check** decides conflicts |
| prod1 | asked about another scene's shots, the model guessed ("3") | code reads a scene the message names into the input |
| prod2 | the model rewrote "engineering" to "medical" (so nothing to warn about) and wrote reasons for every shot unasked | **the person's words stand** (a code guard) |
| prod2 | unsure, the turn asked back, but the model's text said "Inserted…" | code writes the question |
| prod3 | the main call's own conflict list was noise (it listed facts that MATCH) | only the story check lists conflicts |
| prod4 | the main call at minimal effort doubted clear edits, refused a look change, sent junk ops | code reads the common edit sentences; the main call at **low** effort |

## 2. The models and the money

| Role | Model, effort | Measured | Agent (this plan) |
|---|---|---|---|
| plain commands and the common edit sentences | **code, no model** | $0 | `contracts/coverage/quick.py` |
| understand anything else (and answer a question in the same call) | gpt-5-mini, **low** | ≈ $0.0003-0.0013 | `sable_light` |
| story check (only when an edit changes what a shot shows) | gpt-5-mini, low | ≈ $0.0003-0.001 | `sable_check` |
| reply after an edit or a click | gpt-5-mini, minimal | ≈ $0.0005-0.0008 | `sable_reply` |
| a waiting card's reply | **code** | $0 | `card_reply` |

**Turn cap: $0.005 in code** (`SableSettings.turn_cap_usd`). Each call's output is capped at what the turn can still
afford, inputs priced first (the Zora build's `Budget`, §3.1); a call that cannot afford 400 tokens is not sent; a
cut-off answer is not used. Rejected in the lab: gpt-5-nano (misread 5 of 7 messages in the Zora lab); the main call at
minimal effort (prod4); gpt-5 for the reply ($0.006-0.014: over the cap).

## 3. The design

### 3.1 Reused from the Zora build, and what becomes shared

| Part | Where now | In this plan |
|---|---|---|
| Coverage scene, checks (incl. `line_unvoiced`), risk, ledger | `contracts/coverage/` | used as is |
| The row kernel (ops, guarantees, `sound_mode`, lines voiced by sight) | `steps/coverage_kernel/` (ungrouped, shared) | Sable lists it under `shared` in `systems/sable/group.yaml` |
| `quick()` (size, take, remove, "fix the silent shots") | inside `systems/zora/zora_chat/turn.py` | **moved** to `contracts/coverage/quick.py`, plus §3.3's readers; Zora imports it from there (its behaviour unchanged, its tests green) |
| The budget (`Budget.watch`, `output_cap`, `OverBudget`, `CutOff`) | `systems/zora/zora_chat/budget.py` | **moved** to `hiru_ai/core/budget.py` (a grouped system may only name its own group's parts); Zora imports it from there |
| Save in place + revisions (`Saver`) | `systems/zora/zora_chat/store.py` | **moved** to a shared ungrouped step `steps/coverage_save/` (rows in, rows out, as `coverage_kernel`), so Sable and Zora write the same way. ONE revision stack per scene: an Undo in either chat undoes the last change made in either (D-C) |
| `confirm` block, Accept / Reject actions, the confirm card | Zora's turn, `api/routers/zora.py`, `features/zora/components/confirm-card.tsx` | the block's shape in `contracts/coverage/` (shared); Sable renders the same card (move the component to a shared place in the interface, e.g. `src/components/confirm-card.tsx`) |
| Story facts for the production card | — | new, §3.4 |

If a move is refused by the registry or `lint_imports.py` (the Zora build found the registry refuses a `coverage`
group), follow what the Zora build did: an ungrouped shared part listed under `shared` in each group that uses it.

### 3.2 The scope rule (rule 2)

Sable reads the whole production and changes **only the scene in view** (`SableTurnPayload.scene_id`, already decided by
the API). With no scene in view it answers and changes nothing ("open the scene and ask again"). A change to another
scene is lane `cannot`: "open E2S4 and ask there" (or the existing `Handoff` card to it). `RunContext.stage_scene_only`
stays True.

### 3.3 The turn (`systems/sable/sable_chat`, rewritten; the graph keeps read → … → save)

```
read (6 messages; the thread summary as today) ──┬─ a click: [Accept] [Reject] (actions), "undo" / "redo" ── reply
                                                 ├─ quick(): code reads it ─────────────────────────┐
                                                 └─ sable_light (gpt-5-mini low): lane              │
                                                     answer · cannot · clarify · zora ──── its own answer is the reply
                                                     lookup → code reads ONE scene → sable_light again (no 2nd lookup)
                                                     edit ─────────────────────────────────────────┤
     edit → words guard → story check (only what a shot newly shows) → row kernel → checks → risk + conflicts
          → safe: save (revision) → sable_reply          risky or a conflict: confirm card, nothing saved → card_reply
```

- **quick() readers** (all whole-sentence matches; anything partial goes to the model; a shot that does not exist goes
  to the model): size and take ("Make S01 a wide, 6 seconds"), remove ("Drop S08", "Remove S05, …"), move ("Move S15
  before / after S14"), **add** ("Add a [4-second] insert / shot / close-up / wide / two-shot / MCU / reaction after
  S03 of / showing <what>": size from the word, take 4 s unless 4 / 6 / 8 said, the block is the last block of the shot it
  follows, on screen = cast names in the words, what = the person's words), **show** ("In S05, show <what>", "make S05
  show …", "S05 should show …" → `set sees` = their words), and Zora's "fix the silent shots". Port them and their tests
  from `lab/sable_rows/light.py` (`quick_move`, `quick_add`, `quick_show`) and `lab/zora_rows/turn.py` (`quick`).
- **`sable_light`**: prompt = `lab/sable_rows/prompts/light_prod.md`; schema = lab `prod_schema()` (lane, confidence,
  lookup, ops, answer; NO conflicts). Its input, in this order (the first part is the same bytes every message in a
  production, so the provider caches it): the PRODUCTION CARD (§3.4), the OPEN SCENE label and view (every clip one line,
  the shots the message names in full, the sound mode of each clip, CHECKS from code incl. silent shots with a line),
  a scene the message names read in by code (one), the last 6 messages, the message. Confidence < 0.5 on an edit → code
  asks "which shot … and what exactly should we see?" (never the model's text).
- **Words guard** (`keep_words`, the Zora lab's `_invented` test): a new clip's subject and what a shot shows are the
  person's words (a model rewrite is replaced by their sentence); any other prose they did not say is dropped. Record what
  was guarded on the turn's meta.
- **Story check** (`sable_check`, prompt `lab/sable_rows/prompts/check.md`, schema `{conflicts: [{fact, source, why}]}`):
  runs only when an edit's ops change what a shot shows (an insert's `what`, `set sees` / `why`); input = the production
  card (cached) + the open scene label + the change in plain words. Its conflicts make the turn a confirm card whose
  reasons start "may contradict <source>: <fact>"; the card's reply is code: "Heads-up: the story says <fact> (<source>),
  but <why>. It's your call. If you accept: <changes>. Nothing is saved until you press Accept; Reject leaves the scene as
  it is." **Accept = override**, recorded on the turn's meta (`override: [...]`) and the audit row.
- **Lanes the old Sable had, kept:** `zora` → the existing `Handoff` card to the same scene's Zora with the request;
  "remember this" → the existing `sable_memory` card (`memory_propose`); a state change ("Kamal is dead from b12") → the
  existing `sable_state` card (`sable_state_propose`, `api/services/sable.apply_state_card`). These two were not in the
  lab: phase 0's small check covers them (D-B).
- **Silent shots** (the Zora build's D-B): every turn the code check runs on the open scene; found ones are mentioned and
  offered as the one-click "Fix the sound" confirm card; asked by message, fixed at once.
- **Reply** (`sable_reply`, prompt `lab/sable_rows/prompts/reply.md`): after a saved edit or a click, plain facts last
  (`plain()`), the code guard (a pasted header, a card that is not shown) after it. Say "Sable" in Sable's facts (prod5:
  a Reject reply said "Zora won't offer…": the reject fact came from Zora's code).

### 3.4 The production card (code, `contracts/coverage/production.py` or `hiru_ai/core/production_card.py`)

Written by code from the ports, the same bytes for every message of a production until something changes:
`PRODUCTION: <title>`; `EPISODES` (number: synopsis); `SCENES` in story order, one line each: `E1S2 <heading> · speaks:
<names> · <what happens>`; `CANON`: `<name> (<code>, <kind>): <card summary> (<card facts: age, wardrobe, look …>)`; the
production's direction memory entries if any (`core/memory.entries`), one line each. "What happens" in a scene: the
scene packet's summary when the breakdown made one (`scene_packets`), else the scene's title and its first and last
action blocks (what the lab used). A scene read (`read_scene("E1S3")`) is that scene's coverage view (`render(only=set())`
with the script's blocks). In the lab the card for 12 scenes was 768 tokens; a long production must fit a cap (D-A).

### 3.5 API and interface

- API (`src/api/routers/sable.py`, `src/api/services/sable.py`): `POST /turn` unchanged; the card routes
  `…/cards/{index}/accept` and `/dismiss` gain the `confirm` kind: Accept applies through the function as an action (the
  row kernel, the shared save; refused when the rows' fingerprint changed; approved scene → 409), Dismiss = Reject. The
  classic applier (`ChoicePayload` → the director function) is no longer used for Sable. `sable_change` cards already
  stored in old messages read as settled (no Accept on them).
- Interface (`hiru-ai-studio-interface/src/features/sable/`): `sable-blocks.tsx` renders the shared confirm card
  (reasons, conflicts as "Heads-up", the changes, Accept / Reject, settled "Accepted · revision N" / "Rejected"); the
  handoff, memory and state cards stay; no cost anywhere. Tests beside the components.

### 3.6 What goes away

`agents/sable/sable_agent` (the react agent) and its tier pair `sable` / `sable_deep` and the `tiering` settings for
Sable (`core/middleware/tiering.py` stays: it is generic); `tools/sable/sable_think_harder`; Sable's use of
`change_propose` and `plan_try` (the tools stay for others); `steps/sable/sable_route` if nothing else uses it (the
starting tier); the `sable_change` card kind for new messages. Keep `sable_summary` (the thread summary) and
`sable_overview` / `sable_scene_find` only if a lane uses them (otherwise remove). Update `systems/sable/group.yaml`,
the Sable removal tests and `tests/sable/test_zora_untouched.py` (Zora is touched only by §3.1's moves).

## 4. Phases

| Phase | What | Done when |
|---|---|---|
| 0 | Read §0-§3, `lab/sable_rows/RESULTS.md`, `plan/2026-11-13/IMPLEMENTED.md`; run the baseline; a $0 check that the state and memory lanes fit the light call's schema (offline, rehearsal answers) | baseline recorded; D-B written down |
| 1 | Shared parts: `contracts/coverage/quick.py` (all readers + their tests from both labs), `core/budget.py`, `steps/coverage_save` (Zora's `Saver`), the confirm block in `contracts/coverage/`; Zora imports them | Zora's whole test suite green, unchanged behaviour |
| 2 | Production card + scene read (§3.4), with the lab's story copy as fixture (`lab/sable_rows/input/story_production.json`) | card text and scene read tests |
| 3 | Agents `sable_light`, `sable_check`, `sable_reply` (component.yaml, prompts from the lab, schema, tests); tiers `sable_light` (gpt-5-mini low), `sable_check` (gpt-5-mini low), `sable_reply` (gpt-5-mini minimal) in `core/models.yaml` and `SableSettings` (`turn_cap_usd = 0.005`, `history_messages = 6`) | `hiru_ai validate`, `catalog --check` |
| 4 | The turn (§3.3): quick, light, lookup, words guard, story check, kernel, checks, risk + conflicts, card or save, reply; the old lanes (handoff, memory, state); silent shots | the lab scenarios replay offline with the recorded answers (below) |
| 5 | API (§3.5) | `tests/sable/test_api.py`: confirm Accept / Reject / stale card / approved scene / override recorded |
| 6 | Interface (§3.5) | component tests; `npm run check` |
| 7 | Removal (§3.6) | no `sable_agent`, no Sable `change_propose`; `pytest` green apart from the baseline |
| 8 | Live check, the person's yes, cap $0.30: in the new database, on a scene the person picks (the "test" seed has no story: the person decides whether to write a few facts into it first, or uses a real production), the twelve prod messages adapted | every message right; each ≤ $0.005; the three conflict kinds warned |

**Recorded answers for phase 4.** `lab/sable_rows/runs/prod5/light.json` (production suite, with the story check's
answers in `story_check` and the replies) and `runs/run1/light.json` (the Raphael scene suite) hold every answer;
`lab/sable_rows/runs/cache/*.json` holds every model answer by request hash. Write a fake model backend that returns them
by message and role, and assert the product's turn makes the same lanes, saves, cards, conflicts and overrides (assert
facts, not wording). The lab's tests (`lab/sable_rows/tests/test_light.py`, `lab/zora_rows/tests/test_lab.py`) port to
`tests/sable/` and `tests/coverage/`.

## 5. Decisions

- **D-A Production card size.** A 12-scene production is 768 tokens; 120 scenes ≈ 6-8k (cached at 10 % after the first
  message, but the first costs ≈ $0.002). Recommended: the whole card up to 6k tokens; past that, the open scene's
  episode and its neighbours in full and every other scene by its heading only (the lookup reads any scene in full).
- **D-B The state and memory cards.** Recommended: keep both as lanes of `sable_light` producing the existing
  `sable_state` / `sable_memory` cards (their apply code unchanged); phase 0 checks the schema offline; a paid check of
  these two lanes (≈ $0.005) goes into phase 8.
- **D-C One undo stack for both chats.** Recommended: yes (the same `scene_plan_revisions`); a Sable change undone from
  Zora's panel or the other way round, each reply says which change it undid.
- **D-D What a shot shows.** Recommended: `set sees` (`intent.what_we_see`), as the lab; the old Sable's
  `dop_note.set` (`person_edits.dop_note`) stays readable but Sable no longer writes it.
- **D-E Story check on every edit?** Recommended: only on edits that change what a shot shows (prod5: no false warning,
  no cost on size / take / move / remove). A removal that drops the only shot of a story event is the risk rule's, not
  the story check's.

## 6. Not in this plan

Zora's behaviour (only the moves of §3.1); craft edits (Zora's); changing a canon card or the script (their panels);
document or knowledge-base search as a lookup (the lab tested scene lookups only: a later plan with its own lab);
rendering frames, prompts or videos.
