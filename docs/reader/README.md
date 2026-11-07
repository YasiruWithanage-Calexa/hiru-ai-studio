# The document reader (plan/2026-11-06f)

The model reads a whole uploaded document once, at ingest, into one format of our own, and code maps that format into
the system. It replaces the rules' reading of a script or a bible, never what comes after it: the structure build, its
questions, the canon write and the shot planners are unchanged.

## Where things are

| What | Where |
|---|---|
| The format, `to_parsed`, `to_candidates`, `reading_candidates`, `strict_schema` | `src/libs/contracts/doc_read.py` |
| Is the text scrambled? Where are the episodes? (`quality`, `pieces`, `halves`) | `src/libs/contracts/doc_read_quality.py` |
| The checks, the mends, the patch | `src/libs/contracts/doc_read_checks.py` |
| The run (pieces → calls → checks → repairs → one reading) and the messages | `src/libs/contracts/doc_read_run.py` |
| The agents (`reader_canon`, `reader_episode`, `reader_repair`) | `src/libs/hiru_ai/agents/reader/` |
| The step (`reader_checks`, JSON in and out) | `src/libs/hiru_ai/steps/reader/` |
| The graph engine's door (read, save, load, PDF slices) | `src/libs/hiru_ai/core/doc_reader.py` |
| The service engine's door, and its copy of the prompts | `src/services/doc_ingest/doc_ingest/engine/reader.py`, `reader_prompts/` |
| Probe (Phase 0) and accuracy test (Phase 5): a person's to run | `scripts/reader_probe.py --yes`, `scripts/eval_reader.py --yes` |
| Gold (a draft) and its scorer | `tests/eval/reader/` |

The run lives in `contracts` with its three model calls passed in, so both engines run the same code and send the same
bytes; the prompts are the agents' files, copied into the service (a test holds them equal).

## How a document is read

1. **Text or pages.** Every page's text is scored: the share of Sinhala words with an ASCII digit or symbol glued inside
   (`බෙක7ළඹ`, the mark of a font whose ToUnicode map stores the vowel signs wrongly). A page over 5 % is corrupt; a
   document with 20 % or more corrupt pages is read from its page images (`pages`), else from its numbered lines
   (`text`). Measured: clean Sinhala scores 0 on every page of every fixture; Avasana scores 11–89 % on every page.
2. **Pieces.** A document of 8 pages or fewer is one call that returns its canon and its scenes. A longer script is its
   front pages (one canon call) then one call per episode, four at a time, each given the cast list (names, aliases,
   codes). Episode boundaries come from the text layer (`SEASON ONE EPISODE 01` survives the broken font); an index
   page and "END OF EPISODE" never split. No boundaries: 12-page windows sharing a page. A bible, a canon index or an
   outline: canon calls over 60-page windows.
3. **Checks** (code). Text mode: every block's words are its source lines' words (page headers left out), every line
   inside a scene is in a block, no lines lost between scenes, a time of day only when the heading says it. Pages mode:
   the Latin part of every heading the text layer shows is in a scene's heading, in order, and every page has its
   transcription. Code mends a cue that is a page header (dropped), an empty speaker (the cue), a new speaker (a
   supporting character, reported), and reports a runtime that does not add up.
4. **Repairs.** The same model gets only the problems and answers with a patch (replace runs of scenes); a patch that
   does not reduce the problems is not kept; at most two. Left over: text mode reads that piece with the rules and
   says so; pages mode keeps the answer and reports the problems.
5. **Kept.** `reading.json` beside `extracted.txt` (`documents.reading_path`, `read_from`). In pages mode the clean
   transcription replaces the text for chunks, search, the story reader and production memory; `extracted.txt` keeps
   the original.

Absent-safe: with the reader off (`READER__ENABLED`, default false), no key, a failed canon call, a failed pages-mode
piece, or a failed one-call document, there is no reading and the rules read the document as before; the job says why.

## After ingest

- `structure_build` (both engines): a script with a reading takes its scenes from it (`to_parsed`), with no prose cut;
  each scene keeps `read_from`, and a heading's stated length becomes its envelope.
- `canon_extract` (both engines): when readings exist their canon is the candidate list (an index first, then the bible,
  then the scripts); documents without a reading add their rules' canon; the rules give codes only. No model
  extraction, no dedupe: the reader already mapped every cue to a person.
- A scene with `read_from = "pages"` shows "Dialogue read from page images: check it" in the script panel until a
  person who may edit the script confirms it (`POST /scenes/{id}/read-check`); a rebuild that rewrites the scene clears
  it. "Read again" on a document re-ingests it.
