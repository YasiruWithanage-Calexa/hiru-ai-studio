# 0001. One shared package `hiru_ai`, bundled into every function

Status: accepted (plan default, 2026-11-03).

**Context.** `tests/test_isolation.py` and the deploy workflow let a function import only its own package and
`contracts`. So `runtime/llm.py`, `config.py`, `store.py`, `rest.py` and `checkpoint.py` exist once per service (up
to eight copies), and an agent cannot be reused by a second function.

**Decision.** `src/libs/hiru_ai/` is installed like `contracts`: every function zip holds its own folder,
`contracts` and `hiru_ai`. This replaces the "a service imports only itself" rule with layer rules enforced by
`import-linter` (see [AI_ARCHITECTURE.md](../AI_ARCHITECTURE.md)).

**Consequences.** Reusable parts; one place to fix a model wrapper. A change to `hiru_ai` redeploys every function
(as a change to `contracts` does today). Until Phase 8 the old rules stay: `lint_imports.py` keeps the services
apart and `tests/test_isolation.py` stays.
