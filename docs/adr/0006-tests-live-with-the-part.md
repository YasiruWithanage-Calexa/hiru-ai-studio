# 0006. Tests live in each part's folder

Status: accepted (plan default, 2026-11-03).

**Decision.** An agent's tests and eval cases sit in its own folder, like a tool's or a panel's. `tests/` keeps the
API, `contracts`, cross-system, parity and eval tests.

**Consequences.** Removing a part removes its tests. Generated contract tests run over the registry. Pytest must be
pointed at `src/libs/hiru_ai` as well as `tests/` (Phase 1).
