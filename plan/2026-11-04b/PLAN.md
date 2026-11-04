# Shot Planner Adam: a director's shot planner, built new: plan

Status: proposed (2026-11-04). Nothing in this plan is built. No code is changed by this file.
It builds on [plan/2026-11-03](../2026-11-03/PLAN.md) (parts: agents, steps, panels, systems) and
[plan/2026-11-04](../2026-11-04/PLAN.md) (tools), and changes none of their rules. Decisions marked **(default)** in §12
are the assumptions this plan is written on; change them before Phase 0 starts.

**The current Shot Planner (`script_split`) is not changed.** Adam is a second, separate system. A production or a scene
chooses which one plans its shots. Both write the same `shots` rows, so everything after the plan keeps working.

## 1. The goal

Turn a scene into a shot breakdown that a good drama director would be proud of. The viewer should feel they are
*in* the scene, not watching a reading of the script.

The person's test scene (2026-11-04), "An Unexpected Phone Call": Anudi laughing with Dasun, a call from her father
about her marriage, her smile fading, "I'll come, Thaththe", a restrained "See you", Dasun watching her go.

| | Shots | What it does |
|---|---|---|
| `script_split` today (estimate from its rules) | 5–6 | Legible and continuous: each line framed on its speaker, a hold at the turn |
| The person's "average" breakdown | 12 | Adds the baseline happiness, Dasun's side, the silence after the turn, the call ending, the mask |
| **Adam's target** (§9) | 13 | Adds a plan: whose scene it is, a planted object and its payoff, sound that narrows into her head, focus that pushes Dasun out, the smile that outlives the eyes, the POV handed to Dasun, an empty-frame ending |

Success means:

| Measure | Target |
|---|---|
| Blind A/B on the gold set (§8), a Hiru director judging | Adam preferred over `script_split` on ≥ 80% of scenes; ≥ 4/5 average on "I felt I was there" |
| Adam vs the gold "master" breakdowns | ≥ 40% of scenes judged as good or better than the master |
| Story invented (a new person, line, event or fact) | 0, checked by code on every plan |
| Each line's words and language | unchanged, bound by code (as today) |
| Veo rules (4 / 6 / 8 s, 2.2 words/s, overruns reported, never trimmed) | unchanged |
| Mute test: the emotional story readable with dialogue muted (judge) | ≥ 4/5 |
| A plan a person cannot change | never: every card, every elaboration and the treatment are editable and removable |

## 2. Why a new system and not another fix

Plan [2026-11-01d](../2026-11-01d/PLAN.md) gave `script_split` a reading, staging and three critics. Plans are now
*correct*, but still flat. The causes are structural, so a new design fixes more than another round of rules:

| # | Cause | Where in `script_split` | Effect |
|---|---|---|---|
| R1 | **The unit is wrong.** A shot is "a contiguous range of script blocks". | `scene_planner/schema.py` (`start`, `end`) | Moments between the lines (the happy face before the call, the listener, the silence, the hand lowering the phone) have no block, so they cannot become shots. |
| R2 | **The order is backwards.** Structure first, meaning after. Purpose, staging and performance are written by `shot_intent` and the DoP after the list is FIXED. | `pipeline.py` → `shot_producer` | Meaning is painted onto a structure chosen without it. |
| R3 | **The guardrail is too wide.** "Never invent an event" also forbids *visual elaboration*: a reaction, a detail, a POV, the place. | planner and critic prompts | The film grammar a director uses is ruled out along with invention. |
| R4 | **Pressure to minimise.** "Merge a run of short actions", "add no shots that only hold a picture", "scenes are short", breath dropped first. | planner prompt, `scene_reader`, envelope | The model learns that fewer shots is better. The `model_plan` parity fixture: a homecoming scene in 2 shots, three critics say "acceptable", 0 notes. |
| R5 | **"Every line in a shot that frames its speaker."** | planner, coverage critic | Talking-head ping-pong. A line can't play over the face that hears it, though that is often where the drama is (Murch, Dmytryk). |
| R6 | **The critics find errors, and code scores only defects.** "Acceptable unless clearly broken"; `kernel_score` counts problems; a tie keeps the first plan. | `critic.py`, critic prompts | A dull plan with zero defects beats a vivid one. Nothing rewards craft. |
| R7 | **The plan is thin.** `framing` (7 values) + `title`. No angle, height, movement, focus, composition, sound concept, performance or purpose at plan time. | `schema.py`, `shots.framing` check | The planner can't express the decisions that make a scene. |
| R8 | **No directorial questions are asked.** Whose scene is it? What does the audience know that a character doesn't? What is the baseline before the break? What object is planted? What is the size arc? | `scene_reader` | No POV, no suspense, no irony, no setup/payoff. |
| R9 | **The craft knowledge is for social ads**: hooks, retention, the scroll-stop. | `knowledge_bases/craft/sources` | The agents learn ad grammar, not drama grammar. |
| R10 | **One plan, one interpretation.** | `pipeline.py` | A scene can be played restrained, heightened or intimate. Today the system averages them. |

## 3. What directors do, and what Adam takes from it

| Source | Idea | Adam takes |
|---|---|---|
| Walter Murch, *In the Blink of an Eye* | Rule of Six: emotion, story, rhythm, eye-trace, 2D plane, 3D space, in that order | The scoring order of the screening panel (§5.4) |
| Robert McKee, *Story* | A scene turns a value; beats are action/reaction | The dramaturg's value shift and beats |
| Judith Weston, *Directing Actors* | Playable verbs, objectives, obstacles, subtext as behaviour | Wants as verbs; performance as visible micro-action |
| Steven Katz, *Film Directing Shot by Shot* | Design the scene's coverage from the staging and the POV; storyboards as thinking | Treatment before shots; POV owner |
| Nicholas Proferes, *Film Directing Fundamentals* | Dramatic blocking: movement shows a change in power; "whose scene is it" | The blocker places people for meaning, not just position |
| Alexander Mackendrick, *On Film-making* | Show, don't tell; dramatise the inner state | Every STORY NOTE becomes behaviour, an object or a sound |
| Hitchcock / Truffaut | Size of the subject = its importance; suspense (the bomb under the table) | Size follows weight; "what the audience knows" in the analysis |
| Kuleshov, Pudovkin, Eisenstein | Meaning comes from putting two shots side by side | Juxtaposition as a named device |
| Sidney Lumet, *Making Movies* | A lens and size progression across the work | The treatment's size arc, checked by code |
| Bruce Block, *The Visual Story* | Contrast raises intensity; affinity calms; plan the visual structure | The treatment's visual strategy per section |
| Joseph Mascelli, *The Five C's of Cinematography* | Angle, continuity, cutting, close-ups, composition | Fields on every shot card |
| Daniel Arijon, *Grammar of the Film Language* | Coverage patterns, the 180° line | The continuity check (code) |
| Michel Chion, *Audio-Vision* | Sound adds value to the image; off-screen sound; point-of-audition | The sound map: subjective sound, silence, pre-lap |
| Edward Dmytryk, *On Film Editing* | Cut on the reaction; a cut must have a reason | Lines may play over the listener; every cut has a motive |
| Chekhov's gun; William Goldman | Plant and pay off; enter late, leave early | Plant/payoff and in/out points in the treatment |
| Ozu (pillow shots), the studio's `editing.md` | Quiet shots of place give a scene room to breathe; spend one rhythm break | Atmosphere moments; "the one break" in the treatment |
| Chakrabarty et al., *Art or Artifice?* (CHI 2024) | LLM judges don't agree with expert judges on creativity | Model critics write notes; code and a person decide |
| Lu et al., *LLM Discussion* (2024) | Diverging, then converging role agents are more original than one model | Three treatments, then a choice |
| MovieAgent (Wu et al., 2025), FilmAgent (Xu et al., 2025) | Plan top-down (director → scene → shots); role agents + verify | Adam's stage order |

## 4. The core idea: imagine first, then cut

A director doesn't cut the script into shots. They **imagine what the viewer lives through, moment by moment**, and
then choose how to film each moment. Adam works in that order:

```
scene script + story context + canon + location
        │
        ▼
 ① ANALYSE   adam_dramaturg        what the scene is about, the value shift, beats, wants (verbs), subtext,
        │                          whose scene it is, who knows what, baseline → break → aftermath, the key moment
        ▼
 ② CONCEIVE  adam_director ×3      three treatments that differ on purpose ("restrained", "intimate POV",
        │                          "heightened"): concept line, size arc, camera behaviour, sound concept, motif,
        │                          plant/payoff, rhythm map, the one rhythm break, entry, exit, ending image
        ▼   pick: a person, or the screening score (§5.4)
 ③ IMAGINE   adam_moment_writer    the viewer's experience as an ordered list of MOMENTS, each tagged
        │                          SCRIPT / IMPLIED / ELABORATION, with who, what is seen, the feeling, the seconds
        ▼   code: fidelity (§6.1)
 ④ STAGE     adam_blocker          where everyone is and how movement shows power; eyelines; props in hand
        │
        ▼
 ⑤ DESIGN    adam_shot_designer    moments → SHOT CARDS (size, angle, height, lens feel, movement, focus,
        │    adam_sound_designer   composition, performance per beat, line on or off its speaker, sound in/out,
        │                          the cut into it, purpose, emotional beat, Veo notes) + the scene's SOUND MAP
        ▼   code: fit (Veo lengths, word timing), continuity, fidelity again
 ⑥ SCREEN    adam_screening panel  four critics with different lenses → notes → one revision
        │                          code scores both versions; the better one is kept
        ▼
 ⑦ WRITE     shots rows (+ card), lines bound, the treatment and report on the scene
        │
        ▼  (unchanged path) shot_producer: the DoP realises each card; the prompt carries performance and sound
```

### The three tiers: what Adam may add

The rule changes from "never invent" to "**never invent story; always elaborate the picture**":

| Tier | Meaning | Examples | Rule |
|---|---|---|---|
| **SCRIPT** | The script says it | the call, the lines, "her smile begins to fade" | Fixed. Every SCRIPT moment appears, in order. |
| **IMPLIED** | The script needs it, without spelling it out | picking up the phone, lowering it, the listener's face while a line plays, a walk the staging needs | Allowed; must name the script moment it serves. |
| **ELABORATION** | A director's choice that adds no story | a CU of the baseline happiness, the phone face-down on the bench (a plant), a detail of hands, the place's atmosphere, a POV, a held empty frame, a sound choice | Allowed from a fixed list of kinds (§6.1); a person present, an object that fits the place; labelled "Added by director", removable. |
| **INVENTION** | New story | a new person who acts or speaks, a new line, a new event that changes the story, a fact the script doesn't give, a different outcome | **Forbidden.** Code refuses it (§6.1). |

## 5. The parts

### 5.0 Where Adam lives: an `adam` folder inside each layer

Nothing of Adam is mixed in with the existing parts. Each layer folder of the AI package gets one `adam` subfolder, and
every Adam part of that layer lives inside it. The existing parts stay where they are, beside it:

```
src/libs/hiru_ai/
├── systems/
│   ├── script_split/ … (existing, unchanged)
│   └── adam/
│       ├── group.yaml                       id: adam · version · owner · status (active | disabled)
│       ├── README.md                        what Adam is, the stage order, links to this plan
│       └── shot_planner_adam/               the flow (graph.py, state.py, component.yaml, tests/)
├── panels/
│   ├── plan_review/ … (existing)
│   └── adam/
│       ├── group.yaml
│       └── adam_screening/                  the four critics + judge
├── agents/
│   ├── scene_planner/ … (existing)
│   └── adam/
│       ├── group.yaml
│       ├── adam_dramaturg/                  each agent: component.yaml, prompts/, schema.py, agent.py, evals/, tests/
│       ├── adam_director/
│       ├── adam_moment_writer/
│       ├── adam_blocker/
│       ├── adam_shot_designer/
│       ├── adam_sound_designer/
│       ├── adam_reviser/
│       ├── adam_critic_audience/
│       ├── adam_critic_editor/
│       ├── adam_critic_opportunity/
│       └── adam_critic_fidelity/
├── steps/
│   ├── kernel_score/ … (existing)
│   └── adam/
│       ├── group.yaml
│       ├── adam_fidelity/
│       ├── adam_fit/
│       ├── adam_continuity/
│       ├── adam_score/
│       ├── adam_feasibility/
│       └── adam_write/
├── tools/
│   ├── scene_read/ … (existing)
│   └── adam/
│       └── group.yaml                       (empty at first; read tools only if an agent needs them)
└── knowledge_bases/
    ├── craft/ … (existing)
    └── adam/
        ├── group.yaml
        └── adam_film_grammar/               principles, device library, house notes, Veo notes
```

The rest of the repo follows the same idea, one `adam` folder per area:

```
src/libs/contracts/adam/                     Adam's pure contracts (pydantic + stdlib, like the rest of contracts)
    plan.py                                  SceneAnalysis, Treatment, Moment, ShotCard, SoundMap, AdamPlan
    tiers.py                                 the three tiers and the allowed elaboration kinds (§6.1)
    mapping.py                               ShotCard → the existing `shots` row (§5.1)
src/services/shot_planner_adam/              the Cloud Run function (engine/, runtime/, app/handler.py); a service must
                                             be a top-level folder for the deploy and isolation rules
tests/adam/                                  contracts, steps, system, parity fixtures, the isolation test
tests/eval/adam/                             the gold set: scenes, masters, A/B results (§8)
docs/adam/                                   architecture, device library index, how to add a device
plan/2026-11-04b/                            this plan and its IMPLEMENTED.md
hiru-ai-studio-interface/src/features/adam/  api.ts, types.ts, components/, lib/ (treatment, cards, compare)
```

Two shared places can't be avoided, and each is kept to the smallest change:

| Shared place | Adam's change | Why it can't be separate |
|---|---|---|
| Database (`supabase/migrations`, `Database/schema_v11.sql`) | one migration `…_adam.sql`: `shots.card`, `shots.planner`, `scenes.adam`, the production setting; every new column named for Adam | one database |
| The structure build hop + `task_manager.FUNCTIONS`, `deploy-functions.yml`, `start-functions.ps1` | one branch on the production's `shot_planner` setting, and the registration of one new function | the build is the one place that chooses a planner |

**The rules that keep the `adam` folders separate**, enforced by code:

1. **The registry finds groups.** Today `core/registry.py` `discover()` reads only `<layer>/*/component.yaml`. It also
   reads `<layer>/<group>/*/component.yaml` when the folder has a `group.yaml` (a folder with neither file is an error,
   so a typo can't hide a part). The package becomes `hiru_ai.agents.adam.adam_dramaturg`; the folder name still equals
   the id. A group whose `group.yaml` says `disabled` switches off all its parts in that layer.
   `hiru-ai list --group adam`, `hiru-ai new agent <id> --group adam` (writes it into `agents/adam/`), and
   `hiru-ai remove --group adam` (lists everything outside the group that still names it: the migration, the build
   branch, the function registration).
2. **Ids start with `adam_`** inside an `adam` folder (`validate` refuses any other, and refuses an `adam_` id outside
   one), so an id never collides with an existing part.
3. **Adam names only Adam.** `validate` refuses an Adam manifest that names a part outside the group (an agent, step,
   tool, panel or knowledge base), and an existing manifest that names an Adam part.
4. **Import rules** (`pyproject.toml`, import-linter, plus `tests/adam/test_isolation.py` for what import-linter can't
   say):
   - the existing layers contract already covers `hiru_ai.<layer>.adam` (systems → panels → agents → tools | steps →
     knowledge bases);
   - the existing independence contracts (`hiru_ai.agents.*` and so on) already keep the `adam` folder independent of
     every existing part of the same layer; new ones (`hiru_ai.agents.adam.*`, `hiru_ai.steps.adam.*`, …) keep Adam's
     parts independent of each other;
   - the isolation test: a module under `hiru_ai.<layer>.adam` imports only its own `adam` folder, a lower layer's
     `adam` folder, `hiru_ai.core`, `hiru_ai.rag` and `contracts`; no module outside an `adam` folder imports one;
   - the "migrated function" contract gains `shot_planner_adam`: it reaches the AI only through
     `hiru_ai.systems.adam`, the core and the adapters;
   - `contracts.adam` imports nothing from the rest of `contracts` except `contracts.timing` (the Veo clock, one source
     of truth).
5. **Reuse by copy, not by import.** Where Adam wants something an existing part has (the stager's prompt, the timing
   fit), it starts from a copy inside its `adam` folder with an `ORIGIN.md` (the source path, commit and every change),
   as the PromptMotion forks do. The old part stays as it is.
6. **Deleting the `adam` folders removes Adam.** Removing the six `hiru_ai/<layer>/adam/` folders, `contracts/adam/`,
   `services/shot_planner_adam/`, `tests/adam/`, `tests/eval/adam/`, `docs/adam/` and the interface's `features/adam/`,
   then the one build branch and the function registration, leaves the system exactly as before (the new columns stay
   unused). A test in `tests/adam/` checks that list against `hiru-ai remove --group adam`.

The system may *read* what `script_split` stored (the reading, the staging) as context through the scenes port, never
by importing its parts.

### 5.1 Contracts (pure, `src/libs/contracts/adam/plan.py`)

```
SceneAnalysis   about · dramatic_question · value {start, end} · tone · beats[{blocks, action, reaction, turn}]
                · wants {who: verb} · obstacles · subtext[{block, who, behaviour | object | sound}]
                · pov_owner {start, end, why} · audience_knows[{fact, who_doesnt, from_block}]  (irony, suspense)
                · baseline {blocks, state} · break {block} · aftermath {state} · key_moment {block, why}
Treatment       name · concept (one sentence: "we make the viewer feel X by Y") · sections[{beats, camera_behaviour,
                size_band, sound_state}] · size_arc · motif · plant {object, plant_moment, payoff_moment} · rhythm
                (tempo per section) · rhythm_break {moment, kind: silence | long hold | sudden cut} · entry · exit
                · ending_image · transition_in · transition_out (to the neighbouring scenes)
Moment          id · tier (script | implied | elaboration) · kind (from §6.1 for elaborations) · serves (moment ids or
                blocks) · who · seen (what the camera can film) · heard · feeling · seconds_need · lines[] (line ids)
ShotCard        number · moments[] · title · size (EWS WS MWS MS MCU CU ECU INSERT) · arrangement (single TWO OTS POV
                GROUP) · angle (eye | high | low | dutch) · height · lens_feel (wide | normal | long) · movement
                (static | push_in | pull_out | pan | tilt | track | handheld | crane | reveal) · focus (deep | shallow
                | rack {from, to}) · composition (foreground, negative space, frame side) · blocking_in_shot ·
                beats[{window, action, performance, camera}] · lines[{line_id, on_speaker: bool, over_whom}]
                · sound {ambience, effects, music, silence, pre_lap, carries_over} · cut_in {link, motive}
                · purpose · emotional_beat · veo_notes · take_s (4 | 6 | 8) · use_s (≤ take_s; §5.6)
SoundMap        layers per section · subjective moments (point of audition) · silences · pre-laps · music in/out
AdamPlan        analysis · treatment · moments · staging · cards · sound_map · report
```

`ShotCard` maps onto the existing `shots` row so later stages keep working: `size` + `arrangement` → `framing`
(ECU→CU, EWS/WS/MWS→WIDE, POV→MCU or INSERT, GROUP→WIDE), `take_s` → `duration_s`, the card's moments → `block_start`
and `block_end` (the script range it belongs to), `cut_in.link` → `camera_link`. The full card goes in `shots.card`.

### 5.2 Agents (new folders)

| Agent | Tier | Does | Reads |
|---|---|---|---|
| `adam_dramaturg` | high | §5.1 `SceneAnalysis` | the scene, the episode synopsis, the scenes before and after, canon characters, the director's note, the `film_grammar` KB |
| `adam_director` | high | three `Treatment`s that differ on purpose (one call, or three in parallel with different temperature and stance) | the analysis, the location card, the device library (§7) |
| `adam_moment_writer` | high | the `Moment` list for the chosen treatment | the analysis, the treatment, the script blocks |
| `adam_blocker` | medium | zones, marks, facing, frame side, props, and *why* a move happens (power, avoidance, approach) | the moments, the location card |
| `adam_shot_designer` | high | `ShotCard`s: groups moments into Veo-length takes and designs each one | moments, treatment, staging, the device library, the Veo feasibility notes |
| `adam_sound_designer` | medium | `SoundMap` and the `sound` field on each card | treatment, cards |
| `adam_reviser` | high | rewrites the cards from the panel's notes (operations, not a fresh plan) | cards, notes, the code report |

Prompts follow the repo rules: the static part first, byte-identical, data last and wrapped as data. Few-shot examples
come from the gold set (§8), never from the scene being planned.

### 5.3 Steps (code, no model)

| Step | Does |
|---|---|
| `adam_fidelity` | §6.1: every SCRIPT block and line appears once, in order; IMPLIED and ELABORATION moments are allowed kinds, name what they serve, and use only people present and objects that fit the place; no new lines, people or events. Breaks are refused with a reason, and the moment is dropped or sent back. |
| `adam_fit` | Moments and cards onto the Veo clock: the word timing (2.2 words/s, through `contracts.timing`), action seconds, 4/6/8 s takes; reports overruns, never trims a line. |
| `adam_continuity` | 180° line, eyeline pairs, screen direction, a person in two places without a move, props that change hands without being seen. |
| `adam_score` | §6.2: the craft score, by code. |
| `adam_feasibility` | Flags what Veo renders badly: readable text on screens, many people in one frame, fast complex hand actions, crowds, mirrors, a line spanning two takes. Suggests the known fix (a reaction instead of text, add in post). |
| `adam_write` | Writes shots, binds lines, stores the plan on the scene. Idempotent per job; an approved scene is never touched. |

### 5.4 Panel: `adam_screening`

Four critics in parallel (medium tier), each with one lens. Each returns at most four notes with a severity, plus a 1–5
score on its own lens:

1. **Audience seat**: would the viewer feel they are there? The mute test. Where does attention drift? Where does a
   feeling not land?
2. **Editor** (Murch order): is every cut motivated? Rhythm, juxtaposition, the in and out points, the one rhythm break.
3. **Opportunity**: what would a master director add or remove here? It may only propose allowed kinds (§6.1).
4. **Fidelity and feasibility**: does any card drift from the script, the treatment or what Veo can render? It reads the code reports.

One revision (`adam_reviser`). **Code picks the version** by `adam_score`, with a fidelity break as an automatic loss.
The critics' scores are stored as notes for a person; they never decide alone (Chakrabarty et al.).

### 5.5 System: `shot_planner_adam`

`src/libs/hiru_ai/systems/adam/shot_planner_adam/` (graph, state, manifest) and a function `src/services/shot_planner_adam/`
(the `echo` template: `engine/`, `runtime/`, `app/handler.py`), registered in `FUNCTIONS`, `deploy-functions.yml` and
`scripts/start-functions.ps1`. Jobs: `plan_scene_adam` (one scene, "Plan with Adam") and the build hop when the
production's setting says `adam`. Same rules as `script_split`: waves of scenes in parallel, the time budget handed to a
fresh delivery, idempotent, absent-safe (no model key → the job fails clearly and says "use the classic planner", because
Adam has no rules fallback worth having).

Treatment choice: the default runs all three treatments to cards only when a person asked to compare. Otherwise it
picks the treatment by a quick score on the treatment alone (fit to the analysis, distinctness, feasibility), and keeps
the other two on the scene so a person can switch.

### 5.6 Take length and used length

Veo makes takes of 4, 6 or 8 s. Editors cut shorter than the take. A card carries `take_s` and `use_s` (the part kept in
the final cut, at least 2 s) and an optional `in_s`. Until the final cut can trim (Phase 9), `use_s = take_s` and short
cutaways are planned only inside longer takes. After Phase 9, a 2 s reaction becomes a 4 s take cut down to 2 s, which is
how film is made, and it is the single biggest unlock for rhythm.

## 6. The rules in code

### 6.1 Allowed elaboration kinds (fidelity)

`baseline` (the state before the break) · `reaction` (a person present) · `listener` (a line played over the face that
hears it) · `insert_detail` (an object the script names or the location card has) · `hands` · `pov` (of a person
present) · `atmosphere` (the place, its light, its weather as given) · `hold` · `plant` (an object shown early that a
later SCRIPT moment uses) · `transition` (the way into or out of the scene) · `empty_frame` (a place after a person has
gone) · `implied_action` (a step the script needs: picking up, lowering, turning) · `move` (a walk the staging needs).

Refused: a new person who acts or speaks; a new line or words in a line; a new event that changes the story; a fact
not in the script or the canon; an object that doesn't fit the place; a moment that serves nothing.

### 6.2 The craft score (`adam_score`)

Higher is better. A fidelity or overrun problem is a loss before any of this counts.

| Signal | Counts |
|---|---|
| Turn seen | each turn's reaction is in frame while it lands |
| Baseline shown | the state before the break gets a moment of its own |
| POV kept | the POV owner's shots dominate their section; a handover is deliberate (a named moment) |
| Size arc kept | shot sizes follow the treatment's arc (tolerance of one step) |
| One rhythm break | exactly one; it sits on the key moment |
| Plant paid off | every plant has its payoff in the scene (or a later scene, named) |
| Line placement | at least one line plays off its speaker when the treatment asks for it; never one whose lip sync matters |
| Variety | no two adjacent cards with the same size + angle + arrangement on the same person |
| Motivated cuts | every `cut_in` has a motive (action, look, line, sound) |
| Ending | the last card is the treatment's ending image |
| Sound | the sound map has a state change at the turn |
| Feasibility | no high-risk Veo flag left unaddressed |

Weights start equal and are tuned on the gold set against the person's A/B (Phase 10). The score explains itself:
every point names the card and the signal.

## 7. Knowledge: `film_grammar` and the device library

A new knowledge base `src/libs/hiru_ai/knowledge_bases/adam/adam_film_grammar/` (the `craft` KB stays as it is for the
agents that use it):

- **Principles** (about 15 sources): one file per source in §3, written as paraphrased rules with when-to-use and
  when-not, no long quotes.
- **Device library** (about 40 entries), one per device: what it does to the viewer, when to use it, when not to, the
  allowed kind (§6.1), Veo feasibility (good, risky, post-only), how to write it on a card, and an example from a Hiru-style
  scene. A first list: baseline before the break · smile that outlives the eyes · line over the listener · reaction
  before the cause · plant and payoff · object as emotion (a cup gone cold) · hands tell the truth · subjective sound
  drop · silence before the key line · pre-lap into the next scene · sound arriving before its picture · rack focus to
  separate · push-in on realisation · pull-out to isolate · high angle to make small · low angle for authority ·
  foreground frame (a doorway, a shoulder) · negative space for absence · empty frame after an exit · POV insert ·
  reveal by camera move · held wide in an intimate moment (distance as respect) · match cut · mirror composition
  (same framing, new meaning) · weather or light echoing feeling (only as given) · walk-and-talk · turning one's back ·
  standing up and sitting down as power · the unanswered look · interrupted gesture · the delayed reaction · cut on
  the look · enter late · leave early · the button · callback framing · the long take on the actor · intercut
  phone call (both ends; only when both are present in the script) · contrast cut (warm → cold) · pillow shot.
- **Hiru house drama notes**: the family's authority, respectful address, how marriage pressure plays on Sri Lankan
  television, what a teledrama audience expects (and when to surprise them). Written with the person.
- **Veo feasibility notes**: what renders well (faces, slow push-ins, hands on simple props, shallow focus, golden
  light), what is risky (readable text, mirrors, fast hand work, many faces, two people touching), and the workarounds.

## 8. The gold set and the evals

The gold set is the heart of quality: a system can't get better than the yardstick it is judged by.

1. **15 scenes** from Hiru scripts covering: a call that breaks a mood (the test scene), an arrival, an argument, a
   silent scene, a confession, a group scene, a walk-and-talk, a scene with a STORY NOTE, a comedy beat, a scene with
   narration, an exit watched, a scene in one wide place, a scene in a vehicle, a night scene, a song or prayer.
2. For each: the **master breakdown**, written by a Hiru director (or the person, with the team) in the card format
   of §5.1, plus a one-paragraph director's note on *why*. The person's 2026-11-04 breakdown is kept as the
   "average" reference for the test scene; §9 is a first draft of its master.
3. **Evals** (`hiru-ai eval`): scripted cases per agent (the repo standard); code metrics on every gold scene
   (fidelity 0 breaks, overruns, score signals); live runs only when a person starts them.
4. **Blind A/B** in the interface: two plans side by side (classic vs Adam, or Adam vs master), unlabelled, judged on
   Murch's order and "I felt I was there", 1–5 each. Results recorded in this folder's `IMPLEMENTED.md`.

## 9. The test scene, as Adam should plan it

The first gold master draft, and the north star for every stage.

**Analysis.** About: a daughter's freedom ends with one phone call. Value: warmth → dread. Wants: Anudi *to enjoy*,
then *to obey*, then *to hide*; Dasun *to amuse her*, then *to understand*. Baseline: blocks 0–1. Break: the father's
"marriage". POV: Anudi's until "See you", then Dasun's. The audience knows what Dasun doesn't (irony) from the call to
the end. Key moment: the silence after "marriage".

**Treatment ("intimate, then distant").** Concept: we make the viewer lose the warmth with her, then be left behind
with him. Sizes: MW → CUs as the call isolates her → ECU at the break → wide on Dasun alone. Sound: the warm place
narrows to the phone and her breath, then the world returns without her. Plant: her phone face-down on the bench;
payoff: she turns it face-down again. Rhythm break: the silence (shot 8). Enter late: mid-laugh. Ending image: Dasun
and the empty space beside him.

| # | Card | Tier | Take | Purpose |
|---|---|---|---|---|
| 1 | MW two-shot, eye level, slow push-in. Mid-laugh; her phone face-down on the bench between them. Warm ambience. | S + E (plant) | 6 | The world before it breaks |
| 2 | CU Anudi, Dasun's shoulder soft in the foreground. She laughs, tucks her hair. | E (baseline) | 4 | Her happiness at full strength |
| 3 | CU Dasun mid-story, glancing to check she's laughing. A buzz is heard before the cut; his eyes flick down. | E + sound leads | 4 | Gives him a stake |
| 4 | INSERT phone vibrating on wood; the screen lights. The laughter dies. (Name added in post, or by her reaction.) | S | 4 | The interruption |
| 5 | MCU Anudi sees who it is, still smiling, a small "it's Dad" look to Dasun; answers. | S | 6 | She is still relaxed |
| 6 | OTS onto Dasun; he politely looks away and waits. | I (listener) | 4 | He doesn't know yet, and we will |
| 7 | CU Anudi, slow push-in. The father's voice, thin through the phone. On "marriage" the smile stays a beat after her eyes change; ambience drains; Dasun goes soft behind her. | S + E (subjective sound, rack focus) | 8 | The turn |
| 8 | ECU eyes, locked-off. Only her breath. Her eyes drop. | I (hold, the rhythm break) | 4 | Let it land |
| 9 | MCU, slightly high angle. A breath. "I'll come, Thaththe." Quiet, dutiful. | S | 4 | Obedience, made small |
| 10 | INSERT hands: her thumb ends the call; she turns the phone face-down again. Ambience creeps back. | S + E (payoff) | 4 | The same gesture now means something |
| 11 | CU Dasun, his smile fading as he reads her. | I (reaction) | 4 | His face shows what she hides |
| 12 | Reverse OTS onto Anudi. She turns to him; the smile she puts on stops at her eyes. "See you." | S | 6 | The mask |
| 13 | MW on Dasun, locked-off. She takes her bag and walks out of frame; the camera stays with him; the world's sound carries on. | S + E (empty frame, POV handover) | 8 | Left behind: the button |

Total 66 s. Nothing in it is new story.

## 10. Phases

Each phase ends with its exit checks and an update to `IMPLEMENTED.md`. `script_split` and its parity fixtures stay
green in every phase.

### Phase 0: the `adam` folders and the yardstick
1. **The `adam` folders** (§5.0): an empty `adam/` with its `group.yaml` in each layer (and `README.md` in
   `systems/adam/`); group discovery in the registry; the `--group` options on `list`, `new` and `remove`; the `adam_` id rule in `validate`; the new import-linter contracts; the
   removal test. No Adam behaviour yet.
2. **The yardstick:** the gold set (§8.1–2) with the person: at least 5 masters before Phase 3, all 15 before Phase 10,
   in `tests/eval/adam/`. The rubric and the A/B form. A baseline: `script_split` run on the gold scenes (live, a person
   starts it), and its plans stored.
**Exit:** `hiru-ai validate`, `python scripts/lint_imports.py` and `tests/parity` green with the empty `adam` folders in place, and
nothing outside the `adam` folders changes behaviour (the registry lists exactly the same parts as before); a scaffolded
`adam_example` agent placed outside `agents/adam/`, or one importing an existing agent, is refused; 5 masters in the card format;
baseline scores recorded.

### Phase 1: contracts and code
`contracts/adam/` (§5.1), the steps `adam_fidelity`, `adam_fit`, `adam_continuity`, `adam_score`, `adam_feasibility`,
with tests built from the gold masters (each master passes fidelity and scores above the baseline plans).
**Exit:** every gold master passes; a hand-made plan with an invented line, person or event is refused with its reason.

### Phase 2: knowledge
The `adam_film_grammar` KB: principles, the device library (§7), the house notes and the Veo notes; `hiru-ai ingest adam_film_grammar`.
**Exit:** 40 devices with all fields; `search_kb` finds the right device for 10 probe questions.

### Phase 3: the thinking (analyse, conceive, imagine)
`adam_dramaturg`, `adam_director`, `adam_moment_writer`, with scripted evals per agent and few-shot examples from the gold set.
**Exit:** on 5 gold scenes, the moment lists pass fidelity and a person judges ≥ 4 of 5 treatments "a real director's
idea"; the three treatments of a scene differ (a code check on size arc, POV and sound concept).

### Phase 4: the cards (stage, design, sound)
`adam_blocker`, `adam_shot_designer`, `adam_sound_designer`; `adam_fit` and `adam_continuity` run on the output.
**Exit:** the test scene's cards read like §9 to the person; 0 fidelity breaks and 0 unreported overruns on the gold set.

### Phase 5: screening
The `adam_screening` panel, `adam_reviser`, selection by `adam_score`.
**Exit:** the revised plan wins on score in ≥ 60% of gold scenes and never loses fidelity.

### Phase 6: the system, storage and the switch
`systems/adam/shot_planner_adam`, `services/shot_planner_adam`, the jobs, and schema v11 (the one shared migration, §5.0):
`shots.card jsonb`, `shots.planner text check (planner in ('classic', 'adam')) default 'classic'`,
`scenes.adam jsonb` (analysis, treatments, the chosen one, moments, sound map, report),
`productions.settings.shot_planner` (`classic` | `adam`). RLS and pgTAP rows as the repo rules say. The structure build
calls Adam instead of `script_split` only when the setting says `adam`.
**Exit:** a production set to Adam builds end to end on localhost; one set to classic is byte-identical to today.

### Phase 7: after the plan (shot_producer)
When a shot has a `card`, the intent agent is skipped (the card already has purpose, what we see and performance); the DoP
reads the card's camera fields as decisions (as it reads a person's beat notes today); `serialize` carries performance,
the line placement (an off-speaker line is voiced off screen, with the speaker never shown talking) and the sound cues
into the Veo prompt. Prompt lint learns the new fields.
**Exit:** the test scene's 13 prompts render (live, a person starts it) and a person judges them against §9.

### Phase 8: the interface (`hiru-ai-studio-interface`, all in `src/features/adam/`)
Everything lives in `src/features/adam/` (`api.ts`, `types.ts`, `components/`, `lib/`), read through its own `api.ts`. The
existing scene and director features gain only the mount points (a tab or a button that renders an Adam component).
- **Scene → "Director's treatment"** card: concept, POV, size arc, sound concept, plant/payoff, ending. Three
  treatments as options; switch re-plans the cards.
- **Shot cards** in the person's breakdown format: number and title, size and angle, bullets for what we see, the
  line (rendered with `spoken()`), purpose, sound. Chips per moment: "Script", "Implied", "Added by director" (removable;
  never re-added after removal).
- **Plan with Adam** on a scene; **Compare** (classic vs Adam, side by side, the blind A/B form).
- The scene header shows the runtime the treatment needs and the envelope (§12 D2). No credits or costs anywhere.
**Exit:** `npx next typegen && npm run check && npm run format:check`; the person can read, edit and compare on the test scene.

### Phase 9: the editorial layer (take vs use)
The final-cut assembler trims a take to `use_s` (with `in_s`), and lays sound across cuts (pre-lap, J and L cuts) from the
sound map. Optional by setting until it is proven.
**Exit:** a scene with a 2 s reaction cut from a 4 s take, and a pre-lap into the next scene, plays correctly.

### Phase 10: A/B and the default
Blind A/B on all 15 gold scenes; the score weights tuned against the person's judgements; the §1 targets checked. Only
then does a person decide whether Adam becomes the default for new productions.

## 11. Cost, time and risk

- **Calls per scene:** about 11 (dramaturg, director, moments, blocker, designer, sound, four critics in parallel,
  reviser) against about 7 today; the high tier on five of them. Static prompts are cached. Scenes run in waves of 4 within
  the time budget, with fresh deliveries as `script_split` does. Measured in Phase 6.
- **More shots per scene** (the test scene goes from about 5 to 13) means more generation, more chances for a face to
  drift between takes and a longer scene. The treatment can choose a sparser plan; Phase 9 trims make dense plans cheaper
  on screen time.
- **Runtime vs the envelope** (§12 D2): the master version of the test scene is 66 s. A 60 s episode can't hold many scenes
  like that. Adam reports what the treatment needs and offers a tighter treatment; it never squeezes dialogue.
- **Off-speaker lines:** the voice must match the character's voice in their on-screen shots. Each prompt needs the same
  voice description for that person; checked live in Phase 7.
- **Over-direction:** a scene stuffed with devices is as bad as a flat one. The treatment names its devices; the score
  checks the one rhythm break; the opportunity critic may also remove.

## 12. Decisions for the person

| # | Question | Recommendation |
|---|---|---|
| D1 | The three tiers and the allowed kinds (§4, §6.1) | **(default)** Yes, as written; every elaboration labelled and removable |
| D2 | Runtime: does the scene's length follow the treatment, or must it fit the envelope? | **(default)** The treatment proposes; the scene header shows "needs 66 s · envelope 40 s"; the person chooses a tighter treatment or a longer episode |
| D3 | Three treatments per scene: does a person pick, or the score? | **(default)** The score picks; the other two are one click away |
| D4 | Trims in the final cut (Phase 9) | **(default)** Yes, after Phase 8 |
| D5 | The switch | **(default)** A production setting (`classic` by default) plus "Plan with Adam" per scene |
| D6 | Who writes the gold masters | The person and a Hiru director; Claude drafts, they correct |
| D7 | Storage | **(default)** New columns (`shots.card`, `shots.planner`, `scenes.adam`); `shots.framing` keeps its 7 values through the mapping in §5.1 |
| D8 | Models | **(default)** OpenAI only (fixed decision); the high tier for the thinking and design agents |
| D9 | The name | `shot_planner_adam` in code, "Shot Planner Adam" in the UI (from the person's "shot-planer-adam") |
| D10 | Where Adam lives | **(default)** An `adam` subfolder inside each layer folder (`systems/adam/`, `agents/adam/`, …) and one per repo area (§5.0); shared files limited to the one migration, the build branch and the function registration |

## 13. Sources

Books: Murch, *In the Blink of an Eye* (2001); McKee, *Story* (1997); Weston, *Directing Actors* (1996); Katz, *Film
Directing Shot by Shot* (1991); Proferes, *Film Directing Fundamentals* (3rd ed., 2008); Mackendrick, *On Film-making*
(2004); Truffaut, *Hitchcock/Truffaut* (1967); Lumet, *Making Movies* (1995); Block, *The Visual Story* (2nd ed., 2008);
Mascelli, *The Five C's of Cinematography* (1965); Arijon, *Grammar of the Film Language* (1976); Chion, *Audio-Vision*
(1994); Dmytryk, *On Film Editing* (1984); Bordwell & Thompson, *Film Art*.

Papers: Chakrabarty et al., *Art or Artifice?* (CHI 2024) https://arxiv.org/abs/2309.14556 ; Lu et al., *LLM Discussion*
(2024) https://arxiv.org/abs/2405.06373 ; Wu, Zhu & Shou, *MovieAgent* (2025) https://arxiv.org/abs/2503.07314 ; Xu et al.,
*FilmAgent* (2025) https://arxiv.org/abs/2501.12909 ; Cemri et al., *Why Do Multi-Agent LLM Systems Fail?* (2025)
https://arxiv.org/abs/2503.13657 . Google Cloud, *Ultimate prompting guide for Veo 3.1*
https://cloud.google.com/blog/products/ai-machine-learning/ultimate-prompting-guide-for-veo-3-1 .
