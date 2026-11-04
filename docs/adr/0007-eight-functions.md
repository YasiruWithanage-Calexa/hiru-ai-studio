# 0007. Keep eight Cloud Run functions

Status: accepted (plan default, 2026-11-03).

**Decision.** One function per system, as today. A single generic runner is a later option, chosen on deploy and
cold-start numbers (see [ADR 0003](0003-litellm-in-process.md)).

**Consequences.** The job rules in CLAUDE.md ("Jobs") do not change. A new system still needs a `JobKind`, a
`FunctionSpec`, a line in `deploy-functions.yml` and one in `scripts/start-functions.ps1`.
