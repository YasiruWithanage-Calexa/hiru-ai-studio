# Cinematic David: prove it in a lab before building it (plan/2026-11-06)

Status: written 2026-11-06, nothing built. Plain-words version: [human-read.md](human-read.md).

## 1. Why this plan exists

Shot Planner David (plan/2026-11-05e) planned Episode 1 ("The First Meeting", production `131d1409…`, episode
`7215f510…`) as 12 shots with **no added shots**, simple coverage and one flat colour. One ChatGPT message planned the
same story as 19 shots in five sequences, with an establishing shot, close-ups of the phone and the tea, reactions, a
colour arc and director's advice. The person wants **the most cinematic version**: a plan that feels made by an
experienced director, DoP, producer and editor.

What we found in the stored run (`scenes.david`, read 2026-11-06):

| # | Finding | Owner |
|---|---|---|
| F1 | The prompt asks for restraint: "Use few devices" (`david_author/prompts/system.md:25`), "planner", "without going back", and a worked example that is "Restrained", one shot per block. David's own notes say "keep coverage simple". | prompt |
| F2 | The answer has one short `notes` paragraph: no beats, sequences, geography, colour script or advice. | schema |
| F3 | "Keep light … word for word the same" also freezes the grade: every shot is "naturalistic, warm skin tones", even the father's call. | prompt |
| F4 | Takes are 4/6/8 s with no shorter use in the edit, and the scene had 56 s (it already needed 68 s): coverage was squeezed. | schema, time policy |
| F5 | Sizes lack ECU, EWS and MWS. | schema |
| F6 | The people rows carry name, code, look and voice; not who they are or what they want. | pack |
| F7 | `gpt-5` at medium effort writes ~7,000 tokens of strict JSON in one go. | model |
| F8 | **Bug:** mend's split copies the whole IR into both halves (`contracts/david/mend.py:76-88`): S1 has no line but its beat says "speaks" and it is not silent (Veo will invent speech); S2 repeats the tea. | code |
| F9 | Repair at low effort failed twice on Anudi's car-to-stall walk; both answers made a new teleport. | repair |
| F10 | The reading lost "he told himself" (L5 is spoken aloud), dropped the narrator's last line, and cut the rain into its own 4 s scene with no link to scene 2. | Story Reader / split |

The last large system (Adam) cost credits and was built before it was proved. So this plan builds the **whole proposed
system as a small lab**, outside the product, runs it on this one story with a hard budget, and fixes it until it beats
the ChatGPT answer. Only then does a separate plan move the winning parts into David.

## 2. The rules of the lab

1. **Outside the product.** Everything lives in `lab/cinematic/` at the repo root. Nothing under `src/` changes, no
   database row is written, no service or interface file changes. Deleting the folder removes the lab.
2. **Reuse, don't copy.** The lab imports `contracts.david` (checks, clock, staging), `contracts.shotplan`,
   `hiru_ai.agents.david.wire_schema` (the Veo IR schema) and `hiru_ai.core.llm.openai_client`. Where the lab needs a
   different behaviour (the split fix) it has its own small module, not an edit to `src/`.
3. **Free until proven.** Everything is built and tested offline with a hand-written answer first. A paid call happens
   only after the dry run shows the exact message, the schema and the price estimate.
4. **A hard budget of $5 for the whole lab** (the person's decision, 2026-11-06). `run.py` keeps a ledger
   (`lab/cinematic/runs/ledger.csv`: time, model, effort, input, cached, output and reasoning tokens, dollars,
   hypothesis). Every call sets `max_output_tokens` (default 40,000, reasoning included), so its worst case is known
   before it is sent: worst case = input tokens × input price + `max_output_tokens` × output price. `run.py` refuses
   when the ledger total plus that worst case passes **$5.00**. The cap is a constant in `run.py`, not a flag; raising
   it is a code change the person asks for. A call that fails or is cut off is still entered in the ledger at its
   worst case unless the API reports its usage.
5. **Never pay twice.** A run is keyed by the hash of (system prompt, example, user message, schema, model, effort).
   The same key reuses the saved answer.
6. **One change per paid run.** Each paid run after the first has a written hypothesis and one change (prompt,
   example, pack, schema or checks) in `runs/<n>/notes.md`. No change, no run.
7. **Stop rule.** If the gate (§7) is not met after **4 improvement runs**, or the $5 runs out, stop and write down why. No more spending
   until the person decides.
8. **No invented story** stays a hard rule. ChatGPT invented a line ("I'll come, Thaththa"); the lab must not.
9. **Test, don't overfit.** The worked example in the prompt is never Episode 1. The gate includes a second, different
   scene.

## 3. The folder

```
lab/cinematic/
  README.md                 how to run, the budget, what each file is
  input/
    story.txt               the raw Episode 1 story (the person's message, 2026-11-06)
    reading.yaml            the corrected reading: ONE scene, the blocks, the cast, the place, the people's essence,
                            the style guide, the time policy (§4.1)
    reading_db.yaml         the reading as the database has it today (2 scenes), for comparison
    chatgpt.md              the ChatGPT answer, as pasted
    david_today.json        David's stored plan for both scenes (scenes.david), as read on 2026-11-06
    second_scene.yaml       the overfit guard: a different scene (the gold `phone_call`, or a real one the person picks)
  prompt/
    system.md               the team prompt (§4.3)
    example.json            ONE worked example, a different scene, written cinematically (§4.4)
  schema.py                 CinemaWire: the answer's shape (§4.2), and its strict JSON schema
  pack.py                   the user message (§4.5)
  checks.py                 the existing David checks + the craft measures (§5)
  mend.py                   the split fix (F8) and the other code mends the lab needs
  run.py                    dry run, paid run, budget, cache, save, check, render
  render.py                 the HTML shot list a person reads (§6) and the side-by-side
  rubric.md                 how a person scores a plan (§7)
  fixtures/fake_answer.json a hand-written answer for the offline tests
  tests/test_lab.py         offline tests (no model)
  runs/
    ledger.csv
    <n>-<model>-<effort>/   request.json, answer.json, usage.json, checks.json, plan.html, notes.md
  RESULTS.md                what each run showed, the gate, the decision
```

`runs/*/` is git-ignored except the runs a person keeps. Whether the lab is committed at all is the person's choice.

## 4. What the lab builds

### 4.1 The input (fixes F10 by hand, so David's quality is measured alone)

`input/reading.yaml` is what a perfect reader would give, written by hand from `story.txt`:

- **One scene**, the rain and the road included (EXT. COLOMBO ROADSIDE – DAY, heavy rain). Place objects: the road,
  traffic, the three-wheeler, the counter, tea, glasses, short eats, the family car, an umbrella, the phone, puddles.
- Kasun's thought "One day… I'll have my own restaurant" is a **voice-over** (`delivery: "voice over, to himself"`,
  which `HEARD_MARKS` already treats as heard).
- The narrator's last line "He had no idea that this meeting was about to change his life." is kept as a
  **narrator voice-over** block.
- The father's line is `delivery: "on the phone"` (as today).
- The descriptive sentences stay as blocks ("His clothes are simple", "His eyes are full of ambition"): they are
  direction for performance and look, not separate pictures.
- `people`: name, code, look, voice **and essence**: Kasun, a young street-food vendor, proud and hungry to grow,
  shy with strangers; Anudi, from a comfortable family, warm and curious, under her father's control; the father, heard
  only.
- `style`: "Cinematic Sri Lankan romantic drama for television. Realistic, monsoon Colombo, rich but natural colour."
- `time`: the length is a **guide** (about 60 s); the plan may run longer; the overrun is reported, never trimmed.

The words of the lines are the stored English lines (the story is in English). A Sinhala production keeps Sinhala.

### 4.2 The answer's shape (`CinemaWire`, fixes F2, F4, F5)

Built on `contracts.david.wire` so the existing checks can read it (a `to_david()` conversion drops the new fields).

```
treatment:
  logline           one sentence
  arc               the emotional beats in order, each {beat, blocks: [first, last], feeling}
  approach          the visual approach in plain words (lenses, movement, framing philosophy)
  colour_script     per sequence {sequence, palette, light, grade}: the physical light stays continuous, the grade
                    may move with the story
  geography         the layout: what is on screen left and right, the camera's side of the line, how it changes
  key_image         the one image the scene is remembered by
  advice            director's advice for the person: shown, never applied (0-5 items)
sequences           [{id: "A".., title, purpose, shots: [first, last]}]
shots               ShotW + sequence, angle, lens, use_s
                    size: EWS, WIDE, MWS, MS, MCU, CU, ECU, TWO, OTS, INSERT, POV
                    take_s: 4|6|8 (what Veo makes); use_s: the seconds the edit keeps (2..take_s), the editor's call
                    a line's shot keeps the whole line (use_s >= the line's need)
added, staging, end_state   as today
```

### 4.3 The team prompt (fixes F1, F3, F6)

Rewritten, not patched. Its parts:

1. **Who you are:** a top production team for Sri Lankan television drama: director, DoP, producer, editor, sound.
   The goal is the most cinematic version of the scene, the one an audience remembers. One answer, written as the team
   would agree it in a pre-production meeting.
2. **How the team works, in this order:** the treatment first (director: beats, whose scene, key image; DoP:
   approach, colour script, light sources, lens plan; producer: geography and the line; editor: rhythm, where to hold,
   how each sequence ends), then the sequences, then the shots written from them.
3. **Coverage grammar** (replaces "use few devices"): open on the world (a wide, or a detail that opens out); give each
   lead an introduction; a story object that changes hands or matters gets an insert; important lines get the
   listener's reaction; turns go closer with a motivated push; a compound action block may take two or three shots;
   let big moments breathe; end each sequence on an image; repeat a motif to open and close.
4. **Camera language:** every move has a reason (emotion or geography); lens by intent (wide for the world, long for
   intimacy); foreground layers (rain, the umbrella, the counter); practical light sources; contrast in scale and
   angle between the two worlds.
5. **Sound:** ambience, effects and music as storytelling (the rain softens at the connection; the ringtone cuts the
   music); a line may be heard before its cut (the listener shot).
6. **Veo:** limits change HOW a moment is filmed, not WHETHER (the phone landing in a puddle in ECU, not the fall).
   The list of what Veo cannot do stays as advice.
7. **The hard rules, unchanged:** no invented person, line, event or object; every block shown in order; lines named by
   id and never quoted; a voice that is only heard is never in frame; one dialogue block in one shot; the end state.
8. **Time:** cinematic first. Write the plan the scene deserves; `use_s` lets the edit keep 2–3 s of a 4 s insert.

### 4.4 The worked example

ONE example, not Episode 1: the `refuses_money` scene (the envelope) re-planned cinematically, about 9 shots in three
sequences, with a treatment, a colour script, two added shots (an insert of the envelope, a reaction), a `use_s`
shorter than its take, and advice. Hand-written in phase 1, validated against `CinemaWire` by a test. Its quality is
the prompt's ceiling, so the person reads it before the first paid run.

### 4.5 The pack

`david_pack` logic reused, plus: each person's essence, the style guide, the time policy as a sentence, and a VO marker
on heard lines in the script listing (`b5 line [L5] Kasun, voice over, to himself …`).

### 4.6 The mends the lab needs (F8)

- **Split fix:** when a shot is split, each part keeps only the beats inside its own blocks, re-timed from 0; a part
  with no line gets `silence: true` when nobody speaks; a beat that says "speaks" in a part with no line is a problem,
  not a pass.
- The rest of `contracts.david.mend` is reused as it is.

Repair (F9) is **not** in the lab at first: the lab measures the author. If the gate is met except for faults code
cannot mend, phase 5 adds the existing `david_repair` at medium effort as one measured experiment.

### 4.7 The model (F7)

Phase 2 lists the models the account can use (`client.models.list()`, free) and the person picks two: a **working
model** (mid-price, at `high` effort, about $0.30–0.50 a run) for every improvement run, and the **strongest
flagship** for one comparison run at the end, only if the budget still holds its worst case. Prices go in the lab's
own price table before any paid run (the sources disagree on today's prices; OpenAI's pricing page is the reference).
The lab calls the OpenAI Responses API directly with a strict JSON schema, `max_output_tokens`, a 20-minute timeout,
and records reasoning tokens.

## 5. Checks and measures

**Hard (fail = the plan is wrong):** every existing David check (blocks, lines in order and once, the clock, invented
names, quoted speech, staging, end state, heard voices out of frame) plus: no beat says someone speaks in a shot with no
line; `use_s` within 2..take_s and never below a line's need; every shot is in exactly one sequence; the colour script
names every sequence.

**Craft measures (reported, never blocking; a person judges taste):**

| Measure | Read from |
|---|---|
| Opens on geography (EWS/WIDE, or an INSERT that leads into a wide, in the first 2 shots) | sizes |
| Each lead's first appearance has a shot where they are the main subject | subjects, blocks |
| Story objects named in the script (phone, tea, umbrella) get an INSERT or ECU | sizes, `added.object` |
| Each line has a reaction or listener shot for the main other person, within 1 shot | `over`, `added.kind` |
| Compound action blocks (two verbs or more) covered by more than one shot | blocks, block text |
| Size variety and progression (the closest sizes sit at the arc's turns) | sizes, `treatment.arc` |
| The grade moves at least once across sequences | `colour_script` |
| Each sequence ends on a shot with no line (a held image) or a strong cut | shots, sequences |
| Shot count, total take seconds, total use seconds vs the 60 s guide | shots |
| Additions: count and kinds | `added` |

`checks.json` holds both; `render.py` shows them on the page.

## 6. What the person reads

`runs/<n>/plan.html`, a self-contained page, laid out like a professional shot list:

- the treatment card (logline, arc, approach, key image, advice)
- the colour script as a strip of swatches per sequence
- the sequences with their time windows (from `use_s`)
- one card per shot: number, size, angle, lens, movement, purpose, the line (by speaker and words, from the reading),
  sound, take and use seconds, and the beats
- the staging as a simple floor plan list (zones and marks)
- the hard problems and the craft measures

`runs/<n>/side_by_side.html`: this plan, David today and ChatGPT, each as a plain shot list (sequence, size, what,
purpose), names hidden as X, Y, Z for the blind read.

## 7. The gate (before any move into the product)

All of these, on the winning configuration:

1. **Hard checks:** zero problems left in Episode 1 and in the second scene.
2. **Blind read:** the person (and a Hiru director if one is free) prefers this plan to ChatGPT's on Episode 1, or
   rates them equal, using `rubric.md` (geography, coverage per beat, reactions, inserts, camera language, colour arc,
   sequence endings, would I shoot this).
3. **Not luck:** one more run of the same configuration on Episode 1 gives the same quality (it still passes 1 and
   scores within one rubric point).
4. **Not overfit:** the second scene passes 1 and the person rates it at least as good as David today.
5. **Cost and time recorded** per scene (these never appear in the app).

## 8. Phases

| Phase | What | Paid? | Exit |
|---|---|---|---|
| 0 | Set up `lab/cinematic/`, save `story.txt`, `chatgpt.md`, `david_today.json`, `reading_db.yaml`; write `reading.yaml` (§4.1) and `rubric.md`. The person confirms the reading (L5 voice-over, the narrator line, one scene) and the second scene. | no | the person's yes |
| 1 | Build offline: `schema.py`, the prompt, the worked example, `pack.py`, `checks.py`, `mend.py`, `render.py`, `run.py --dry`, the budget, the cache, `fake_answer.json` (a hand-written Episode 1 plan) and the tests. | no | tests pass; the dry run prints the message, the schema size, the token and price estimate; `plan.html` renders from the fake answer; the person reads the example |
| 2 | Models: list them (free). Schema smoke: one call with the cheapest model at low effort and `max_output_tokens` 8,000, to prove the API accepts the strict schema and the answer parses, checks and renders. | ≤ $0.05 | parsed, checked and rendered end to end |
| 3 | First real run: Episode 1, the working model at high effort. Read `plan.html` and the side-by-side; write findings in `RESULTS.md`. | ≤ $0.50 | findings written |
| 4 | Improve: at most 4 runs on the working model, one hypothesis and one change each (prompt, example, pack, schema, checks). A two-call variant (treatment first, then shots) counts as one of the 4 and is tried only if the one-call answer is good but thin. | ≤ $2.00 | the gate's points 1–2 met, or the stop rule |
| 5 | Stability and overfit: 1 more run on Episode 1 and 1 run on the second scene, both on the working model. No repair experiment inside this budget. | ≤ $1.00 | the gate's points 3–4 |
| 6 | Reader check: run the real Story Reader on `story.txt` (one cheap call) and compare its reading with `reading.yaml`: one scene or two, L5 a voice-over, the narrator line kept. | ≤ $0.20 | the gaps listed for the reader's own fix |
| 6b | Flagship comparison: ONE run of the best prompt on the strongest model, only if the ledger plus its worst case stays under $5.00; otherwise skipped and noted. | what is left (≤ $1.25) | the working model vs the flagship, side by side |
| 7 | Decide: `RESULTS.md` with the gate, the cost per scene, the model, and a list of what would move into the product. If the gate is met, a new plan moves it; if not, stop. | no | the person's decision |

**Hard limit: $5.00 for the whole lab.** The rows above add up to $4.95 at their limits. The stop rule (§2.7) becomes
**4 improvement runs**. If the budget runs out before the gate, the lab stops and `RESULTS.md` says what was learnt and
what one more run would test; spending more is the person's new decision.

## 9. What would move into the product later (not in this plan)

If the gate is met, a separate plan moves: the prompt and the example into `david_author`; `CinemaWire`'s new fields
into `contracts.david.wire` and `scenes.david`; the craft measures beside the checks; the split fix into
`contracts.david.mend`; the pack's essence and style; the time policy (`use_s`) into the shot producer and the editor;
the reader fixes (F10) into the Story Reader; the David tab's treatment card, colour strip, sequences and shot cards in
the interface (it already has `TreatmentCard` and `StagingMap`). The F8 split bug may be fixed in the product at any
time; it does not wait for the lab.

## 10. Decisions for the person

| | Question | Suggestion |
|---|---|---|
| L1 | The budget cap for the whole lab | **decided: $5.00, hard** (2026-11-06) |
| L2 | The two models (after phase 2 lists them) | a mid-price working model at high effort for all improvement runs; the strongest flagship for one run at the end if the budget allows |
| L3 | The corrected reading: one scene, L5 a voice-over thought, the narrator line kept | yes |
| L4 | The second scene for the overfit check | a real Hiru scene of yours; the gold `phone_call` if none |
| L5 | The time policy in the lab: the length is a guide, overruns are reported, `use_s` lets the edit keep part of a take | yes |
| L6 | Who reads the blind comparison | you, plus a Hiru director if one is free |
| L7 | Is the lab committed, or kept local and deleted after phase 7 | keep local until the gate |
