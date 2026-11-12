# The drama's identity reaches every scene: genre, tone, world, theme (plan/2026-11-12b)

Revision 2 (2026-11-12, afternoon). Phase 0 (the lab) is done and paid ($0.0204, one call). Phases 1 to 6 are built
offline, both repos, uncommitted: see [IMPLEMENTED.md](IMPLEMENTED.md), which also records one change to D1 (the prompts
read the genre from the production-memory rows). Phase 7 is a paid live check, the person's yes first.

**Read §1, §2 and §3 first if you are a new chat picking this up.** This plan shares files with
[plan/2026-11-12](../2026-11-12/PLAN.md) (house rules), which is being built now: see §6.

## 1. Why

The person asked (2026-11-12), looking at the storyboards of *hiru short combined 1* (Ekama Sakshiya): the script says
**Genre: Action / Crime Thriller / Love** and **Tone: Grounded South Indian realism with commercial action energy**, but
the shots do not feel like a crime thriller. Scene 2 (Colombo, night, sodium light) looks the part; Scene 1 (a body found
at a village canal at dawn) looks like a calm rural drama.

What the stored outputs of that run show (read-only queries, 2026-11-12):

1. **No reader keeps the Overview lines.** The PDF's page 2 has Genre, Setting, Tone and Tagline. The source memory holds
   them (lines 9 to 12). The breakdown's direction rules start at line 25 (`D01` Colombo palette): the split reads HOW to
   make the drama, and "Genre: ..." is WHAT it is, so it has no slot. `production_memory` has 14 entries for the
   production, none with topic `series`, none a `fact`; no production in the database has ever had one.
2. **So every fallback fires.** `memory.genre()` (`hiru_ai/core/memory.py:119`) returns its default "Sri Lankan
   television drama". Even with a genre, the prompts would not use it: the frame lead (`contracts/frame_brief.py:51`), the
   video FORMAT line (`steps/serialize/shots.py:85`) and the Veo medium style (`steps/serialize/schemas/
   clip_schema_veo_3_1.yaml:22`) are fixed text.
3. **Scene 1 followed the only direction it had.** Its packet has `D02` "Village palette - Warm amber and earthy red.
   Locked-off frames, natural light and longer silences" with nothing beside it. The first-frame prompts say "Soft overcast
   top-light; low contrast", "Grade: Restrained warm earth tones", "Mood: Routine under oppressive rain". The packet's mood
   was "bleak, restrained, ominous"; Raphael's clip notes say "unhurried workday ... feel ordinary", "without a dramatic
   gesture". Raphael's prompts have no line about genre.
4. **Scene 2 got the look from its own script line** ("Colombo streets shine under rain and sodium lights") and the
   Colombo palette, not from the genre. Its notes are as flat ("routine journey").

## 2. What the lab proved (phase 0, done)

`lab/series_block/` (prompt.md, run.py), run 2026-11-12 on `ekama_sakshiya_screenplay (clean).pdf`: one structured call
(`gpt-6.1-sol`, medium, the `breakdown` tier's model) over the numbered lines, code checks, then `J_series` added to the
packets built from the last pipeline run's breakdown memory (`lab/two_memories/runs/pipeline_ekama_sakshiya_screenplay_
clean/07_memory.json`, line numbers checked equal) and placed in Raphael's real opening message.

| | |
|---|---|
| Cost | $0.0204 (2,051 in, 1,632 out, 37.5 s); worst case $0.083, cap $0.25 |
| Code findings | none: every quote in its lines, no number or gated word in any `says`, every facet in its quote |
| Genre | action (main), crime thriller (main), love (thread), line 9 |
| Tone | "Ground the characters in South Indian realism while making the action energetic and crowd-pleasing.", line 11 |
| World | Colombo -> L01, Mahawewa village -> L02, line 10 |
| Theme | "Only one person knows the truth." (the tagline's meaning; quote kept, `si-Latn`), line 12 |
| Premise | "... after witnessing a crime against his closest friend ...": the reader removed "murder" and the sum; `planner_only` because the quote has a gated word, lines 14-16 |
| Left out, with reasons | "A 4.5-minute crime thriller" (running time), "Evidence: C-17" (story clue), "Original screenplay and visual treatment" (label), three cover lines said again, the whole visual treatment (another reader's) |

Not proved: that Raphael USES the section, and what it does to the frames. That is phase 7.

One fault found: the scene's place is `L03` (the canal), the world names the regions `L01`/`L02`. The scene's line must
say which region its place is in (`Entity.within`), or the planner cannot join the canal to "Mahawewa village".

## 3. The design

```
documents ─► breakdown_series (one call, after the merge) ─► code checks ─► Breakdown.series (breakdown memory)
                                                                              ├─► production_memory: `fact` / `series` rows
                                                                              │     → memory.genre(), the 5 subscribed agents
                                                                              ├─► every packet: J_series (+ this scene)
                                                                              │     → Raphael (SERIES first inside <packet>)
                                                                              └─► genre_phrase() → frame lead, video FORMAT
                                                                                    and medium style
```

### 3.1 The reader

A new agent `breakdown_series` (`hiru_ai/agents/breakdown/breakdown_series/`), tier `breakdown`, prompt = the lab's
`prompt.md`. It reads the MERGED document (`memory.merge`), so its line numbers are the breakdown's own. It runs once per
build, beside the continuity call, as `Calls.series` in `contracts/breakdown/run.py`. A failure is a note on the job
("the drama's genre could not be read"), never a stop: the block is then empty and every fallback stays as today.

The reader judges; code checks (§3.2). It decides what each line is, weights the genre's facets (`main` / `thread`),
writes `says` in plain words without numbers or gated words, and lists what it left out and why. That last list is what
keeps a running time, a prop, a label or a direction out of the block (the person, 2026-11-12: the reader identifies, it
does not copy).

Wire shape (`contracts/breakdown/schema.py`, `SeriesW`): `genre {found, says, quote, line_from, line_to, facets[{name,
weight}]}`, `tone`, `world {..., places[]}`, `theme {..., language}`, `premise`, `left_out[{quote, line_from, line_to,
why}]`. Stored shape (`Series`, on `Breakdown.series`, default empty): per field `says`, `quote`, `lines`, provenance
`script`; `genre.facets`; `world.places[{name, id}]`; `premise.planner_only`; `left_out`. A field the reader did not find,
or code dropped, is `{"empty": "<why>"}`, like every packet field.

### 3.2 The checks (code, `contracts/breakdown/series.py`)

From the lab, unchanged: the quote lies in its lines (spacing and case aside); `says` holds no digit and no duration or
count word; `says` passes `safe_depiction.blocking`; a facet's words are in its quote; a world place is matched to a place
card by name (kept without an id when none matches, with a finding). A failing field is dropped and reported as a
non-blocking `Finding` on the breakdown, so it shows where the breakdown's other findings show.

### 3.3 Production memory

`fill.memory_rows` adds one `production_memory` row per kept field: topic `series`, strength `fact`, applies to
`production`, `says` = the reader's words, `quote` = the document's words, status `draft`, source `reader`. Then, with no
other change: `memory.genre()` finds the genre row (its quote has "genre"); the `production_memory` middleware gives facts
to every subscribed agent (cinematographer, shot_writer, look_drafter, editor, sound_designer, chat_answerer); Zora and
Sable can see it. `premise` is written only when `planner_only` is false.

### 3.4 The packet

`packet.assemble` adds `J_series`: the stored block (without `left_out`) plus `this_scene`:

```json
"this_scene": {"place": "L03", "region": "L02", "scoped_rules": ["D02", "D12", "D13"],
               "mood": ["sombre", "restrained", "unsettling"]}
```

`incomplete()` never waits on it. `contracts/raphael/packet.render` prints it FIRST inside `<packet>` (it is the same for
every scene of a production, so the cached prefix grows by one constant block):

```
SERIES (what this drama is; play every scene as part of it)
Genre: crime thriller (main), action (main), love (thread)
Tone: Ground the characters in South Indian realism while making the action energetic and crowd-pleasing.
World: Colombo [L01], Mahawewa village [L02]
Theme: Only one person knows the truth.
Premise: ...
This scene: Mahawewa Canal [L03] in Mahawewa village [L02]; scoped direction D02, D12, D13; mood sombre, restrained,
unsettling.
```

`contracts/breakdown/render.py` (the person's packet view) shows the same section.

### 3.5 The planner reads the scene through the genre

One instruction, given to `raphael_planner` and `raphael_cinematic`:

> The production's genre and tone are the lens for every scene. A scoped direction (a place's palette, a love-scene lens)
> sets the look; the genre sets the tension. Name, in the treatment's approach, which facet of the genre this scene plays
> and how it shows in light, frame and timing. Do not soften a scene's mood below what the packet says.

As house rule **H-13 "Genre lens"** (`kind: default`, topics `[tone, visual]`) when plan/2026-11-12 phase 1 has landed
(D6); otherwise as one paragraph in both prompts, moved into H-13 later.

### 3.6 Frame and video prompts

`contracts/breakdown/series.py: genre_phrase(series) -> str`: the `main` facets in the reader's order, at most two,
joined ("crime thriller and action"), each through `safe_depiction.blocking`; "" when there is none. Only `genre` reaches
a picture prompt: tone, theme and premise are for planners (D2).

- **Frame:** `frame_brief(..., genre="")`. LEAD becomes `"Photorealistic still frame from a Sri Lankan {genre or
  'television drama'}, shot on a cinema camera ..."`, still tagged `fixed`, so `prompt_writer` never rewords it. BOTH
  callers pass it: the API's preview (`api/routers/production.py`) and the renderer (`frame_render` pipeline /
  `steps/frame_compose`), so the text a person reviews is the text that is painted.
- **Video:** `FORMAT: Sri Lankan {genre or 'television drama'}, live action, ...` in `steps/serialize/shots.py`, and the
  Veo `medium_style` in `serialize/logic.py` the same way.
- **Not here:** canon reference sheets (`contracts/canon.py`) stay "television drama": they are identity references and
  must not carry a genre's light (D4).

The callers read the genre from the production's `series` rows in `production_memory` (approved or draft, a person's
edit first; `contracts.memory.genre_of(rows)`), the same rows the middleware uses, so one edit changes every prompt.

## 4. Phases

| Phase | What | Cost | State |
|---|---|---|---|
| 0 | Lab: one reader call on Ekama, checks, `J_series` in Raphael's opening | $0.02 | done |
| 1 | Reader: `SeriesW` / `Series`, agent `breakdown_series` (manifest, prompt from the lab, evals with the Ekama lines as a fixture), `Calls.series`, call in `run.create` beside continuity, failure as a note; `breakdown_build` wires the agent | $0 | |
| 2 | Checks: `contracts/breakdown/series.py` (`check`, `genre_phrase`); tests: quote not in lines, a number in `says` ("4.5-minute"), a gated word ("murder"), a facet not in its quote, an unmatched place, an empty answer | $0 | |
| 3 | Memory: `fill.memory_rows` writes the `series` facts; `contracts.memory.genre_of(rows)`; `memory.genre()` uses it; tests (rows written once, a rebuild does not duplicate them (`core/memory` dedupe), a rejected row is not used, a person's row wins) | $0 | |
| 4 | Packet: `J_series` + `this_scene` with region; Raphael and packet renderers; tests (present in every packet, constant bytes across scenes except `this_scene`, empty block renders nothing, `incomplete()` unchanged) | $0 | |
| 5 | Planner: H-13 or the prompt paragraph (D6); the Raphael prompt evals still pass | $0 | |
| 6 | Prompts: frame LEAD, video FORMAT and medium style; both frame callers pass `genre`; tests (fallback text byte-for-byte as today with no series, `prompt_writer` leaves the lead alone, preview = render). Interface: the production memory panel lists the `series` facts under "Series"; the packet view shows the section (no new screen) | $0 | |
| 7 | Live check, the person's yes: rebuild Ekama's breakdown (all reader calls), re-plan Scene 1 with Raphael at its own cap, paint Scene 1's draft first frames (low quality). Pass: Scene 1's treatment names a crime-thriller facet; its frames keep the Village palette but lose "routine / low contrast"; Scene 2 does not get worse; no number, running time or gated word in any prompt | about $1.20, cap $1.50 | |

Checks before finishing (backend): `ruff check src tests scripts`, `mypy`, `scripts/lint_imports.py`, `hiru_ai validate`,
`hiru_ai catalog --check`, `pytest -q` (with `ADAM_MODE=staged OPENAI__API_KEY=`). Interface: `npx next typegen && npm
run check && npm run format:check`.

## 5. Decisions

- **D1. Where a person's change lives.** Recommended: the `production_memory` `series` rows. The breakdown's block is
  what the documents said; a person edits or rejects a row in the memory panel, and the packet and prompts read the rows
  (person > approved > draft), falling back to the breakdown block when there are none.
- **D2. What reaches a picture prompt.** Recommended: the genre's main facets only, at most two ("crime thriller and
  action"). Raw tone ("commercial action energy") pushes image models toward glossy, over-styled frames; the planner turns
  tone into light, frame and timing per shot instead.
- **D3. A scene in a different facet** (a love scene in a crime thriller). Recommended: the planner chooses the facet per
  scene and names it in the treatment's approach (§3.5). No new field.
- **D4. Canon reference sheets.** Recommended: stay neutral ("television drama").
- **D5. The other planners** (Jonathan, David, DaVinci, Adam) do not read the packet. Recommended: not in this plan; they
  get the genre only through `memory.genre()` and the subscribed agents. Their own plan if wanted.
- **D6. H-13 or a prompt paragraph.** Recommended: H-13, if plan/2026-11-12 phase 1 lands first; the paragraph is the
  fallback and moves into H-13 later.
- **D7. The scene mood in the frame's `Mood:` line.** Scene 1's "ominous" became "Routine under oppressive rain". This
  plan fixes the planner's reading (§3.5) and expects the mood line to follow; if phase 7 shows it does not, a small
  follow-up puts the packet's mood words beside `look.feeling`.

## 6. Shared files with plan/2026-11-12 (house rules)

That plan has uncommitted changes in `contracts/breakdown/{build,checks,fill,schema}.py`, `contracts/raphael/packet.py`,
`breakdown_build/graph.py`, the manifest and the middleware. This plan touches the same files. Build this plan's phases 1
to 4 after that plan's phase 3 is committed, or on top of its working tree with care; phase 5 waits for its phase 1 (D6).

## 7. Not in this plan

- A production with no genre in its documents keeps today's text everywhere. Asking the person for one at upload is a
  later choice.
- Changing look_drafter or prompt_writer to a larger model (both are `gpt-5-mini` at low effort today).
- The `gpt-5` shutdown on 2026-12-11 for the `high`, `reader` and `author` tiers.
