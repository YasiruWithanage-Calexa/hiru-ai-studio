# Story Reader: what is built

Plan: [PLAN.md](PLAN.md). Built 2026-11-05, phases 0 to 4, **offline**: every model answer in the tests is scripted. Nothing was
run on a real model, nothing is deployed, nothing was run against the hosted database. Work is uncommitted. Phase 5 (the live
check on the four real files) is a person's, because it costs model calls.

Decisions D1 to D4 were taken as the plan recommends: **D1** the deterministic parser stays the fast path for real
`INT.`/`EXT.` screenplays (the reader is never asked for a document the parser can already split); **D2** without a key, or
without a saved reading, today's regex rules run unchanged; **D3** the interface row (S6) is **not** built, it is not needed
for the fix; **D4** 60 000 characters, with a warning when a document is longer.

## Where things stand

| Phase | State | What is open |
|---|---|---|
| 0. The yardstick | **Built** | The four real files were not on this machine. `tests/fixtures/prose/` holds the drama (the real fixture from before) and **three synthetic files** in the layouts the plan describes (`DASUN` / `(Smiling)` / line; `**FATHER (ON THE PHONE)**` / `*(Quietly)*` / line; a bible with no dialogue). Baseline test: 1 of 3 story files builds scenes by rules. |
| 1. The reader and its check | **Built** | The real prompt has never met a real document. |
| 2. Ingest and the cache | **Built** | Re-ingest is not needed for older documents: `story_for` reads then and keeps the result. |
| 3. Structure build | **Built** | |
| 4. Canon | **Built** | |
| 5. Live check | **Not done** | A person: the four real files through a real ingest and build; count the lines by hand. |

## What changed

- **`agents/story_reader`** (new): `Input{filename, text}`, `Output{contains, episodes[{number, title, starts_with, ends_with,
  duration_s, kind, spoken[]}], people[], ignore[]}`, tier `high`, phase `doc_ingest.story`, middleware
  `[static_first, usage, absent_safe]`. The document is wrapped as data (`untrusted_text.wrap`) and cut at `MAX_DOC_CHARS`.
- **`steps/story_check`** (new, no model): finds every quote in the document by its letters, marks and digits only (any case,
  quote style, dash, spacing; whole words), in order. An episode whose anchors are missing or out of order is dropped; one that
  runs into the next is cut where the next begins; a number found twice keeps the longer slice; a spoken line not in its
  episode is dropped; a person needs a quote that is in the text. What is kept is cut **from the source**: the episode `body`,
  each spoken line's `text` (with the document's own punctuation), and `gaps` (the text before the first line, between two
  lines, after the last: what is seen). `ignore` quotes are cut out of the body and the gaps everywhere they repeat, but never
  from inside a spoken line, and never when shorter than 4 letters. Counts and warnings travel in the reading
  (`dropped`, `warnings`). The saved file carries the SHA-256 of the text it was made from, so a reading of other text is never
  used. Matching is by `fold` (letters/marks/digits) and not `verbatim_check.flat`, because the offsets into the source are
  needed to cut it; Sinhala vowel signs are marks and are kept.
- **`core/story.py`** (new): `read`, `save`, `load`, `story_for(ctx, doc, text)`. In `core` so the ingest, the structure build and
  the canon share one rule without importing each other.
- **`doc_ingest`**: a `story` node after `role`, only when a model is available; saves `story.json` beside `extracted.txt`
  (no migration). A missing or failing reader leaves no file and the ingest still succeeds. What the check dropped goes to the
  job events as warnings.
- **`steps/prose_cut` and `structure_build`**: `to_cut(text, story)`. A real screenplay still goes to the parser. Otherwise the
  reading's `script` episodes become the sections, with no `is_script_like` gate (`Read`, a `Section` that carries the verified
  lines and gaps). Rules look again only when there is no reading, or the check lost episodes. `trusted()` for a `Read`
  section is now **two reads agreeing**: the cutter's dialogue must equal the reader's lines, same lines, same order. When it
  does not, `by_rules` cuts from the reader's lines (`by_lines`: dialogue, and everything between two lines is action, minus the
  speaker name and direction written above the next line). That makes the fallback independent of `Name:` too. An episode with
  `number: null` is assembled without an `EPISODE` line, so the existing "which episode is this?" question asks.
- **`agents/canon_extractor`**: every document is sent (the `ROLES` filter is gone), the reader's `people` are listed in the
  summary ("heard only" for a voice), and the prompt asks for what the story shows or implies without describing. The
  extractor's input gained `people`; `canon_extract` collects them with `story_for` for each document.
- **`agents/prose_writer`**: `Input.number` may be `None` (a lone scene). **The plan's "one sentence in the prompt" about page
  footers was not added**: `story_check` already cuts the reader's `ignore` text out of the body in code, and the prompt is
  held byte for byte to the legacy engine by `tests/hiru_ai/test_agents_parity.py`.
- **`tests/hiru_ai/test_agents_parity.py`**: the canon extractor is now held to the engine's message for the documents the
  engine sent, and its prompt must still contain every line of the engine's (it sends scripts now and adds one rule).
- `docs/AI_CATALOG.md` and `doc_ingest/tests/graph.mmd` regenerated.

## Tests

`tests/hiru_ai/test_story_reader.py` (the yardstick, the ingest and the cache, the build on the four fixtures, the canon),
`steps/story_check/tests`, `agents/story_reader/tests`. On the four fixtures with scripted answers: **3 of 3 story files build
scenes**, 23 + 8 + 3 spoken lines, **none changed, dropped or reordered**; a writer that loses a line is replaced by the
reader's lines with a warning; the bible-only file builds none and feeds the canon; a real screenplay never calls the reader.

## Known limits

- The reader and the cutter missing the **same** line is not caught by code (PLAN §7). Phase 5 counts by hand.
- A reader that gives wrong `ends_with` for an episode loses that episode (dropped, warned, rules look again if nothing else
  was found); only an overlap with the next episode is repaired.
- A very short stage direction that is the last line before a spoken line and is wrapped in `( )` or `* *` is treated as that
  line's direction in the fallback cut, not as action.
- The warnings from a reading are repeated in each structure build's job log.
