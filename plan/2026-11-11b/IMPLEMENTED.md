# Frame brief: what is built (plan/2026-11-11b)

Built offline on 2026-11-11, both repos, uncommitted. No model call, no image, $0 spent. Phase 5 (a richer `first_frame`
from the planners) and Phase 7 (the paid lab) are not built: they are the person's (§ "Open").

## Decisions as built

The person said "yes do it", then "implement it": the plan's recommendations were taken, with one change.

| | As built |
|---|---|
| D1 | Not reached (Phase 5 waits for the person's read of Phase 0) |
| D2 | Code assembles the brief; no model step |
| D3 | Lens and stop are written as what they look like ("a slightly long lens: gentle compression…", "shallow focus: …"); the numbers stay in the shot data and on the panel |
| D4 | The same-setup frame is attached automatically; a person can turn it off per shot |
| D5 | **Changed: the cap is 2,600, not 2,000.** Measured on Ekama run3: a Raphael shot is ~1,850–2,450 characters uncut. At 2,000 every mood and grade line would be cut, which is what the person asked for. Over the cap, cut in order: mood, the frame's second light line, the colour script's palette/grade. Never cut: references, shot, people, place and time, who is heard |
| D6 | Not reached (Phase 7) |
| D7 | The "no text, no watermark…" close is kept as it was |

## What changed

### Backend (`hiru-ai-studio`)

- **`src/libs/contracts/frame_brief.py` (new): the one builder.** `frame_brief(...)` → `FrameBrief` (sections, each part with its
  source, `.text()`, `.view()`, `.fit(cap)`); `frame_prompt(...)` is its text. Moved here from `contracts/producer.py`
  (which keeps a pointer comment). Sections in order: lead · references · shot · composition · people · place and time ·
  light · colour and grade · mood · heard-not-seen · close.
  - The fuller IR field wins over the short `first_frame` line; the frame line is added as "In this frame: …" only when it
    says something new.
  - `cinematography.white_balance`, `color_tone`, `depth_of_field`, `framing`, `angle` now reach the prompt; a field a
    person changed on the panel wins over the planner's words (`recommended` vs the camera as it stands).
  - Time of day and interior/exterior from the heading, always (found anywhere in it: "SCENE 02 - INT. …" works).
  - Weather only from words the IR or the clip's sound already use (rain, wet, mist, storm, wind); "no rain" is not rain.
  - People: the card's identity line, then the IR subject's own description (its dress only when no card wardrobe or look
    dresses them), then its position (screen side, which wrist).
  - The scene's treatment (Raphael scenes): the colour script entry of the shot's own sequence (clip slate → moment →
    sequence) and the moment's feeling, read from `scenes.raphael`.
  - Every attached picture is named in order AND given its job ("Take from image 1: Dinu's face and body, not its light
    or backdrop; image 2: the place and its fixtures, not its light or time of day; …").
  - `plan_references(...)`: the pictures in their fixed order (people seen, place, other place, props, same-setup frame),
    each with its role and (label, path) choices; `missing_references(...)` says what is wanted but has no picture.
  - `setup_frame(...)`: for slate "2B-2", the first earlier shot of setup "2B" with an accepted final frame.
  - `nearest_option(...)`: the panel's nearest lens/stop. `expected_frame(...)`: the vision check now also expects the
    time and the weather. `opens_line` moved here from the `frame_compose` step so the API can use it.
- `contracts/producer.py`: `PersonEdits.setup_frame_off` (a person's mark; dumped only when set).
- `steps/frame_compose/logic.py`: `World` takes `shots` and `accepted`; `reference_choices` comes from
  `plan_references` (with `role` and `bucket`); `brief()`/`compose()` use `frame_brief`; `expected()` uses `expected_frame`.
- `systems/frame_render/graph.py`: loads the scene's shots and their accepted finals once per scene; downloads a
  same-setup frame from the `frames` bucket; `reference_ids` (uuid[] of canon entities) never holds the frame id.
- `core/ports.py` `FrameStore.accepted_finals`, with `adapters/supabase_rest.py` and `core/fakes.py`.
- Legacy `services/frame_render`: the same brief, reference plan and same-setup frame (`Store.shots`,
  `Store.accepted_finals`), so the parity tests still compare like with like.
- `camera_hint` (Raphael, Jonathan, David): the nearest panel lens and stop instead of nothing (65mm → 50mm).
- API (`api/routers/production.py`): the shot's `frame_prompt` is now built exactly as the renderer builds it (same
  pictures and order, looks, hands, opening state); new `frame_brief`, `frame_references`, `frame_missing`,
  `setup_frame_off`; `PUT /v1/productions/{id}/shots/{shot_id}/setup-frame {off}` (GENERATE, refused on an approved
  scene, audited as `shot.setup_frame`).
- `lab/frame_brief/compare.py` + `expect_ekama.json` (Phase 0): old and new prompts side by side for every clip of a
  Raphael run. The old builder is copied word for word from a8feb50.

### Interface (`hiru-ai-studio-interface`)

- `FirstFramePrompt`: the dialog now shows the pictures (numbered as attached, role chip, what each gives, missing ones
  in amber), the brief by section, the whole text to copy, and the "Match the setup's first accepted frame" switch
  (writes through `setSetupFrame`, answer into the cache with `applyShot`). A chip beside the button says how many
  pictures are missing.
- `ShotProduction` gains `frameBrief`, `frameReferences`, `frameMissing`, `setupFrameOff` (mapped in `map-scene.ts`).

## Phase 0 result (Ekama run3, $0)

`python lab/frame_brief/compare.py` → `lab/frame_brief/runs/ekama_run3.md`. All 60 clips of the three scenes:

- Facts the planner wrote that reach the prompt: **old 0–1 of 5–11 per clip, new all of them** (white balance, colour tone,
  the fuller light, time, weather, each seen person's position; and night / rain / 4300K / the red thread on the left
  wrist / right-hand drive on the S02 shots in `expect_ekama.json`).
- Length: old ~1,090 characters on average, new ~2,010; nothing had to be cut at 2,600.

## Checks

- Backend: `ruff check src tests scripts`, `mypy`, `hiru_ai validate`, `hiru_ai catalog --check`, `pytest -q`: see the
  last section for what failed before this work and still fails.
- New tests: `tests/contracts/test_frame_brief.py` (17), two API tests in `tests/api/test_production.py`, two
  graph-vs-legacy parity tests in `tests/hiru_ai/test_frame_render_system.py`. The frame_render parity fixtures were
  re-recorded (`python -m tests.parity.record frame_render`): only prompt text changed, plus `reference_sheet.json`,
  which was already stale before this work (the sheet prompt's gender wording from 4c1f21b).
- Interface: `npx next typegen`, `npm run lint`, `npm run typecheck`, the new `first-frame-prompt.test.tsx` (4).

## Open (the person's)

- **Read `lab/frame_brief/runs/ekama_run3.md`** and say whether Phase 5 (richer `first_frame` fields from the planners)
  is still wanted, and D1 (shared schema or Raphael only).
- **Phase 7**, the paid lab (≤ $1.50, gpt-image-2): needs a yes before any image is made.
- The Jonathan/David scenes get every section except the treatment's colour script and mood (their stored plans are not
  read yet).
- Same-setup frames come from Raphael's slates only; other planners write none.
- The key image is not used: nothing says which shot carries it.
