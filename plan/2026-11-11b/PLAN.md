# Frame brief: the first frame gets everything the planner already wrote (plan/2026-11-11b)

Revision 2 (2026-11-11, evening). Phases 0, 1, 2, 3, 4 and 6 are built offline, both repos, uncommitted: see
[IMPLEMENTED.md](IMPLEMENTED.md), which also records one change to the design (D5: the cap is 2,600, measured). Phase 5
waits for the person's read of Phase 0's side-by-side; Phase 7 is a paid lab the person starts.
**New chat picking this up: read IMPLEMENTED.md, then §1, §3 and §5.**

The person asked (2026-11-11), looking at E01-S02 shot 6 of Ekama Sakshiya: Raphael writes a lot of information for each
shot, but the first-frame prompt is "a very simple basic prompt". It needs reference-image mapping, correct light,
framing, mood, environment, vibe and colour temperature. Then: look at PromptMotion's image prompting and take what
is useful.

## 1. What we found

### 1.1 The prompt the person saw

```
Photorealistic still frame from a Sri Lankan television drama, shot on a cinema camera with real optics and natural
imperfections. Camera: Medium close-up, eye level, 50mm lens at f/2.8, shallow depth of field. Locked-off, no camera
movement. Tight 3/4 on Dinu, eyes near upper third; windscreen glow behind. Dinu listening, hands unseen but steady on
the wheel. People: Dinu. Setting: Cab interior moving through wet streets. Lighting: Soft top-front spill keys his face,
with gentle dashboard fill in the eyes. Aruni is not in this place and not in the frame (heard from off screen). The
people, place and everyday details are Sri Lankan. 16:9 framing. A single still frame: no text, no watermark, no
captions, no collage, no split panels.
```

That text is not in `lab/two_memories/runs/pipeline_ekama_run3/12_raphael/E01-S02.json`. The shot in the database came
from another Raphael run. The structure is the same, so run3 is used below as the worked example (clip c06, slate 2B-2).

### 1.2 What Raphael writes for one shot (run3, c06 / 2B-2)

| Where | What it says |
|---|---|
| `ir.cinematography` | camera "braced handheld, 65mm, f/2.8"; angle "passenger-side profile at eye level"; framing "MCU of Dinu's profile and upper shoulders"; movement "restrained handheld drift"; **white_balance "4300K mixed night practicals"**; **color_tone "cold blue and green shadows with restrained sodium orange highlights"**; **depth_of_field "shallow; wet street lights form crowded soft points"**; lens_artifacts |
| `ir.setting` | "Inside a right-hand-drive cash van moving through rain-lit Colombo **at night**." |
| `ir.lighting` | "Passing sodium lamps and headlights filter through rain, with dim green-blue dashboard practicals lighting the cab." |
| `ir.subjects[]` | "Dinu, 30, a Sri Lankan cash-transport driver in a plain charcoal work shirt"; position "right-hand driver's seat, frame right facing the windshield; **red thread around left wrist**" |
| `ir.first_frame` | 4 short fields: composition, subjects, setting, lighting |
| `sound` | "Rain and enclosed vehicle rumble", "Regular wipers" |
| `edit.treatment` (scene) | `colour_script` per sequence (palette, light, grade), `key_image`, `geography` (right-hand drive, camera stays on the passenger side), `approach` |
| `edit.moments[]` | `feeling` per moment ("Private unease") |
| clip | `setup` letter (B: 2B-1, 2B-2, 2B-3 are one setup), `anchor` (c16 anchors c05, c06) |

### 1.3 What `frame_prompt()` uses (`src/libs/contracts/producer.py:475`)

| Prompt part | Source | What is lost |
|---|---|---|
| Camera | `CameraSettings`: the panel's options only (28/35/50/85mm; Static/Dolly/Pan/Handheld). `camera_hint()` (`steps/jonathan/jonathan_write/logic.py:75`, used by Raphael) copies a value only on an **exact** match, so 65mm is dropped and MCU's default 50mm stands | The planner's lens, and every other `cinematography` field |
| Composition / subjects / setting / lighting | `ir.first_frame` first; `ir.setting` / `ir.lighting` only when the frame field is empty | The fuller setting and light lose to the short frame line ("Cab interior moving through wet streets") |
| White balance, colour tone, depth of field | not read | 4300K, the palette, the grade |
| Time of day, weather | not read | **"night" is not in the prompt.** Rain is not either |
| People | `identity_line()` from the cast card | `subjects[].description` and `position` (shirt, red thread, which wrist). On Ekama Dinu's card has no appearance, so the line is "People: Dinu." |
| Scene treatment | not read | colour script, key image, geography, the moment's feeling |
| References | the sheets of who is seen, the place, held props (`contracts/holding.references_for`) | No continuity frame. Each label has no "take this, ignore that" |

Two more faults:

- **The prompt on the shot screen is not the prompt that is painted.** `api/routers/production.py:387` calls
  `frame_prompt()` with no `references` and no `hands`. The renderer (`services/frame_render/.../pipeline.py:237`,
  `steps/frame_compose/logic.py:159`) passes both. The person reviews a different text and never sees the reference
  mapping.
- A missing sheet (no sheet for Dinu, no plate for the van) is skipped quietly. The prompt then has no reference line,
  and nothing on screen says why.

### 1.4 What PromptMotion offers

Hiru's `frame_prompt()` is a port of PromptMotion's **Nova** builder
(`nova_producer/engine/serialize.py:770`), which is just as thin. The richer work is in PromptMotion's older movie
engine and its media contract.

Take:

1. **The first-frame field set** (`pm_contract/prompt_schema/first_frame_schema.yaml`): light (main and second source,
   quality, colour temperature, shadow direction, mood), colour grade (palette, saturation, contrast, highlight and
   shadow colour, overall temperature), composition (rule, subject position, leading lines, negative space, foreground),
   environment (background, props, atmosphere), camera (focal point, depth of field, bokeh).
2. **Prompt order and wording** (`build_nano_first_frame_prompt`, `pm_contract/veo_prompt.py:602`, and
   `docs/engines/nano-banana-prompting-guide.md`): a strong verb first; subject, action, place, composition, style;
   narrative sentences, not tag lists; named materials and textures; describe what is there, not what is absent.
   That guide is Google's, for Nano Banana. Hiru paints with **gpt-image-2**. The ordering and narrative style are
   expected to carry over; Phase 7 measures it.
3. **Reference rules** (`libs/contracts/media.py:545`, `_asset_block`): every attached image is named in the prompt
   (an uncited image still steers the frame, with no instruction); names are plain labels, never ids (models paint
   id-like strings as lettering); order is fixed across shots; each image says what stays the same.
4. **How a shot joins the last** (`camera_link` cut / continuous / match, `match_of`, `nova_production.py:826`;
   `docs/frame-continuity/`): a *match* shot is shown the earlier shot of the same setup. This is Raphael's setup letter.
5. **Lens numbers become lettering** (`_movement_phrase`): "Arri Alexa LF, 50mm, f/4.0" was painted into storyboard
   images. Describe the visible effect instead.
6. **One look line in every frame** (`treatment.visual_language`), and the `prompt_fragment` vocabulary in
   `pm_contract/cinematography/{lighting,color}.yaml` as fallback wording.
7. **Wardrobe before hair** when an identity line is trimmed: the outfit is what keeps a face matched.
8. **Prompt hygiene** (`docs/engines/prompt-hygiene.md`) for any charter change: code first, one principle line, no
   words from the incident in the prompt.

Leave: the old schema's `negative_prompt` list (PromptMotion's own guide dropped it), style presets named after
directors and studios, the social-media `image_scenarios`, and the Nova builder we already have.

## 2. Goal

The first frame is painted from **everything the planner already decided**, in a fixed order, with every reference
image named and given a job, and the person sees exactly that prompt before anything is billed.

Not goals: a new model call to write prose (code assembles it; §3 D2); changing what Raphael plans; trimming dialogue.

## 3. Decisions

Taken (2026-11-11, the person: "yes do it"):

- **T1. Build it.** Write the brief in code first. The richer Raphael `first_frame` (Phase 5) comes after the code-only
  brief has been read on Ekama, so its value is measured, not assumed.

Open, with a recommendation:

| | Question | Recommendation |
|---|---|---|
| D1 | Phase 5's richer `first_frame`: in the shared clip schema (DoP, Jonathan, David, Raphael all fill it) or Raphael only? | Shared. One schema, one prompt builder; the old fields stay so stored shots still render |
| D2 | Code-assembled brief, or a small model step that rewrites it as prose? | Code. Free, the same every time, testable offline. Revisit only if Phase 7 shows the sectioned text paints worse |
| D3 | Lens and stop in the prompt as numbers, or as their visible effect? | Effect in the prompt ("face sharp, the street lights behind melt into soft round points"); numbers stay in the shot data and on the panel |
| D4 | Same-setup frame: attached automatically, or only when ticked? | Automatic once that frame is accepted; the person can untick it per shot |
| D5 | Prompt length cap | 2,000 characters, enforced by a test; cut order in §4.2 |
| D6 | Phase 7 lab budget | Hard cap $1.50 (§5, Phase 7) |
| D7 | The fixed "no text, no watermark…" line: keep as a negative, or rephrase positively? | Keep it until Phase 7 tests it; gpt-image may need the explicit ban |

## 4. Design

### 4.1 One builder, two callers

`contracts/producer.py` gets `frame_brief(...) -> FrameBrief` (a small model of named sections plus the reference
plan) and `frame_prompt()` becomes `frame_brief(...).text()`. Both the shot screen (`api/routers/production.py`) and
the renderer (`frame_render` pipeline, `steps/frame_compose`) call the same function with the **same reference plan**.
The screen gets the plan without downloading any image (`references_for` already works on rows; only the download
moves out).

`FrameBrief` holds what it read, by section, with where each piece came from (`ir.lighting`, `treatment.colour_script
S2`, `ledger`). The shot screen can then show the sections, and a test can check that a known fact reached the text.

### 4.2 The sections, in order

Each section is one or two sentences. Empty sections are left out. Source order inside a section: the person's own edit,
then the fuller IR field, then `first_frame`, then the rule-based default.

1. **Lead.** "Photorealistic still frame from a Sri Lankan television drama, shot on a cinema camera with real optics
   and natural imperfections." (unchanged: it is the strong-verb opening already)
2. **References.** §4.3.
3. **Shot.** Size, angle, side of the axis; the move as a still ("handheld, a slight off-level drift"); depth of field
   as its effect (D3). From `cinematography.{framing,angle,movement,depth_of_field}` with `CameraSettings` where the
   person changed it.
4. **Composition.** `first_frame.composition`; then what is in front, at the subject, and behind (Phase 5 fields, or
   `first_frame.composition` alone until then); eyeline and screen side from `subjects[].position`.
5. **People.** Per person seen: identity (card), wardrobe (look or card or `subjects[].description`, wardrobe kept
   before hair when cut), position and posture (`subjects[].position`, the scene state ledger), hands (`hands_for`),
   expression (`first_frame.subjects`, the first beat's `performance`).
6. **Place and time.** `ir.setting` (fuller wins), the scene heading's interior/exterior and **time of day** (always
   stated), weather and atmosphere (from the setting, the lighting and `sound.ambience` words such as rain or wind,
   never invented).
7. **Light.** `ir.lighting` (fuller wins), `first_frame.lighting` when it adds what this frame shows, and
   **`cinematography.white_balance`** as the colour temperature.
8. **Colour and grade.** `cinematography.color_tone`, then the treatment's `colour_script` entry for the shot's
   sequence (`moment → sequence`). The palette and grade are written once per sequence, so every frame of a sequence
   gets the same words.
9. **Mood.** The moment's `feeling` and, on the shot that carries it, the `key_image`. One line.
10. **Unseen.** `unseen_sentence()` (unchanged).
11. **Fixed close.** Sri Lankan people and place; aspect ratio; single still, no lettering (D7).

Cut order when over the cap (D5): mood, then composition layers, then the second light sentence, then the grade's
second half. Never: references, people, time of day, unseen.

### 4.3 References: role, label, job

`references_for()` keeps choosing **which** images. Each one now also carries a **role** and the label says its job:

| Role | Label in the prompt |
|---|---|
| look / character sheet | "image 1 is Dinu's look sheet: take his face, hair, build, skin tone and clothes; ignore its light and backdrop" |
| location plate | "image 2 is the location plate for the cash van: take the place and its fixtures; the light and time come from this prompt" |
| prop sheet | "image 3 is the reference sheet for the faded photograph: reproduce it exactly where it appears" |
| same-setup frame (§4.4) | "image 4 is the accepted frame of shot 2B-1, the same camera setup: match its framing, light and grade; the pose and expression come from this prompt" |
| approved draft | unchanged |

Rules (from PromptMotion §1.4 item 3):

- Fixed order: people seen (in `on_screen` order), the place, other places, props, then the same-setup frame.
- Plain names, never ids or paths.
- A test asserts the images attached are exactly the images named, in the same order.
- `MAX_REFERENCES = 6` stays. When over, the same-setup frame drops before a prop, never before a person.
- A reference the plan wanted but could not attach (no sheet, unreadable) is listed in `FrameBrief.missing`, and the
  shot screen shows it ("No sheet for Dinu: his face is painted from words only").

### 4.4 Same-setup continuity

- Raphael's `setup` letter and slate are already in the clip. Store `setup` on the shot (`design.setup`, no schema
  change: `design` is JSON).
- For a shot whose setup has an earlier shot with an **accepted final** frame, attach that frame (D4).
- Other planners have no setup letter; nothing changes for them.
- Later, not in this plan: a "continuous" join that reuses the previous clip's last video frame (PromptMotion
  `docs/frame-continuity/`).

### 4.5 Camera

`camera_hint()` maps to the **nearest** panel lens (65mm → 50mm or 85mm by distance; a tie goes longer) instead of
dropping it. The brief's Shot section uses the planner's own words where they are more exact than the panel (D3). A
person's camera change still wins over both.

### 4.6 Vision check

`expected()` (`frame_render/engine/pipeline.py`) reads the same brief, so the checker also asks for night, rain and the
thread on the left wrist, not only who is in frame.

## 5. Phases

| # | What | Where | Cost |
|---|---|---|---|
| 0 | **Side-by-side harness.** `lab/frame_brief/compare.py` reads a Raphael run (run3's 20 clips, the person's DB shot if exported) and writes old prompt, new prompt and the brief's sections to `lab/frame_brief/runs/<name>.md`. Fails if a fact listed in a per-clip `expect` file is missing (night, rain, 4300K, red thread on left wrist) | backend lab | $0 |
| 1 | **`frame_brief()`** with §4.2 sections and source order, `frame_prompt()` as its text; length cap test (D5); tests per section, including a shot with an empty IR and a pre-plan shot (old stored IR still renders) | `contracts/producer.py`, tests | $0 |
| 2 | **References with roles** (§4.3): role + job labels, fixed order, attached == named test, `missing` list; the shot screen and the renderer share one reference plan | `contracts/holding.py`, `contracts/producer.py`, `frame_render` pipeline, `steps/frame_compose`, `api/routers/production.py` | $0 |
| 3 | **Same-setup frame** (§4.4): `design.setup` from Raphael; attach the accepted frame; untick per shot (a `frame_refs_off` list in the shot's person edits) | `steps/raphael/raphael_write`, `frame_render` pipeline, API | $0 |
| 4 | **Nearest lens** in `camera_hint()` (both copies) and the Shot section's planner words (§4.5); vision check reads the brief (§4.6) | `steps/jonathan/jonathan_write`, `steps/david/david_write`, `frame_render/engine` | $0 |
| 5 | **Richer `first_frame`** (D1): add `foreground`, `background`, `eyeline`, `key_light` (direction and source), `practicals` (light sources seen in frame), `materials` (fabrics and surfaces that matter in this frame). Short strings, all required, "" allowed. One principle line in each planner's charter, per prompt hygiene. Update eval cases. Measure the token change on Ekama with the offline token counter before any live run | `steps/serialize/schemas/clip_schema_veo_3_1.yaml` (and the `shot_producer` copy), planner charters, evals | $0 offline |
| 6 | **Interface.** The shot screen's frame prompt shows the brief by section, the reference list with each image's job, and any missing reference. No costs on screen | interface repo: shot workspace frame panel, `features/scenes` types | $0 |
| 7 | **Lab (the person starts it).** Ekama S02: 6 shots (2B-1, 2B-2, 2C-2, 2D-1 insert, 2E-1, 2A-2), old prompt vs new, gpt-image-2 medium, same references. Blind read by the person. Hard cap D6 ($1.50; about 12 frames at ~$0.08 plus reference input) | `lab/frame_brief/paint.py` | ≤ $1.50 |

Order: 0 → 1 → 2 → 6 can ship as one piece. 3 and 4 are independent. 5 waits for the person's read of Phase 0's
side-by-side (T1). 7 waits for the person's yes.

Checks before finishing any phase: `ruff check src tests scripts`, `mypy`, `scripts/lint_imports.py`,
`hiru_ai validate`, `hiru_ai catalog --check`, `pytest -q` (with `OPENAI__API_KEY=` blank); interface: `npx next typegen
&& npm run check && npm run format:check`.

## 6. Risks

| Risk | Answer |
|---|---|
| A longer prompt paints worse on gpt-image-2 | D5 cap; Phase 7 compares directly; the cut order keeps the facts that matter |
| A location plate's light overrides the night | The plate's label says the light comes from the prompt (§4.3); Phase 7 checks it |
| The same-setup frame copies the pose too | Its label says pose and expression come from the prompt; untick per shot |
| Weather words invented from nothing | Only words already in the IR or sound are used; a test with a dry scene |
| Shared schema change raises every planner's token cost | Phase 5 is measured offline first and waits for the person |
| Old shots in the database have the thin IR | Every section falls back to what exists; a pre-plan shot renders as today plus time of day and grade |
| Lettering from numbers or ids | D3; labels are plain names; existing "no text" close |

## 7. What is the person's

- D1 to D7.
- Reading Phase 0's side-by-side before Phase 5.
- Phase 7: the yes, the spend, the blind read.
