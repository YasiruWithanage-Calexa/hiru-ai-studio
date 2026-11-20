# One video prompt agent writes every video prompt (plan/2026-11-20b)

Revision 1 (2026-11-20). Agreed with the person in chat on 2026-11-20. Building status: IMPLEMENTED.md (not yet).

Why: [findings/issues/2026-11-20/NATURAL-DIALOGUE.md](../../findings/issues/2026-11-20/NATURAL-DIALOGUE.md). Proof:
`lab/natural_dialogue` (2 takes, a scene not an interview) and `lab/video_prompt` (the agent on Api Denna E01-S04,
18 clips; four model runs; two Omni takes of clip 4A-2). Read `lab/video_prompt/README.md` first.

## 0. Rules for the chat that builds this

- **No paid call without the person's yes, each time** (model, image, video). Tests run with `OPENAI__API_KEY=` blank.
- **Only Shot Planner Raphael stays.** Do not build for Adam, David, Jonathan or DaVinci; ignore their test failures.
- **Never write or translate a spoken line.** The agent never sees a line it could change: code puts the exact words in.
- **Report an overrun, never trim.**
- **Both trees have uncommitted work.** Read `git diff` of a file before you edit it. Never stash; use a worktree to
  compare.
- **The lab is the reference.** `lab/video_prompt/system.md`, `cards/*.md` and `run.py` (brief, gates, assemble) were
  proved; port them, do not rewrite them from memory. Where this plan and the lab differ, this plan wins.

## 1. What the person asked for

1. **One video prompt agent** (no persona name) that writes the video prompt of **every** video shot: dialogue,
   phone, silent, reaction, insert, establishing.
2. **It replaces today's video prompt makers outright**: the code serializer's prose and the prompt writer's polish.
   **No fallback** to the old prompt.
3. **Model: gpt-6.1-sol, low reasoning** (chosen 2026-11-20 over gpt-6.1-terra low/medium and gpt-5-mini).
4. **Prompt versions already made stay as they are.** Only a new press writes with the agent.
5. **The prompt writer's video path is removed.** (Its first-frame path stays: it was not part of the question.)
6. The agent must get **the scene packet** (who each line is said to, its intent, the reader's delivery note, what
   each person wants and feels), **the look the scene uses** (the look sheets the take attaches) and **the
   carried-over / join facts** of the shot.

## 2. Decisions

| # | Decision | Why |
|---|---|---|
| D1 | New agent `video_prompter` (`libs/hiru_ai/agents/video_prompter/`) + new pure step `video_prompt` (`libs/hiru_ai/steps/video_prompt/`: brief, gates, assemble, checks). The agent writes **direction only**; the step owns every fact | The house pattern (model writes, code keeps facts and checks). Same split as the lab |
| D2 | New model tier `video_prompter` in `core/models.yaml`: `model_video_prompter` = `gpt-6.1-sol`, `effort_video_prompter` = `low`, timeout 120 s, retries 1, structured output | The lab's choice. A tier so the model can change by env (`OPENAI__MODEL_VIDEO_PROMPTER`) |
| D3 | **No fallback.** If the agent's answer fails the gates, ONE repair call with the faults. If that fails too, **no new prompt version** is written for that shot: the job adds a WARNING event naming the faults, and the shot keeps the prompt it had | The person: "straight use it, no need fallback". An old prompt must not come back silently under a new version number |
| D4 | No key, or models off (`llm.models_enabled()` false): the job writes **no** prompt and says "the video prompt agent needs a model" | Same as D3: no code-only prompt |
| D5 | **The scene packet is required.** Read with `ctx.ports.breakdown.packet(scene_id)` under the same rules as `breakdown_build.packet_for` (current `script_version`, no `waits`). No usable packet: no prompt for that scene's shots, with the reason as a WARNING ("the script changed after the breakdown: refresh the scene's breakdown") | The packet holds the addressee, intent and delivery note; without them the agent writes today's flat prompt again |
| D6 | A line row maps to its packet block **by script position**: scene script block *i* is packet `E_blocks[i]` (both made from the same script version; checked by D5) | How `lab/coverage` and `raphael_write` already pair them |
| D7 | **Which lines a clip speaks** = the shot's lines when its sound mode is `dialogue`, `voiceover` or `sung`; none otherwise. A line on an ambient/silent clip is given to the agent as "heard in the edit over this clip" (context for the faces) | Fixes today's fault: S05/S15 wrote speech into clips whose sound says nobody speaks |
| D8 | **The facts code writes, never the agent**: the opening-frame / carried-frame sentence, the Join sentence, each line's words (Sinhala as its own segment, the database's own quotes stripped once), the register line, "only these words are spoken", the Hands sentence (`contracts.holding`), clean frame + `on_screen_text.VIDEO`, the format. The "Image n" citations stay where they are: `video_gen.build_omni_input` at render | The lab's assembly, plus the product's carry/join rules (item 6 of §1) |
| D9 | **The agent keeps the planner's camera**: size, angle, lens and the ONE movement. A locked-off clip stays locked off (gate) | Raphael decides the camera; the agent directs the people |
| D10 | The prompt row keeps its shape (`sections`, `prose`, `checks`, `ir`, `camera`, `frame_id`, `pins`, `model`, `version`) and gains no column. New section ids: `opening`, `situation`, `people`, `action` (Action & dialogue), `camera`, `sound`, `rules`, `format`. The direction (to whom / how / listener per line) is readable in the `action` section | The render, the workspace pane, versions and stale reasons read these; no database change |
| D11 | A whole scene's shots are written **in order, one call each, with the same scene part first** (system + `<scene>` identical, so it caches). No parallel calls inside one scene | Cache (the lab cached ~1.5k of ~3.6k tokens; find out why in phase 1) and cost |
| D12 | The prompt writer's video path goes: `polish_video`, `POLISHABLE["video"]`, the `"video"` kind of its `Input`, the video words in its system prompt, `PROMPT_WRITER__ENABLED` stops meaning "video". First-frame polish (`frame_prompt` mode) stays | The person: remove it |
| D13 | `steps/serialize` stays (Raphael's write, the shot model, the design rows and the first frame use it). Only its job as the **video prompt writer** ends: `design.write_prompt` is no longer called by the job | Many things read it; its prose is what is replaced |
| D14 | The legacy engine (`services/shot_producer/shot_producer/engine/`, `AI_ENGINE=legacy`) is not changed. It is not deployed (`deploy-functions.yml`: `"ai":true`). Add one line to its module docstring: video prompts are written only by the graph engine | Out of scope; removed with the old planners later |
| D15 | Cost estimate row `prompt` in `contracts/costs.py`: $0.02 → **$0.01** (lab: sol $0.0093 a clip). No cost in the UI (CLAUDE.md rule) | The admin price list only |

## 3. The agent

`libs/hiru_ai/agents/video_prompter/`:

- `component.yaml`: `id: video_prompter`, `kind: agent`, `model: video_prompter` (tier), `shape: structured`,
  `phase: video_prompter.write`, middleware as `prompt_writer` (`static_first, usage, untrusted_text, absent_safe`),
  `writes_dialogue: false`.
- `prompts/system.md`: `lab/video_prompt/system.md`, with the "What you return" part matching §3's schema. Keep the
  hard rules (no Sinhala, no ids, no quotes, no invented people/objects/events/sounds/screen words, nobody speaks in a
  silent clip, safe depiction) and the planner's-decisions part (D9).
- `prompts/cards/{dialogue,phone,silent,detail,sinhala_voice}.md`: the lab's cards, unchanged. The step picks them
  (`cards_for`, from the lab).
- `schema.py`:
  ```python
  class Step(BaseModel):          # one beat of the clip, in order
      kind: Literal["action", "line"]
      text: str                   # action: what happens; line: ""
      line_id: str                # line: the brief's id (L4); action: ""
      to: str                     # line: who it is said to ("herself" when muttered)
      how: str                    # line: the delivery, a phrase
      listener: str               # line: what the listener does; "" when nobody else is there
  class Direction(BaseModel):     # the agent's answer (Output)
      situation: str; people: str; flow: list[Step]; camera: str; sound: str
  class Input(BaseModel):         # what the step built
      scene: str                  # the <scene> part: identical for every shot of the scene (cache prefix)
      clip: str                   # the <clip> part
      cards: str                  # the chosen cards
      repair: list[str] = []      # the faults of the first answer, on the repair call only
  ```
- `agent.py`: `user_message(inp)` = scene, then clip, then cards (that order: the cache prefix first); on a repair,
  the first answer and the faults follow, as in the lab. No `fallback()` that writes a prompt (D3): with no model the
  agent is not called (D4).
- `evals/cases.yaml`: E01-S04's 4A-1 (one line, two sentences), 4A-2 (exchange), 4E-2 (phone voice), 4H-1 (silent
  reaction), 4K-1 (insert): the briefs saved from the lab, with what a good answer must hold (each line once, `to` is
  the addressee, a listener on 4A-2, no speech verbs on 4H-1).

## 4. The step `video_prompt` (pure, no model)

`libs/hiru_ai/steps/video_prompt/` with `component.yaml`, `step.py` (`op`: `brief` | `check` | `assemble`),
`logic.py`, tests.

### 4.1 Brief

From the lab's `scene_brief` / `clip_brief`, built from product rows, not lab files:

| Part | From |
|---|---|
| Scene: title, summary, purpose, before / after, place, mood, people (presence, wants, feeling start → end), relationships, the production's direction lines, every block in order (line id, speaker → addressee, "through the phone", words, the reader's `delivery_hint`, `intent`) | the packet (D5, D6). The line ids are the scene's short ids L1…, the same in every shot's brief |
| Production genre and style note | `ProductionInput.genre`, `.style_note` |
| Clip: role, framing, angle, lens, movement, take seconds, why, the planner's summary | the shot row + its `ir` + `design` |
| Who is in frame, each with the scene's look (not the planner's clothes), position, action | `ShotInput.seen`, `ir.subjects`, `Context.wardrobe` (`wardrobe_by_code`, as the job builds it today) |
| Who is only heard and from where | `ShotInput.heard`, `staged.voice_source` |
| Hands | `ShotInput.hands` |
| The planner's beats and sound | `ir.beats`, the shot's sound card |
| Lines spoken in this clip, each with its seconds; speech against the take | D7; the measured clock of `lab/sinhala_pace` (start ~1 s, ~2.6 words/s, ~0.8 s between sentences), as in the lab |
| Lines heard in the edit over this clip | D7 |
| Opens on the accepted first frame / on the previous take's last frame; Join (continuous / matched re-angle / cut) and what is carried over | `frame_strategy`, `camera_link`, `carried_state` (as `design.write_prompt` builds them) |
| Pictures attached (opening frame; face and look sheet per person seen) | the same list `build_omni_input` will cite |

### 4.2 Gates (code, every answer)

The lab's `gates()`, with the fix it found:

- the flow's line ids are exactly the clip's spoken lines, each once, in script order; every line has a `how`
- no Sinhala letters, no line or block id, no quotation marks in any text the agent wrote
- a clip that speaks nothing has no speech verb (says, asks, tells, replies, whispers, shouts, speaks, talks, calls
  out, murmurs, answers)
- a heard-only person is not placed in frame (named **as heard** is fine: "Father (heard only, never in frame)")
- the camera keeps the planner's movement: a locked-off clip has no handheld / push-in / dolly / pan / tilt / zoom /
  tracking / drift / sway / creep
- no words the video models decline (`contracts.safe_depiction.blocking`)
- no notes to us inside the prompt: no "(…in the edit…)", "not spoken here", "the planner", "the brief" (new: gpt-5-mini
  did it in the lab)
- lengths: situation ≤ 450, people ≤ 650, camera ≤ 300, sound ≤ 250, each flow text ≤ 450 characters

### 4.3 Assemble

The lab's `assemble()` into **sections** (D10), with D8's code sentences. A line step becomes:
`{Speaker}, to {to}, {how}:` + the Sinhala segment + `{listener}.`; a heard line:
`{Speaker}'s voice through the phone, {how}:` + segment + "No one on screen mouths these words." + listener. The
register line follows the flow (on-screen speech, or the phone wording when only a heard voice speaks); a clip that
speaks nothing gets "Nobody speaks in this clip: no dialogue, no voice." No citations (render adds them).

### 4.4 Checks on the prompt row

Shown on the Video prompt pane as today: `Lines verbatim from the script` (the segments equal the line rows' words),
`Direction for every line`, `One visible speaker` / `2 speakers in one clip` (advisory, as today), `Heard only · X
(phone)`, `Voice pins for every speaker` (advisory, as today), speech against the take (`7.2 s of speech in a 6 s
take`, advisory: reported, never trimmed), `Repaired once` when the second answer was used, `Opens on the accepted
first frame` / `Starts on S03's last frame`.

## 5. Where it plugs in

`libs/hiru_ai/systems/shot_producer/graph.py`, mode `"prompt"` (today lines ~337–361):

```
for each scene:
    packet = packet_for(...)            # D5: none → WARNING for the scene, next scene
    scene_part = step brief(scene)      # once per scene
    for shot in wanted (in number order):
        frame check as today (no accepted frame and not carry_last_frame → skipped, as today)
        clip_part, cards = step brief(shot)
        answer = agents.build("video_prompter").run(Input(scene, clip, cards), ctx)
        faults = step check(answer) → if faults: one repair run → check again
        faults left → WARNING "S07: video prompt not written: …" ; continue        # D3
        row = step assemble(answer) + the row fields write_prompt sets today
        row["version"] = last + 1 ; scenes_port.add_prompt(row) ; PROGRESS "S07: prompt v3 written"
```

- `polish_mod.polish_video(...)` is removed from this loop (D12). `sz.write_prompt` is no longer called here (D13).
- Job events keep `agent=AGENT_PROMPT`; its label becomes "Video prompt".
- Usage is recorded by the agent middleware (`usage`), as for every agent.

## 6. Removed

| What | Where |
|---|---|
| `polish_video` | `libs/hiru_ai/systems/shot_producer/polish.py` |
| `POLISHABLE["video"]`, `Kind` "video" | `libs/contracts/prompt_polish.py` (+ tests) |
| `Input.kind` "video", `_FOR["video"]`, the video words in its prompt | `libs/hiru_ai/agents/prompt_writer/` (+ evals, tests) |
| The `shot_producer` system's dependency on `prompt_polish` for video | `component.yaml` of the system; `docs/AI_CATALOG.md` row |
| `PROMPT_WRITER__ENABLED` description "video and first frame" | settings docstring, `.env.example`: first frame only |

## 7. Interface

`hiru-ai-studio-interface`:

- `features/production/components/video-prompt-pane.tsx`: renders the new section ids (it already renders
  `sections` and Sinhala segments; check titles and order, `spoken()` for each line segment, no hard-coded
  `lang="si"`). Snapshot/unit test with a new-shape prompt.
- Job progress text: "Video prompt" instead of "Prompt writer" where the UI names it.
- The workspace's "Generate prompt" message when nothing was written: show the job's WARNING (packet missing, gates
  failed, no model) instead of a silent empty state.
- No cost anywhere (CLAUDE.md).

## 8. Phases

| Phase | What | Repo | Cost |
|---|---|---|---|
| 0 | Read-only: on one real production in the database, read a scene's `scene_packets` row and its lines; confirm block *i* = script block *i* and the line ids (D6); confirm `ctx.ports.breakdown` in the shot_producer job; find why only ~1.5k of the ~3.6k shared tokens were cached in the lab (prefix layout, `prompt_cache_key`) | backend | $0 |
| 1 | Agent `video_prompter` (prompt, cards, schema, agent.py, component.yaml, evals), model tier + settings | backend | $0 |
| 2 | Step `video_prompt` (brief, gates, assemble, checks) from the lab; tests on E01-S04 rows (fixtures saved from the lab), the S05/S15 ambient case, the phone case, a carried-over shot, a matched re-angle | backend | $0 |
| 3 | Wire into `graph.py` mode "prompt" (§5), D3/D4/D5 warnings; graph tests with fakes (agent stubbed) | backend | $0 |
| 4 | Remove the prompt writer's video path (§6); fix its tests; docs (`AI_CATALOG.md`, `AI_ARCHITECTURE.md`, `.env.example`), cost estimate row (D15), legacy docstring (D14) | backend | $0 |
| 5 | Interface (§7) and its tests | interface | $0 |
| 6 | Live: write the video prompts of one scene with the agent (~$0.17 for 18 clips), read them; render two of them at 360p (~$1.20 at most) | live | paid, the person's |

## 9. Not in this plan

- Raphael's one-speaker rule and exchanges in one clip ("will figure out later", the person).
- Raphael choosing locked-off for every clip (camera life).
- Editing the direction (to whom / how / listener) in the workspace.
- Voice pins for every speaker.
- The first-frame prompt.
- Removing the legacy engine.

## 10. Risks

- **The packet is stale or missing** on older productions → no prompts until the breakdown is refreshed (D5). The
  warning must say so plainly.
- **sol is down or slow** → no prompts (D3/D4). Retries 1, timeout 120 s; the job reports and moves on.
- **One take showed a caption** ("Colombo / Colomban") despite "no captions" (`lab/video_prompt`, sol 4A-2). Watch in
  phase 6; `on_screen_text.VIDEO` may invite lettering of a place name.
- **The gates are new**: a check that is too strict leaves shots with no prompt (the lab's heard-only rule did). Each
  gate needs a test with a good answer that passes.
