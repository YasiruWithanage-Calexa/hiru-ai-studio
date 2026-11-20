# plan/2026-11-20: what is built

Built offline on 2026-11-20, both repos, **uncommitted**. No paid call was made.

| Phase | State | Where |
|---|---|---|
| 0 Audit | DONE (below) | |
| 1 The clock | BUILT | `contracts/sentences.py` (D2); `timing.SENTENCE_PAUSE_S`, `speech_seconds(..., breaks)`, `spoken_seconds`, `overrun_seconds(breaks=)`; `shotplan` LEAD_IN 1.0, LINE_GAP 0.8, a pause at each sentence end and between consecutive parts (a turn's gap moves to after the last part); coverage and Raphael's `line_facts` count the pauses. Interface: `lib/text/sentences.ts`, `lib/veo/timing.ts` (LEAD_IN_SEC … `lineNeedSeconds`), `scenes/lib/analysis.ts`. Shared cases: `tests/contracts/clock_cases.json` = `src/lib/veo/clock-cases.json` (lab lines B ≥ 7.25 s → 8.1, G ≥ 5.8 → 7.3, E01-S04 B12 9.46 must split) |
| 2 Take lengths + picker | BUILT | steps 4/6/8/10 (+15 at a 15 s maximum) both repos (D3); "Always 8 s" gone from the template form, "8 s shot lists" → "Shot lists" on the create form; the API refuses a new or changed `fixed_shot_seconds` (an existing one is kept or cleared, D4); `features/director/components/take-length-picker.tsx` (ToggleGroup for steps, − / + for any length, each choice's fit from `need_s`: "runs 2.1 s over" / "fits" / "+4 s spare") replaces the Select |
| 3 Takes that hold the line | BUILT | `checks.overrun` (D5): blocks with the take that holds it, or "cut it at a line or a part"; report-only when one line alone is past the longest take. `checks.target_s` (D6) = max(given, the script's own time rounded up); cap and floor read it; `<length>` says so in one sentence only when the script is longer. Bug found and fixed: `_fits` counted the old 0.5 + 0.5 lead-in/tail as handles (now `LEAD_IN_S + TAIL_S`) |
| 4 Line parts in the data | BUILT | `Database/upgrade_v27_to_v28.sql`, `schema_v28.sql` (`scenes.line_parts`, D9) — **not applied**. `Item.part/parts/whole`; `sceneplan.items_for(parts=)`, `in_parts`, `scene_items(parts=None → scenes.line_parts)` (reading applied to whole lines first; turn on part 1, hold on the last); `item_row/item_of` carry them; `script_rows`/`lines_from_items` fold parts back into one block and one row; `shotplan.bound_lines` (first part's shot, summed overruns). `raphael_write` binds a row to its first part's clip, counts a part's own words, writes `line_parts` with the shots, and re-pins the stored map to the numbering it writes. API: `ShotView.line_parts`, `LineView.parts`, script blocks mapped to their first item, staging-stale and script-edit remaps count parts; production panel shows a part's own words |
| 5 Raphael plans in parts | BUILT | `packet.split_packet` (equal to the lab's split, block for block), `scene_from_packet` part fields, `opening(parts=)`; DB path `script_of(parts=)`; `part_groups`, listing marks ("Part 2 of 3 of ONE line …, too long for one take"), `packet.timing` D12 per-part seconds with the lead-in or pause before each, the whole line under its last part. `checks.line_parts` (`parts:whole`, `parts:jump`, blocking) and `cut_jump` (report) in stage 1. House rule H-17 (`house_rules/line_parts.md`, from the lab's H-91). `StoredRaphael.line_parts` (left out of the JSON when false). Setting `RAPHAEL_LINE_PARTS` (default **false**: turn on after v28). "More cinematic" reads the scene the way its stored bin was cut |
| 6 Interface | BUILT | `DialogueLine.part/parts/lineNo`, `map-scene.shotDialogue` (each shot lists the parts it carries), `lib/line-label.ts` ("Line 4 · part 2 of 3"), keys per part in the shot list and both timelines; words through `spoken()` |
| 7 Zora / Sable | BUILT | `Coverage.from_rows` on a scene in parts builds part blocks with Raphael's `L<block>` ids; a later part is performed by the first voiced clip whose card carries it; `coverage_rows` binds the row to its first part's clip. Zora writes no scene field, so `line_parts` stays. No split/merge tool (out of scope) |
| 8 Live check | 8.1 RUN 2026-11-20 ($0.33, the person's yes, $2 cap) | `lab/line_parts/live_product.py` → `runs/003_product`: the PRODUCT's Raphael (nothing patched), packet path, steps 4/6/8/10/15, `RAPHAEL_LINE_PARTS=true`. Both stages finished, nothing left reported, 18 clips. The father's call (must split) is parts 1–2 on 4H-1 (MS, setup H) and part 3 on 4C-2 (MCU, setup C): no jump cut. B02 and B08 kept whole lines in one clip each (may split). `raphael_write`: every line row bound to its first part's clip, **0 overruns** (run 001: 5), `line_parts=true` in the scene fields. The same clips through plan/2026-11-20b's video prompt agent: 18 of 18 prompts, parts briefed `L11.1`…`L11.3`, each clip speaks only its part (lab/video_prompt/runs/006_product_parts, $0.16). Note: written with the canon, 4J-1 (Anudi's CU under part 3) is voiceover (`sound_mode_of`: a heard-only speaker's line bound to the clip); run 003's rows, written without the canon, said ambient. 8.2 (renders of the parts) not run |

## Phase 0 audit: what keys or counts by line or block

| Reader | Verdict |
|---|---|
| `raphael_write.rows_for` (`by_short`, `bound`) | fixed: part by block number; row bound to the first part; overruns summed |
| `serialize/model.py` `by_line` (beat index) | unaffected: a part's `Line` carries the part's words; the beat index is the row's (first part) |
| `contracts/raphael/scene.py` `line_facts` | fixed: per part, D12 measure |
| `sceneplan.items_for` / `scene_items` | fixed (D8) |
| `sceneplan.rows_after_fit`, API `timed` | fixed: `bound_lines` |
| `script_rows`, `lines_from_items` (Zora/Sable save, director chat) | fixed: parts fold back to one block and one row |
| `contracts/coverage` (Zora/Sable) | fixed (phase 7) |
| `contracts/holding` (raw staging block numbers vs shot ranges) | fixed by storing the map in the shots' numbering (`raphael_write.renumbered_staging`); the stager keeps a map whose basis matches the stored numbering |
| `reading.block_key` | fixed: part 1 has the line's key (anchors resolve to where the line starts), later parts `#k` |
| API scene view script blocks, `natural_cast`, `_replace_script` keys, staging stale | fixed |
| production panel `shot_view` lines | fixed: a part's own words |
| `handoff_checks` | unaffected (part words); a part shows the row's summed overrun (minor) |
| `scene_kernel` / `turn_logic.find` (classic director chat, dropped) | first part (acceptable) |
| `feeling.wants` (reading units by raw block number) | known: on a scene in parts the units after a cut line are off by the extra parts; only the classic serializer's "wants" phrase reads it (the video prompt no longer does) |
| Adam, David, Jonathan, classic `script_split` | not changed (rule 0); they never set `line_parts`. A classic re-split of a Raphael scene in parts would leave `line_parts` true — re-plan with Raphael |

A script edit already moves shots across by block keys (`_replace_script` → `remap_plan`); a part count that changes with the edit takes the same path (the keys count parts).

## Deviations

- **Run 002 does not pass on the product clock.** D1 counts a pause at every sentence end inside a line, which the lab's clock did not ("ඔව්. පොඩියට පටන් ගත්තේ."). Five of run 002's clips are 0.1–0.7 s short and now block with the next length up (Raphael fixes them itself). The test checks run 002 passes on the clock the lab ran, and records the five on the measured one.
- Tests that replay a plan recorded on the old clock (run 3's gold in `tests/raphael`, the recorded Zora scene) run on that clock (`tests/clock_before.py`); the measured clock is tested in `test_clock_cases.py` and `test_line_parts.py`. Kernel tests (`test_shotplan`, `test_scene2_clock`, the timeline text) and the classic planner's parity recordings were moved to the new numbers (only line start times moved, +0.5 s).
- No `supabase/migrations` file for v28 (v26 and v27 had none either); not verified on a local stack.
- `cut:jump` orders must clips by (moment, id), not by the blend notes.

## Open for the person

1. ~~Apply v28, set `RAPHAEL_LINE_PARTS=true`~~: v28 applied by the person and `RAPHAEL_LINE_PARTS=true` in `.env`, 2026-11-20.
2. Phase 8 (paid): Raphael on Api Denna E01-S04 with any 3–15 s and with steps 15 (cap $0.40 each); optional 360p takes of the father's call in parts (~$1.80) to hear the voice across cuts.
3. D11: promote `cut:jump` to blocking once you have seen how often it fires.
4. Full backend run after both plans: 5,951 passed. Against the clean baseline (a copy of the tree before this work), the
   new failures are 34 Adam / David / Jonathan / classic `script_split` / `plan_score` tests whose numbers are the old
   clock's (rule 0: not changed), and 8 API tests that fail on file URLs 8001 vs 8000 from the local `.env` (they pass
   without it; listed as pre-existing in plan/2026-11-19). The tests that failed before still fail (Raphael length cap,
   removal allow-lists, frame_render, parity recordings of frame_render/structure_build).
