# 0003. LiteLLM in-process, behind `get_llm`

Status: **decided 2026-11-03: `get_llm` returns `ChatOpenAI`; LiteLLM stays the documented swap.** The Phase 0 spike
finished the same day; the plan's default had been LiteLLM.

**Context.** The plan routes every model call through LiteLLM's Router library (`langchain-litellm`'s
`ChatLiteLLMRouter`) for tiers, retries, fallbacks and one usage callback, with no separate proxy server. It also
says: if the spike shows too high a cold-start cost, `get_llm` returns `ChatOpenAI` and nothing else changes.

**Spike** ([plan/2026-11-03/spike/](../../plan/2026-11-03/spike/), run against a local fake of the OpenAI endpoint,
so it cost nothing and used no key):

| | today (`openai` + langgraph) | `langchain-openai` | `langchain-litellm` |
|---|---|---|---|
| strict `json_schema` on the wire, schema intact | n/a | yes | yes |
| messages byte-identical to today's call (cache prefix) | n/a | yes | yes |
| `reasoning_effort` passes through | yes | yes | yes, via `model_kwargs` |
| usage numbers equal today's `token_usage` row | n/a | yes (`usage_metadata`) | yes (callback) |
| retry, then fall back to the next tier | by hand | `with_fallbacks` | Router, yes |
| embeddings with `dimensions` | yes | yes | yes, set on the embeddings object |
| installed size / zip (Linux wheels, the largest service set) | 85 MB / 23 MB | 95 MB / 26 MB | **287 MB / 97 MB** |
| packages | 60 | 63 | 105 |
| import time, median of 7 fresh interpreters (Windows laptop) | 3.7 s | 3.6 s | **8.7 s** |
| peak memory after import | 97 MB | 100 MB | **204 MB** |

What the spike did not prove, because it needs the real service: OpenAI prompt-cache hits (we checked the bytes
that decide them, not the hits), and cold start on Cloud Run (the laptop has antivirus, so read the ratio, not the
seconds).

**Decision (taken by the product owner after the spike).** Start Phase 1 with `get_llm` returning **`ChatOpenAI`**, and keep
LiteLLM as the documented swap for when a second provider is approved. Both behave the same on every check;
LiteLLM's extra value (many providers) is unused under [ADR 0002](0002-openai-only.md), while it adds about 5 s of
import and 190 MB to every function, including `director_chat`, which a person waits for, and which runs in 512 Mi.
Retries and tier fallback are a few lines in `get_llm` (`max_retries`, `.with_fallbacks()`). Both hashed
requirement sets are ready: `requirements/hiru_ai.txt` (LiteLLM, the plan's default) and
`requirements/hiru_ai_openai.txt` (the fallback).

**Consequences of choosing the fallback.** `core/llm.py` and `core/usage.py` are written against LangChain's
`BaseChatModel` and `usage_metadata`, so either gateway fits. Nothing else in the plan changes. If LiteLLM is
chosen instead, re-measure on Cloud Run before Phase 6.
