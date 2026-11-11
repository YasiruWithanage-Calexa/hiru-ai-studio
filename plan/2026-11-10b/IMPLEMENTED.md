# plan/2026-11-10b: implemented

Built offline 2026-11-10/11, uncommitted. No model, Veo or image call was made.

## What is built

| Piece | Where | Notes |
|---|---|---|
| Word list, scan, messages, prompt line | `src/libs/contracts/safe_depiction.py` | 18 terms; harmless phrases excluded ("dead of night", "wound up", "dying light", "dead still"); "shot", "body", "gun" not listed |
| Video gate | `contracts/video_gen.py` | `validate_render` blocks a listed word in the prose (covers the API plan, "Make again" and the render function's backstop); `check_render` gives a spoken-line advisory; the negative prompt is never scanned |
| Frame gate | `services/frame_render/engine/pipeline.py`, `hiru_ai/systems/frame_render/graph.py` | the frame is stored `refused` with the words and a way out; the image model is not called |
| Refusal hint | `veo.py`, `omni.py`, `frame_render/engine/image.py`, `hiru_ai/adapters/images.py` | `REFUSAL_HINT` ends every provider refusal |
| Prompt line | `shot_writer` + legacy `shots.py` (identical: parity hash), `adam_take`, `adam_shot_designer`, `david_author`, `jonathan_author`, `jonathan_revise`, `zora_author`, `raphael_planner`, `raphael_cinematic`, `sable_agent` | one line (a paragraph in Adam's); the lab-parity tests declare it as an addition |
| Knowledge base | `knowledge_bases/rules/sources/safe_depiction.md`, `component.yaml` | in the `rules` corpus; **not ingested** |
| Docs | `CLAUDE.md` section, both `UPSTREAM.md` files | |

No interface change: the Generate card already shows the first blocking check, and a refused frame shows its error.

## Tests

- `tests/contracts/test_safe_depiction.py`: what blocks, what passes, spoken lines, Sinhala, the video checks, the
  frame message, the non-group writers, and every tagged prompt holding the exact line.
- `tests/<group>/test_safe_depiction.py` (adam, david, jonathan, zora, raphael, sable): each group checks its own
  writers, so no file outside a group names it (the removal tests).
- Parity: new case `frame_render/safe_depiction` (both engines stop the frame, nothing painted);
  `shot_producer/model_design` re-recorded (only the DP prompt's hash changed).
- `tests/jonathan/test_lab_parity.py`, `tests/raphael/test_lab_parity.py`: the line is a declared addition.

## Gates

- My areas: 676 passed (contracts, group safe-depiction tests, lab parity, frame_render, video_render, parity).
- `ruff check src tests`: one error, in `tests/api/test_production.py` (not touched here).
- `mypy` clean on the changed modules; `hiru-ai validate` 185 parts, 0 errors.
- `lint-imports`: two contracts broken that this work does not touch (`api -> hiru_ai`, David's agents).
- Failing before this work, unchanged by it: parity `canon_extract/model_cards`, `doc_ingest/*`,
  `structure_build/prose_model*` (graph); the `test_removal` schema files (`schema_v19/v20.sql`, Raphael's
  `models.py`); Raphael's length cap; Adam's score mutations; `raphael_breakdown` eval cases; reader ingest. Adam's
  `test_system` fails locally because `.env` sets `ADAM_MODE=take`.

## Open (the person's)

1. **Ingest the knowledge base.** `hiru-ai` ingest of `rules` embeds the new file: an OpenAI embedding call, so it
   waits for a yes.
2. **Live check.** Render a few sad or crime shots on Veo with the new wording and see which still refuse. Each
   refusal is on its row (`status = refused`); add a word to `TERMS` only when a refusal proves it.
3. **Commit.**
