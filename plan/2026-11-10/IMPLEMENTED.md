# Implemented: Raphael's breakdown (plan/2026-11-10)

Built offline with fake models, uncommitted. All five build-order steps are done.

1. `BreakdownW` (`contracts/raphael/wire.py`), `breakdown_faults` and `breakdown_missing` (`checks.py`),
   `pack.breakdown_block` / `pack.scene_opening` (`pack.py`).
2. Agent `agents/raphael/raphael_breakdown` (schema, prompt, eval case, test); tier `raphael_breakdown` in `models.yaml`;
   settings `OPENAI__MODEL_RAPHAEL_BREAKDOWN`, `OPENAI__EFFORT_RAPHAEL_BREAKDOWN`, `RAPHAEL_BREAKDOWN` (`.env.example`).
3. `Planner.make_breakdown` (one request, one retry with the faults, fall back with a job warning, charged to the scene's
   meter), both openings, three stage 1 prompt lines and one stage 2 line (`test_lab_parity.py` allows exactly these),
   `breakdown:missing` in `check_stage1` (report only), `StoredRaphael.breakdown`, reuse on the same input hash,
   `more_cinematic` reads the stored one. The input hash is taken WITHOUT the breakdown, so it is unchanged.
4. API: `/scenes/{id}/raphael` returns `result.breakdown` with the rest (the router passes the stored JSON through).
   Interface: `types.ts`, `lib/map-raphael.ts`, a read-only "Breakdown" table in `raphael-panel.tsx`, panel tests.
5. Docs: `docs/raphael/README.md`.

Tests: `tests/raphael/test_breakdown.py` (15). `tests/raphael` conftest sets `RAPHAEL_BREAKDOWN=false` so the older tests are
unchanged. Four tests in `tests/raphael` (1.0 cap in two API tests and one check test; `schema_v20` in the removal test) and
one in the interface (caps list) failed before this work and still do.

Not done, the person's: the first live scene (needs a yes), D1 to D4.
