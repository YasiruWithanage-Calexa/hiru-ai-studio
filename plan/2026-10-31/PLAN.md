# Dialogue coverage fix: plan

Date: 2026-10-31. Write-up with diagrams: the "Missing dialogue in Create all" doc
(claude.ai artifact 6HJoDWZzqFKSEVRSLVhxHg). Phases run one at a time; `IMPLEMENTED.md` in this
folder is updated at the end of each.

## 1. The problem

Production `dfa3a927-7cd1-4e63-bd03-909efd010d08` was built from the 3-episode Kasun / Anudi script
(the same text as `tests/fixtures/prose/three-episode-drama.txt`). Every spoken line survived:
24 of 24 lines are in `dialogue_lines` and bound to a shot. The shot plan around them is the
problem:

| Episode | Target | Shots run | Silent shots | Silent share | Speech needs |
|---|---|---|---|---|---|
| 1 | 60 s | 72 s (+12) | 7 · 38 s | 53% | 22 s |
| 2 | 60 s | 78 s (+18) | 10 · 46 s | 59% | 21 s |
| 3 | 60 s | 74 s (+14) | 6 · 32 s | 43% | 24 s |

Five of seven scenes are over their envelope. Nine lines sit in shots Veo is likely to get wrong:

- E1 S2 shot 10: the father's phone call is `dialogue` on an MCU of Anudi. He is not in frame.
- E3 S1 shot 3: TWO, 8 s, three lines from two speakers.
- E2 S3 shot 4: TWO, two speakers. E2 S3 shots 2 and 3: TWO with one line each.
- E1 S2 shots 1 and 11: lines in WIDE shots.

The prompt writer (`shot_producer/engine/serialize.py`) is correct: lines are verbatim. No takes are
uploaded yet, so the Veo failures are predicted, not observed.

## 2. Root causes

| # | Cause | Where |
|---|---|---|
| C1 | The critic asks for reaction and insert shots and is told "Timing is checked by code; ignore it". | `script_split/engine/critic.py` `CRITIC_SYSTEM` |
| C2 | The plan score counts only `line_overrun`, `word_budget`, `repaired`, `long_line`. No envelope, silence or two-speaker shots. The revised plan wins ties (`<=`). | `critic.py` `_SIGNIFICANT`, `kernel_score`; `script_split/engine/pipeline.py` `plan_scene` |
| C3 | The planner calls one speaker per shot "safest" but never requires it, and has no rule that keeps silent shots few. The kernel does not report two-speaker shots. | `script_split/engine/planner.py` `PLAN_SYSTEM`; `contracts/shotplan.py` `fit` |
| C4 | No off-screen voice. The prose model leaves `delivery` empty for a phone call, so the kernel picks `dialogue`. The kernel already maps `v.o` / `voice over` marks to `voiceover` (`_VOICEOVER_MARK`), but no phone or off-screen mark. | `structure_build/engine/prose.py` `SYSTEM`; `contracts/shotplan.py` `_VOICEOVER_MARK` |

## 3. Rules kept

- Lines are never trimmed, reworded or dropped. Overruns are reported, never auto-trimmed.
- Approved scenes are left alone by a re-split.
- Static prompt text stays byte-identical across calls (cache); scene data goes last.
- Absent-safe: without a key the rules planner still runs and the new checks still apply.
- No frontend change is required. New issue codes show up as messages where issues already show.

## 4. Phases

### Phase 1: the kernel reports what is wrong (contracts)

`src/libs/contracts/shotplan.py`

1. `fit` adds an `Issue("multi_speaker", …)` for a `dialogue` shot with more than one speaker
   (the same check that already leaves `speaker_id` empty).
2. `FitResult` gets `silent_s` (sum of shots with no lines) and `silent_share` (`silent_s / total_s`).
   Properties computed from `shots`, no new stored field.
3. `_VOICEOVER_MARK` gains off-screen marks: `"o.s"`, `"off screen"`, `"off-screen"`, `"on the phone"`,
   `"over the phone"`. A line whose delivery says it is heard, not seen, becomes `voiceover`.
4. Update the `Issue.code` comment. Check `api/routers/scenes.py` `IssueView.code` and
   `contracts/sceneplan.py` accept a new code (they pass strings through).

Tests (`tests/contracts/`): two speakers in one shot gives `multi_speaker`; one does not; a line
with delivery "on the phone" gives `voiceover`; `silent_share` on a mixed plan.

Note: `fit` is also used by `director_chat/engine/kernel.py` and `api/routers/scenes.py`. The new
issue appears in their reports as a message. Run the director_chat tests and the replay
(`tests/eval/director_replay.json`) to confirm nothing reads it as a refusal.

### Phase 2: score plans on speech coverage (script_split)

`src/services/script_split/script_split/engine/critic.py`, `engine/pipeline.py`

1. Replace the integer score with a tuple, compared lowest first:
   `(significant issues, multi_speaker shots, over_envelope_s, silent_s)`.
   `_SIGNIFICANT` stays as it is; the new terms come after it, so a plan that clips a line still loses.
2. `plan_scene`: the revised plan replaces the first only when its score is strictly lower.
   A full tie keeps the first plan.
3. The rules-versus-model check uses the same tuple.
4. `SILENT_SHARE_MAX = 0.4` (a tunable constant in `critic.py`, first guess to test on the fixture).
   A plan above it gets one extra point on the significant count, unless the scene has no lines
   (action-only scenes are exempt).

Tests (`tests/services/script_split/test_split.py`): an over-envelope revised plan loses to an
on-envelope first plan; a tie keeps the first plan; a plan with a two-speaker shot loses to one
without; an action-only scene is not penalised for silence.

### Phase 3: the critic respects the budget

`critic.py` `CRITIC_SYSTEM`, `describe`, `review`

1. `describe` adds a header line: `Envelope: {envelope_s} s. Plan runs {total_s} s. Silent: {silent_s} s.`
2. `CRITIC_SYSTEM` (still static): remove "Timing is checked by code; ignore it". Add: when the plan
   runs over the envelope, do not add a shot; fix coverage by reframing or merging. Flag a dialogue
   shot whose speaker is not in frame, and any shot with two speakers. Do not ask for a reaction or
   insert the script does not name.

Tests: the fake critic receives the envelope line; with the fake returning "add a CU" on an
over-budget scene, the revised plan is rejected by the score (Phase 2).

### Phase 4: speech-first planner

`script_split/engine/planner.py`

1. `PLAN_SYSTEM` (static) rules:
   - Every line goes in a shot that frames its speaker. One speaker per dialogue shot. TWO or OTS
     only when the second person listens without speaking.
   - Silent shots only for beats the script names (an arrival, a phone dropped, a cheque pushed back,
     a sign unveiled). Merge runs of short actions into one shot.
   - Stay within the envelope; when speech fills it, add no silent shots.
   - A line marked off screen or on the phone goes in a `voiceover` shot framed on whoever is present.
   - Prefer MCU or CU for a line; WIDE only for a line shouted across distance.
2. `scene_listing` shows `delivery` already; nothing else to add once Phase 5 fills it.
3. `plan_by_rules`: when a shot holds only off-screen lines, frame the present listener (MCU).

Tests: the rules plan for the phone-call scene puts the father's line in a `voiceover` shot.

### Phase 5: mark off-screen voices at the source

`structure_build/engine/prose.py`

1. `SYSTEM`: `delivery` is "on the phone" when the text says the call or voice comes through a phone,
   and "off screen" when the speaker is not physically in the scene. Keep "" otherwise.
2. `by_rules`: no change; rules do not guess. The planner rule (Phase 4) and kernel marks (Phase 1)
   handle whatever the model marks.

Tests (`tests/services/structure_build/test_prose.py`): a fake model answer with
`delivery: "on the phone"` survives `trusted()` and `render()` as `@Father\n(on the phone)\n…`.

### Phase 6: report it in the build

`script_split/engine/pipeline.py` `report()`

1. `fit_report` gains `silent_s`, `silent_share`, `multi_speaker` (shot numbers) and `voiceover`
   (shot numbers).
2. The build's agent step says, per episode: "Episode 1: 60 s, 34 s spoken, 2 lines off screen".

Tests: the report fields are present and correct on the fixture.

### Phase 7: verify on the real script

1. New test using `three-episode-drama.txt` end to end with the fake model (rules mode and model
   mode): 24 of 24 lines bound; no `multi_speaker` issue; the father's phone line in a `voiceover`
   shot; each episode within 60 s plus one 4 s shot, unless speech alone is longer.
2. `pytest`, `ruff`, `mypy` clean; `scripts/eval_retrieval.py` untouched (no retrieval change).
3. On localhost against the hosted dev DB: re-split production `dfa3a927` (no scene is approved).
   Ask the user first: it rewrites shots and unlinks frames made for the old shots.
   Compare against the table in §1.
4. With the user: generate takes for the five risky shots and confirm each line is heard from the
   right person.

## 5. Out of scope

- The prompt writer and Veo serializer (already verbatim and voiceover-aware).
- Frontend changes. A "spoken vs silent" bar on the episode overview is a follow-up if wanted.
- Auto-fixing existing productions. A re-split is a person's choice.

## 6. Open questions

- Is 40% the right silent-share ceiling, or should it be a production setting
  (`ProductionSettings`, which would need a schema and frontend change)?
- Should a re-split keep frames already made for shots whose range is unchanged? Today they are
  reported out of date through `Pins`, not redone (CLAUDE.md "Designs, frames and prompts are never
  redone").
