# Dialogue coverage fix: what is built

Plan: [PLAN.md](PLAN.md). Phases 1 to 7.2 are done (2026-10-31). Phases 7.3 and 7.4 need the user.

## Phase 1: the kernel reports what is wrong (done)

`contracts/shotplan.py`

- `fit` adds `Issue("multi_speaker")` (with the shot number) for a `dialogue` shot with more than one
  speaker. A voiceover shot with two voices is not flagged: lip-sync is not at risk.
- `FitResult.silent_s` and `silent_share`: properties over `shots`, nothing stored.
- `_VOICEOVER_MARK` gains `o.s`, `off screen`, `off-screen`, `on the phone`, `over the phone`. A shot is
  `voiceover` only when every line in it is marked, so one on-camera line keeps it `dialogue`.
- `IssueView.code` and `Issue.code` comments list the new code; both pass strings through.

Checked: `director_chat` only shows issue messages (continuity notes, option impact) and treats just
`repaired` as a refusal. The director replay still scores 100% in rules mode.

## Phase 2: score plans on speech coverage (done)

`script_split/engine/critic.py`, `engine/pipeline.py`

- `kernel_score` is now `(significant, multi_speaker shots, over_envelope_s, silent_s)`, lowest first.
- `issue_count(result)` is the first term: the `_SIGNIFICANT` issues plus one when
  `silent_share > SILENT_SHARE_MAX` (0.4), unless the scene has no lines. The build's `issues` total
  uses it, so a mostly silent scene is counted as one thing to look at.
- `plan_scene`: the revised plan replaces the first only when strictly lower. A tie keeps the first.
  The rules-versus-model check already used `<`, now on the tuple.

## Phase 3: the critic respects the budget (done)

`describe` starts with `Envelope: N s. Plan runs N s. Silent: N s.` `CRITIC_SYSTEM` no longer says
timing is ignored; it forbids adding a shot when over the envelope, asks for two-speaker and
speaker-not-in-frame shots to be flagged, and forbids asking for a reaction or insert the script
does not name. The prompt stays static.

## Phase 4: speech-first planner (done)

`script_split/engine/planner.py`

- `PLAN_SYSTEM` rules rewritten as planned (one speaker per dialogue shot, voiceover for off-screen
  lines, silent shots only for named beats, stay in the envelope, MCU/CU for lines). Still static.
- `plan_by_rules`: a shot holding only heard-not-seen lines is MCU, `voiceover`, titled
  "<listener> listens". The listener is the nearest on-camera speaker before the line, else after it.

## Phase 5: mark off-screen voices at the source (done)

`structure_build/engine/prose.py` `SYSTEM`: `delivery` is "on the phone" or "off screen" as planned.
`by_rules` is untouched. `trusted()` and `render()` already carry `delivery` through; a test pins it.

## Phase 6: report it in the build (done)

- `contracts/sceneplan.fit_report` (shared by the API and `script_split`) gains `silent_s`,
  `silent_share`, `multi_speaker` (shot numbers) and `voiceover` (shot numbers).
  `pipeline.report` now delegates to it, so the two shapes cannot drift.
- The build's agent step: one line per episode, e.g. `Episode 1: 72 s (12 s over), 34 s spoken, 2 lines
  off screen`. "Spoken" is the seconds of shots that carry a line. Totals are carried in
  `progress.episodes` across time-boxed deliveries and said once, when the hop is complete.

## Phase 7: verify on the real script

7.1 and 7.2 done. `tests/services/script_split/test_dialogue_coverage.py` runs the 3-episode script
through the structure build and the split, in rules mode and model mode: 24 of 24 lines bound and
verbatim, no `multi_speaker`, the father's call in a `voiceover` shot, every episode within 60 s + one
4 s shot (or its speech alone). `pytest` 688 passed, `ruff`, `mypy` (root and per service) clean.
`eval_retrieval.py` untouched (no retrieval change).

### Deviations from the plan

- **Rules planner folds silent shots when over the envelope** (`planner.fold_silent`, called from
  `plan_by_rules(items, envelope_s=…, fixed_seconds=…)`). Not in the plan, but 7.1 cannot pass without
  it: after Phases 1 to 6 the rules plan for episode 3 ran 68 s against 60 s with 22 s of silent
  shots. The longest silent shot is folded into the next shot (the previous one for a trailing action)
  until the scene fits or only speech is left. Speech is never touched. Without an envelope, or inside
  it, the plan is unchanged. The model path is not folded: the score and the critic handle it.
- Two speakers are counted by `speaker_id`, falling back to the speaker name when a line is not linked
  to a canon character. The plan said "the same check as `speaker_id`", which would miss an unlinked
  speaker.
- "Model mode" in the test uses a deterministic fake planner that follows the new rules, not a real
  model; it checks the plumbing and the score, not what the real model does with the new prompt.

### Not yet done (needs the user)

- **7.3** Re-split production `dfa3a927` on localhost against the hosted dev DB. It rewrites shots and
  unlinks frames made for the old shots, so it waits for a yes. Compare with the table in PLAN §1.
- **7.4** Generate takes for the five risky shots and check each line is heard from the right person.
- The prose prompt change (Phase 5) only matters for a production built after it; the existing one
  keeps the father's line with an empty `delivery`. A re-split alone will not mark it off screen: the
  planner and kernel only see what `delivery` says. For `dfa3a927`, either re-run the structure build
  or set that line's delivery to "on the phone".

## Open questions (from the plan, unchanged)

- Silent-share ceiling 0.4 is a constant, not a production setting.
- Whether a re-split keeps frames for shots whose range is unchanged.

## Follow-up (2026-10-31): looks are drafted by the build

Found by the user after the dialogue fix: characters were generated, their **looks** were not (the
character page said "No looks yet"). Nothing in the build wrote `canon_looks`.

- `contracts/lookdraft.py` (pure): `by_rules(card, episodes)` makes one look ("Everyday") from the
  card's wardrobe, or two when the wardrobe turns to "Later, …" (the second look takes the second
  half of the episodes). Accessories (jewelry, bag, watch…) leave the outfit; short hair and makeup
  notes come from the appearance. `clean_proposals` checks a model's looks (name, a wardrobe field,
  ranges inside 1..N, unique names, at most 4). A card with no wardrobe gets no look: nothing is
  invented.
- `structure_build/engine/looks.py` + a `looks` node after `write`: with a key the model
  (`medium` tier, schema `canon_looks`, static system text) proposes the looks from the cards and
  the episode count; without one, or when its answer does not hold up, the rules do. A character
  that already has a look is skipped, so a re-run never doubles or overwrites. Skipped when the
  build excludes canon. A failure is a warning, never a failed build. The report says
  "Drafted N looks for M characters (drafts: make each sheet, then mark it ready)."
- **Drafts only.** `resolve_look` uses READY looks, so a drafted look changes no frame until a
  person has made the sheet and marked it ready. Sheets are not painted by the build (they cost an
  image call each and need the base sheet first).
- `POST /v1/productions/{id}/looks/draft` (EDIT_CANON, rules only) does the same for a production
  built before this: for `dfa3a927`, no re-build needed. The interface's empty looks panel has a
  "Draft looks from wardrobes" button for it.
- Tests: `tests/contracts/test_lookdraft.py`, `tests/services/structure_build/test_looks.py`,
  `tests/api/test_looks.py` (draft endpoint). 706 pass, ruff and mypy clean.
- Not run: the model path against OpenAI (the tests use a fake), and the endpoint against the
  hosted dev DB.
- Six existing API tests assume `API__PUBLIC_URL=http://localhost:8000`; `.env` now says 8001, so
  they fail unless the variable is overridden. Not caused by this change.
