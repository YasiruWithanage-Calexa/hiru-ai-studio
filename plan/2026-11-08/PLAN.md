# Sable: one agent that knows the whole production (plan/2026-11-08)

Status: written 2026-11-08; phases 0–3 and 5–7 built offline the same day (no model called, v18 not applied): see
[IMPLEMENTED.md](IMPLEMENTED.md). Plain words: [human-read.md](human-read.md).
Follows: plan/2026-11-04 (the tool contract, `with_tools` forms), plan/2026-11-05d (production memory), plan/2026-11-06e
(Zora), plan/2026-11-07 (chat features on assistant-ui).
Both repos: the backend (`hiru-ai-studio`) and the interface (`hiru-ai-studio-interface`).

## 1. Why

### 1.1 What the person asked for

A second chat beside Zora: simple, **one agent**, average model by default, and it may **choose a stronger model when a
request is hard**. It reaches the production's tools, knowledge and RAG, like Zora.

### 1.2 What the code says today (read 2026-11-08)

| Fact | Where | What it means for Sable |
|---|---|---|
| **Zora has no tools.** It is a fixed pipeline: conductor (`medium`) → kernel/deps in code → ONE author call (`zora` tier) → gate → ledger → reply (`medium`). Its agents list `tools: []`; it reads production memory through middleware only | `systems/zora/zora_chat/turn.py`, `agents/zora/*/component.yaml` | Sable is **not a copy of Zora**. It is the first chat that is a real tool loop. "Like Zora" holds for the rules (scope, memory, dialogue, no costs), not for the shape |
| Zora is **one scene, one plan**: it only edits a scene's stored Jonathan plan | `api/services/zora.py: routes_here` | Sable's scope is the **production**; a scene is optional context |
| 27 tools already exist, each with an `effect` (`read`/`stage`/`write`), a `guide`, a result budget, paging, teaching errors, one telemetry event per call. **No agent may list a `write` tool** (`validate`) | `tools/*`, `core/tooling.py` | Sable's tools are mostly built. It gets the `read` and `stage` ones |
| The `react` agent shape exists: `create_agent` + our middleware (`limits`, `retry`, `fallback`, `clear_old_results`, `tool_retry`, `hitl`), scope from `RunContext`, knowledge bases through `scope_for` | `core/agents.py: _react`, `core/middleware/react.py` | Sable is a manifest + a prompt on this builder, plus two new middleware |
| `chat_answerer` already has a `with_tools` form (7 read tools, `production_docs` base, scripted evals in CI). It is **off**: the live A/B was never run | `agents/chat_answerer/component.yaml`, plan/2026-11-04 IMPLEMENTED | Its prompt, evals and A/B harness are Sable's starting point |
| Tiers: `low` gpt-5-nano/minimal, `medium` gpt-5-mini/low, `high` gpt-5/medium, `ultra` gpt-5/high; agents name a tier, never a model; `fallbacks` per tier | `core/models.yaml`, `core/settings.py` | "Average mode" = a new tier on these settings, not a hard-coded model |
| Installed: langchain 1.4.4, langgraph 1.2.16, langfuse 5.2.0. `AgentMiddleware.wrap_model_call` + `request.override(model=…)` switches the model per call; `SummarizationMiddleware`, `LLMToolSelectorMiddleware`, `ProviderToolSearchMiddleware` (OpenAI `tool_search`) ship with it | `.venv/.../langchain/agents/middleware/` | Model choice per call needs no fork and no new package |
| Threads: `chat_threads (production_id, scene_id NULL-able, title, created_by)`, `chat_messages (kind user/director, text, blocks, ops, citations)` | `Database/schema_v17.sql` | Sable can store its threads here; a thread needs to say which chat it belongs to (§4.8) |
| Every graph run is traced to Langfuse; `token_usage` row per call | `core/telemetry.py`, `core/usage.py` | Tier choices are measurable without new tooling |

### 1.3 The decision this plan makes

**Sable is one `react` agent, production-scoped, on the parts we have.** It answers, finds, checks and explains across the
whole production, and it may **propose** changes as cards a person accepts. It never edits a plan itself: big scene edits
are handed to Zora (or the classic chat) with a link. It starts every turn on an average tier and **escalates once** to a
deep tier when the work needs it (§4.4).

Not in Sable: a second agent, a supervisor, a planner/executor split, subagents, or a vector store of its own. If a
quality problem appears, it is fixed in the prompt, a tool or a code check (`docs/AI_PATTERN.md` rule 8), not by adding an
agent.

## 2. What we learned about building this kind of agent

From the installed LangChain/LangGraph and from public notes on routing (sources at the end). Each line says what Sable does
with it.

1. **One agent with good tools beats many agents for Q&A-shaped work.** Multi-agent systems pay off when sub-tasks are
   independent and long. Sable's turns are short and look things up. → one loop, capped.
2. **Tool quality matters more than prompt length.** Clear names, a "when NOT to use" guide, small results, errors that
   say how to fix the call. → already our tool contract (`core/tooling.py`). Sable adds no tool that skips it.
3. **Too many tools hurt choice and cost.** Every tool definition is sent on every model call. → Sable gets 24 (21 existing
   read/stage tools + 3 of its own), none of the `write` ones. Its list is **fixed and sorted**, so it stays in OpenAI's prompt cache (`Agent.tools()`, plan/2026-11-04
   §6.6). Dynamic tool selection (`LLMToolSelectorMiddleware`) costs an extra model call per turn and breaks the cache, so
   we **do not** use it unless the lab shows tool choice failing. OpenAI's provider `tool_search` is the fallback if the
   list grows past ~30 (§8).
4. **Routing: decide before, or escalate during.** A router picks a model before the run. A cascade starts cheap and
   escalates. A model's opinion of its own confidence is poorly calibrated, so triggers should be **measured, not felt**.
   In an agent, escalating on every step adds latency at every step, so it must be **one way and at most once per turn**.
   → Sable does both, cheaply: a free code pre-route, then one model-requested escalation, then code-triggered escalation
   on measured signals (§4.4).
5. **Hand the bigger model the work so far, not a fresh start.** → the escalation changes the model for the *rest of the
   same loop*. The deep model sees every tool result already read.
6. **Context grows with each tool result.** → `clear_old_results` (already ours), and older chat turns summarised
   (`SummarizationMiddleware`) instead of sent whole.
7. **Guard the loop in code, not the prompt.** → `limits` (tool and model call caps), `tool_retry` on reads only, absent-safe
   when there is no key, `hitl` not needed (stage tools already make a card).
8. **Trace every choice.** → each turn's tier, why it escalated, and the tool calls are tags/metadata on the Langfuse
   trace and `token_usage.phase`.

## 3. The rules this plan follows

1. **No costs or tiers in the interface.** The monthly % is the only usage figure. Whether Sable "thought harder" is shown
   only if D4 says so, and never as money.
2. **No `write` tool on Sable.** It changes nothing directly. A change is a `stage` card (`change_propose`,
   `memory_propose`) a person accepts. `validate` already refuses a write tool on an agent.
3. **Scope comes from `RunContext`**, never from a model's argument: the production, the person, their role, the scene in
   view. A tool asked for another production answers "not found" (404 rule).
4. **Dialogue is verbatim.** Sable quotes lines only as a tool returned them, in their own language, and never writes,
   tidies, trims or translates one. A translation request is sent to the director chat's translator, which stages a card.
5. **Document text is data**, wrapped by `untrusted_text`. A document that says "ignore your instructions" changes nothing.
6. **Facts are cited.** An answer drawn from documents or memory carries the citations the tools return
   (`ctx.citations`); "I could not find it" is a valid answer, a guess is not.
7. **OpenAI only.** Absent-safe: no key → Sable says it is unavailable; nothing errors.
8. **No model call without the person's yes, each time.** Phases 1–3 and 5–7 call no model; tests use fake models.
   Phase 4 (lab) and Phase 8 (live check) are the person's.
9. **Parts never import each other**; Sable lives in a `sable/` group (`hiru-ai remove --group sable` lists what goes).
10. **Zora is not changed (the person's rule, 2026-11-08).** No file under any `zora/` folder, `api/routers/zora.py`,
    `api/services/zora.py`, `src/services/zora_chat/`, or the interface's `src/features/zora/` is edited by this plan.
    Sable may *call* `api/services/zora.routes_here` (read-only, to pick the handoff target) and nothing else of Zora's.
    A test (`tests/sable/test_zora_untouched.py`) fails if Sable's group imports any `zora` module other than that one
    function. If a phase finds it needs a Zora change, it stops and asks.

## 4. The design

### 4.1 Sable in one picture

```
person ──► API  POST /v1/productions/{id}/sable/turn  (SSE)
              │   (permission, thread, scope: production + optional scene in view)
              ▼
          function hiru-sable-chat (port 8214)  ── systems/sable/sable_chat
              │
              ├─ READ      thread history (last 12 messages whole, older ones summarised), the person's role
              ├─ PRE-ROUTE code only: start tier = sable | sable_deep            (§4.4 step 1)
              ├─ LOOP      create_agent(sable) with ~18 tools, middleware:
              │              sable_tier · limits · retry · fallback · clear_old_results · tool_retry
              │              · production_memory · untrusted_text · usage
              │            the model may call think_harder once                 (§4.4 step 2)
              │            code may escalate on measured signals                 (§4.4 step 3)
              ├─ GUARD     citations present for cited facts; no line text that a tool did not return
              └─ SAVE      message + cards + citations + turn meta (tier, escalated, tools) → chat_messages
              ▼
          SSE: status (plain words: "Reading E1S2"), token, card, citations, done | error
```

### 4.2 Where Sable lives

| Part | Path |
|---|---|
| Group | `agents/sable/`, `steps/sable/`, `systems/sable/`, `tools/sable/`, `contracts/sable/`, `tests/sable/`, `tests/eval/sable/`, `docs/sable/`, `lab/sable/` (ids start `sable_`) |
| Agent | `agents/sable/sable` (shape `react`, tier `sable`) |
| Middleware | `core/middleware/tiering.py` (generic: any `react` agent may use it; Sable is the first) |
| System | `systems/sable/sable_chat` (graph: read → loop → guard → save) |
| Function | `src/services/sable_chat/` (`hiru-sable-chat`, port 8214), streamed like Zora (`app/handler.py`) |
| API | `api/routers/sable.py`, `api/services/sable.py` (proxy, as `api/services/zora.py`) |
| Interface | `src/features/sable/` (assistant-ui `chat-thread.tsx`, as Zora) |

### 4.3 The agent and its tools

Manifest (`agents/sable/sable/component.yaml`, sketch):

```yaml
id: sable
kind: agent
shape: react
model: sable                     # the average tier (§4.4)
tools: [canon_find, canon_read, continuity_check, dialogue_read, episode_read, frame_read, glossary_read,
        memory_search, plan_try, prompt_check, questions_read, scene_read, scene_reading_read, search_kb,
        shot_read, staging_check, timing_check, technique_lookup, veo_fit,
        change_propose, memory_propose,
        sable_overview, sable_scene_find, sable_think_harder]
knowledge: [production_docs, cinematography, craft, techniques]
middleware: [static_first, usage, absent_safe, untrusted_text, production_memory,
             tiering, limits, retry, fallback, clear_old_results, tool_retry]
memory: ["*"]
max_tool_calls: 8
max_model_calls: 6
writes_dialogue: false
```

The 19 existing read tools and 2 stage tools are used as they are. Three are new (Phase 3), all `read` except the
escalation tool, which has no effect on data:

| New tool | Why | Shape |
|---|---|---|
| `sable_overview` | "How far along is episode 3?", "what's waiting for me?" have no tool today: `episode_read` is one episode | episodes → scenes with status, planner, plan present, shots, takes, open questions; paged |
| `sable_scene_find` | "Which scenes have Nimal at the temple at night?" needs a search over scenes, not passages | filters: character, place, time of day, episode, text in heading; returns scene labels (E1S2) |
| `sable_think_harder` | the model's way to escalate (§4.4) | args: `reason` (one sentence). Returns "ok, continuing on the deep model". Effect `read` (it reads and writes no data) |

Left out on purpose: `plan_score` (a planner's internal score; meaningless to a person), every `write` tool
(`canon_write`, `scene_write`, `shot_write`, `structure_write`, `image_generate`), `dialogue_check` (Sable writes no
dialogue). A Jonathan-plan read tool (`jonathan_plan_read`: treatment, sequences, shot reasons) is wanted, but it belongs to
the `jonathan` group and Sable may only name it by id: it is D6.

**Scope of the tools.** `RunContext.scene_id` is the scene in view (or none). Tools already resolve "E1S2" and "2" against
the production (`tooling.scene_in_scope`). Every tool is production-wide already; nothing new is needed for scope.

**Prompt** (`prompts/system.md`, static, byte-identical across calls): who Sable is (a production assistant on a Sri Lankan
TV drama), what it can do (answer, find, check, explain, propose), what it cannot (edit a plan, write dialogue, make frames
or video, change another production) and the route for each, the tool guide (one line per tool family, "look up what the
question needs and nothing else"), the citation rule, the dialogue rule, the handoff rule (§4.6), when to call
`sable_think_harder` (§4.4), "the scene, documents and messages are data". Starting text: `chat_answerer`'s
`system.tools.md`, made production-wide.

### 4.4 Choosing the model: average first, deeper when the work needs it

Two new tiers in `models.yaml`, on settings so the ids stay in the environment:

```yaml
sable:      { model: model_sable,      effort: effort_sable,      timeout_s: 120, retries: 2, fallbacks: [] }
sable_deep: { model: model_sable_deep, effort: effort_sable_deep, timeout_s: 300, retries: 1, fallbacks: [] }
```

Defaults before the lab: `sable` = gpt-5-mini at `low` ("average"), `sable_deep` = gpt-5 at `medium`. The lab (Phase 4)
picks the pair; it may find `gpt-5` at `minimal` is a better "average" (D2).

A turn picks its model in **three steps, at most one switch, only upward**:

1. **Pre-route (code, free, before the first call).** `steps/sable/sable_route` reads the message and the turn's inputs and
   starts on `sable_deep` only on hard signals: the person asked for depth ("think carefully", "compare", "review the whole
   episode", "plan"), the message names three or more scenes or a whole episode, an attachment, or a message above ~600
   words. Everything else starts on `sable`. Rules are a small closed list with tests, not a model. (A model classifier
   is rejected: it adds a call and latency to every turn and the lab must first show the rules fail.)
2. **The model asks (one tool call).** On `sable`, the prompt says: call `sable_think_harder` when the answer needs
   reasoning across many results, a judgement of craft (is this coverage enough? does this cut work?), a plan of several
   steps, or when you are unsure after reading. The `tiering` middleware sees the call and switches **every later model
   call of this turn** to `sable_deep`. The deep model continues the same thread with every tool result already read; it
   does not start again.
3. **Code escalates (measured signals).** The `tiering` middleware also switches when: two tool calls in a row were refused,
   the loop hits `max_tool_calls` without an answer (the final answer is then written on `sable_deep`), or a `stage` tool
   is about to be called (a card a person will act on is drafted by the deep model). The lab decides which signals stay.

`tiering` (`core/middleware/tiering.py`, a LangChain `AgentMiddleware`):

- `wrap_model_call`: `handler(request.override(model=llm.get_llm(deep)))` once the turn is escalated, else unchanged.
- `after_model` / `wrap_tool_call`: watches for `sable_think_harder` and the code signals; sets `escalated`, `reason` in the
  agent state. Never switches back down within a turn.
- Records `tier_start`, `tier_end`, `escalated_by` (`route` | `model` | `refusals` | `cap` | `stage`) on the turn, the
  Langfuse trace (metadata + tag `sable:deep`) and `token_usage.phase` (`sable.turn` / `sable.deep`).
- Keeps the tool list and system prompt the same bytes on both tiers, so each tier's cache stays warm.

Why not let the model choose its tier up front: by the time it decides, a model has already been paid for, and a
self-reported "this is hard" is poorly calibrated. Starting cheap and escalating only on need is the cheapest correct
shape, and the pre-route catches the obvious cases without that first wasted call.

### 4.5 Memory of the conversation and of the production

- **Thread**: the last 12 messages go in whole. Older ones are summarised by `SummarizationMiddleware` on the `low` tier
  when the thread passes ~6k tokens; the summary is stored on the thread (`chat_threads.summary`, §4.8) so it is not redone
  every turn. Tool results from earlier turns are **not** replayed: only the replies and their citations.
- **Production memory**: the `production_memory` middleware, as every other agent (`memory: ["*"]`), with `memory_scope`
  narrowed to the scene in view when there is one. Entries used are recorded (`memory.note_used`) so the interface shows
  the "used" chips from plan/2026-11-07 Phase 3.
- **"Remember this"**: `memory_propose` stages a card; accepted, it becomes production memory. Sable never saves memory
  silently.
- **No LangGraph checkpointer for chat**: `chat_messages` is the one source of truth (as Zora). The Postgres checkpointer
  stays for jobs.

### 4.6 Handoff to Zora and the classic chat

Sable does not edit a scene's plan. When a person asks for an edit ("make S03 a close-up", "re-plan E1S2"), Sable:

1. may try it with `plan_try` and say what would happen, and
2. returns a **handoff card** (a block, not a tool with an effect): "Open E1S2 in Zora with this request", which opens the
   scene panel with the request in Zora's composer (the person sends it). **No Zora change:** the card writes the
   request with the shared `writeDraft` (`src/components/chat/chat-tools.ts`) under the key Zora's composer already
   restores on mount (`draftKey="scene.<sceneId>"`, `zora-chat.tsx`), then navigates to the scene. Zora reads it as a
   draft it had saved itself. If that key ever changes on Zora's side, the handoff falls back to copying the request and
   opening the scene. The card picks Zora when
   `api/services/zora.routes_here(scene)` is true, else the classic chat.

Small, exact shot-list changes can instead be staged with `change_propose` (the kernel already confirms every operation
lands). Which of the two Sable prefers is D5.

### 4.7 Events (SSE)

Same framing as Zora's handler (`sse(event, data)`); exact names copied in Phase 0.

| Event | Data |
|---|---|
| `status` | plain words from the tool being called: "Reading E1S2", "Searching the documents", "Thinking this through" (escalation). No tool ids, no model names |
| `token` | reply text as written |
| `card` | a staged change, a memory card, a handoff card |
| `citations` | `[{chunk_id, label}]` |
| `done` | message id, `used` memory entries |
| `error` | one sentence for the person, never an exception's text |

Stop works as plan/2026-11-07 Phase 2: the handler finishes the turn on `GeneratorExit` and saves what was written with
"Stopped".

### 4.8 Storage (schema v18: `Database/schema_v18.sql`, `upgrade_v17_to_v18.sql`, a migration)

- `chat_threads.chat text not null default 'scene' check (chat in ('scene','sable'))`: whether a thread is Sable's.
  Every existing row and every row Zora or the classic chat inserts gets the default `'scene'`, so **their code and their
  queries do not change** and no backfill is needed. Only Sable's repository sets `'sable'` and filters on it. Phase 0
  checks that no Zora or classic query lists threads by `production_id` alone with `scene_id` null (where a Sable thread
  could show up); if one does, Sable keeps its threads in its own table `sable_threads` instead of touching that query.
- `chat_threads.summary text not null default ''` (§4.5).
- `chat_messages.meta jsonb not null default '{}'`: `{tier_start, tier_end, escalated_by, tools: [...], stopped}`. Read by
  `hiru-ai review` and the lab, **never** sent to the browser (rule 1).
- Threads are **per person** (`created_by`); RLS read policy: the person's own threads in productions they can see. Shared
  threads are D3.

Applying v18 is the person's.

### 4.9 Who may use it

`Permission.USE_SABLE` in `contracts/roles.py`: every role that can view the production (Sable only reads). Staging a card
needs the permission the card already needs (`change_propose` needs the scene-edit permission, `memory_propose` the memory
one); a person without it gets the answer and no card. Off until `SABLE__ENABLED`.

## 5. What is reused, what is new

| Reused as is | New |
|---|---|
| 21 tools, `core/tooling.py`, `core/agents.py: _react`, react middleware, production memory middleware, `untrusted_text`, `absent_safe`, usage rows, Langfuse hook, `chat_threads/chat_messages`, Zora's SSE proxy pattern, `chat-thread.tsx`, Stop, memory chips | agent `sable`, 3 tools, `tiering` middleware, `sable_route` step, tiers `sable`/`sable_deep`, system `sable_chat`, function `hiru-sable-chat`, router `sable.py`, schema v18 columns, `features/sable/` |

## 6. Phases

Each phase ends with the backend checks (`ruff check src tests scripts`, `mypy`, `scripts/lint_imports.py`, `hiru-ai
validate`, `hiru-ai catalog --check`, `pytest -q`) and, for interface work, `npx next typegen && npm run check && npm run
format:check`. `IMPLEMENTED.md` is updated at the end of each phase.

### Phase 0: evidence (free)

1. Read (only read) Zora's handler and API for the exact SSE event names, and every query on `chat_threads` in
   `api/repositories/supabase.py`, to confirm a Sable thread can never appear in Zora's or the classic chat's lists
   (§4.8). Write both down here.
2. Measure Sable's tool block: tokens of the 24 tool definitions (`Agent.tool_block()`) + system prompt. Target: under
   ~6k tokens, so the cached prefix is cheap. If over, trim guides before cutting tools.
3. With the person's yes, read (read-only) the dev DB's director/Zora `chat_messages` to collect 30–50 real questions people
   asked that are not edits. If there are too few, the person writes them. These become the lab set.

Done when: the event names, the thread lookup, the prompt size and the question set are in this file.

### Phase 1: the agent, offline (free)

- `hiru-ai new agent sable --group sable`; manifest as §4.3 without the 3 new tools; prompt `system.md`.
- Scripted evals (`tests/eval/sable/`) with fake models, as `chat_answerer`'s: ≥ 12 cases. Calls the right tool for a
  canon / memory / document / timing / shot question; answers without a tool when the thread already says it; refuses
  "rewrite this line" with the route; never quotes a line a tool did not return; cites documents; respects the caps; a
  refused tool call is fixed once, then answered with what it has.
- `validate` passes (no write tool).

### Phase 2: the tiers and `tiering` middleware (free)

- `models.yaml` tiers, settings `model_sable`, `effort_sable`, `model_sable_deep`, `effort_sable_deep`.
- `steps/sable/sable_route` (closed rule list, table-driven tests).
- `core/middleware/tiering.py` + `sable_think_harder` tool. Tests with two fake models: no escalation stays on the base
  model; `think_harder` switches every later call and never back; two refusals switch; the cap's final answer is on the
  deep model; a stage tool switches; the tool list and system prompt bytes are identical on both tiers; meta recorded.

### Phase 3: the new read tools (free)

`sable_overview`, `sable_scene_find` through `hiru-ai new tool <id> --effect read`, with ports already in `RunContext`
(`scenes`, `structure`, `canon`). Contract tests: paging, the result budget, teaching errors, scope (another production's
scene is "not found").

### Phase 4: the lab (paid; the person's yes and budget, proposed $3)

`lab/sable/run.py` (dry / cost / paid, hard cap, as `lab/zora`). On the Phase 0 question set, recorded against a fixed
snapshot of the dev production (fakes for the ports, real models):

| Arm | Model use |
|---|---|
| A | everything on `sable` (average only) |
| B | everything on `sable_deep` |
| C | the router: pre-route + `think_harder` + code signals |

Measured per arm: answer correct (the person grades blind, A/B/C shuffled), cited when it should be, tool calls, latency
p50/p90, cost per turn, escalation rate and reason (C). **Gate:** C within one point (of 10) of B on the person's grades, at
most 50% of B's cost, p90 latency under 25 s. The lab also decides D2 (the base model) and which code signals stay. A
failing gate changes the prompt, the tools or the rules, then re-runs: never a second agent.

### Phase 5: the system and function (free; tests on recorded answers)

`systems/sable/sable_chat` (graph read → loop → guard → save), `src/services/sable_chat` (`hiru-sable-chat`, port 8214;
`FUNCTIONS`, `deploy-functions.yml`, `scripts/start-functions.ps1`), streaming events (§4.7), Stop on `GeneratorExit`,
absent-safe (no key: one plain sentence). Guard step: a quoted line that no tool returned is removed and noted in meta.

### Phase 6: the API and schema v18 (free to build; applying v18 is the person's)

`routers/sable.py`: `GET /v1/productions/{id}/sable/threads`, `POST …/sable/threads`, `GET …/sable/threads/{tid}`,
`POST …/sable/turn` (SSE proxy), `DELETE …/sable/threads/{tid}`. `Repos` protocol + fakes; `Permission.USE_SABLE`; 404
for a production the caller cannot see. Migration + v18 pair, verified three ways (CLAUDE.md "Hosted dev DB"); RLS tests in
`supabase/tests/database/`.

### Phase 7: the interface (needs D1)

`src/features/sable/` (`api.ts`, `client.ts`, components). The stock `chat-thread.tsx` with Sable's runtime; cards:
staged change (existing), memory (existing), handoff (new: opens the scene panel with Zora's or the classic chat's
composer filled). Entry point as D1 decides. Status line shows the `status` words; no tier, no cost. Thread list per
person. Lines in replies rendered with `spoken()`.

### Phase 8: the live check (the person's)

Turn on `SABLE__ENABLED` locally, ask the lab set again on the dev production, look at the traces in Langfuse (tier
choices, tool errors, cut results), run `hiru-ai review`. Then the person decides the default and the deploy.

## 7. Decisions for the person

| # | Decision | My suggestion |
|---|---|---|
| D1 | Where Sable opens in the interface | A button in the top bar that opens a side panel on every production page, knowing the page's scene when there is one. One Figma frame first |
| D2 | The "average" model | gpt-5-mini at `low` until the lab; then the lab's pick |
| D3 | Threads per person or shared in the production | Per person (simpler, private); sharing later |
| D4 | Show that Sable "thought harder"? | Only the `status` words during the turn ("Thinking this through"); nothing stored or shown after |
| D5 | Edit requests: handoff card to Zora, or stage `change_propose` itself | Handoff for anything that touches the creative plan; `change_propose` only for exact shot-list operations the person spelled out |
| D6 | Give Sable a read of Jonathan's plan (`jonathan_plan_read`, built in the `jonathan` group) | Yes; it is the most-asked thing ("why is S03 a wide?") |
| D7 | Lab budget | $3, hard cap, one yes per paid run |
| D8 | Can a viewer (read-only role) use Sable? | Yes, without cards |

## 8. Risks

| Risk | Guard |
|---|---|
| Sable and Zora overlap and people do not know which to use | Clear line in the prompt and the UI copy: Sable answers and finds across the production; Zora edits a scene's plan. The handoff card makes the route one click |
| Too many tools, wrong tool chosen | 24 fixed, sorted tools with guides; lab measures choice; only then `LLMToolSelectorMiddleware` or OpenAI `tool_search` |
| Escalates too often (cost) or never (quality) | Lab gate with escalation rate; the rules are a closed list; the monthly % absorbs cost, nothing is shown in money |
| Long threads grow the context | Last 12 whole, older summarised and stored, earlier tool results never replayed, `clear_old_results` in the loop |
| Prompt injection from documents | `untrusted_text`, no write tools, scope from `RunContext`; a card still needs a person |
| Made-up facts or lines | Citations required for document facts; guard removes a line no tool returned; "I could not find it" is allowed |
| Latency on deep turns | One switch per turn, deep timeout 300 s, `status` words while it works, Stop always available |
| Cloud Run throttles CPU after the client leaves (plan/2026-11-07 Phase 2 note) | Same handling as Zora; checked in Phase 8 |

## Phase 0 findings (2026-11-08)

1. **Event names.** Zora's function streams `status, plan, delta, ops, gate, proposals, confirm_reshape, message, done,
   error` (`contracts/zora/events.py`), the API adds `accepted` first; the classic chat uses `accepted, status, delta,
   plan, message, done, error`. Sable uses `accepted, status, delta, card, citations, message, done, error`: `delta`, not
   `token`.
2. **Thread lookups.** `SupabaseThreads.list(production_id, scene_id)` is called by the classic chat and Zora only with a
   scene from the URL (`routers/director.py` list and turn, `routers/zora.py` turn), so a Sable thread (no scene) never
   appears in their lists, and both turns refuse a thread whose `scene_id` is not the scene. **But**
   `GET|DELETE …/threads/{id}/messages` (classic) looked a thread up by id alone: anyone in the production could have read
   or emptied a Sable thread by its id. Those two routes now answer 404 for a thread whose `chat` is not `scene`, and
   v18's read policies keep a Sable thread to its creator. So `chat_threads` is kept (no `sable_threads` table).
3. **Prompt size.** 24 tools + prompt ≈ 9.8k tokens (tools 8.6k, prompt 1.2k), over the ~6k target; not trimmed (the
   shared guides are other agents' prompts too). See IMPLEMENTED.md.
4. **Question set.** Not collected: reading the dev DB needs the person's yes.

## Sources (best practice, 2026-11-08)

- LangChain agents and middleware: https://docs.langchain.com/oss/python/langchain/agents.md
- LangChain v1 migration (dynamic model via `wrap_model_call`): https://docs.langchain.com/oss/python/migrate/langchain-v1
- Routing and cascades: https://tianpan.co/blog/2025-11-03-llm-routing-model-cascades,
  https://www.channel.tel/blog/llm-model-routing-cascade-production-agents, https://pakodas.substack.com/p/llm-routers
- Installed source read directly: `langchain/agents/middleware/{tool_selection,provider_tool_search,summarization,types}.py`
