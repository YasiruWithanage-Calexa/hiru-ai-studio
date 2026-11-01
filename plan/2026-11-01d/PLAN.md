# Shots planned by a director, not a timetable: plan

Date: 2026-11-01 (fourth plan of the day; builds on [../2026-11-01b/PLAN.md](../2026-11-01b/PLAN.md), which is built).
Write-up with diagrams: the "Directed Shots" artifact. Phases run one at a time; `IMPLEMENTED.md` in this folder is
updated at the end of each. No code is changed by this file.

## 1. The problem

The person's review of recent shot lists (2026-11-01):

- Camera, framing, lenses and movement are good. The production settings are not the problem.
- Scenes feel made by a technical person: dry, with little feeling.
- Continuity breaks: a person is suddenly somewhere else in the same place ("how did she get there?"). The scene
  feels like cropped highlights instead of a flow.
- An earlier change to remove non-dialogue silent shots went too far. The intent was to keep the meaningful ones.

## 2. What the code does today

The shot list is decided in one place (`script_split`), then every later agent is told it is FIXED.

```
story prose ─► prose.py ─► script blocks ─► beats.classify ─► bridges ─► planner ─► kernel fit ─► critic ─► (re-plan once)
                (events)     (action/line)   (move/act/with_line/        (phone     (groups     (clock,     (coverage)
                                              info/inner)                 only)      blocks)     issues)
                                                                    ───────────────── shot list FIXED ─────────────────►
                                                                    intent agent ─► DoP ─► serialize ─► Veo 3.1 prompt
```

### Where feeling is lost (E = emotion, C = continuity)

| # | Finding | Where | Effect |
|---|---|---|---|
| E1 | **The planner never sees the story.** It gets the heading, the envelope and the block listing. No synopsis, no scene before or after, no director's note, no characters' wants. | `planner.plan_by_model` (user message) | Shots are grouped by timing and speaker turns, not by what the scene is about. |
| E2 | **Meaning comes after the cut.** Purpose and `emotional_beat` are written by the intent agent, after the shot list is fixed and approved. | `pipeline.plan_scene` → `shot_producer/intent.py` `SYSTEM` ("FIXED") | Feeling is painted on a structure built without it. The intent agent can only suggest `split_after`. |
| E3 | **Silence is a cost in four places.** Planner: "silent shots are only for beats the script names", "when speech fills it, add no silent shots". `fold_silent` merges silent shots when over the envelope. Critic: "do not ask for a reaction or an insert the script does not name". Score: `silent_s` is a cost; `SILENT_SHARE_MAX = 0.4` adds a problem. | `planner.py` L229–231, `fold_silent`; `critic.py` L35, L47–66 | Reactions, pauses, arrivals and the held last image are removed first. They are what carries feeling, and scripts rarely write them down. |
| E4 | **Reactions are timed as 0.5 s.** `with_line` (smile, look, nod, sigh, hesitate, pause, stare, swallow …) plays "under the line after it" for 0.5 s. "Her smile disappeared" becomes half a second under the next line. | `contracts/beats.py` `_REACTION`; `contracts/timing.py` `SCREEN_SECONDS` | A turn in feeling gets no screen time of its own. |
| E5 | **Lines are delivered back to back.** `LINE_GAP_S = 0.3`, `TAIL_S = 0.5`, `LEAD_IN_S = 0.5`. No pause before an answer, none after a line that lands. | `contracts/shotplan.py` | Dialogue plays as a read-through, not a scene. |
| E6 | **Inner life is thrown away, not translated.** Blocks with *felt, thought, knew, hoped, realised, had no idea …* become `STORY NOTE (not filmed)`. Correct not to film them as text, but nothing turns them into behaviour an actor could play. | `contracts/beats.py` `_INNER`; `intent.py` `block_label` | The writer's emotional intent never reaches the camera or the face. |
| E7 | **The video prompt has no performance field.** The clip schema has setting, camera, light, subjects (`description`, `action`) and beats (`camera`, `director_line`, `action` "the literal physical action"). Nothing for expression, inner intention or tone of voice. Google's Veo 3.1 guide names emotion, expression and voice tone directly in its examples. | `clip_schema_veo_3_1.yaml` `required_structure` | Veo plays faces neutral unless a beat happens to describe them. |
| E8 | **One critic, mostly rules.** The critic checks coverage (speaker in frame, sizes, WIDE, crowded). It has no lens for arc, turns, rhythm or endings. | `critic.CRITIC_SYSTEM` | The measurable rules win, so plans pass that are correct but flat. |
| E9 | **The craft notes do not reach the planner.** `knowledge_base/craft/directing.md` and `editing.md` already say "emotional arc beats plot arc", "a held look and a quick reveal are not the same length", "a cut to silence before the key moment makes it land twice as hard". Only the DoP's technique palette uses the knowledge base. | `techniques.py` (DoP only) | The planner works without the studio's own craft rules. |
| C1 | **No one knows where people are.** The continuity ledger carries `setting`, `lighting`, `last_action` as text. No positions, facing, props in hand, entrances or exits. | `shot_producer/engine/continuity.py` | Nothing notices that she ends S03 at the gate and starts S04 at the stall. |
| C2 | **Unwritten moves never become pictures.** Bridges cover answering and lowering a phone only. A walk across the yard that the script implies is never shown. | `contracts/bridges.py` | People teleport between shots inside one place. |
| C3 | **No screen direction or eyeline in the plan.** The DoP is told to keep one side of the action and `coverage.axis` is prose. No left/right of frame per person, no check between shots. | `shots.py` `SYSTEM`; `intent.py` coverage | Cuts can flip who is on which side, which reads as a jump. |

### Constraints the new design must respect

- Veo renders whole 4, 6 or 8 s shots, and nothing trims them in an edit. A separate reaction shot costs at least 4 s,
  which is 7% of a 60 s episode. **So most breath has to live inside shots** (a hold at the end of a shot, the
  listener in an OTS or TWO, a push-in onto the reaction), not in extra cutaways.
- Episodes are short (often 60 s, 2–4 scenes). Breath competes with story. The system must choose *where* to spend it,
  not add it everywhere.
- Dialogue is never changed. A person's edits win. Overruns are reported, never squeezed. Without a key, rules still work.

## 3. What reputable sources say (and what we take from each)

| Source | Idea | What we take |
|---|---|---|
| Walter Murch, *In the Blink of an Eye* (Rule of Six) | A cut is judged by emotion first, then story, rhythm, eye-trace, the 2D plane of the screen, 3D space. He weights emotion at about half. | The plan's score and critics follow this order: emotion and story before coverage rules. |
| Robert McKee, *Story* | A beat is "an exchange of behaviour in action/reaction"; a scene turns on a change in value (hope → dread). A new beat begins only when behaviour clearly changes. | The scene reading names the value at the start and end and the turns, by block. Every turn needs its reaction seen. |
| Judith Weston, *Directing Actors* | Direct with playable action verbs and intentions ("to reassure", "to hide"), not adjectives or results ("be sad"). | Inner notes become playable behaviour; each beat gets a `performance` line written as visible behaviour. |
| Kuleshov effect (Soviet montage) | The audience reads the feeling from the cut between an event and a face. | The reaction shot or reaction hold is where feeling is made. A turn without a reaction is a defect. |
| Bordwell & Thompson, *Film Art*; continuity-editing practice | 180° rule, eyeline match, match on action, screen direction, 30° rule. Most Hollywood shots follow these. | A staging map with left/right and facing per person; code checks that cuts keep it, or name a deliberate re-angle. |
| Yasujiro Ozu (pillow shots), and the studio's own `editing.md` | Quiet shots of place and time let a scene breathe; a held silence before the key moment makes it land. | Breath is a typed, budgeted tool with a reason, not a cost. |
| Google Cloud, *Ultimate prompting guide for Veo 3.1* | Prompt = cinematography + subject + action + context + style. Examples name emotion, expression and voice tone. Timestamped segments direct pacing inside one shot. First/last frame and reference images hold continuity. | Add a `performance` field per beat. Use beat windows for holds. Carry end positions into the next first frame. |
| FilmAgent (Xu et al., 2025) | Director, screenwriter, actor and cinematographer agents with Critique-Correct-Verify and Debate-Judge; actors placed at designated positions in each 3D place. GPT-4o in this setup beat single-agent o1. | Role-split agents with a shared position map; verify by code where possible. |
| MovieAgent (Wu et al., 2025) | Director → scene planner → shot planner, with chain-of-thought; the shot planner checks visual coherence across shots in a scene. | Plan top-down: what the scene is about, then shots. |
| HoloCine (2025), OneStory (2025) | Research models now generate several shots together for consistency. | Not usable with Veo today, but it confirms that shots must be planned as a sequence, not one by one. |
| Cemri et al., *Why Do Multi-Agent LLM Systems Fail?* (MAST, NeurIPS 2025) | Most failures come from system design and agents misaligned on the spec, not from the model. | Give every agent the same shared spec (the scene reading) and check outputs by code, not by more prompts. |
| Chakrabarty et al., *Art or Artifice?* (CHI 2024) | LLM stories pass 3–10× fewer creativity tests than experts', and LLM judges did not correlate with expert judges. | Use model critics to write notes, not to decide. Decide by code metrics and a person's A/B judgement. |
| Lu et al., *LLM Discussion* (2024) | Agents with distinct roles that diverge, then converge, are more original than one model. | Separate critics with different lenses, and offer 2–3 interpretations instead of one average plan. |
| Anthropic, *Building effective agents* | Evaluator-optimizer loops work when the criteria are clear; orchestrator-workers when subtasks vary. | Keep the bounded re-plan loop, with clearer, measurable criteria. |

## 4. The design

```
script blocks + story context
        │
        ▼
 ① SCENE READING (new, high)          what the scene is about: value start→end, units, turns, objectives (verbs),
        │                             subtext as behaviour, breath moments with reasons and priority, the ending image
        ├──────────────┐
        ▼              ▼
 ② STAGING (new)   kernel picture clock      where everyone is per block (zones, facing, frame side, props);
        │          + holds, turn timing      a person who changes zone with no move → a "move" bridge (implied, removable)
        ▼
 ③ SHOT PLANNER (changed)             plans by units and turns, with the reading and staging in hand
        │
        ▼
 ④ KERNEL FIT + CODE METRICS          crowded, overrun … + turn_unseen, teleport, line_crossed, breath_band, no_button
        │
        ▼
 ⑤ CRITIC PANEL (changed)             coverage · emotion · editor/continuity → notes → one re-plan → code picks
        │
        ▼  shot list (person approves)
 ⑥ INTENT + DoP (changed)             read the reading; write `performance` per beat; positions from staging
        │
        ▼
 ⑦ PROMPT                              expression + playable intention + voice tone per beat; start positions carried
```

**Rules that do not change:** no dialogue edits; no new people, lines or story events; a person's edits win; overruns
reported; rules fallback without a key; static prompt text first.

**What is new and allowed, all labelled and removable:**

- A **hold**: extra seconds on an existing moment (a smile fading, a look held). Not a new event.
- A **reaction** from a person who is already present when a line lands.
- A **move bridge**: walking from one named spot to another, when the staging needs it.

## 5. Phases

### Phase 1: the scene reading · fixes E1, E2, E6, E9

`src/libs/contracts/reading.py` (new, pure), `script_split/engine/reading.py` (new), `script_split/engine/pipeline.py`,
API `GET/PUT /scenes/{id}/reading`.

1. `SceneReading` (stored on the scene with `for_version` = script version, `by` = model | rules | person):
   - `about`: one sentence; `value`: `{start, end}` ("hope", "dread"); `tone`: an adjective pair.
   - `units`: `[{from_block, to_block, wants: {character: verb}, turn_block | null}]`. Verbs are playable, Weston-style
     ("to charm", "to hide", "to escape").
   - `subtext`: `[{block, who, behaviour}]`. Every STORY NOTE block is turned into visible behaviour, or marked
     "narration only" with a reason. Example: "He has no idea this will change his life" → "Kasun watches her go,
     still smiling, unaware".
   - `breath`: `[{after_block, kind: reaction|transition|atmosphere|button, who, seconds: 1–3, priority: 1–3, why}]`.
     `why` must name a turn, a unit or a subtext entry.
   - `ending`: the last image (a callback, a reveal, a held face).
2. Inputs: the full scene listing (STORY NOTEs included), episode synopsis, scene before and after, director's note,
   canon character summaries, and `craft/directing.md` + `editing.md` (static, cached).
3. Validation in code: blocks exist; `who` is present in the scene (speaks or is named in an action); at most one
   `button` per scene; at most one breath per block; priorities 1–3. Invalid entries are dropped, not repaired.
4. Rules fallback: turns are lines that follow a `with_line` reaction or a ring/arrival; the button is the last action
   block; no subtext; breath is one reaction (priority 1) at each turn.
5. A person can edit the reading (Director panel). A person's reading is never replaced; a script edit marks it stale.

Tests: Scene 2 (Episode 1) reads to value "joy → dread", a turn at the call, subtext on the closing note, a button on
Kasun watching her go. A fake model answer with a breath for an absent person is cleaned.

### Phase 2: the kernel gives feeling time · fixes E4, E5

`contracts/timing.py`, `contracts/shotplan.py`, `contracts/sceneplan.py`; interface `src/lib/veo/timing.ts` (parity).

1. `Item.hold_s` (from the reading's breath, 0 when none): extra seconds after the block, counted by the picture clock.
   A hold is time on an existing block, never a new block, so block numbers do not move.
2. A `with_line` block that the reading marks as a turn counts as `act` (1.5 s) instead of 0.5 s.
3. `TURN_GAP_S` (start 1.0 s) replaces `LINE_GAP_S` before a line that answers a turn. `TAIL_S` becomes the breath's
   seconds when a reaction hold follows the shot's last line.
4. `FittedShot.holds` (block, seconds, kind) so the beat windows and prompts can show them.
5. Parity cases in `tests/contracts/test_timing.py` and `timing.test.ts`. A scene with no reading times exactly as today.

### Phase 3: the planner plans by turns; silence is budgeted · fixes E1, E3

`script_split/engine/planner.py`, `critic.py`, `pipeline.py`.

1. The planner's user message gains the scene context (synopsis, before/after, note) and the reading
   (units, turns, breath, ending). `PLAN_SYSTEM` (static) gains: plan by units; every turn's reaction is seen, inside the
   shot (an OTS/TWO with the listener, or a hold at the end) or as its own shot when priority 1; end on the reading's
   ending image; prefer breath inside a shot over a separate 4 s cutaway.
2. Remove: "Silent shots are only for beats the script names", "When speech fills it, add no silent shots", and the
   critic's "Do not ask for a reaction … the script does not name". Replace with: "Breath comes only from the reading;
   never invent an event".
3. `fold_silent` → `fold_breath`: over the envelope, drop the lowest-priority breath first (priority 3, then 2), then
   fold silent shots that carry no breath. Priority 1 breath is never dropped by code; the envelope overrun is
   reported (as in plan 2026-11-01b D2) with "needs 42 s, 37 s without optional breath".
4. Score (`kernel_score`): replace `silent_s` as a cost with `breath_band` (seconds of reading-backed breath outside
   15–30% of the scene) and add `unearned_silent_s` (silent seconds no breath or action asks for). `SILENT_SHARE_MAX`
   applies to unearned silence only.

Tests: Scene 2 keeps a reaction at the call and the button; a talking-heads scene with no reading plans as today;
a plan that drops a priority-1 reaction loses to one that keeps it.

### Phase 4: staging and the teleport check · fixes C1, C2, C3

`contracts/staging.py` (extend), `contracts/bridges.py` (new kind), `script_split/engine/staging.py` (new).

1. `SceneStaging`: `zones` (3–6 named spots in the location, from the location canon card when there is one:
   "gate", "tea stall", "bench"), and per block per present person `{zone, facing, frame_side: left|right|centre,
   holding}`. Entrances and exits are zone changes to or from `off`.
2. One `medium` call per scene with the reading; validated in code: every present person has a zone on every block
   where they are seen; zones come from the list.
3. Code checks (kernel issues, free):
   - `teleport`: a person changes zone between two blocks with no `move` block between them.
   - `line_crossed`: two consecutive shots put the same two people on opposite frame sides with no `match` link or
     re-angle note (180° rule).
   - `eyeline`: in a shot/reverse pair, the two singles do not face opposite frame sides.
4. `move_bridge` (new bridge kind): "{who} crosses to the {zone}". Proposed by the staging agent, accepted only when
   code finds a `teleport` it fixes, and only for a person already present. `implied: true, by: staging`, `move` 2.5 s,
   shown with the "Implied" chip, removable, never re-added after removal (same rules as the phone bridges).
5. Rules fallback: no zones, no checks (absent-safe); phone bridges as today.

Tests: a fixture where Anudi is at the stall in block 3 and the gate in block 6 with no move gets `teleport` and one
`move_bridge`; removing it is remembered; a scene whose script already says "she walks to the gate" gets none.

### Phase 5: three critics, one judge · fixes E8

`script_split/engine/critic.py`.

1. Three `medium` reviewers in parallel, each with its own static prompt and the same reading and staging:
   - **Coverage**: today's checks (speaker in frame, sizes, WIDE, crowded).
   - **Emotion**: Murch order. Every turn has a reaction; the feeling moves (no two adjacent units with the same
     value); the ending lands; holds are where the reading put them.
   - **Editor/continuity**: cuts are motivated (on an action, on a look); screen direction and eyelines hold; rhythm
     varies (not all one length, not all one size); no `teleport`.
2. Notes are merged (at most six, by severity) for the one bounded re-plan. **The model critics never pick the plan.**
   Code picks by score: significant kernel issues, then `turn_unseen`, `teleport`, `line_crossed`, `no_button`, then
   `breath_band`, then over-envelope seconds.

Tests: a fake plan that drops the reaction at the call loses to one that keeps it, whatever the critics said.

### Phase 6: performance reaches the prompt · fixes E6, E7, C1, C3

`shot_producer/engine/intent.py`, `shots.py`, `serialize.py`, `continuity.py`, `schemas/clip_schema_veo_3_1.yaml`.

1. Intent agent reads the scene reading: `purpose` and `emotional_beat` come from the units and turns; it no longer
   invents them after the fact.
2. Clip schema: each beat gains `performance`: the visible expression and the playable intention, in one sentence
   ("Anudi keeps smiling a moment too long, then her eyes drop to the phone"). Never words, never an inner thought.
   Each subject gains `position` (zone + frame side + facing) from the staging.
3. `serialize`: the beat text carries performance and, for a line, a voice-tone cue from `delivery` and the reading
   ("softly, holding back"). The Veo guide's examples write emotion this way.
4. Continuity ledger: end positions per person carried to the next shot's `first_frame` ("Anudi at the gate, facing
   right, phone in her left hand").
5. Free checks: `performance_missing` on a turn beat; `position_jump` when a first frame contradicts the previous
   shot's end positions.

### Phase 7: interface · shows all of the above

`hiru-ai-studio-interface`: `src/lib/veo/timing.ts`, `src/features/scenes/*`, `src/features/director/*`,
`src/features/production/components/shot-intent-card.tsx`.

1. "The scene" card above the shot list: about, value start → end, turns, ending. Editable (a person's reading wins).
2. Breath on the shot timeline: holds as hatched segments with their kind and priority; a priority toggle per breath.
3. A small top-down staging map per scene (zones, people per shot); `teleport` / `line_crossed` as warning chips;
   move bridges with the "Implied" chip and remove.
4. Scene header: "Needs 42 s · 37 s without optional breath · envelope 35 s".

### Phase 8: eval and A/B with a person

1. `tests/eval/staging_scenes.json` gains scenes for: a turn broken by a call, an exit watched, a silent arrival,
   a person who crosses a yard unwritten, a closing story note. Metrics with floors: `turn_unseen = 0`,
   `teleport = 0`, `line_crossed = 0`, `button_present = 1`, `breath_band` within range on drama scenes,
   `inner_as_behaviour ≥ 0.8`.
2. A/B with the person on 3–5 Episode 1 scenes (current plan vs new), judged blind on Murch's order: does it make me
   feel something, is the story clear, does it flow, do I always know where everyone is. 1–5 each.
3. `pytest`, `ruff`, `mypy`; interface `npx next typegen && npm run check && npm run format:check`.

### Later (separate plans)

- **Interpretations:** two or three readings ("restrained", "heightened", "intimate") → three plans; the person picks
  on the existing options card.
- **Trims in the final cut:** the ffmpeg assembler can already probe takes and pull frames. Letting the cut trim a
  4 s take to 2–3 s would make short reaction cutaways affordable.
- **Frame-level continuity:** a vision check of each shot's last frame against the next shot's first frame
  (positions, wardrobe, props in hand).

## 6. Cost and latency

New calls per scene: the reading (high), staging (medium), two more critics (medium, in parallel with the first).
About 3 more calls per scene on a split, cached static prompts. Phases 1–3 alone add one call per scene. This stays
inside `TIME_BUDGET_S` with `PLAN_WORKERS = 4`; measure in Phase 8.

## 7. Decisions for the person

| # | Question | Recommendation |
|---|---|---|
| D1 | May the system add **holds** (more seconds on a moment the script has) and **reactions** of people already present? | Yes. Both come from the reading, are shown on the timeline and can be removed. |
| D2 | May the staging agent propose **move bridges** (a walk between named spots) when code finds a teleport? | Yes, accepted only when code confirms the teleport, labelled "Implied", removable, never re-added. |
| D3 | Breath target for drama scenes: 15–30% of the scene's seconds, priority 1 never dropped by code. | Start here; tune with the A/B. |
| D4 | With 60 s episodes, breath can push scenes over their envelope. | Report "needs X s, Y s without optional breath" and let the director choose, as in 2026-11-01b D2. |
| D5 | Scenes for the A/B. Approved scenes are never re-split. | Copy Episode 1 into a test production and re-split the copy, so approved frames stay linked. |
| D6 | Order. | Phases 1–3 first (the reading, timing, budgeted silence): most of the dryness. Then 4 (teleports), 5, 6, 7. |

## 8. Sources

- Murch, W. *In the Blink of an Eye* (1995/2001), Rule of Six: https://www.studiobinder.com/blog/walter-murch-rule-of-six/ ,
  https://nofilmschool.com/2016/11/6-rules-good-cutting-according-oscar-winning-editor-walter-murch
- McKee, R. *Story* (1997), the beat as action/reaction: https://en.wikipedia.org/wiki/Beat_(filmmaking)
- Weston, J. *Directing Actors* (1996), playable action verbs:
  https://scalar.usc.edu/works/experiments-in-game-based-pedagogy/directing-with-action-verbs-flat ,
  https://filmcourage.com/2022/06/15/why-result-direction-with-actors-doesnt-work-judith-weston/
- Kuleshov effect and reaction shots: https://www.studiobinder.com/blog/kuleshov-effect/
- Continuity editing (180°, eyeline, match on action, 30° rule; Bordwell, Staiger & Thompson):
  https://en.wikipedia.org/wiki/Continuity_editing
- Google Cloud, *Ultimate prompting guide for Veo 3.1*:
  https://cloud.google.com/blog/products/ai-machine-learning/ultimate-prompting-guide-for-veo-3-1
- Xu et al., *FilmAgent* (2025): https://arxiv.org/abs/2501.12909 , https://github.com/andyzlys/FilmAgent
- Wu, Zhu & Shou, *Automated Movie Generation via Multi-Agent CoT Planning* (MovieAgent, 2025):
  https://arxiv.org/abs/2503.07314
- Meng et al., *HoloCine* (2025): https://arxiv.org/abs/2510.20822 ; *OneStory* (2025): https://huggingface.co/papers/2512.07802
- Cemri et al., *Why Do Multi-Agent LLM Systems Fail?* (NeurIPS 2025): https://arxiv.org/abs/2503.13657
- Chakrabarty et al., *Art or Artifice?* (CHI 2024): https://arxiv.org/abs/2309.14556
- Lu et al., *LLM Discussion* (2024): https://arxiv.org/abs/2405.06373
- Anthropic, *Building effective agents* (2024): https://www.anthropic.com/research/building-effective-agents
- Studio craft notes: `src/knowledge_base/craft/directing.md`, `editing.md`
