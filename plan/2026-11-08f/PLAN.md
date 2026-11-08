# Raphael's cost and length (plan/2026-11-08f)

The 2026-11-08 build of production `bf459277…` (3 scenes, Raphael at gpt-5 high) cost **$3.92** of model tokens. The
person's acceptable cost is **about $0.30 a scene**. This plan says why it cost that, what was fixed (built offline,
2026-11-08, uncommitted) and what is left for the person.

## Findings (from `token_usage` and `scenes.raphael`, read only)

| Scene | Target | Script's own time | Bin | Stage 1 | Cost (est.) |
|---|---|---|---|---|---|
| 1 Aruni Finds Nimal's Body | 60 s | 26 s | 26 s, 4 clips | 20 of 20 turns, **stopped** | ~$1.5 |
| 2 Mudalali Orders Old Port Route | 90 s | 23 s | 60 s, 8 clips | 20 of 20 turns, **stopped** | ~$1.5 |
| 3 Nimal Gives Dinu C-17 Key | 120 s | 24 s | 180 s, 26 clips | 4 + 4 turns, finished | ~$0.75 |

1. **A check no bin could pass.** Scene 1's b0 ("Heavy rain. Aruni walks…", six sentences) is read as `move` × 6 = 15 s;
   scene 2's b0 as `move` × 4 = 10 s. No take is longer than 8 s, a clip covers whole blocks, and every clip over the
   block was checked against all of it, with no "report" way out for a silent action (a line has one). Raphael tried
   handles and takes for 20 turns. About $3 of the $3.92.
2. **Every turn re-reasoned from zero.** The product ran Chat Completions, so reasoning was not carried between turns
   (the lab used `previous_response_id`). Product later turns averaged ~5k reasoning tokens; the lab's fell to 0.1–3.6k.
3. **Nothing checked a bin under its length.** Only the 1.5× cap was checked. Scenes 1 and 2 ended at 43 % and 67 % of
   their target; a stopped stage 1 also skips the cinematic pass.
4. **The lab's real per-scene cost was $0.58–0.73**, not $0.32–0.46: those figures are stage 1 only; stage 2 added
   $0.26–0.27. Scene 3 ($0.75) matches the lab. $0.30 needs phase 3, not only the bug fix.
5. **No model reading in Raphael's build.** The Raphael pipeline (canon → structure → `plan_scene_raphael`) skips
   `script_split`, the step whose model reads each scene (events, breaths, implied steps). `scenes.reading` is `{}` for
   all three; the free rules (`contracts.beats.read_block`) time the whole block as `move` (2.5 s) for EVERY sentence
   once one sentence has a move verb, and add no breaths. Shared with Adam, David and Jonathan's pipelines.

## What was built (offline; no model called)

| § | Fix | Where |
|---|---|---|
| 1 | An action longer than any take is shown over consecutive must clips: a clip over it shows a PART (≥ 1.5 s); `long_action` checks the must clips' parts add up to the action. The old check was strictly harder, so no stored bin newly fails. | `contracts/raphael/checks.py` (`clock`, `part_s`, `long_action`), `scene.py` (`long_actions`, `parts_needed`) |
| 2 | The listing gives every action its seconds and marks a long one ("15.0 s on screen, longer than any take: show it over 3 consecutive clips"); errors name the seconds. | `contracts/raphael/scene.py` `listing` |
| 3 | A must bin under 80 % of the target cannot finish (`length:short`, stage 1 only); the `<length>` block says what the script times at and that the rest is coverage. Three prompt lines (FLOOR, COVERAGE, LONG ACTIONS); the parity test allows exactly those. | `checks.short`, `pack.length_block`, `raphael_planner/prompts/system.md`, `tests/raphael/test_lab_parity.py` |
| 4 | A stuck scene stops (4 reports without fewer blocking faults, counted only once every block has its must clip) as `stuck`, keeping its clips. Turn caps 20 → 10 and 12 → 8. A per-scene money limit, `RAPHAEL_SCENE_CAP_USD` (default $1.00), replaces the lab's $5. | `contracts/raphael/tools.py`, `systems/raphael/…/scene.py`, `core/settings.py` |
| 5 | Raphael's tiers use the Responses API with `previous_response_id` (`responses: true` in `models.yaml`), as the lab did. `Agent.converse(later_tier=…)` answers turns after the first on a repair tier; the cinematic pass has its own tier. New settings `OPENAI__EFFORT_RAPHAEL_REPAIR`, `OPENAI__MODEL_RAPHAEL_CINEMATIC`, `OPENAI__EFFORT_RAPHAEL_CINEMATIC`, `OPENAI__EFFORT_RAPHAEL_CINEMATIC_REPAIR`, all defaulting to gpt-5 high (unchanged quality until the lab). | `core/models.yaml`, `core/models.py`, `core/llm.py`, `core/agents.py`, the two agents |
| 6 | Each scene's calls carry its `scene_id` (written once `USAGE_SCENE=true`, schema v17). | `systems/raphael/…/graph.py` |

Proof, offline, on the three scenes' saved bins: scene 1 now gets two errors it can fix (b0 needs 7 s more; the bin is
under 48 s) instead of one it could not; with b0 over three 8 s clips its clock passes. Scene 2 passes whole with b0
over three clips. Scene 3 passes unchanged. Tests: `tests/raphael/test_cost_fixes.py`,
`tests/raphael/test_responses_api.py` (the real `ChatOpenAI` on a mock transport: the second turn sends
`previous_response_id` and only the tool result; the repair turn sends the lower effort).

## Open: the person's

- **The cost lab** (~$3 hard budget, after the person's yes): scenes 1–3 again with phase 1–5 on, then the cinematic
  pass on `gpt-5-mini` and repair turns at `low`/`medium`. It decides the defaults of §5 and whether $1.00 per scene
  becomes ~$0.40. Estimates, unmeasured: phases 1–4 → ~$0.70 a scene; + cheaper cinematic → $0.35–0.45; + low-effort
  repairs → $0.25–0.35.
- **The Responses API in the live product** has only been tested on a mock transport. OpenAI stores responses (needed
  for `previous_response_id`); confirm that is acceptable.
- **Finding 5** (no model reading, the `move` overcount): a change to shared timing or to the build pipeline, for all
  planners. Not changed here.
- **`USAGE_SCENE`** needs schema v17 applied before it is turned on.

## Lab, arm C (2026-11-08, the person's yes): Sol turn 1, Terra for repairs and the cinematic pass

The product planner on the three scenes, read-only (nothing written back), $1 per scene limit. Script:
the session scratchpad's `lab_c.py`; results `lab_c/scene{1,2,3}.json`.

| Scene | Result | Turns | Takes (must + cinematic) | Cost |
|---|---|---|---|---|
| 1 | finished / finished | 8 + 3 | 56 + 26 = 82 s of 60 s target | $0.16 |
| 2 | **stuck** after 10 turns, stage 2 skipped | 10 | 88 s must of 90 s | $0.15 |
| 3 | finished / finished | 5 + 3 | 120 + 42 = 162 s of 120 s | $0.18 |
| | | | **total** | **$0.49** (was $3.92) |

- The model switch mid-conversation (Sol → Terra with `previous_response_id`) worked; reasoning stayed small
  (Sol turn 1: 516-1034 reasoning tokens; gpt-5 high used 6-14k).
- Sol's one turn writes only the intended cut (1.8-2.4k tokens out); **Terra writes every clip**.
- Scene 2's stop: L1 is Aruni's voice message ("Aruni's voice message plays" in the action before), but the line has no
  V.O./phone mark, so `coverage` asks a must clip to perform it and Raphael (rightly) never shows Aruni. The stuck rule
  ended it at $0.15. A script mark (V.O.) or detecting "voice message" before a line would fix it.
- Quality, a first look (the person's read decides): mostly `locked_off`; scene 1's five must clips over the 15 s walk
  repeat the same middle beat rather than each taking the NEXT part (the long-action check counts angles of one part as
  parts: a known limit, no part field on a clip). Cinematic pass: insert + rack focus, POV, drone, atmosphere.
- Cache writes are not in these figures (Terra $1.25 / 1M tokens written); small next to output.

## Lab, arm B (2026-11-08): Sol writes the cut AND the clips (both stages), Terra only repairs

Plus the voice-message fix (`contracts.raphael.scene.mark_recorded`: a line the action just before calls the speaker's
voice message / voice note / recording is heard, not performed). Scenes 1 and 2, read-only, `lab_b/`.

| Scene | Result | Turns | Takes (must + cinematic) | Cost | Arm C |
|---|---|---|---|---|---|
| 1 | finished / finished | 5 + 3 | 66 + 38 = 104 s of 60 s | $0.25 | $0.16 |
| 2 | finished / finished | 5 + 3 | 94 + 40 = 134 s of 90 s | $0.22 | $0.15, stuck |
| | | | **total** | **$0.47** | |

- Sol splits the 15 s walk into real consecutive parts ("b0 part 1, action seconds 0-5", "part 2, 5-10", "part 3,
  10-15"); Terra (arm C) repeated one beat over five clips.
- More technique: dolly in, drone pull-away, slow creep, rack focus, foreground framing (arm C: mostly locked off).
  Must clips are still mostly locked off.
- Scene 2: Aruni's message plays over Dinu, no clip performs it; the dashboard photo's people are kept unreadable.
- Labs today: $0.49 (C) + $0.47 (B) = $0.96.
