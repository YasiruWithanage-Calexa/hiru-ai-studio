# Sable, the production assistant chat (plan/2026-11-08)

Sable answers, finds, checks and explains across a whole production. It is **one react agent** (`sable_agent`) with the
production's read tools; it changes nothing itself (a change is a card a person accepts) and hands a scene's plan edits to
that scene's own chat (Zora or the classic one). Zora is not changed by Sable and Sable reads nothing of Zora's but
`api/services/zora.routes_here`.

```
browser ─ POST /v1/productions/{id}/sable/turn ─► API (who, may they accept cards, their thread, the scene in view)
          ◄── SSE: accepted · status · delta · card · citations · message · done | error
             └─► hiru-sable-chat (port 8214) ─► systems/sable/sable_chat: read → loop → guard → save
```

| Part | Where |
|---|---|
| Agent | `agents/sable/sable_agent` (tier `sable`, `deep_model: sable_deep`, 24 tools, `tool_cap: 24`) |
| Thread summary | `agents/sable/sable_summary` (tier `low`) |
| Pre-route | `steps/sable/sable_route` (closed rule list) |
| Model switch | `core/middleware/tiering.py` (generic; once per turn, upward only) |
| Tools | `tools/sable/sable_overview`, `sable_scene_find`, `sable_think_harder` + the shared ones in `agents/sable/group.yaml` `shared:` |
| System | `systems/sable/sable_chat` (`turn.py`, `guard.py`, `graph.py`) |
| Function | `src/services/sable_chat` |
| Contracts | `contracts/sable/events.py` |
| API | `api/routers/sable.py`, `api/services/sable.py`, `SableRepo` |
| Storage | schema v18: `chat_threads.chat / summary / summarised`, `chat_turn_meta` (admin-read only) |
| Interface | `hiru-ai-studio-interface/src/features/sable/`, "Ask Sable" in the top bar |
| Tests | `tests/sable/`, each part's own tests, `hiru-ai eval sable_agent` |

Rules that must not drift: no write tool on the agent; scope from `RunContext`; dialogue quoted only as a tool returned
it (the guard takes out any other); no tier, model, tool id or cost reaches a browser (`chat_turn_meta` is not readable by
members); a thread is one person's own; a card needs Permission.DIRECT and is carried out by code.

Switches: `SABLE__ENABLED` (API and function; needs schema v18), `OPENAI__MODEL_SABLE`, `OPENAI__EFFORT_SABLE`,
`OPENAI__MODEL_SABLE_DEEP`, `OPENAI__EFFORT_SABLE_DEEP`. Read `plan/2026-11-08/IMPLEMENTED.md` for what is built and what
waits for a person.
