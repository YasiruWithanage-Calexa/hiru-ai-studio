# plan/2026-11-12b: what is built

## Phases 1 to 6, built offline 2026-11-12 (both repos, uncommitted, $0, no model called)

Built on top of plan/2026-11-12 (house rules), which was committed first (`8e0a2c8`), so H-13 is a house rule (D6).
D2, D3, D4, D5 taken as recommended. D1 taken with one change, below. D7 waits for phase 7.

### Phase 1: the reader

- `contracts/breakdown/schema.py`: the wire shape `SeriesW` (`SeriesFieldW`, `GenreW` with `FacetW` main/thread,
  `WorldW`, `ThemeW`, `LeftOutW`); pointers are `lines {start, end}` like every breakdown wire. `Breakdown.series`
  (default None) holds the checked block.
- `hiru_ai/agents/breakdown/breakdown_series/`: tier `breakdown` (gpt-6.1-sol, medium), the lab's prompt adapted to the
  wire shape and to "you are given the parts that can say this"; evals: the real lab answer (converted) and an empty
  one; tests beside it. Registered on `breakdown_build`'s manifest.
- `contracts/breakdown/run.py`: `Calls.series` (optional: None = not read); `create` starts it in a thread beside the
  continuity call and collects it after; `read_series` checks the answer onto `bd.series`. A failed call or nothing
  found is a note on the job, never a stop.
- The message (`series.message`) is NOT the whole document: each document's title page, overview and `other` sections
  (the split's labels) plus its first 60 lines, or its first 200 lines when it has none of those sections; at most 600
  lines in all. Numbers are the breakdown's own, gaps shown as `...`. On a long script this keeps the call cheap.

### Phase 2: the checks (`contracts/breakdown/series.py`)

`check`: the quote is in its lines; `says` has no digit and no length/count word; `says` passes
`safe_depiction.blocking`; a facet's words are in its quote; a world place matches a place card (else kept without an
id). A dropped field is a non-blocking `Finding(code="series")`. `checks.run_all` now keeps `series` findings when it
replaces the memory's findings (they come from the reader, not a check that runs again).

### Phase 3: production memory

`fill.memory_rows` adds `series.memory_rows(bd)`: one `fact` row per kept field, topic `series`, the whole production,
attributed to the document its lines are in. The genre row says `Genre: action, crime thriller; love as a thread.
<the reader's sentence>`. A premise whose quote has a gated word is not written (`planner_only`).
`contracts.memory.genre_of(rows)`: the phrase for picture prompts ("action and crime thriller"): a person's row first,
then approved, then draft, never rejected; the facets before the first `;` or `.`, at most two; "" when it has a number
or a gated word. `core.memory.genre()` (the shot producer's technique search) finds the new row with no change.

### Phase 4: the packet

`packet.assemble` adds `J_series` (the block without `left_out`, plus `this_scene`: place and its region by name and
id, the scoped rule ids, the mood). `incomplete()` never looks at it. `contracts/raphael/packet.render` and
`contracts/breakdown/render.render` print it first (`series.render_lines`); with no `J_series` both are byte for byte
as before. Stored packets get it at the next breakdown build or scene refresh.

### Phase 5: the planner

House rule `H-13` "Genre lens" (`house_rules/genre_lens.md`, `default`, topic `genre`); `raphael_planner` and
`raphael_cinematic` subscribe (`[objects, sound, genre]`). Both also have the `production_memory` middleware, so the
series facts reach them a second time, at the end of the user message.

### Phase 6: the prompts and the interface

- Frame: `frame_brief(..., genre="")` / `frame_prompt(..., genre="")`; `lead_line(genre)` swaps "television drama" for
  the phrase; "" keeps `LEAD` byte for byte. The lead stays `fixed` (not in `POLISHABLE`). Callers: the API preview
  (`Loaded.genre`, read with the scene through `repos.direction.series`) and the renderer (`frame_render` `Scenes` reads
  it once per job from the memory port; `frame_compose.World.genre`). Preview and render read the same rows.
- Video: `serialize.logic.medium_style(rules, genre)` uses the new `medium_style_genre` rule of the Veo schema;
  `Context.genre`, `ProductionInput.genre`, set in the shot producer from `memory.entries(ctx)`. The shot writers'
  FORMAT line reads the same.
- Interface: `ScenePacket.series` (`toScenePacket` reads `J_series`), a "The drama" card at the top of the packet view
  (facets as chips, main or thread; each part's words; where the scene sits). There is no production-memory panel in
  the interface; the series facts show as chat "used" chips like any entry.

### Change from the plan

- **D1:** the prompts read the genre from the production-memory `series` rows, not from the breakdown memory: every
  prompt caller can read those rows cheaply, and a person's edit or rejection of the row changes every prompt. The
  packet's `J_series` is the breakdown's block (what the documents said), like its direction rules.
- **Not changed:** `src/services/frame_render` and `src/services/shot_producer` (the older ported copies) keep the
  general wording; the live paths are `hiru_ai/systems/frame_render` and `hiru_ai/systems/shot_producer`. Canon
  reference sheets stay "television drama" (D4).

### Tests

`tests/breakdown/test_series.py` (message, checks, absent-safe, packet, Raphael rendering, memory rows, `genre_of`),
`tests/contracts/test_frame_brief.py` (lead), `tests/hiru_ai/test_series_prompts.py` (video style, FORMAT, renderer
World, H-13), `tests/api/test_production.py` (a series row changes the shot screen's frame prompt and nothing else), the
agent's own tests; interface `packet-view.test.tsx`.

### Checks

Backend: ruff (3 errors, all in files this plan did not touch), mypy clean, `hiru_ai validate` clean, `catalog`
regenerated, `lint_imports` (2 broken contracts, both before this plan: `api.services.media_thumbs`, the David agents),
pytest (full run, 25 min): 5,598 passed, 31 failed; 28 of the 31 fail the same on the clean tree (the removal and
isolation lists that name schema files, the API frame/take/look tests, the parity recordings, Raphael's caps). The other
3 were this plan's and are fixed: the Raphael render test moved to `tests/raphael/test_series_packet.py` (only raphael
folders may import Raphael), and `test_implied_packet.py` now expects H-12 and H-13 on both Raphael stages. Interface: tsc, eslint clean; vitest 1 failure that fails on the clean tree too
(`raphael-panel.test.tsx` caps); `format:check` fails on 29 files on this machine for CRLF line endings (my files pass
with `--end-of-line auto`; two other files have real style issues, not touched here).

## Phase 7: run 2026-11-12, $1.0407 of the $1.50 cap

Run as a lab that writes nothing to the database (`lab/series_block/live_check.py`, output
`lab/series_block/runs/live_20261112_135757/`): the breakdown rebuilt from the PDF with the product's agents ($0.1793,
5 calls, the series call $0.0185), Raphael on Scene 1's packet ($0.2105, 6 calls), 15 draft frames composed by
`raphael_write.write` + `frame_compose` with the production's real canon sheets (read only) and painted at draft quality
($0.6508). Re-planning in the product would have replaced the person's current Scene 1 shots.

What passed:
- The reader kept genre (action main, crime thriller main, love thread), tone, world, theme and premise; left out the
  running time, the evidence label, the document label, the repeats and the visual treatment; no finding.
- `J_series` is first in Raphael's packet; Raphael named the facet ("Play the crime-thriller facet through withheld
  information and sustained observation"). Its arc and moments darkened: "Bleak attention tightening into dread",
  "Unresolved threat", "Exposed and watchful" (11-11: "Concern becomes fixed attention", "Routine under oppressive rain").
- Every frame prompt opens "a Sri Lankan action and crime thriller"; no number or gated word in any prompt.

What did not change enough:
- The pictures look like the 11-11 ones. The lines that set the look are unchanged in kind: "Soft overcast dawn light
  ... gentle contrast and diffuse shadows", "Grade: Low saturation, warm earth retained, soft highlights". Raphael read
  the Village direction ("natural light") as soft, flat light and put the thriller into what is withheld, not into light.
  The lead word alone does not move the image model.
- The two black title plates (S14, S15) were painted as photographs (two men under an umbrella; an empty canal). On 11-11
  they came out black with the general lead. One sample: the genre lead may be the cause, with the location plate
  attached; a graphic plate should not be painted at all.
- S07 (the key in Nimal's fist) shows a standing man holding it out: the prompt says he lies on the bank. Not this plan's.

### Follow-up, built and re-run 2026-11-12 afternoon (the person's yes)

Built: H-13 v2 (`house_rules/genre_lens.md`: in a thriller scene light with direction and contrast, deep shadow,
"natural light" never means soft, flat, even light); D7 (`StoredRaphael.mood`, set from the packet's `F_feeling.mood` by
the Raphael graph; the frame brief adds "Scene mood: ..." as a part that is never cut); black plates by code
(`contracts.frame_brief.black_plate`, `World.plate`, `frame_compose.black_png`, `frame_render.graph.black_plate`: a shot
whose blocks are only a cut to black or a title card is stored as a black PNG, no model). Tests added; the related suites
pass except 4 that fail on the clean tree.

Re-run (`runs/live_20261112_144933`, the breakdown reused, cap $1.00): Raphael $0.1707; it now writes the thriller into
the light ("directional dawn light, deep wet shadows", "gate recess held dark", "Controlled saturation, deep blacks").
Four frames painted ($0.21): storm sky, a black gate recess, clearly more contrast. Both title plates black, made by
code. Six frames (S05-S10) FAILED in the image model with no recorded cause (the lab printed only the adapter's message;
it now logs the cause); the lab counted each at its $0.10 worst case, so S11-S14 were not painted to keep the cap. A
failed image call is normally not billed: the true spend is likely about $0.38, not $0.98. Still open: every lighting
line opens with the camera panel's preset label "Dawn, soft ambient:", which fights the planner's light.

Earlier next steps, for the record: (1) H-13 v2 that says the genre shapes contrast, shadow and exposure inside a scoped palette
("natural light" is not "soft, flat light"), and that the colour script's grade carries it; (2) D7, the packet's mood
words beside the frame's `Mood:`; (3) black/graphic plates made by code, never painted. Each is a small change and a
Scene 1 re-run (about $0.85).
