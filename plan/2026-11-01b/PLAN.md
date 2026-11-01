# Shots measured in pictures, not only words: plan

Date: 2026-11-01 (second plan of the day; follows [../2026-11-01/PLAN.md](../2026-11-01/PLAN.md)).
Write-up with diagrams: the "Crowded Shot Trace" artifact. Phases run one at a time;
`IMPLEMENTED.md` in this folder is updated at the end of each.

## 1. The problem

Episode 1, Scene 2 (`032f2749…`), shot S05 (`0369e443…`). The story says:

> Anudi smiled back. Suddenly, her phone rang. It was her father.
> Father: "Anudi, where are you? Come home. We need to talk about your marriage."
> Her smile disappeared. She looked at Kasun one more time.

The 2026-11-01 fixes work: the father is now only heard. But the shot list is wrong:

| Shot | Length | Blocks it plays | Picture it needs* |
|---|---|---|---|
| S05 MCU, voiceover | 8 s | Anudi smiles back · phone rings · "It is her father" · father's 13-word line | ≈ 9.4 s (10.9 s with "she answers") |
| S06 MCU, dialogue | 4 s | smile disappears · looks at Kasun · her line · walks away · Kasun watches · "He has no idea…" | ≈ 8.3 s |

\* with the proposed time model (§4 Phase 1): an action 1.5 s, a move through space 2.5 s, an action that plays under the
line that follows 0.5 s, plus speech at 2.2 words/s.

What Veo is asked for in S05: the father's line is bound to **beat 0 (0–3 s), starting at 0.5 s**, while the intent says
the phone starts ringing at 3–6 s. The voice starts before the phone rings, and nobody answers the phone.

Evidence (read-only, hosted dev DB and offline run of today's code):

- The 6 shots came from the original split on 2026-10-31 and the scene was approved. Director edits since then only
  changed S05's title and sound and one block's text. Yesterday's planner fixes (D10–D11) never ran on this scene.
- Re-running **today's** rules planner on the same script gives the **same 6 shots, 30 s, all MCU, and zero kernel
  issues**. Every line starts 0.5 s into its shot. `BUSY: S06` and `No WIDE` appear only as hint text for the critic.
- The scene's `fit_report.issues` is `[]`. The system believes the scene is clean.

## 2. Root causes

| # | Cause | Where |
|---|---|---|
| R1 | **The clock counts words only.** In a shot with a line, actions take 0 s: `needed_seconds` sums speech, and every line starts at `LEAD_IN_S` (0.5 s) whatever comes before it. So a shot "fits" however many actions it holds, and lines land on the wrong beat. | `contracts/shotplan.py` `fit`, `needed_seconds`, `_split_long` |
| R2 | **No check counts pictures.** The kernel has no "crowded" issue. `BUSY` is critic prompt text, only for 4 s shots with ≥ 3 action blocks (S05 is 8 s, so never flagged), and it runs only in a fresh split, never after the director chat or an API edit. | `script_split/engine/critic.py` `coverage_lines`; `director_chat/engine/turn.py` `persist` |
| R3 | **Implied steps are forbidden.** "She answers the phone" is needed for the voice to make sense, but every agent is told never to add an event. The voice arrives from nowhere. | `structure_build/engine/prose.py` `SYSTEM`; `shot_producer/engine/intent.py` `SYSTEM` |
| R4 | **Unfilmable text is treated as action.** "It is her father (voice only)" is information (the camera can carry it with an insert of the phone screen or by the line itself); "He has no idea that this meeting is about to change his life" is a thought. Both count as actions and reach the camera. | `prose.py` (block kinds), `contracts/screenplay.py` |
| R5 | **Downstream agents cannot push back.** The intent agent and the DoP are told the shot list is FIXED, so they compress: S05's "what we see" keeps the smile and the ring and drops the answer, the voice and the fading smile. S06's intent says "two-shot … walks away" on an MCU and nothing compares them. | `intent.py` `SYSTEM`, `shots.py` `SYSTEM` |
| R6 | **The budget pushes pictures into speech shots.** The envelope (35 s) is the prose model's guess scaled to 60 s. The planner is told "when speech fills it, add no silent shots", and `fold_silent` merges silent shots into neighbours when over. A scene that needs 42 s is squeezed into 30 s and reports no overrun. We auto-trim pictures while promising never to auto-trim. | `planner.py` `PLAN_SYSTEM`, `fold_silent`; `prose.py` `fit_seconds` |
| R7 | **"One event per shot" is advice, not a measure.** One action block can hold several events ("Kasun picks it up and runs after her"), and nothing counts them. | `planner.py` `PLAN_SYSTEM`; `prose.py` |

## 3. Rules kept

- Lines are never reworded, trimmed or split. A shot is never cut inside a line.
- Overruns are reported, never auto-trimmed. **New:** this now covers pictures too: a scene that needs more time than
  its envelope is reported, not squeezed.
- Approved scenes are left alone by a re-split.
- A person's edits (shot ranges, locked lengths, intent, coverage, camera) are never replaced by an agent.
- Absent-safe: without a key, rules classify blocks and the kernel's picture clock still runs.
- Static prompt text first and byte-identical across calls; scene data last.
- `contracts/timing.py` and the interface's `src/lib/veo/timing.ts` change together, with parity tests.

## 4. Phases

### Phase 1: the kernel keeps a picture clock (contracts) · fixes R1, R2

`src/libs/contracts/timing.py`, `src/libs/contracts/shotplan.py`, `src/libs/contracts/sceneplan.py`

1. `timing.py`: `SCREEN_SECONDS = {"move": 2.5, "act": 1.5, "with_line": 0.5, "info": 0.0, "inner": 0.0}` and
   `action_seconds(screen, events=1)`. Unknown screen kind counts as `act`. First guesses, tuned by the eval (Phase 9).
2. `Item` gains `screen: str = "act"` and `events: int = 1` (filled by Phase 2; until then every action is one `act`).
3. `fit` walks each shot's items in order on one clock: an action adds its seconds; a line starts at
   `max(clock, LEAD_IN_S)` (an action before the first line replaces the lead-in), then adds speech + `LINE_GAP_S`;
   `TAIL_S` is added only when the shot ends on a line. `needed = clock`. Line `start_s` and `beat_index` come from
   this clock, so a voice after "phone rings" lands after it.
4. `_split_long` becomes `_split_to_fit`: an unlocked shot that needs more than the longest rung is split at a block
   boundary (action or line, never inside a line), choosing the split that leaves each part within the ladder.
   The follow-on is `cut` when the split falls on an action, `continuous` when it falls between lines (as today).
5. New issue `crowded` (significant): a locked or fixed-length shot whose picture + speech needs more than its length;
   message names the shot, the need and the length ("S05 needs about 10.9 s to show what it holds; it is 8 s").
6. `FittedShot` gains `picture_s` (action seconds) and `need_s`. `sceneplan.fit_report` adds `crowded` (shot numbers)
   and `need_s` (scene total).

Tests (`tests/contracts/`): Scene 2's script reproduces today's 6-shot plan as a proposal → S05 and S06 are split,
the father's line starts after "phone rings"; a locked 8 s S05 gives `crowded`; a shot of one line and no action
times exactly as today (no regression for talking heads); parity cases added to `tests/contracts/test_timing.py`.
Run `director_chat` tests and `tests/eval/director_replay.json` (the director's kernel calls `fit`).

### Phase 2: read the script as pictures · fixes R4, R7

`src/services/script_split/script_split/engine/beats.py` (new), `structure_build/engine/prose.py`

1. `beats.classify(items)` labels every action block once per script version: `screen` (move / act / with_line /
   info / inner) and `events` (how many visible events it holds). Medium tier, strict schema, one call per scene,
   stored on the scene's script blocks (`script[i].screen`, `script[i].events`) with the `script_version` it was made
   for. Rules fallback: sentence count for `events`; keyword lists for `move` (runs, walks away, drives, crosses…),
   `with_line` (smiles, looks, turns, nods, directly before a line by the same person), `inner` ("had no idea",
   "thought", "knew", "felt", "would change"), `info` ("It was X", "it is her father"). Never rewrites a block.
2. Existing productions are classified on the next re-split or design, so no rebuild is needed.
3. `prose.py` `SYSTEM`: one visible event per action block (split "Anudi smiled back. Suddenly, her phone rang." into
   two). `by_rules` splits action paragraphs at sentence boundaries. New builds only; stored scripts are not rewritten.
4. Intent and DoP prompts show `inner` blocks as `STORY NOTE (not filmed)` and `info` blocks as
   `THE VIEWER LEARNS: … (show it with an insert, a line or a look)`.

Tests: Scene 2's blocks classify as expected by rules (18 → inner, 11 → info, 1 → move, 9/10 → act); the fake model
answer survives validation; a prose fixture splits two-event paragraphs.

### Phase 3: implied steps, named and removable · fixes R3 (needs decision D1)

`src/libs/contracts/bridges.py` (new), `script_split` pipeline, API, interface

1. A closed list of bridges a script implies but does not write: **answer the phone** (a ring followed by a line
   marked on the phone, with no answer between) and **lower the phone** (a phone line followed by action by the
   holder). Each is an action block `{"implied": true, "by": "rules"}` inserted at a block boundary, `act` 1.5 s.
2. Rules only (no model may add a bridge in this phase). Never a line, never a new person, never a story event.
3. Shown in the script and the shot page with an "Implied" chip and a remove control; a removed bridge is remembered
   per scene and never re-added (person edit wins).
4. The intent and DoP prompts keep "never add an event", with "IMPLIED steps are part of the script" added.

Tests: Scene 2 gets "Anudi answers the phone" between block 10 and the father's line; removing it and re-splitting
does not bring it back; a script that already says "she answered" gets no bridge.

### Phase 4: the planner and critic see time · fixes R2, R6, R7

`script_split/engine/planner.py`, `critic.py`, `pipeline.py`

1. `scene_listing` shows each block's kind and seconds: `[10] ACTION (act, 1.5 s): Suddenly, her phone rings.`,
   `[11] INFO (needs a carrier): It is her father.`, `[18] STORY NOTE (not filmed): …`.
2. `PLAN_SYSTEM` (static): a shot holds its picture + speech, code checks; a turn in feeling (a smile broken by a
   call) starts a new shot; an INFO block rides with a line that says it or gets an INSERT; a heard voice starts only
   after its source is shown; a move through space gets a WIDE or MS.
3. `critic.describe`: per shot `need 10.9 s in 8 s`; `CROWDED:` replaces `BUSY:` (measured, any length).
4. `crowded` joins `_SIGNIFICANT`, so a crowded plan always loses to an uncrowded one.
5. `fold_silent` stops folding when the merge would crowd the neighbour; the scene then reports its envelope
   overrun (Phase 6) instead of hiding it.

Tests: on Scene 2 the rules plan has no crowded shot; a fake model plan with today's S05 loses to the rules plan.

### Phase 5: the same checks wherever a plan changes · fixes R2

`director_chat/engine/turn.py`, `options.py`, `agents.py`; `api/routers/scenes.py`

1. `persist` and the API re-timing store `crowded` and `need_s` in `fit_report`. The scene's issue list shows them.
2. The director chat's impact line names a merge or length change that crowds a shot ("S05 would need 10.9 s in 8 s").
3. Approving a scene with crowded shots asks once ("2 shots hold more than they can show. Approve anyway?"); it never
   blocks.

Tests: a director-chat merge of S05 + S06 reports `crowded`; the replay eval is unchanged otherwise.

### Phase 6: honest envelopes · fixes R6 (needs decision D2)

`script_split/engine/pipeline.py` `episode_line`, `contracts/shotplan.py` `envelope` issue, `prose.py`

1. The envelope issue says what the script needs: "Scene 2 needs 42 s on screen; its envelope is 35 s (7 s over)."
2. The build log per episode: "Episode 1: needs 78 s to show its script; target 60 s."
3. The director chooses: grow the envelope, cut a beat (a person's script edit), or approve as is. Nothing is merged
   or dropped automatically.
4. `prose.py` `SYSTEM`: the scene `seconds` estimate counts what is seen, not only what is said.

### Phase 7: intent and DoP work on the timeline, and can say "split here" · fixes R5

`shot_producer/engine/intent.py`, `shots.py`, `serialize.py`; `contracts/staging.py`

1. Each shot's prompt carries its TIMELINE from the kernel: `0.0–1.5 Anudi smiles back · 1.5–3.0 her phone rings ·
   3.0–4.5 Anudi answers (implied) · 4.5–10.4 LINE Father (phone)`.
2. Intent schema: `what_we_see` follows the timeline in order; new optional `split_after` (a block index) with a
   one-line reason when the agent finds the shot cannot be played as one take. Stored on the intent, shown as a check.
3. Free checks (`staging_checks`): `skips_beat` when a visible block's key words are missing from `what_we_see`;
   `size_vs_intent` when the intent says two-shot / walks away / wide and the framing is MCU or CU.
4. DoP `shot_block` gets the TIMELINE; `fit_beats` maps the DoP's beats by time, not by position.
5. Video prompt: a heard line's beat says what happens first ("Anudi raises the phone; then the voice: …").

Tests: S05's intent prompt carries the timeline; a fake intent that omits the call gets `skips_beat`; S06 (MCU +
"two-shot … walks away") gets `size_vs_intent`.

### Phase 8: interface · shows all of the above

`hiru-ai-studio-interface`: `src/lib/veo/timing.ts`, `src/features/production/components/shot-intent-card.tsx`,
`scene-coverage-card.tsx`, `src/features/scenes/lib/map-scene.ts`, `types.ts`

1. `timing.ts` mirrors `SCREEN_SECONDS` / `actionSeconds` (parity tests).
2. "What this shot is for" card: a timeline strip on the shot's 0–8 s ruler (picture blocks, line bars, beat
   windows); a `Chip tone="warning"` "Crowded · needs 10.9 s in 8 s"; "Implied" chips with remove; story notes greyed.
3. A "Split here" action when the intent suggests one (calls the existing director-chat split op).
4. Scene header: "Needs 42 s · envelope 35 s".

### Phase 9: eval, then Scene 2 for real

1. `tests/eval/staging_scenes.json` gains hard scenes: a call that breaks a moment, drop-pickup-run, an exit watched,
   a caller named only in prose, a closing thought. New metrics with floors in `staging_thresholds.json`:
   `crowded_shots = 0`, `voice_before_source = 0`, `inner_filmed = 0`, `info_carried ≥ 0.8`.
2. `pytest`, `ruff`, `mypy` (root and per service); interface `next typegen`, `npm run check`, `format:check`.
3. With the user: un-approve Scene 2, re-split (unlinks the frames of the old S05 / S06), design, new frames.
   Expected: 8 shots, about 42 s, a WIDE for the drop and run, the call over two shots, the exit in a WIDE.

## 5. Decisions for the user

| # | Question | Recommendation |
|---|---|---|
| D1 | May the system add an implied step such as "Anudi answers the phone"? | Yes, from a closed rules list only, shown as "Implied" and removable. |
| D2 | When a scene needs more time than its envelope, what happens? | Report it and let the director choose. Never squeeze or cut automatically. |
| D3 | Picture times: move 2.5 s, act 1.5 s, under a line 0.5 s. | Start with these; tune on the eval. |
| D4 | Scene 2 is approved; re-splitting it unlinks S05 / S06 frames. | Do it in Phase 9, after the eval passes. |
