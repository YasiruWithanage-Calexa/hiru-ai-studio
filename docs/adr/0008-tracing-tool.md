# 0008. Tracing tool

Status: **open.** Not needed before Phase 8.

**Options.** LangSmith (hosted, deepest LangGraph integration), Langfuse (open source, self-hostable), or
OpenTelemetry only, to Google Cloud Trace.

**To decide against.** Prompts and scripts are Hiru's unreleased content, and Supabase is the only hosted data
store today, so a new third-party tracing service needs a person's approval before any trace leaves. Traces are
tagged with component id, version and prompt hash whichever tool is chosen.
