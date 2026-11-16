# plan/2026-11-15 — The model reads the documents; code only checks it

The person's rule: **every fact taken from an uploaded document is read by the model.** No pattern, regex or layout
rule reads an input document. Code may (a) turn the file into text, mechanically, (b) check the model's answers
(they are our schema), (c) do arithmetic and storage on the model's values. Gates stop the build before credits are
spent on a document the build cannot use.

Proven first in `lab/llm_reader/` (README there): seven layouts of the person's script read right (run5), the PDF text
fixed, the reading fed through today's breakdown, and episode 1 of "Api Denna" taken from PDF to Raphael's shots
(`runs/e2e/step1-6.md`, $1.05 of a $1.50 cap). Findings the lab made are the reasons for each phase below.

## Decisions (the person, 2026-11-15)

| | |
|---|---|
| D1 | A stated range gives its **top** ("25–30 seconds" → 30 s). |
| D2 | **Any scene's problem holds the whole build** (a gate on one scene stops or pauses all of it). |
| D3 | "Needs input" is answered by the roles that hold `answer_questions` (producer, director, writer). |
| D4 | **No model, no upload**: the build never falls back to rules. |
| D5 | Only text PDFs are accepted; scanned PDFs stay rejected (today's rule). |
| D6 | A text PDF whose text is still damaged after the extractor (old non-Unicode fonts, nothing in the file to fix it) **stops** with "export it again with a Unicode Sinhala font" — no model writes the dialogue. *(Chosen by Claude as recommended while the person's answer was open; flip `D6` to the page reading by changing gate 0's stop to the reader's pages mode.)* |
| D7 | The PDF engine is **poppler** (`pdftotext -enc UTF-8 -layout`). See phase 1 for where it can run. |
| D8 | Raphael's "must" seconds over the stated length on a dialogue-heavy scene are expected (the extra shots we ask for). |

## What the lab found (each is a phase)

1. Scene lengths were never read: `breakdown/fill.py` `_MINUTES` (also `packet.py`, `checks.py`) only matched
   "N MINUTES" at the end of a heading. Every scene got the 60 s default.
2. The Sinhala was never damaged in the file: the PDFs carry `/ActualText` for each cluster; pypdf's `extract_text()`
   ignores it (vowel signs first, ligature letters lost: "ෙදන්නා" for "දෙන්නා"). poppler, Xpdf and a small walker that
   honours `/ActualText` all give the same 301 lines and 313 Sinhala words.
3. `build.py:97` copies the whole line at the split's heading number: a heading glued to a sentence became the title.
4. The breakdown's word check (`checks.words`) sends "Location:" / "Duration:" lines and `Name:` speaker labels (only
   `ARUNI -` is exempt, `checks.py:95`) to **repair, and the repairs damage the script**: the labels and the metadata are
   pushed into action blocks and junk "text" blocks ("Anudi: Kasun: Anudi: …") that reach the shot planner.
5. Patterns read the input in many places: `document_role` rules, `memory.strip_furniture` (page numbers),
   `doc_read_quality._EPISODE_LINE`, `screenplay.py`, `prose_cut`, `canon_rules`, `analyse`.

## Where things run (found while planning)

The documents are read by **Cloud Run functions** deployed from a source zip with Google's `python312` runtime
(`.github/workflows/deploy-functions.yml`): there is no Dockerfile, so `apt-get install poppler-utils` is impossible
there. Phase 1 therefore ships the extractor as **one function with two engines**: poppler when `pdftotext` is on the
PATH (a container, a developer's machine), and otherwise the pure-Python `/ActualText` walker (BSD, pypdf only), which
the lab proved byte-identical to poppler on both of the person's PDFs. `PDF_TEXT__ENGINE=auto|poppler|walker`
(default `auto`). Moving `doc_ingest` to a container (as `infra/assemble` is) to run poppler everywhere is a deploy
change for the person (P-1 below).

## Phases

### Phase 1 — PDF text that honours /ActualText
- `pdf_text.py` beside each extractor (`hiru_ai/steps/extract_text/` and `services/doc_ingest/doc_ingest/engine/`, two byte-identical copies held equal by a test; `contracts` must stay standalone, so not there): `page_lines(pdf)`
  per page. `walker`: the lab's content-stream walker (pypdf `Font` maps; inside an `/ActualText` span its text replaces
  the glyphs). `poppler`: `pdftotext -enc UTF-8 -layout` in a subprocess, pages split on form feeds. Each line's spaces
  collapsed. `engine()` picks by setting and PATH.
- `hiru_ai/steps/extract_text/logic.py` and `services/doc_ingest/doc_ingest/engine/extract.py` use it in place of
  `page.extract_text()`; the scanned-PDF rejection stays (D5).
- Tests: a tiny hand-made PDF with an `/ActualText` span (glyphs "XY" stand for "ගේ"); the walker returns "ගේ", the
  old call does not.

### Phase 2 — The reading: two agents and their checks
- `contracts/breakdown/reading.py` (new): the wire shapes `ProbeW` and `ReadingW` (the lab's `schema.py`: every fact
  carries a `Quote` — line and words copied exactly; scenes have word-level `heading` and `end` quotes; `Length`
  low/high seconds; people with roles; skipped ranges; declared episode count), and pure code over the answers:
  `check()` (quotes on their lines; every story word in exactly one scene, word by word; numbering; sane seconds),
  `gates()` (D2), `envelope()` (D1), `fact_lines()` (the lines a scene's place and length were read from, plus the
  skipped lines), `cuts()` (the split's scene cuts from the reading), `messages`.
- Agents `breakdown_probe` (tier `breakdown_probe`: the breakdown model at low effort) and `breakdown_read` (tier
  `breakdown`), prompts from the lab (`probe.md`, `system.md`), each with scripted tests and eval cases.
- Settings: `effort_breakdown_probe = "low"`; `models.yaml` tier `breakdown_probe`.

### Phase 3 — The reading drives the breakdown
- `contracts/breakdown/run.py` `create()`: per document, `probe` → gate 0/1 → `read` → `check` → at most one repair
  call ("fix what the checks say if they are right; if a check is wrong about the document, keep your reading") →
  gates. A stop ends the run (`Result.stop`); needs-input returns its questions (`Result.questions_open`) before any
  split/continuity/episode call is paid. Answers already given (on a resumed build) are applied first.
- The split still runs for its cards and rules; its scene cuts are replaced by the reading's (`cuts`). Today's page
  furniture strip (`memory.strip_furniture`) is no longer applied: the reading marks page furniture as skipped.
- `Scene` gains `stated_s` (float | None), `title_doc` (the document's own title) and `facts` (lines that hold no story
  words). `build.py` takes the heading's own words from the reading (finding 3).
- `SourceMemory` gains `reading` (the checked `ReadingW`), kept with the document.

### Phase 4 — The breakdown's word check stops sending good scripts to repair
- `checks.words`: a scene's `facts` lines hold no story words; on a dialogue block's first line, the words **before**
  the model's span are the speaker's label in any style (`Kasun:`, `KASUN`, `Kasun -`), replacing the `ARUNI -` rule
  (finding 4). Code over the model's answer, not a pattern over the document.

### Phase 5 — Lengths from the reading, never from a pattern
- `fill.envelope_of`, `packet.assemble` (`H_length.stated_seconds`), `checks.length`: the scene's `stated_s` (D1,
  rounded). `_MINUTES` is deleted from all three. A scene the person gave a length for (Needs input) carries it.
- `fill.structure` writes the document's title (`title_doc`) when it gives one.

### Phase 6 — Gates in the build
- `breakdown_build.graph`: a stop fails the job with the gate's words; needs-input writes **open** questions
  (`breakdown:length:<doc>:E01-S03`, `breakdown:lead:<doc>`, `breakdown:episodes:<doc>`), sets the job
  `waiting_input` and ends; the API already resumes the build when the last one is answered (D3: `answer_questions`).
  Lengths: "Use the default (60 s)" or a typed number of seconds. No-model builds stop (D4, already so).
- Changed while building: a scene the document names **no place** for is a **warning**, not a question (the episode
  call infers the place from the scene's words, and an answer would have nowhere to go); a missing title is not a gate
  (screenplays rarely title scenes; the brief's title stands in).
- The breakdown reads the text layer only (D6: a damaged one has stopped at gate 0; the page transcription is not used).

### Phase 7 — The person answers in the Build chat
- Interface `features/build/components/build-chat.tsx`: a question that allows text gets a small input beside its
  buttons ("seconds"); the answer goes as `{ text }` through the existing `answerQuestion`.

### Phase 8 — The upload's own patterns, behind the breakdown
- `hiru_ai/systems/doc_ingest/graph.py` with the breakdown on: the role is the model's (`role_classifier`) every time,
  not the rules' first guess; a failed role call keeps the document as `other` with a warning (D4: the build then has
  no story document and stops at its gate 1).

## Not in this plan (the person's, after the live check)

- P-1: move `doc_ingest` to a container image (as `infra/assemble`) so poppler runs in production (D7).
- P-2: the live check: one upload of each lab layout through the product, then the build; a budget the person sets.
- P-3: retire the old path for good (`screenplay.py` for uploads, `prose.py`, `analyse.py`, `canon_rules`,
  `document_role` rules, `doc_read_quality._EPISODE_LINE`, the document reader's pages transcription) and the
  `BREAKDOWN__ENABLED` switch, once P-2 passes. `screenplay.py` stays for a person's edits of a scene's script.
- P-4: long scripts (40+ scenes: the reading in pieces), Sinhala headings, screenplay and prose layouts, several
  documents in one production (the lab's untested list).
- P-5: the stager/episode disagreement over who holds what at a scene's end (non-blocking notes in the lab).

## Checks before finishing
`ruff check src tests scripts`, `mypy`, `scripts/lint_imports.py`, `hiru_ai validate`, `hiru_ai catalog --check`,
`pytest -q` (with `OPENAI__API_KEY=` blank); in the interface `npx next typegen && npm run check && npm run format:check`.
No model call is made by the implementation or its tests.
