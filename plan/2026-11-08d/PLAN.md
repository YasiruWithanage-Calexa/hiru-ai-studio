# Shot Planner DaVinci: raw coverage for post-production, planned by an orchestrator (plan/2026-11-08d)

> **Superseded in part (2026-11-08):** the orchestrator (§4) was too slow and never finished in the lab
> ([RESULTS.md](RESULTS.md)). The person chose the staged version: see [PLAN-B.md](PLAN-B.md).

Status: written 2026-11-08; Phase 0 (the free half of the lab) built offline the same day, see [IMPLEMENTED.md](IMPLEMENTED.md) and `lab/davinci/`; no model called. Plain words: [human-read.md](human-read.md). A **new** planner
beside Adam, David and Jonathan; none of them change.

## 1. Why

Every planner today (Adam, David, Jonathan) acts as the **editor making a finished cut**: each moment is shown once, from
one angle, in story order; `use_s` chooses what the edit keeps; `link` (cut / continuous / match) decides how shots join;
the length budget is screen runtime (`jonathan_author/prompts/system.md` lines 26-27, 63).

Hiru TV has an expert post-production team. They do not want a finished cut. They want **raw material**: the same action
from several angles, reactions, inserts, fillers, establishing and B-roll, with handles, so the editor can cut freely.

But the material must still serve a vision. DaVinci therefore plans in two layers:

1. **The intended cut**: how the final scene should look (what Jonathan writes today, as a reference, not a binding edit).
2. **The shoot bin**: every clip needed to build that cut, plus the alternates and extras an editor wants.

And it uses an **orchestrator**, not a fixed pipeline: a director agent decides what to do next, delegates, checks and
repairs only what failed.

## 2. What DaVinci delivers

### 2.1 Intended cut

The treatment (logline, arc, approach, colour script, geography, key image), the sequences, and for each moment the clip
the vision uses and why. Reference for the editor only.

### 2.2 Shoot bin

Each clip carries:

| Field | Meaning |
|---|---|
| `role` | master, single, ots, two_shot, reaction, insert, cutaway, establishing, atmosphere, clean_entry, clean_exit, pov, transition_out, transition_in |
| `covers` | the blocks / lines the clip overlaps (several clips may cover the same moment) |
| `handles` | about 1 s before and after the action, inside the take |
| `take_s` | 4, 6 or 8 s (Veo; `src/lib/veo/timing.ts` in the interface, the backend's clock) |
| `priority` | **must** (the intended cut's primary clip), **should** (alternates, reactions, inserts), **nice** (drone, B-roll, filler, alternate performance) |
| `technique` | from §3, with a one-sentence story reason (`why`) |
| `speaks` | whether the clip performs the line (D2) |
| `slate` | e.g. `12B-3`: scene 12, setup B, clip 3 (D8) |
| `ir` | the full Veo clip IR, as Jonathan's today |

### 2.3 Editor notes

What each clip is for, risky match cuts, techniques left for post (speed ramp, digital punch-in, freeze frame, split
screen) and what was avoided because Veo cannot do it.

## 3. Camera vocabulary

The director may use the full toolbox; every use needs a story reason, and code refuses what Veo cannot do.

| Family | Techniques | Veo |
|---|---|---|
| Aerial | drone establishing, drone reveal / pull-away, top-down, orbit | strong |
| Zoom | crash / snap zoom, slow creep | good; **dolly zoom refused** (unreliable) |
| Moving | dolly in / out, tracking, lead, follow, arc, crane / jib, Steadicam, handheld | one move per clip |
| Pan / tilt | whip pan, slow pan reveal, tilt reveal | good |
| Angle | low, high, Dutch, worm's eye, overhead | good |
| Focus / lens | rack focus, shallow isolation, foreground framing | good; split diopter refused |
| Reveal | push past foreground, pull back, enter a held frame | good |
| Light | silhouette, shadow before the person, flare, light across a face | good |
| Time | slow motion (no dialogue), timelapse, hyperlapse | good |
| Transition pairs | whip out → whip in, match cut, object wipe, focus out → in | both halves planned |
| Post only | speed ramp, freeze, punch-in, split screen | noted for the editor; shoot a clean source |

Existing Veo limits stay refused: readable text, mirrors, fast finger work, bodies in contact, a sharp crowd.

The production's **visual language** (allowed techniques) limits the menu (D3).

## 4. Architecture: an orchestrator

```
                    ┌────────────────────────────────────┐
                    │  DAVINCI DIRECTOR (strong model)   │
                    │  loop: think → call → read → decide│
                    └──────┬──────────────┬──────────────┘
             delegates to  │              │  calls
      ┌────────────────────┘              └──────────────────┐
      ▼                                                      ▼
 WORKERS (called like tools)                     CODE TOOLS (no model)
 coverage_planner(seq)    cheap                  bible_lookup, memory_lookup
 clip_writer(clip ids)    cheap, parallel        check_coverage, check_clock
 continuity_critic(ids)   strong                 check_continuity, check_feasibility
      │                                          entity_state(beat), finish()
      ▼                                                      ▼
 ┌────────────────────────── MEMORY (blackboard) ──────────────────────────┐
 │ story bible · visual language · production memory   read only          │
 │ edit plan (intended cut)                             director writes    │
 │ shoot bin                                            workers write,     │
 │                                                      director approves  │
 │ entity state · scene chain                           code computes      │
 │ work log (calls, results, faults)                    everyone appends   │
 └─────────────────────────────────────────────────────────────────────────┘
                              │ finish()
                              ▼
           intended cut + shoot bin (slates) + editor notes
```

### 4.1 The director

A strong model in a tool-calling loop. It reads the scene, looks up the bible and memory, writes the edit plan and
staging, and then **chooses**: delegate a sequence to `coverage_planner` or plan a hard one itself; send clips to
`clip_writer` in parallel; call the critic where match action is risky and skip it where code already passed; re-send
only the clips that failed. It ends by calling `finish()`.

### 4.2 Workers

| Worker | Model slot | Job | Writes |
|---|---|---|---|
| `coverage_planner(sequence)` | cheap | a sequence's beats → angles, techniques, priorities, who speaks | menu entries in the shoot bin |
| `clip_writer(clip ids)` | cheap | each menu entry → full Veo clip IR (beats, subjects, first frame, sound) | the clips' `ir` |
| `continuity_critic(clip ids)` | strong | what code cannot judge: match action across angles, eyelines in context, whether a technique serves the story | faults in the work log |

A worker sees a whole sequence, not one beat, so neighbouring clips stay consistent.

### 4.3 Code tools

| Tool | Does | Reuse |
|---|---|---|
| `bible_lookup`, `memory_lookup` | cast, places, looks, production memory | canon, plan/2026-11-05d |
| `check_coverage` | every beat has its must clip; counts of should / nice | new |
| `check_clock` | 4 / 6 / 8 s takes, handles fit, 2.2 words/s; reports overruns, never trims | Jonathan's clock checks |
| `check_continuity` | staging, axis, facing, teleports | `contracts/jonathan/checks.py` |
| `check_feasibility` | Veo limits, refused techniques, the visual language | new |
| `entity_state(beat)` | who is where, holding and wearing what | `jonathan_seams` end-state logic |
| `finish()` | writes the result; **refuses until the checks pass** | `jonathan_write` shape |

Every fault names its owner (code mend, clip writer, director), as `jonathan_check` does today.

### 4.4 Memory ownership

Only the director changes the edit plan. Workers write only their own clips. Only code writes entity state and the
scene chain. The work log stops the director retrying the same fix and is traced in Langfuse step by step.

### 4.5 Model slots

Three: director (strong), worker (cheap), critic (strong). Choice is D7.

## 5. Spending cap

- **$5 of model tokens per scene run**, one number in config.
- DaVinci works freely. After each model call, code adds that call's cost to a running total; at $5 the run stops.
- The last call (or parallel group) may take the run a few cents over $5.
- What is saved on a stop is D1. The total is logged with the run.
- No UI, no budget shown to the model. Model tokens only; Veo generation is separate.

## 6. Rules kept

- Dialogue is never trimmed or translated; the clock reports overruns.
- No costs in the UI beyond what the interface's CLAUDE.md allows.
- Adam, David and Jonathan do not change.
- No live model call without the person's yes, each time.

## 7. Decisions (the person's)

| # | Question | Recommendation |
|---|---|---|
| D1 | At the $5 cap: save nothing, or save what it has, marked *incomplete*? | open |
| D2 | Which angles speak the line? | the master and the speaker's single speak; other angles play silent under the chosen audio |
| D3 | Where the visual language (allowed techniques) is set | open: Canon page or chat |
| D4 | Coverage level: always must + should + nice, or a level per run? | **settled in part (2026-11-08): a total, not a level: at most given length + 50% in seconds of takes**; no multiple angles for every shot or action |
| D5 | Storage: extra fields on the shots table, or a new table? | extra fields, so render and the interface keep working |
| D6 | Zora chat editing DaVinci plans | later |
| D7 | Models for the three slots | open |
| D8 | Slate naming convention | the post team's, if they have one |

## 8. Phases

| Phase | Work |
|---|---|
| 0 | **Lab.** One of the person's scenes, under the $5 cap: DaVinci vs Jonathan. Generate a small part (one moment × 3 angles, one transition pair, one drone or B-roll clip) and give it to the post team to cut. |
| 1 | Contracts: clip role, priority, covers, handles, technique, speaks, slate; intended cut; work log. |
| 2 | Code tools (reuse Jonathan's checks). |
| 3 | Worker and director prompts; the orchestrator loop; the cap. |
| 4 | Storage (migration, D5) and scene chaining. |
| 5 | Interface: intended cut view and shoot bin view grouped by role. |
| 6 | Live trial on one episode; the post team's verdict. |

## 9. Risks

| Risk | Answer |
|---|---|
| Veo makes each angle separately, so gestures and timing drift: the editor cannot cut on action | simple actions described identically in every angle, shared first-frame reference; the lab proves it first |
| Lip sync across angles | the speak rule (D2) |
| Long exchanges exceed 8 s | split into overlapping beats with handles |
| The loop wanders | the $5 cap; `finish()` gates; the work log |
| Coverage multiplies Veo cost 2-4× | **the person's rule (2026-11-08): the bin's takes add up to at most the scene's given length + 50%** (60 s -> 90 s, about 15-22 clips), a blocking check in code; priorities decide what is dropped first (nice, then should, never must); the scene cost figure shows the rest |
| Technique overuse looks cheap | story reason required; the visual language limits the menu |

## 10. Not in this plan

Transitions planned across neighbouring scenes (needs reading scene N+1); EDL / XML export of the intended cut; Zora
editing DaVinci plans (D6).
