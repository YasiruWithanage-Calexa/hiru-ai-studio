# The document reader: what is built (plan/2026-11-06f)

Status 2026-11-07: **phases 1 to 4 built offline (backend and interface); phase 0's probe and phase 5's live eval are
written and are the person's to run.** No model was called, nothing was deployed or applied to the hosted database,
nothing is committed. The reader is off (`READER__ENABLED=false`) until a person turns it on.

The person's two files were found in `~/Downloads` and used throughout: Ekama Sakshiya's text is a test fixture in full
(`tests/fixtures/reader/ekama-sakshiya.txt`), Avasana Sangnawa as a skeleton (each page's first and last lines and every
heading line, 57 KB: `tests/fixtures/reader/avasana-skeleton.txt`).

## Read this first

1. **The doc_ingest function's deadline is 540 s.** Reading Avasana is 1 canon call plus 30 episode calls (four at a
   time) on the author's model; that will take far longer than 9 minutes. Before turning the reader on for long
   scripts, the deadline must go up (`deploy-functions.yml`, `FUNCTIONS` in `task_manager`, like Adam's 1800 s), or
   the reading must move to its own job. Not changed here: it is a deploy decision.
2. **The Ekama gold is a draft made by a script** (`tests/eval/reader/gold/ekama-sakshiya.json`), from the text layer,
   checked by eye. The rules now score 1.00 on it partly because both read the same text; a Hiru writer must check it
   (§5). Avasana's gold (episodes 01, 15, 30) is not made: its Sinhala must be typed by a person (Q4).
3. **The reader's model is `OPENAI__MODEL_AUTHOR` (gpt-5 today).** `.env.example` notes that gpt-5 shuts down
   2026-12-11; the tier is a setting, the probe and the eval decide (Q1).

## What the files showed (before any code)

Measured with the shipped extractor on the person's files:

| | Before | After (rules, decision 9) | Reader's plan |
|---|---|---|---|
| Ekama: scenes / dialogue lines | 9 / **0** | 9 / **20** (every line) | one call, text mode |
| Ekama: times of day, lengths, flashback | none | all 9, `stated_seconds`, scene 3 flashback | |
| Ekama: page header as a speaker | `EKAMA SAKSHIYA` | dropped (repeated page furniture) | |
| Avasana: episodes | 33 | 33 (the text is scrambled; no rule reads it) | **30** pieces + front pages |
| Avasana: text quality | warning did not fire | `SCRAMBLED_WARNING` | pages mode |

Text quality (§4.1): the share of a page's Sinhala words with an ASCII digit or symbol glued inside. Avasana: 11 %–89 %
on all 162 pages with Sinhala; every Sinhala fixture in the repo: 0 %. Thresholds: a page over 5 % is corrupt, 20 % of
pages makes the document `pages` mode. The "spelling check" half of §4.1 is not built: there is no Sinhala word list
in the repo and the glued-character signal already separates the two files with a wide margin.

## Phase 1 (contracts, rules)

| File | |
|---|---|
| `contracts/doc_read.py` | The format (§3) as strict wire models; `Reading` (stored, `format: 1`); `to_parsed` (canon names as speakers, episode 0 = not stated); `to_candidates` (cards, line and scene counts); `merge_canon`, `roster`, `numbered`, `normalise` (NFC, ZWJ kept), `strict_schema`, `reading_candidates` |
| `contracts/doc_read_quality.py` | Text quality, `layout`, episode `boundaries` (index pages and END OF EPISODE never split; first time a number appears, rising), `pieces` (whole ≤ 8 pages; front + episodes; 12-page windows sharing a page; 60-page canon windows), `halves` |
| `contracts/doc_read_checks.py` | §4.4 as `Problem`s; `mend` (header cue dropped, speaker from cue); `drop_unquoted` (decision 7); `add_speakers`; `runtime_notes` (reported, never fixed); `apply_patch` |
| `contracts/screenplay.py` | Decision 9: `SCENE nn -` / `FLASHBACK` / `1.5 MINUTES` / a clock time in headings (`Heading.flashback`, `stated_seconds`, `clock`); `NAME - line` dialogue (a wrapped line joins it until the sentence ends); `strip_page_furniture` before parsing |

## Phase 2 (the reader)

- **One run for both engines**: `contracts/doc_read_run.py` (pieces → calls → mend → checks → ≤2 repairs, a worse patch
  never kept → merge → canon quotes, new speakers, runtimes). The three calls are passed in; the messages are built
  here, so both engines send the same bytes. Episode calls run `WORKERS = 4` at a time, each in a copy of the caller's
  `contextvars` (the model, the trace and the usage sink follow the call into its thread).
- **Failure ladder** (decision 9): a failed canon call, a failed pages-mode piece or a failed one-call document → no
  reading (the rules read it, the job says why). A text-mode piece still wrong after two repairs → that piece by the
  rules, noted. A pages-mode piece still wrong → kept, problems reported (the rules cannot read a scrambled font).
  A cut answer (`finish_reason == "length"`) → the piece is split at the scene heading nearest its middle (or its middle
  page) and both halves read, at most two deep.
- `hiru_ai`: the `reader/` group (`agents/reader/reader_canon|reader_episode|reader_repair`, `steps/reader/reader_checks`,
  group.yaml, import-linter independence contracts), tier `reader` in `models.yaml` (model_author at `effort_reader`,
  900 s), `ReaderSettings` (`READER__ENABLED`, `READER__WORKERS`), `core/doc_reader.py` (read, save, load, PDF slices
  with pypdf). The agent runner's new `files(inp)` hook sends `(filename, base64)` PDFs as `file` parts after the text
  (`tests/hiru_ai/test_reader_files.py` checks the request body `ChatOpenAI` builds).
- doc_ingest service: `runtime/llm.py` `json(..., files=)`, tier `reader`, a 900 s timeout for it, and a cut answer
  raises; `engine/reader.py`; `engine/reader_prompts/` (copies; `test_the_two_engines_send_the_same_prompts`).

Deviations from §4: the run, the checks and the quality score live in `contracts` (not `doc_ingest/engine/
text_quality.py`) so the two engines share one copy; `contracts/reader/` is `contracts/doc_read*.py`. The patch replaces
runs of scenes (`replace_from..replace_to`), not "blocks by path", so a skipped scene can be inserted. The plan's single
`quote` per canon entry is kept: an entry whose quote is not in the text loses its whole description, not one field.
The format gained `summary` (characters) and `heading` (scenes, as written).

## Phase 3 (plug in, schema)

- doc_ingest (both engines), after the role: for script / bible / canon_index / outline when on, read, save
  `reading.json` beside `extracted.txt`, set `documents.reading_path` / `read_from`; job events for every note and
  unresolved problem. Pages mode: chunks, headers, the story reader and production memory read the transcription;
  `extracted.txt` keeps the original; the scrambled-font warning still looks at the original.
- structure_build (both engines): a document with a reading takes its scenes from it, no prose cut; scenes carry
  `read_from`; a heading's stated length (≥ 4 s) becomes the envelope (this also applies to the rules' parse, e.g. Ekama).
- canon_extract (both engines): `reading_candidates` (§4.5), no model extraction or dedupe when readings exist.
- Schema: **v16** (`Database/schema_v16.sql` = v15 + these, `upgrade_v15_to_v16.sql`). First folded into v14, moved
  out on 2026-11-07 when the person had applied v14 and v15 had landed:
  `documents.reading_path`, `documents.read_from`, `scenes.read_from`, `scenes.read_confirmed_by` (+ index),
  `scenes.read_confirmed_at`; `supabase/migrations/20261107022120_document_reader.sql`. **Not applied**; `supabase test
  db` and the three-way schema dump comparison were not run (no Docker here). Code names these columns only when a
  reading exists, i.e. only with the reader on.
- API: `SceneView.read_from` / `read_confirmed_at`; `POST /productions/{id}/scenes/{id}/read-check` (EDIT_SCRIPT; 409
  for a scene not read from pages; audited); `Document.read_from`.

## Phase 4 (interface, `hiru-ai-studio-interface`)

- Script panel: `ReadCheckNotice` ("Dialogue read from page images: check it", "I checked the dialogue"; once checked a
  green chip), `confirmReadCheck` in `features/director/client.ts`, `Scene.readFrom` / `readConfirmedAt`.
- Documents: a "Read from page images" chip; the existing re-ingest button is now labelled "Read again".
- No Figma frame was made for the notice; it reuses the amber notice style of the build panels.

## Phase 0 and 5 (written, not run: the person's)

- `scripts/reader_probe.py --yes`: ONE call, Ekama's 4 pages as a PDF in pages mode; prints bytes, tokens, time, cut
  or not, what came back. Dry run: Avasana episode 1 (pages 3–29) is 645 KB as its own PDF.
- `scripts/eval_reader.py [--yes]`: rules vs reader on the gold, scores from `tests/eval/reader/score.py` (scenes,
  headings, time of day, dialogue recall, speakers, word accuracy, canon recall). Offline today:

| arm | scenes | headings | time_of_day | dialogue | speakers | words | canon |
|---|---|---|---|---|---|---|---|
| ekama rules | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 | 0.82 |
| ekama gold replayed through the reader | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 |

## Checks run

- `pytest`: new tests 120+ (contracts 41, agents 21, step 3, ingest both engines 9, consumers 3, API 1, scorer 2, file
  parts 1); see the full-suite note below. `ruff` (changed files), `mypy` (932 files, clean), `lint_imports.py` (reader
  contracts kept), `hiru-ai validate` (172 parts, 0 errors), `hiru-ai catalog` regenerated, `hiru-ai eval reader_*` 6/6.
- Interface: `next typegen`, `tsc`, `eslint` (one warning in `script-edit-form.tsx`, not from this work), `vitest`
  210/210, `prettier --check` on the changed files.
- Full backend suite: 4,671 pass after the fixes; 23 fail, none from this work: three graph parity fixtures differ by
  the 05c story reader's calls (`canon_extract/model_cards`, `structure_build/prose_model`, `prose_model_rejected`);
  12 Adam tests (`tests/adam/test_system.py`, `test_score_mutations.py`: the developer `.env`'s `ADAM_MODE` and a live
  run's score); 8 API tests (`test_handoff`, `test_looks`, `test_production`: the `.env` puts the API on port 8001, the
  tests expect 8000). Import-linter: `david agents never import each other` was already broken. The doc_ingest wiring
  snapshot (`graph.mmd`) was regenerated for the new `reader` node; the tier and agent-contract tests know the
  `reader` tier and PDF parts.

## Open, the person's

1. Phase 0: `scripts/reader_probe.py --yes` (limits, page-image cost). Phase 5: `scripts/eval_reader.py --yes`.
2. Q1 the tier/effort, Q2 transcription for search (built as yes), Q3 (folded into v14), Q4 who types the Avasana gold.
3. The doc_ingest deadline (above), applying v14, then `READER__ENABLED=true`.
