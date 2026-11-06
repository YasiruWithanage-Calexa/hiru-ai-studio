# Architecture decision records

One file per decision of [plan/2026-11-03 §10](../../plan/2026-11-03/PLAN.md), and one per decision the phases found (0009). Format: context, decision,
consequences. A decision changes by a new record that supersedes the old one, never by editing history.

| # | Decision | Status |
|---|---|---|
| [0001](0001-one-shared-package.md) | One shared package `hiru_ai`, bundled into every function | Accepted (plan default) |
| [0002](0002-openai-only.md) | OpenAI only | Accepted (existing rule) |
| [0003](0003-litellm-in-process.md) | Model gateway: `ChatOpenAI` behind `get_llm`; LiteLLM is the later swap | Accepted (2026-11-03, replaces the plan's LiteLLM default) |
| [0004](0004-migrate-one-system-at-a-time.md) | Migrate one system at a time, with a rollback switch | Accepted (plan default) |
| [0005](0005-stop-tracking-upstream.md) | Stop tracking PromptMotion upstream diffs | Accepted (plan default) |
| [0006](0006-tests-live-with-the-part.md) | Tests live in each part's folder | Accepted (plan default) |
| [0007](0007-eight-functions.md) | Keep eight Cloud Run functions | Accepted (plan default) |
| [0008](0008-tracing-tool.md) | Tracing tool | Open (not needed before Phase 8) |
| [0009](0009-parts-reach-siblings-by-id.md) | A part that builds on a sibling asks for it by id and says so in its manifest | Accepted (2026-11-03, found in Phase 2) |
| [0010](0010-one-author-pattern.md) | One author per creative unit, code checks, narrow repair (the Hiru AI pattern) | Accepted (2026-11-05, plan/2026-11-05e) |
