# 0005. Stop tracking PromptMotion upstream diffs

Status: accepted (plan default, 2026-11-03).

**Context.** Three services are forks of PromptMotion engines, each with an `UPSTREAM.md`, and
`scripts/upstream_diff.py` compares them with the source commit.

**Decision.** The forks are ours now. As each system moves into `hiru_ai`, its `UPSTREAM.md` is archived under
`docs/archive/` (Phase 8). `upstream_diff.py` stays until then.

**Consequences.** No more "merge upstream" work; upstream fixes are ported by hand if wanted.
