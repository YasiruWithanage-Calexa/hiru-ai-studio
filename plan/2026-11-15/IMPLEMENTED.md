# plan/2026-11-15 — what was built (2026-11-15)

All eight phases, offline: no model call was made by the implementation or its tests. Uncommitted.

| Phase | Where | Tests |
|---|---|---|
| 1 PDF text honours `/ActualText` | `pdf_text.py` beside each extractor, two identical copies (walker + poppler, `PDF_TEXT__ENGINE=auto\|poppler\|walker`); `hiru_ai/steps/extract_text/logic.py` and `services/doc_ingest/.../extract.py` use it | `hiru_ai/steps/extract_text/tests/test_pdf_text.py` (a hand-made PDF with an ActualText span; poppler = walker when installed). Both engines reproduce the lab's 301 lines of both of the person's PDFs exactly. |
| 2 The reading | `contracts/breakdown/reading.py` (wire shapes, `check`, `coverage`, `gates`, `unglue`, `cuts`, `fact_lines`, `envelope`); agents `breakdown_probe` (tier `breakdown_probe`, `effort_breakdown_probe=low`) and `breakdown_read` (tier `breakdown`) | each agent's `tests/` and `evals/cases.yaml` |
| 3 The reading drives the breakdown | `contracts/breakdown/run.py`: `Calls.probe/read`, `read_document`, `reading_phase` (before any split/continuity/episode call), `apply_reading`; `Result.questions/warnings`; `Scene.stated_s/title_doc/facts`; `SourceMemory.reading`; page-furniture rule not applied when a reading exists | `tests/breakdown/test_reading_run.py` |
| 4 The word check | `checks.words`: fact lines skipped; words before a dialogue span (≤ 5) are the speaker's label in any style | same file |
| 5 Lengths | `fill.envelope_of`, `packet` `H_length` / `A_scene.title`, `checks.length` read `stated_s` / `title_doc`; `_MINUTES` deleted | same file; `test_breakdown_run.py` updated |
| 6 Gates in the build | `breakdown_build/graph.py`: probe/read calls, `answers_of`, `open_question_rows`, `waiting` state → job `waiting_input`; stop → job failed with the gate's words; text layer only (D6) | `breakdown_build/tests/test_breakdown_build.py` (pause, answer, resume; damaged letters fail) |
| 7 Typed answers in the Build chat | interface `features/build/components/build-chat.tsx` (`TypedAnswer`), `types.ts`, `lib/map-build.ts` | `build-chat.test.tsx` |
| 8 The upload's role by the model | `hiru_ai/systems/doc_ingest/graph.py` `model_role` when the breakdown is on | existing ingest tests |

Checks: ruff (4 findings, all pre-existing), mypy clean, `hiru_ai validate` 0 errors, catalog regenerated, import
contracts as before (two pre-existing broken contracts: `api.services.media_thumbs`, the David agents). Full pytest:
baseline before this work 57 failed / 5662 passed; after it, every failure left is one the baseline had, and 8 baseline
failures are gone (`tests/parity/conftest.py` now gives parity the same no-model, no-developer-switch settings as every
`hiru_ai` test folder; the rest were a run that overlapped the edits). Interface: typecheck/lint clean for these
files; `raphael-panel.test.tsx` fails with or without this change.

`pdf_text.py` is not in `contracts`: `tests/test_isolation.py` keeps contracts standalone (no pypdf), so each engine
carries its own copy beside its extractor, held identical by a test.

## For the person

- **Deploy (P-1):** the functions are built from source by Google's `python312` runtime, so poppler cannot be
  installed there; `auto` uses the walker in production (proven identical on both scripts). To run poppler in
  production, move `doc_ingest` to a container image as `infra/assemble` is.
- **D6 was decided for you** (stop on damaged letters, ask for a Unicode export); flip it in `reading.probe_gates`.
- **Turn on:** nothing new to switch; the reading runs wherever `BREAKDOWN__ENABLED` is on.
- **Live check (P-2):** one upload and build of each lab layout through the product; a budget you set.
