# 0002. OpenAI only

Status: accepted (existing rule in CLAUDE.md, restated by the plan).

**Context.** The product decision is that LLMs are OpenAI; Gemini or any other provider needs a person's go-ahead.

**Decision.** `models.yaml` names only OpenAI models. Adding a provider remains a person's decision; with the new
layout it is a `models.yaml` edit, not a code change.

**Consequences.** A gateway's multi-provider value is unused today, which is why
[ADR 0003](0003-litellm-in-process.md) is weighed on its cost alone.
