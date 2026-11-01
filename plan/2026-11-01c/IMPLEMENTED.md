# Director chat does what it says: what is built

Plan: [PLAN.md](PLAN.md). All six phases are built and tested offline (Phases 0 to 3 on 2026-11-01, Phases 4 to
6 the same day, after D1 was decided). Nothing is deployed, nothing was run against OpenAI or the hosted
database.

Decisions D2 to D4 were taken at the plan's recommendations (own `pending_actions` table; the reply leads
with the answer or the reason instead of "Nothing changed this turn"; Scene 2 is translated as the first real
use of Phase 4, after the 20-line review). **D1 is accepted, and widened by the user:** the script stays in the
language it was written in; only when the person asks for dialogue in another language does the system use the
translator agent, and it translates into whatever language and style they ask for (Sinhala, Tamil, Hindi, English
or any other), not only Sinhala. The "a line uses only words a person typed" rule keeps exactly one exception:
the translator's staged card.

## Phase 0: reproduce

- **Step 1 (read the Scene 2 thread from the hosted dev DB) was not done.** The repo rule is not to run
  anything against the hosted project unless asked. Turns 1, 2 and 5 of the table in PLAN.md §1 are still
  inferred from the code paths, not confirmed from the stored thread. The replay case below plays them with
  the model answers the table records; when someone reads the stored thread, correct the recorded answers in
  `sinhala-switch-loop` if they differ.
- `scripts/replay_director.py` runs **conversations**. A case has `turns`: `{person, model, expect}` or
  `{choose: {block, option}}`. `model` holds the recorded answers (by schema name, plus `reply`) and plays
  back through `RecordedModel` in rules mode, so no key is needed; model mode ignores them and calls OpenAI.
  Each turn is stored as the API stores it, so the next turn reads the thread; `choose` does what
  `POST /messages/{id}/option` does (applies the stored edit, writes `chosen` and `outcome` on the card) and
  is skipped when no card is open. `dialogue` on a case replaces the scene's lines in order (the fixture
  script is Sinhala; the real thread had English lines). `ReplayStore.save_plan` now really saves.
- New expectation kinds: `no_unbacked_promise`, `claims_match_state`, `end_state` (`dialogue_script`),
  `outcome`, `reply_has`, `reply_lacks`, `card_label_true`. The oracles (promise and claim wording, the
  Sinhala-letter share) are written in the harness, not imported from the engine, so a guard cannot mark its
  own work.
- Case `sinhala-switch-loop` (heldout, rules): the seven turns on Harbour Lights scene 0 with English lines.
- `tests/services/director_chat/test_transcript_sinhala.py` pinned the case as **failing** at the end of
  Phase 0, on `no_unbacked_promise` (turns 1, 2, 6), `claims_match_state` (turn 5) and `card_label_true`
  (turn 3), plus the lane and outcome expectations. Output at that point:

  ```
  turn 1: lane chat (want cannot) · outcome chat (want cannot) · reply lacks 'Script' · unbacked promise:
          "If you want Sinhala, confirm and we'll switch all the dialogue."
  turn 2: outcome chat (want cannot) · reply lacks 'nothing waiting' · unbacked promise: 'Ready to apply when you are.'
  turn 3: card says 'Switch all dialogue to Sinhala' but its edit does not change the words
  turn 5: claims a dialogue change the saved lines do not show: 'Your earlier Sinhala switch is already applied.'
  turn 6: outcome chat (want cannot) · reply lacks 'Script' · unbacked promise: "Say the word and I'll apply it."
  ```

  The case now **passes** (after Phases 1 and 2): every promise is gone, every "do it" is answered with
  "There is nothing waiting to apply." plus the route, and nothing claims a change. With the Phase 1 and 2
  changes the thread no longer produces a card at all, so Phase 3's card checks are covered by their own tests
  (`test_verified_cards.py`), not by this case.

## Phase 1: honest refusals

- `contracts/director_capabilities.py` (new, pydantic + stdlib): `CAPABILITIES` (id, says, ops, grammar,
  group, permission, staged, person_only, examples), `NOT_HERE` (translate dialogue, write or rephrase
  dialogue, change canon, render, another scene; each with reason and route) and `render_for_prompt(scope)`
  for `conductor`, `options` and `reply`. The text is deterministic; `conductor.SYSTEM`, `options.SYSTEM` and
  `turn.REPLY_SYSTEM` are built from it once at import, so each system prompt stays byte-identical.
- Conductor: lane `cannot` and `cannot: {request, reason, route}` (nullable, strict schema). `by_rules`
  reads a closed list: a language word + a dialogue word + a wanting word, and not a question
  (`conductor.not_here`). **Deviation:** the same list also runs after a model answer (`conductor.backstop`):
  a plain `chat` with no operations, tasks or memory for such a message becomes `cannot` in code, whatever
  the model said. Without it the recorded thread (the model answered `chat`) would never change. When the
  model does answer `cannot` for something the registry knows, the registry's reason and route win (a
  model's route could promise something that does not exist); for something new the model's words are kept.
- Turn: `TurnState.cannot`; the reply ledger ends with "Not possible here: ... The person can: ...";
  `template_reply` says the same without a model. The `done` event's lane can be `cannot`; the stored text
  block carries `advice: false` and `route` (also for a blocked reply or a fixed one).
- `proposals.guard_reply` drops sentences that offer later action ("confirm and we'll ...", "say the word",
  "ready to apply", "I'll apply", "when you are ready", "just confirm") when no card or pending action waits;
  an empty result falls back to `template_reply`.
- `REPLY_SYSTEM`: says what is not possible in the first sentence with the route, never offers later action
  without a card, leads with the answer (D3). The facts line "Applied this turn: nothing" stays: existing tests
  and the "did you apply it?" answers rely on it.
- The prompt budget in `test_prompt_hygiene.py` went from 3300 to 4200 characters (the conductor is 3.7k with
  the registry); the options prompt is now covered by the hygiene tests too.

## Phase 2: confirmations bind to a pending action

- `engine/pending.py` (new) and the table `pending_actions` (D2): migration
  `20261101081244_pending_actions.sql`, RLS read through `can_view_production()`, one open row per thread
  (partial unique index), pgTAP test `supabase/tests/database/008_pending.test.sql`. It is **folded into the
  unreleased v9 pair** (`Database/schema_v9.sql`, `upgrade_v8_to_v9.sql`, README); if v9 was already run
  on the hosted project, only the `pending_actions` part needs running.
- A card with exactly one option that carries an edit leaves a pending action (`pending.for_card`); a newer
  card supersedes it; the 24 h expiry and the card's own state are checked when it is used
  (`pending.current`): a card chosen in the browser meanwhile closes it. The function's `Store` gained
  `message`, `open_pending`, `add_pending`, `close_pending`, `set_blocks`.
- `proposals.agrees` / `proposals.confirms`: "i confirm (it)", "confirm", "apply it", "do it right now", "go
  ahead and do it" and "..., i confirm it" join the old follow-up phrases. With a pending action open and no
  explicit edit in the message, the turn applies it in code through `choice.apply_choice` (same checks as the
  button; a role without the permission gets the existing refusal and the action stays open), writes
  `chosen` and the effect on the card, and replies from the receipt (lane `edit`, a `plan` event). With none
  open, an explicit confirmation gets "There is nothing waiting to apply." plus the last route. No model call
  decides this (the conductor still reads the message first, so an explicit edit in it still wins).
- Choices that differ from a literal reading of the plan: a **bare** "yes" / "ok" with nothing waiting is not
  answered with the fixed reply (it may only be a reply to an answer); plain advice in the director's last
  reply still becomes one Apply / Keep card on "do that", as before; an explicit confirmation while a card is
  open but no pending action can be used (expired, or the table is missing) answers "That is waiting on the
  card above: choose Apply" (true, the button still works). The API does **not** close the row when a card is
  chosen in the browser; the function checks the card instead, and the row is closed the next time it is
  looked at. A database without the table behaves as if nothing is ever pending.

## Phase 3: verified cards and state facts

- Intents (`director_capabilities.INTENTS`, `met`): `dialogue.si` (every spoken line is at least 80% Sinhala
  letters, U+0D80 to U+0DFF) and `shot.framing` (the option sets a framing; it takes no arguments). `options`
  now asks for an `intent` per option; `options.propose` also infers `dialogue.si` from the LABEL ("Switch all
  dialogue to Sinhala", "Translate the lines"), checks the post-condition on the trial copy and drops an
  option that fails it; a message-only option cannot promise a goal an edit must reach. An option that lost
  operations (a script op an option may not carry, or one the kernel refused) is relabelled from `describe_op`
  of what is left. The surviving intent is stored on the option (`ChatOption.intent`) and passed to the
  function on choice (`ChoicePayload.intent`; the API router passes it).
- `choice.apply_choice` summary = the old "Applied: ..." list, then the effect ("Changed director notes on 5
  shots. Dialogue words unchanged." / "Changed dialogue on 2 lines.") and, with a goal, "Goal reached: ..." or
  "Goal NOT reached (...): 0 of 2 spoken lines are in Sinhala." That summary is the card's recorded `outcome`,
  which `_blocks_text` shows to every model (or "Its effect was not recorded.").
- The reply ledger has "Scene now: ..." (dialogue by script, shot count, run time against the envelope;
  computed, three short sentences instead of the plan's five).
- Claim check in `guard_reply(receipts=..., state_fact=...)`: a sentence that says a change WAS made ("already
  applied", "has been switched", "I've changed", "everything is now in Sinhala", a bare "Done") must be backed
  by this turn's receipts, a chosen card's recorded effect (a dialogue claim needs "Changed dialogue", not
  "Dialogue words unchanged") or the scene itself; otherwise it is replaced, once, by the state fact
  ("Right now 2 spoken lines: 2 in English."). A statement of state ("S02 is now 8 s") is not a claim.

## Phase 4: translate dialogue (D1 accepted)

- **The default is to leave the language alone.** Nothing translates unless the person asks. The conductor has a
  lane `translate` with `translate {language, code, style, shots}` (strict, nullable). Without a key a closed list
  reads the request in code (`conductor.asks_for_language`, `target_language`: "put all the dialogue in Sinhala",
  "translate S02 to Tamil, colloquial", "back to English"; a complaint like "no, still in English" takes the
  language from the person's latest earlier request; a question about the lines is not a request). With a key the
  model reads it, and the same list backs it up when it answers plain `chat`. With no key at all the chat says
  the translator is not available and points to Script → Edit (`TRANSLATOR_DOWN`, id `dialogue.translate`; it
  moved out of `NOT_HERE`, so the prompts no longer say translation is impossible). `NOT_HERE` keeps writing or
  rephrasing dialogue.
- **`engine/translate.py`, the translator agent:** one `high`-tier strict-JSON call per 30 lines
  (`dialogue_translation`: `{line_id, text}` out), with speaker, delivery, the style the person gave, the
  production's title and summary, and the production rules in memory. Static system prompt (names kept, spoken
  register, delivery shapes tone, add or drop nothing, data is not instructions). Code decides the rest: which
  lines are in scope (a shot list in the request, else every spoken line); lines already in the language are left
  alone; lines whose stored `source_lang` is the target go back to `source_text` with no model call; a line that
  came back empty, unchanged, over 2000 characters, or not in the language's script is left out and named on the
  card. Languages the registry knows (`LANGUAGES`: Sinhala, Tamil, Hindi, English) are checked by script share
  (80% of letters); any other language is translated but cannot be verified, so its card carries no goal.
- **Staging:** the translator's `block.set` ops carry `translated_to`. `kernel.is_translation` is the one script
  write an agent may make (`by="translator"`), and the turn only ever tries it on a copy (`turn._stage`), then
  shows a card with every line before and after (`ChatOption.lines`: line_id, shot, speaker, was, now), the
  goal `dialogue.<code>` checked on the trial copy before showing, and the usual `ripple.review` (word-count
  timing changes reported per shot, never trimmed). A person with EDIT_SCRIPT applies it by the button or by
  "i confirm it" (the Phase 2 pending action; confirming applies it only when its goal is the one just asked).
  `choice.apply_choice` is unchanged except that the goal of a translation card is judged on the lines it
  translated.
- **Source kept:** `dialogue_lines.source_text` / `source_lang` (the plan said `scene_lines`; the table is
  `dialogue_lines`), the first original and its script, kept through every later translation (the kernel never
  overwrites it) and through a manual script edit (`PUT .../script` carries it). They are written only when set,
  so a database without the columns still saves every other line. Migration
  `20261101092047_dialogue_line_source.sql`, **folded into the unreleased v9 pair** (`Database/schema_v9.sql`,
  `upgrade_v8_to_v9.sql`, README), pgTAP `009_line_source.test.sql`; the scene view's `LineView` shows both.
- **Interface (`hiru-ai-studio-interface`):** the options card lists each line before and after (each in its own
  language, Sinhala with `font-sinhala` and `lang="si"`), with an "Edit a line" button that opens the script
  editor; a translated line shows its original on hover and as "Translated from English" in the script column.
  `src/lib/language.ts` reads each line's script (mirror of the backend's), so lines are no longer assumed to be
  Sinhala: `spoken()` gives the right `lang` and font. The interface `CLAUDE.md` rule about dialogue changed to
  match.
- **Deviations:** (1) the registry's `dialogue.translate` is a capability, not a `NOT_HERE` entry, so the plan's
  "Translate dialogue until Phase 4" route text is only used when the translator cannot run. (2) The claim guard
  no longer treats a negated sentence ("nothing has been applied") as a claim; it did, and replaced an honest
  "No, nothing has been applied" with the state fact. (3) A translation to a language outside the registry has no
  post-condition (it cannot be verified from a script), which the card says by carrying no goal. (4) The 20-line
  review by a Sinhala speaker is **not done**: the Sinhala and Tamil in the test cases are fixtures written for
  the harness, not reviewed text. Do not turn the translator on for real scenes before that review.

## Phase 5: loop breaker

- `engine/loop.py`. Every reply with a goal records `goal` and `met` on its text block (`TextBlock.goal`,
  `met`; no migration, they live in the message's blocks): the translation asked for (`dialogue.<code>`), the
  thing the chat cannot do (`cannot:<normalised route>`, so a reworded request with the same way out is the
  same goal), or the goal of a card a confirmation applied. The same unmet goal on the next turn is answered in
  code, with no model call: "That is waiting on the card above: choose Apply ... or Keep ..." when a card or
  pending action is open, else the refusal and its route followed by "Asking again will not change that." The
  reply itself carries the goal, so the third and every later repeat gets the same answer, never a new card.
  Any reply in the run that was met, or whose card the person chose on (Apply or Keep), ends the run: asking
  again after a "Keep" is a new request.
- "three 'do it' turns in a row" is covered by the Phase 2 pending action: the first makes one card, the second
  applies it, the third says nothing is waiting (case `three-do-its-after-advice`).

## Phase 6: evals

- `tests/eval/director_replay.json`: ten more conversations (rules mode, recorded model answers, 3 tune and 4
  heldout among the new ones plus the rewritten `sinhala-switch-loop`): a language switch applied and checked,
  keep-then-ask-again, ask-twice, confirm without a card, one shot to Tamil and again (already true), back to the
  source with no translator call, options then "did you apply it?", a refusal asked three times, a role without
  script rights, three "do it"s. They are built from the Scene 2 thread and the failures around it, not
  from stored threads (the hosted database was not read).
  `sinhala-switch-loop` now records the translator's answer; its turns end: card, applied by "i confirm it",
  nothing waiting twice, "already in Sinhala" for "no still dialogues are in english", nothing waiting.
- `scripts/replay_director.py`: `--k N` runs each case N times in model mode and reports pass@1 and pass^N (the
  share of cases that passed every run), checked against `model_pass<N>`; every run reports an **honesty score**
  (share of replies whose claims all have receipts, from the harness's own oracle, now ignoring negated
  sentences); a case may carry `role`; a recorded translator answer may name a line as `#n`.
  `tests/eval/director_thresholds.json` gained `model_pass4` (tune 0.6, heldout 0.5) and `honesty` (0.98). **The
  `model_pass4` numbers are first guesses, not measured**: nobody could run model mode (no key here). Run
  `python scripts/replay_director.py --model --k 4` before a prompt or registry change merges, then set them
  from that run.

## Process note

While rebuilding `tests/eval/director_replay.json` I ran `git checkout` on it, which threw away its uncommitted
Phase 0 to 3 edits (the longer "about" text and the `sinhala-switch-loop` case). Both were rebuilt from what had
been read earlier in the same session and the case was rewritten for Phase 4, but if that file had any other
uncommitted change it is gone; compare against your editor's history if something looks missing.

## Checks

`ruff check src tests scripts`, `mypy` and the per-service mypy for `director_chat` pass. `pytest` was 888
passed and 6 failed after Phase 3; after Phases 4 to 6 it is 934 passed and the same 6 failed (this section's
older numbers are kept below for history). The 6 failures are in `tests/api` (handoff, looks, production): they compare a file link
with `http://localhost:8000/files/` while the local `.env` serves `:8001`, and they do not touch this work.
New tests: `test_cannot.py`, `test_pending.py`, `test_verified_cards.py`, `test_transcript_sinhala.py`, one API
test, and the registry tests in `test_prompt_hygiene.py`. Phases 4 to 6 added `test_translate.py` (27: the
default, the card, scope, language and style, source kept, back to source with no call, stale line refused,
role, failure, wrong script, confirm, the kernel's translator rule), `test_loop.py` (13), replay tests for
honesty and pass^k, an API test for the source text, `009_line_source.test.sql`, and the interface's
`language.test.ts`, `options-card.test.tsx` and a mapper test. The prompt budget in `test_prompt_hygiene.py`
went from 4200 to 5000 characters (the conductor is 4.4k with the translate lane).

Not run: `npx supabase test db` and the v9 dump comparison (no Docker here; the new column, its check and
`009_line_source.test.sql` are unverified), the replay in model mode (needs a key; `--k` is covered with a stub
model), anything against the hosted database or OpenAI. The interface repo needed no change for Phases 0 to 3;
Phase 4 changed it (see above): `npm run check` passes (95 tests); `npm run format:check` fails on 56 files that
were already failing on this machine (line endings); the files touched here pass `prettier --check`.

## Review fixes (2026-11-01, after Phase 6)

A review of the six phases against this plan found six defects; each is fixed and has a test.

- **Saving a partial translation failed.** A line with a source carries `source_text` / `source_lang`, a line
  without one does not, and PostgREST refuses a bulk write whose rows have different keys. So applying "translate
  S02" (or any card that left some lines alone), and every later director edit on that scene, would fail on save.
  `runtime/store.same_keys` now writes a missing key as null (`test_a_one_shot_translation_saves_rows_postgrest_accepts`).
  The API's own writes were not affected (supabase-py sends `columns`).
- **"i confirm" checked permissions for the whole edit, not per operation.** A writer (EDIT_SCRIPT, no DIRECT)
  could confirm a card that also changed shots (a director's translation card with continuity fixes); the button
  refuses that with 403. `_confirm_pending` now checks each operation as the API does
  (`test_a_writer_cannot_confirm_a_card_that_also_changes_shots`).
- **A scoped translation always reported "Goal NOT reached".** The Phase 4 note above says a translation card's goal
  is judged on the lines it translated, but `choice.apply_choice` judged it on the whole scene. It now judges a
  card's `translated_to` lines and says "every translated line is in ..." (`test_a_one_shot_translation_is_judged_on_its_own_lines_when_applied`).
- **The claim check only knew Sinhala.** With D1 widened to any language, "All the lines are now in Tamil" with
  nothing applied passed the guard. `_CLAIM` and `claim_backed` now cover every language in `LANGUAGES` and judge
  the language the sentence says the lines went TO (`test_a_claim_about_any_known_language_is_checked_against_the_scene`).
- **The loop breaker blocked a retry after the translator failed.** A failed or empty translation kept its goal, so
  asking again got "Asking again will not change that." A failure now records no goal and the next ask tries again
  (`test_asking_again_after_the_translator_failed_tries_again`). `TRANSLATOR_DOWN` (no key) no longer says "ask
  again in a little while", which contradicted that same sentence.
- **Interface:** a line put back into its original language (its text equals `source_text`) no longer shows
  "Translated from ..."; the mapper leaves `sourceText` out (`map-scene.test.ts`).

Checks after the fixes: `pytest` 944 passed and the same 6 `tests/api` port failures; ruff, mypy and the
`director_chat` mypy pass; interface `npm run check` passes (96 tests) and the touched files pass `prettier --check`.

## Left

- Run the 20-line review of the translator's Sinhala (and Tamil, if it will be used) by a speaker before turning
  it on for real scenes (plan §4 Phase 4 and D4: Scene 2 is the first real use).
- Run the schema on the hosted dev project (`upgrade_v8_to_v9.sql`, or only its `dialogue_lines` and
  `pending_actions` parts if v9 was run already). Until the `source_*` columns exist, applying a translation
  fails on save.
- Run `python scripts/replay_director.py --model --k 4` with a key, set `model_pass4` from it, and read the stored
  Scene 2 thread from the hosted dev DB to confirm turns 1, 2 and 5 of PLAN.md §1 (still inferred from the code).
- Known limit: "English" is checked as Latin script, so romanised Sinhala would pass as English.
