# 0008. Tracing tool

Status: **decided 2026-11-06: Langfuse Cloud (Japan region, `https://jp.cloud.langfuse.com`).**

**Options weighed.** LangSmith (hosted, deepest LangGraph integration, paid past a small free tier), Langfuse
(open source; hosted or self-hosted), or OpenTelemetry only, to Google Cloud Trace.

**Why Langfuse.** It shows each run as one tree (graph, nodes, every agent and panel call, tokens, timing), so the
way agents hand work to each other can be read and tuned. It is open source, so moving to a self-hosted server
later changes only `LANGFUSE_BASE_URL`.

**What leaves.** Prompts, scripts and model replies are sent to Langfuse Cloud. Prompts and scripts are Hiru's
unreleased content; the person approved sending them on 2026-11-06. To keep them in-house instead, self-host
Langfuse (its docker compose) and point `LANGFUSE_BASE_URL` at it.

**How it is wired.** `hiru_ai.core.telemetry.enable_tracing()` registers Langfuse's LangChain handler as a global
LangChain hook, so no graph or agent is changed to be traced. `supabase_rest.build_context` (every function) and the
CLI call it. A new handler is made per top-level run, which is then one trace, and it flushes when that run ends.
Each agent call is named by its component (`agent:translator`) and carries the usage tags (component, version,
prompt hash, phase) as metadata. Without `LANGFUSE_PUBLIC_KEY` and `LANGFUSE_SECRET_KEY`, or without the `langfuse`
package, nothing is traced.

**Package.** `langfuse==5.2.0` (pyproject dev extras). Langfuse Cloud has retired the v3 SDK for new organisations.
It pulls protobuf 7, above google-cloud-tasks' declared `<5`; `tasks_v2` still imports, but check the API before
installing it into a deployed image.

**Not yet.** The deployed functions' `requirements.txt` do not list `langfuse`, so production does not trace until
a person adds it there and sets the keys. Direct OpenAI SDK calls (pictures, embeddings) are not traced.
