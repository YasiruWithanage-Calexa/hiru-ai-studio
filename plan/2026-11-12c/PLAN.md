# Canon refine: real canon cards and scene looks from the finished breakdown (plan/2026-11-12c)

Revision 1 (2026-11-12). Phase 0 (the lab) is done and paid ($0.181 of a $1.00 cap, four runs). Phases 1 to 7 are
offline. Phase 8 is a paid live check, the person's yes first. Track B (scene places and props by id) is code only.

**Read §1, §2 and §3 first if you are a new chat picking this up.** The design was drawn for the person in two pages:
[Canon Pipeline Map](https://claude.ai/artifact/8aET2iUVY5Kx8D6DjdtzER) (what is wrong, with Ekama's data) and
[Canon Refine Plan](https://claude.ai/artifact/ViB7Zh5vTSjuLJinsv4kYE) (the shape agreed before the looks lab).

## 1. Why

The person reported (2026-11-12), on *hiru short combined 1* (Ekama Sakshiya), three problems with the canon:

1. **Character looks are not produced.** No appearance, no wardrobe, no gender; the reference sheet says "Subject: one
   person".
2. **Canon entries carry the wrong kind of text, so images come out wrong.** L05 Colombo Garage's card is the whole of
   Scene 03 (dialogue, Nimal, Dinu, the key); its reference plate prompt asks for "no people" and then describes them.
3. **A scene's place and props are sometimes wrong.**

What the dev database showed (read-only, 2026-11-12):

- With `BREAKDOWN__ENABLED=true`, `canon_extract` and the old structure build (with its `looks_node`) are skipped. Every
  canon card comes from `contracts/breakdown/fill.canon_cards`, which copies the line range the split pointed at. The
  breakdown is pointer-only by design: no step may describe anything.
- `age` = "Dinu - 30, Colombo cash-transport driver." (the split pointed at six words); `details` is not a person field,
  so the cast lines went to `notes`; Nimal to Inspector Ruwan have no age; gender is empty for all six. The voice pin reads
  "voice (Dinu - 30, Colombo cash-transport driver.), a Sri Lankan (Colombo) accent".
- `summary` is the copied range, and `reference_sheet_prompt` falls back to it when `look` is empty (always). The packet
  already withholds wide summaries (`SUMMARY_MAX_LINES`); the canon fill does not.
- Fill drops `place_kind`, `seen` and `within`: Colombo and Mahawewa village (regions), the canal gate and paddy field
  (spots of the canal), the Old Port warehouse (a destination) and the village bus stop (only in a photo) all became
  locations with plates. The gun (a direction note) and Rs. 300 million (the logline) became props.
- The continuity step finds looks (Nimal: alive in S03, found at the canal gate in S01) but nothing writes them.
- Scene props: the structure writes only `location_id`; the brief's `things` are dropped; planners pick props by
  substring (`objects_of`: "photo" matches "photographs", so the dashboard photo joins the garage scene). Breakdown ids and
  canon ids are linked by name only.

The person's direction (2026-11-12): **do not interrupt the breakdown; add an agent that reads its finished output and
builds the canon properly, in parallel, and let planning start only when both are done.**

## 2. What the lab proved (phase 0, done)

`lab/canon_refine/`. `export.py` and `looks_export.py` read a production read-only; `inputs.py` / `looks_inputs.py`
build the message; `schema.py` / `looks_schema.py` are the strict answer shapes; `system.md` / `looks_system.md` the
prompts; `checks.py` / `looks_checks.py` the code checks; `run.py` / `looks_run.py` run one call, the checks and at most
one repair call, under a $1.00 cap with a cache and a ledger (`runs/ledger.csv`). Nothing is written to the database.
Model: `gpt-6.1-sol`, medium (the `breakdown` tier).

| Run | Production | What | $ | Time | Result |
|---|---|---|---|---|---|
| run1 | Ekama | canon refine | 0.054 | 101 s | cards strong; 8 ids written inside descriptions ("C01's wrist"); reasoning inside a look ("avoids fixing an unstated hour") |
| run2 | Ekama | + names-not-ids and description-only lines, id / reasoning / pronoun checks | 0.058 + repair 0.012 | 111 s + 8 s | 0 findings after the repair; no ids |
| looks1 | Ekama | looks per scene (breakdown timeline and presence) | 0.019 | 32 s | 0 to fix; Dinu keeps his clothes across the flashback; voice-only Aruni gets no look; Nimal is found in the clothes he was last seen in |
| looks1 | You and I 7 (no breakdown, from `scenes`) | looks per scene, story time read by the model | 0.039 | 67 s | 0 to fix; 9 looks for 10 scenes; Kasun goes vendor T-shirt → apron → polished for the opening, as his card's note asks |

What it shows:

1. **One call turns copied script text into usable cards.** Ages are the number with their line; every person has a
   gender, a distinct appearance (siblings share features, the cast cannot be confused) and a base wardrobe; places are
   classified the way a designer would (2 regions, 3 sets/vehicle, 2 spots, 2 unseen) and the three sets have clean,
   people-free looks; the gun and the money are "mentioned".
2. **Two prompt lines and two checks remove the failure modes** (ids, reasoning in a value). The checks must stay: the
   model drifts.
3. **Looks are a separate, cheap call** that needs the refined base wardrobe. It reads story time (flashbacks, "a few
   weeks pass", "that night"), keeps an outfit through continuous time, changes it for a reason, and keeps CONDITION
   (wet, muddy, lying still) out of the outfit, so one look sheet serves many scenes.
4. **Each run gives a different good answer** (run1 dressed Aruni in a blue blouse, run2 in a white nursing dress;
   colours change). The result must be written once and kept, never regenerated silently.
5. **Checks with false positives cost a repair call**: "supports" (steel supports) and gender-from-"him" were check
   bugs, fixed in the lab.
6. **Ekama's cast is locked yet still holds the extracted text.** A rule "never touch a locked entry" would skip exactly
   the cards that need it most (D2).
7. Time: ~2 minutes for the canon call, ~30–70 s for looks, ~10 s a repair.

## 3. The design

### 3.1 Two agents, one job

| Agent | Reads | Writes (answer) | Group / tier |
|---|---|---|---|
| `breakdown_canon` | the breakdown memory: entities with kind, place kind, seen, within, card lines and scenes; each entity's scene lines; palette and lighting rules; continuity looks and timeline; every canon card a person wrote | per person: gender, age, appearance, wardrobe, voice; per place: class, parent, look; per thing: class, details. Every value `{value, source: script|inferred, line, reason}` | `agents/breakdown/`, tier `breakdown` |
| `breakdown_looks` | the episodes, every scene in page order with its script and who is on screen, the timeline, each person's refined appearance and base wardrobe | story time per scene (day, part of day, continues), looks (one outfit each), and per scene: each on-screen person's look, condition and why | `agents/breakdown/`, tier `breakdown` |

Both are ported from the lab (prompts, schemas, checks) and both subscribe to house rules (topics `wardrobe`, §3.8).
The message builders, answer shapes and checks live in **`contracts/canon_refine.py`** and **`contracts/scene_looks.py`**
(pure), so the agents, the job and the tests send and check the same bytes.

**Scale.** The lab sent the whole document (61 lines). The product sends, for each entity, its card lines and the lines
of the scenes it is in, deduplicated. When the message passes a budget (start at 40k tokens), the canon call splits
into people, then places and things (same answer shape, merged by id); the looks call splits by episode, each part
given the previous part's looks so outfits carry over.

### 3.2 The job: CANON_REFINE

A new `JobKind.CANON_REFINE`, served by the existing `hiru-canon-extract` function (port 8205; one function may serve two
kinds, as Raphael's two do). When `BREAKDOWN__ENABLED`, `canon_extract` stays skipped; `canon_refine` is the canon step.

```
load memory + canon ─▶ canon call ─▶ checks ─▶ (repair: failed ids only) ─▶ looks call ─▶ checks ─▶ (repair) ─▶ apply
```

- **Standalone** (phase 5): `POST /productions/{id}/canon/refine` starts it, for any production with a breakdown memory
  (Ekama today) and for re-runs.
- **Inside the build** (phase 7, the person's fork–join): a branch of `breakdown_build`. The memory is complete after the
  `breakdown` node; fill runs as today; the two calls run beside it; `refine_apply` waits for both; then the graph ends
  and PLAN starts. Two nodes, three edges; read, breakdown and fill unchanged.

```
read → breakdown ─┬─ fill (unchanged) ───────────────┬─ refine_apply → END ─▶ PLAN_*
                  └─ refine_calls (canon, then looks) ┘
```

- **Never fails a build.** Every error in the refine branch is a job warning ("Canon kept as extracted"); the build goes
  on with v1. A per-call limit of 240 s (the lab's canon call took 111 s); STRUCTURE_BUILD's 900 s function timeout is
  checked against a long series in phase 8.
- The breakdown graph has no checkpointer today; a retried build re-runs the breakdown. `refine_apply` is idempotent
  (§3.4), so a retry never doubles anything.

### 3.3 Where the answer goes

| Answer | Stored as | New in v23 |
|---|---|---|
| person card fields | a new `canon_versions` row: `card` (gender, age, appearance, wardrobe, voice; summary kept), `wardrobe_anchor`, `voice_pin`, `reference_prompt` rebuilt by the existing builders | `canon_versions.provenance jsonb`: field → `{source, line, reason}`; `source` gains `'refine'` |
| place class and parent | on the entity | `canon_entities.class text` (person: null; place: set, vehicle, region, spot, unseen; thing: prop, mentioned) and `canon_entities.parent_id uuid` (a spot's set) |
| place look, thing details | the new version's `card.look` / `card.details` | |
| looks | `canon_looks` rows, status **draft**, ranges from the episodes the look is worn in, `name` unique per character (the existing rule) | `canon_looks.origin text` (`person` \| `refine`) |
| who wears what | `scene_looks` rows (one per scene and on-screen person) | `scene_looks.condition text`, `scene_looks.why text`, `scene_looks.origin text` |
| story time | `breakdown_memories` is not changed (the breakdown owns it); kept in the job result for the review list | |

Effects downstream, all existing code paths:

- `reference_sheet_prompt`: a character sheet gets gender, age and appearance; a place plate gets the look and **never
  falls back to a summary** (an empty look means no plate). `class` region, spot and unseen get no plate: the API refuses
  `reference-sheet` for them with a reason, the interface hides the button.
- Region looks become the style note of the sets within them (frame brief and packet, beside the palette rule).
- A scene look applies through `looks_in_force` only when the look is **ready**: a person approves drafts first. The
  scene's `condition` goes into the stager's input as each person's starting state (the ledger's 40-character
  `condition` stays the stager's, block by block) and into the frame brief's people line.
- Fill and `structure_write` keep the summary as the documents' words, but `canon_cards` cuts a summary wider than
  `SUMMARY_MAX_LINES` (the packet's rule), so a v1 card is never a whole scene again.

### 3.4 Safe write (`refine_apply`)

One SQL function, `canon_refine_apply(p_production uuid, p_payload jsonb)` (v23), in one transaction:

1. Insert every new version (never current yet) and every draft look and scene look the payload carries.
2. For each entity, switch `current_version_id` to the new version **only if** its current version is the one the job
   read (`expected_version_id`), its source is `extract`, `inferred` or `refine`, and it is not locked.
3. Otherwise the new version stays as a **proposal** (inserted, not current), counted in the result.
4. A scene look is written only where no person chose one (`origin` person wins); a draft look never replaces a look a
   person made.
5. Return counts: switched, proposed, skipped-changed, looks, scene looks.

So readers see all of v1 or all of v2, a crash before step 2 leaves the canon as it was, and a re-run with the same
answer inserts nothing new (versions are keyed by `(entity_id, card_hash)`; the call itself is cached by request hash
for a retry within the job).

### 3.5 No mixed plans

1. **Lock.** `POST /canon/refine` is refused (409) while a STRUCTURE_BUILD or any PLAN_*/CINEMATIC job of the
   production is active; every plan endpoint is refused (409, "Canon is being refined") while a CANON_REFINE job is
   active. Inside the build (phase 7) the order is already serial.
2. **All-at-once switch** (§3.4).
3. **Stamp and flag.** Each plan records the canon versions it was planned against (`design.pins.canon`, which the
   older planners already write). Phase 1 checks whether Raphael writes it; if not, it is added. After a refine, scenes
   planned on older versions show "Planned on old canon: re-plan" (the Canon panel's `usage_by_entity` already counts
   out-of-date shots).

### 3.6 Checks (code, `contracts/canon_refine.py` and `contracts/scene_looks.py`)

`fix` findings go to one repair call with only the failed ids; `review` findings go to the person.

| Check | Level |
|---|---|
| every breakdown id answered once, kinds match, nothing invented | fix |
| a `script` value holds up against its line (digits present; most words on the line; gender from a gendered word such as him, she, brother) | fix |
| age is short and has a digit | fix |
| no id (`[CLP]\d{2,3}`) inside any description; no reasoning words inside a value | fix |
| a place look names no person; a set or vehicle look is long enough to paint; a spot's parent is a set or vehicle | fix |
| safe-depiction `blocking()` on every description and condition | fix |
| looks: every scene answered; every on-screen person (breakdown presence) has one look; a voice-only person has none; a look belongs to its person; no condition word inside an outfit | fix |
| a change of outfit inside continuous story time; one look worn across a new day; a look worn in no scene | review |

### 3.7 Who may refine, and what the person sees

Refine is an edit: the roles that may edit canon (`CanEdit`). The job result and the Canon panel show switched cards,
proposals, draft looks and the review list. **No costs in the interface** (CLAUDE.md).

### 3.8 House rule H-14: working dress

`src/libs/hiru_ai/house_rules/working_dress.md`, `topics: [wardrobe]`, `kind: default`:

> Working dress. A person whose job the story states wears that job's real present-day Sri Lankan working dress when the
> story shows them at work: a nurse or public health midwife in a white uniform, police in khaki with the rank shown, a
> school pupil in white uniform, a bus conductor in the depot's shirt. Off duty they wear their own clothes. A
> production's own direction overrides this.

Subscribers: `breakdown_canon`, `breakdown_looks`. (The lab got the nurse right once in two runs without it.)

### 3.9 Track B: scene places and props by id (issue 3, code only)

- `breakdown_build.canon_rows` and `structure_write` return a **canon map**: breakdown id → canon entity id, stored on
  the breakdown memory (`Breakdown.canon_ids`, like `Scene.line_map`), so a renamed canon entry is still the same entry.
- A scene's canon (`scene_canon_ids`) adds, from the brief through the map: the people on screen (not only speakers) and
  the things with role hero, used, worn or dressing (not mentioned).
- `objects_of` (Adam, David) and Raphael's prop list take the scene's things from the map when the scene has a breakdown,
  and keep the substring match only for productions without one, matched on whole words (`\bphoto\b`).
- A shot's place: the event's `spot` through the map, so a shot at the canal gate is labelled as the canal's gate zone.

## 4. Phases

| Phase | What | Cost | State |
|---|---|---|---|
| 0 | Lab: canon refine (run1, run2), looks (Ekama, You and I 7) | $0.181 | done |
| 1 | Contracts: `contracts/canon_refine.py`, `contracts/scene_looks.py` (messages, shapes, checks, merge), ported from the lab with the lab's fixtures as tests (run2 and looks1 answers: 0 fix findings; run1's answer: the 8 id findings and the reasoning finding; the bad fakes from the lab); check whether Raphael writes `pins.canon` | $0 | |
| 2 | Schema v23 (`upgrade_v22_to_v23.sql`, `schema_v23.sql`): `canon_versions.provenance`, source `refine`; `canon_entities.class`, `parent_id`; `canon_looks.origin`; `scene_looks.condition`, `why`, `origin`; `canon_refine_apply()`. Applied by the person. v22 (inferred) must be applied first | $0 | |
| 3 | Agents `breakdown_canon`, `breakdown_looks` (component, prompts from the lab, schema, evals with the lab cases, tests); house rule H-14 and the subscriptions; `hiru_ai validate`, `catalog --check` | $0 | |
| 4 | The CANON_REFINE system (`systems/canon_refine/`): load, two calls, checks, one repair each, apply; fakes and tests (switch vs proposal, changed-since-read skipped, person look kept, idempotent re-run, failure leaves v1); `fill.canon_cards` cuts wide summaries; `reference_sheet_prompt` never falls back to a summary; no plate for region, spot, unseen | $0 | |
| 5 | API: `POST /canon/refine` (CanEdit, 409 lock both ways), job kind and function wiring, `reference-sheet` refused by class, proposals: `POST /canon/{id}/versions/{v}/accept`; scene looks carry condition; frame brief and stager read condition and region notes | $0 | |
| 6 | Interface: Canon panel "Refine canon" (job progress through the shared activity poll), per-field source label ("From the script, line 17" / "Inferred: …"), class chip and parent, no sheet button for region/spot/unseen, proposal banner (Accept / Dismiss), draft looks with "worn in" scenes, scene panel shows each person's look and condition (editable), review list | $0 | |
| 7 | The fork–join in `breakdown_build` (two nodes, three edges); planning waits; errors are warnings | $0 | |
| B | Track B (§3.9): canon map, scene canon from the brief, planners' props by id, whole-word fallback | $0 | |
| 8 | Live check, the person's yes: v22 and v23 applied; "Refine canon" on Ekama (cards, proposals for the locked cast, looks); one new build of a short production through phase 7; reference sheets for Dinu and Colombo Garage only if the person asks | about $0.30, cap $1.00 (no images) | |

Checks before finishing (backend): `ruff check src tests scripts`, `mypy`, `.venv/Scripts/python.exe
scripts/lint_imports.py`, `hiru_ai validate`, `hiru_ai catalog --check`, `pytest -q` (with `ADAM_MODE=staged
OPENAI__API_KEY=`). Interface: `npx next typegen && npm run check && npm run format:check`.

## 5. Decisions

- **D1 (taken, 2026-11-12):** a separate agent reads the finished breakdown; the breakdown is not changed; inside builds
  it runs in parallel with fill and planning waits for both (fork–join).
- **D2. Locked and person-written entries.** Recommended: **a proposal** (the new version is stored, not current; the
  panel offers Accept). Ekama's locked cast gets refined cards without anyone's choice being overridden. Alternative:
  skip them entirely.
- **D3. Where a scene's condition lives.** Recommended: **`scene_looks.condition`**, passed to the stager as the
  starting state and to the frame brief. (Earlier we said the ledger; its `condition` is 40 characters, block by block,
  and the stager rewrites it, so it cannot hold the agent's answer.)
- **D4. Productions without a breakdown** (You and I 7 and every production built before 2026-11-11). The looks call
  works from today's tables (the lab proved it); the canon call needs the breakdown's structure. Recommended: **looks
  from tables is allowed; canon refine needs a breakdown** ("Rebuild with the breakdown first"). Alternative: canon from
  tables too, as a later plan with its own lab.
- **D5. Draft looks and sheets.** Recommended: looks are drafts; no sheet is painted until a person makes it ready (the
  existing flow). The first look of each person is their base look, so look sheets show real clothes.
- **D6. Per-call time limit.** Recommended: 240 s (lab: 111 s); the build waits at most about 10 minutes in the worst
  case of two calls and two repairs, then goes on with v1.
- **D7. The old `canon_extract` and `look_drafter`.** Recommended: keep them for productions without a breakdown until
  D4 is settled; remove later.

## 6. Not in this plan

- Re-reading or changing the breakdown itself (D1).
- Painting reference or look sheets automatically.
- Canon refine for productions without a breakdown (D4 alternative): its own lab first.
- Children in reference sheets (`contracts.canon` treats every character as an adult today).
- An admin page for house rules (plan/2026-11-12 D2).
