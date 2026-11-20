# Long lines that fit: Omni's real clock, takes that hold the line, and long lines in parts (plan/2026-11-20)

Revision 1 (2026-11-20). Agreed with the person in chat on 2026-11-19/20. Nothing is built yet. Proved in two labs:
`lab/sinhala_pace/` (how long Omni Flash 1.2 takes to say a Sinhala line) and `lab/line_parts/` (Raphael covering a long
line in parts). Read both READMEs before building.

## 0. Rules for the chat that builds this

- **Only Shot Planner Raphael changes.** Adam, David, Jonathan, DaVinci and the classic planner keep what they have; ignore
  their test failures (memory "Only Raphael stays").
- **No paid call without the person's yes, each time** (model, image, video). Tests run with `OPENAI__API_KEY=` blank.
- **Report an overrun, never trim** a line or a clip. A line's words are the script's: a part is a cut at a sentence end,
  never a re-typed or shortened line.
- **Two repos.** The interface (`hiru-ai-studio-interface`) mirrors the clock (`src/lib/veo/timing.ts`) and the lengths
  (`src/lib/takes/lengths.ts`). Both trees hold uncommitted work: read `git diff` of a file before editing it. Never stash.
- **Two serializer copies** (`hiru_ai/steps/serialize/` and `services/shot_producer/.../engine/`) must write the same
  prompt (`tests/hiru_ai/test_steps_parity.py`, `tests/parity`).

## 1. What the person saw, and what the labs found

"Most of the time I'm seeing too short shots for long dialogs." Four causes, each proved:

| # | Cause | Evidence |
|---|---|---|
| C1 | **The clock is wrong for Omni.** Omni starts speaking at 0.75 to 1.0 s (the clock says 0.5) and pauses 0.75 to 1 s at every sentence end inside a line (the clock counts none). The word rate is fine (~2.6 words/s spoken against the clock's 2.2) | `lab/sinhala_pace` run 1: an 11-word, three-sentence line ran 0.75 to 6.75 s; the clock gave it a 6 s take |
| C2 | **An overrun never stops Raphael.** `checks.clock` reports a spoken overrun with `fix="report"`, so `finish` passes even when a longer allowed take would hold the line | `lab/line_parts` run 001: 5 clips over their takes, Raphael finished |
| C3 | **The length cap squeezes takes.** The cap is 1.5 x the stated length. When the script needs more than the stated length (E01-S04: stated 45 s, the script times at 49 s), there is no room to lengthen a take | Raphael's own editor note in run 001: "only 1.5 s of cap headroom" |
| C4 | **Steps waste seconds.** With 4/6/8/10/15 a line needing 6.1 s costs 8 s; under a cap that waste is what makes Raphael pick 6 | Run 002 (any 3 to 15 s, same cap): **0** clips over, against 5 with steps |

Productions made before plan/2026-11-19 are still 4/6/8 (no `max_take_s`): an 8 s ceiling cuts any line past ~15 words
whatever the clock says. That is plan/2026-11-19's "choose once" on the settings page, not this plan's.

What the person asked for (2026-11-19/20):

1. Steps at 15 s are **4 / 6 / 8 / 10 / 15** (not 4 ... 14).
2. **Drop "Always 8 s"** (the fixed shot length).
3. A per-shot length picker that fits each mode (any style is fine).
4. **A long line is covered in parts on changing angles**, the way TV dramas cut a speech: "more natural and more
   cinematic". A line of two or more sentences **may** be split (Raphael's choice); a line that runs **past 8 s must** be.

## 2. Decisions

| # | Decision | Why |
|---|---|---|
| D1 | `LEAD_IN_S` 0.5 -> **1.0**; a new `SENTENCE_PAUSE_S = 0.8` at every sentence end inside a line; `LINE_GAP_S` 0.3 -> **0.8**; `TAIL_S` stays 0.5; `WORDS_PER_SECOND` stays 2.2 | Measured (C1). On the two measured takes this clock is already 0.9 to 1.5 s longer than the real speech, so **no extra safety margin** (the chat suggested 0.5 s before checking). `LINE_GAP_S` between two different speakers was not measured: provisional |
| D2 | One sentence splitter, `contracts/sentences.py` (mirror in the interface): cut after `.` `?` `!` `…` (a closing quote may follow); a piece under 3 words joins the next (the last joins the one before) | `lab/line_parts/run.py` `sentences()`: "ඔව්. රුපියල් ..." keeps "ඔව්." with its sentence. The same function counts sentence pauses (D1) and makes parts (D7) |
| D3 | Steps with a 15 s maximum are **4, 6, 8, 10, 15**; with 10, 4/6/8/10. Any stays 3 ... max | The person (replaces plan/2026-11-19 D3) |
| D4 | "Always 8 s" is no longer offered (template form, create form). `fixed_shot_seconds` stays readable so a production that has it keeps working; the API refuses a new non-null value | The person. Removing the field would break stored settings |
| D5 | An overrun **blocks** `finish` when it can be fixed: a longer allowed take holds what the clip carries, or the clip holds more than one line or part (it can be split). It stays report-only only when one part alone is longer than the longest take | C2. A fault Raphael can fix must not pass silently |
| D6 | The length target is `max(stated length, the script's own time)` on the D1 clock; the cap stays 1.5 x that target. The length block says so in one sentence when the script is longer | C3. The script's words are not optional; the stated length is an estimate |
| D7 | **Line parts.** A dialogue line with 2 or more parts (D2) is given to Raphael as consecutive part blocks ("Part k of n of ONE line"). Raphael may keep parts in one clip or spread them. A line whose own time on the D1 clock is past `SOFT_CAP_S` (8 s) is marked "too long for one take" and **must** be spread over at least two must clips | The person's (c) and (b). Proved in `lab/line_parts` runs 001/002 |
| D8 | Parts are **items**, not rows. `dialogue_lines` keeps one row per line, words unchanged; `sceneplan.items_for` expands a line into part items when the scene was planned with parts. A part item keeps the row's `line_id` and gains `part` (1-based) and `parts` | Every reader (API scene view, serializer, Zora/Sable kernel, director) already gets a shot's lines from the items in its block range (`serialize/model.py` `shot_items`, `scenes.py` `shot_clock(kernel_items[...])`), so they all agree without a second binding |
| D9 | `scenes.line_parts boolean not null default false` (schema **v28**). Raphael sets it true when it plans the scene; `items_for` expands only then | A scene planned before this keeps whole lines: its stored `block_start`/`block_end` index the old items and must stay valid |
| D10 | House rule **H-17** "a long line is covered in parts" (from `lab/line_parts/h91_line_parts.md`), topic `coverage` | What the lab gave Raphael |
| D11 | Two blocking checks: `parts:whole` (a must clip holds every part of a must-split line) and `parts:jump` (consecutive parts in different must clips on the same setup and size). One report-only check: `cut:jump` (any two consecutive must clips in cut order on the same setup and size) | The first two are the lab's. Runs 001 and 002 both put two MCUs on setup B back to back (Anudi greets, then listens): advisory until the person has seen how often it fires |
| D12 | The per-part timing table shows the same measure as the line note: each part's seconds INCLUDE the lead-in and the pause before it | Run 002: Raphael compared 6.4 s (words only) with 9.5 s (with pauses) and wrote a confused editor note |

## 3. Phases

### Phase 0: audit (free, read-only, written into IMPLEMENTED.md)

Before any code: list every place that keys a map by `line_id` and would break when two items share one (D8). The grep
(`src/libs` + `src/api`, planners being removed excluded) finds ~35 files. For each: unaffected / key by `(line_id, part)` /
needs the first part only. Known hot spots: `raphael_write.logic.rows_for` (`by_short`, `bound`), `serialize/model.py`
(`by_line`), `contracts/raphael/scene.py` (`line_facts`), `sceneplan.items_for`, `scene_kernel`, `director_chat`,
`handoff.py`. Also confirm how a script edit already invalidates a scene's shots when blocks shift (a part count that
changes after an edit must take the same path).

### Phase 1: the clock (both repos)

- `contracts/shotplan.py`: D1 constants; `line_seconds(item)` adds `SENTENCE_PAUSE_S x sentence_breaks(item.text)`.
- `contracts/timing.py`: `speech_seconds` gains an optional `text` (or a `breaks` count) so word targets, overruns and the
  API agree with the clock. `contracts/sentences.py` (D2).
- Interface: `src/lib/veo/timing.ts` + `src/lib/text/sentences.ts` mirror; `features/scenes/lib/analysis.ts` uses them.
- Tests: one shared case file both repos read (the `tests/contracts/test_timing.py` precedent), with the lab's two
  measured lines: B (11 words, 3 sentences) needs >= 7.25 s, G (11 words, 2 sentences) >= 5.8 s.
- Expect more overruns reported on existing scenes: that is the truth arriving, not a regression.

### Phase 2: take lengths and the picker (both repos)

- `contracts/take_lengths.py` and `src/lib/takes/lengths.ts`: steps = 4/6/8/10 plus 15 when the maximum is 15 (D3);
  tests for both maxima and both modes; `describe` / `describeLengths` unchanged.
- D4: the template form's "Shot lengths" row and the "Always 8 s" segment go; `PATCH` refuses a new `fixed_shot_seconds`.
- Per-shot picker `features/director/components/take-length-picker.tsx` (shadcn `ToggleGroup` for steps, a − / + stepper
  for any), used by the shot list. Each choice shows its fit from the shot's `need_s` (the API already sends it): "runs
  2.1 s over" (too short), "fits", "+4 s spare". Replaces the `Select` in `shot-list-panel.tsx`.

### Phase 3: Raphael takes that hold the line

- `contracts/raphael/checks.py` `clock`: D5. The fault says which allowed take would hold the clip, or that the clip
  should be split at a line or part.
- `contracts/raphael/pack.py` `length_block` and `checks.length`/`short`: D6 (`limit_s` reads the target from one helper).
- Tests: the run-001 bin (stored in `lab/line_parts/runs/001/result.json`) fails `finish` on the new checks; run 002's
  passes.

### Phase 4: line parts in the data (backend)

- `Database/upgrade_v27_to_v28.sql` + `schema_v28.sql`: D9 (`scenes.line_parts`). Not applied until the person says so;
  until then Raphael runs with parts off (the column is read as false when absent).
- `contracts/sceneplan.py` `items_for(script, lines, parts=False)` and `scene_items(scene, ...)` passing
  `scene.get("line_parts")`: D8. `Item` gains `part: int = 0`, `parts: int = 0` (0 = a whole line).
- Phase 0's list: fix every map it marked. `raphael_write` binds the `dialogue_lines` row to the clip that performs its
  **first** part (`shot_id`, `start_s`) and sums the parts' overruns into `overrun_s`.
- The API scene view (`routers/scenes.py`) sends `part` / `parts` on each line it lists for a shot.

### Phase 5: Raphael plans in parts

- `contracts/raphael/scene.py` (the DB path) and `contracts/raphael/packet.py` (the packet path): part blocks as the
  lab's `split_packet` does: "Part k of n of ONE line ..." in the block's intent; the must mark from D7; a turn in feeling
  moves to the first part, a state change to the last.
- `packet.timing`: D12.
- `hiru_ai/house_rules/line_parts.md`: H-17 (D10).
- `checks.py`: D11, in `check_stage1`.
- `raphael_write`: sets `scenes.line_parts = true` with the shots (one write, same transaction as today's).
- A setting `RAPHAEL_LINE_PARTS` (default on once v28 is applied, off before) so the feature can be switched off without
  a deploy.
- Tests: the E01-S04 packet splits into B02 2 parts (may), B08 2 parts (may), B12 3 parts (must); a fake bin that holds
  all of B12 in one clip fails `parts:whole`; two parts on one setup and size fail `parts:jump`; `raphael_write` on run
  002's stored result gives shot rows whose items show L13/L14 in one shot and L15 in the next.

### Phase 6: the interface

- `features/scenes/types.ts` + `map-scene.ts`: `part` / `parts` on a shot's lines.
- The shot card and the shot list label a part "Line 4 · part 2 of 3", the words through `spoken()` (never a hard-coded
  `lang`).
- `npx next typegen && npm run check && npm run format:check`.

### Phase 7: Zora and Sable

They read a scene through the kernel (`scene_items`), so parts arrive as lines. Check their tools with a part: a Sable
edit of a clip holding part 2 keeps parts 1 and 3 where they are; Zora adopting a shot list keeps `line_parts`. No new
split / merge tool (out of scope).

### Phase 8: live check (PAID, the person's)

1. With the product code, Raphael on Api Denna E01-S04 (any 3 to 15 s, then steps 15): cap $0.40 each. Compare with
   `lab/line_parts/runs/001` and `002`.
2. Optional: 360p takes of the father's call in its parts (about 3 x 6 s, ~$1.80 at the 720p rate) to hear whether his
   voice holds across the cuts. Each clip makes the voice fresh; this is the feature's main untested risk.

## 4. Risks

- **The clock is from two takes.** Two lines, two speakers, no "on the phone" or slow delivery measured. Phase 8 adds data
  for free whenever takes exist: `lab/sinhala_pace/measure.py` reads any take.
- **Voice drift across parts** (Phase 8.2). The canon card's voice pin goes into every prompt; not yet heard across a cut.
- **Shared `line_id`** (D8) touches many readers; Phase 0 exists so none is missed.
- **Jump cuts between neighbours** (D11 `cut:jump`) are advisory; promote to blocking only after the person has read how
  often it fires.
