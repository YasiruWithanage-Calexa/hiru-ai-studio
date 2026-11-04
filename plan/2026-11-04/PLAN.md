# Tools agents use: plan

Status: Phases 0 to 3 built (2026-11-04, see [IMPLEMENTED.md](IMPLEMENTED.md)); the four agents' tools forms are off until
`AGENT_TOOLS` names them after a live A/B, which has not been run; three Phase 3 tools wait for an agent that needs them. It builds on [plan/2026-11-03](../2026-11-03/PLAN.md)
(the part framework: manifests, registry, `react` agents, ports) and changes none of its rules. Decisions marked
**(default)** in §10 are the assumptions this plan is written on; change them before Phase 0 starts.

## 1. The goal

Give the agents a small set of well-made tools so they can **look up what they need instead of being handed
everything**, and **check their own answer in code before they give it**. Two outcomes:

- **More capability**: the director chat can answer questions about any shot, canon card, look or past decision;
  option and translation agents can test what they propose; a person can ask for things that need a lookup.
- **Lower token cost**: large blocks that are sent on every call (the whole shot list, the whole canon, the memory
  list) are replaced by a short summary plus tools, and fewer proposals are refused or sent back by critics.

Success means:

| Measure | Target |
|---|---|
| Agents that use tools | `chat_answerer`, `options_writer`, `translator`, `shot_critic` (Phase 2); others only where an A/B wins |
| Input tokens per director chat turn (eval set, live) | at least 30 % lower than today at equal or better eval scores |
| Option cards refused by the kernel after they are offered | at least 50 % fewer |
| Tool errors per run (eval set) | under 5 % of tool calls |
| Tools any one agent sees | at most 8 (OpenAI's soft limit is 20) |
| A model writing stored data without a person | never (unchanged) |

## 2. What the code does today

- **11 tools** in `src/libs/hiru_ai/tools`, each `run(args, ctx) -> Result` plus `as_tool()` (`core/tooling.py`).
- **No agent lists a tool.** All 29 agents have `tools: []` and are `structured` or `text` calls. The catalog shows
  "used by: –" for 9 of the 11 tools; `canon_write` and `structure_write` are called by systems in code.
- **The `react` builder is built and tested but unused** (`core/agents.py`, `core/middleware/react.py`: `hitl`,
  `retry`, `fallback`).
- **The director's four read tools are not parts.** `search_production`, `get_canon`, `get_shot_timing`,
  `list_open_questions` live as hand-written OpenAI definitions in `steps/scene_kernel/tools.py` (and the legacy
  `director_chat/engine/tools.py`).
- **Context is packed in up front.** `chat_answerer` gets persona, history and the full shot list every turn;
  `conductor` and `options_writer` get the memory list and the shot list; `shot_writer` gets a frozen production
  block (cast, style, technique palette), which is cached and cheap.
- **What we measure**: `token_usage` has `phase`, `model`, `input_tokens`, `cached_input_tokens`, `output_tokens`.
  It cannot say which part made a call or how many tool calls a run took.
- **`RunContext`** carries production, actor, job, corpora, documents and ports. It has no scene and no record of the
  person's own words, so a tool cannot default to "this scene" or check dialogue against what the person wrote.

## 3. Industry practice this plan follows

| Practice | Source | How it shows up here |
|---|---|---|
| A few well-designed tools for real workflows; merge calls that always go together; no overlapping tools | Anthropic, *Writing tools for agents*; OpenAI, *Function calling* | `plan_try` is one call (kernel + refusal + ripple); looks fold into `canon_read` |
| Keep under ~20 tools in view; defer the rest | OpenAI, *Function calling* | at most 8 per agent; `tool_search` only if ever needed (Phase 3) |
| Just-in-time context: hand a short reference, let the agent fetch details | Anthropic, *Effective context engineering* | summaries in prompts, read tools for the rest |
| Concise vs detailed responses, paging, truncation with a hint, human-readable names over ids | Anthropic, *Writing tools for agents* (concise ≈ ⅓ the tokens) | `response_format`, `page`, codes `C01` and shot numbers |
| Errors that say how to fix the call, with an example | Anthropic; MCP tools spec (`isError`) | `ToolRefused` gains `how_to_fix` and `example` |
| Poka-yoke the arguments; strict schemas; never ask the model for what code knows | Anthropic, *Building effective agents*; OpenAI | scope, scene and the person's words come from `RunContext` |
| Tool definitions are part of the cached prompt prefix; keep them stable, restrict with `allowed_tools` | OpenAI, *Prompt caching* (cached input 0.1×) | a fixed, sorted tool list per agent; no per-call tool lists |
| Least privilege; a person approves sensitive actions; validate inputs, rate-limit, log | OWASP Top 10 for LLM apps (Excessive Agency); MCP tools spec | `effect: read / stage / write`; models only `stage` |
| Cap loops, clear old tool results | LangChain 1.x built-in middleware | `ToolCallLimit`, `ModelCallLimit`, `ContextEditing` |
| Evaluate with realistic tasks; track tokens, tool calls, errors; spend more time on tools than prompts | Anthropic, *Writing tools for agents* and *Building effective agents* | tool eval cases and new usage columns (Phase 0) |

## 4. Rules every tool follows (the tool contract)

1. **One folder, one manifest.** `tools/<id>/` with `component.yaml`, `tool.py`, `examples/basic.json`, `tests/`.
   Deterministic logic lives in a **step**; the tool is a thin wrapper that names the step in `uses:` (ADR 0009).
2. **Ids are unique across kinds.** A tool never takes the id of the step it wraps (`staging_check` wraps the step
   `stage_check`).
3. **Effect is declared.** `effect: read | stage | write` replaces `writes: bool` (`write` = old `writes: true`).
   - `read`: no change anywhere; free to call.
   - `stage`: creates a pending card a person accepts; never changes the plan, script or canon itself.
   - `write`: changes stored data; **no agent may list it** (`validate` refuses). Only systems call write tools in code.
4. **Arguments hold only what a model may choose.** Production, actor, corpora, the scene in scope and the person's
   own words come from `RunContext`. A scene argument is optional and defaults to the run's scene.
5. **Results are small by default.**
   - `response_format: "concise" | "detailed"`, default `concise`.
   - Lists are paged (`page`, `page_size` ≤ 30) and say `next_page` and `total`.
   - A manifest `max_result_tokens` (default 1,500) is enforced in `tooling.from_part`. Over it, the result is cut
     and ends with a hint naming the argument that narrows it.
   - Codes (`C01`, `L03`), shot numbers (`S04`) and episode / scene numbers, never UUIDs, in what the model reads.
   - Spoken lines go out byte for byte with their language; nothing is translated or trimmed.
6. **Errors teach.** A refused call returns `{"error", "how_to_fix", "example"}`; "not found" lists the 3 closest
   names. Never a stack trace.
7. **The description is written for a new hire**: what it returns, when to use it, when **not** to use it and which
   tool to use instead, one example. `summary` stays one line for the catalog; a new manifest field `guide` holds the
   longer text that becomes the tool description.
8. **Every tool is tested three ways**: unit tests, the generated contract tests (example runs, only declared ports),
   and at least one eval case in an agent that uses it.
9. **Absent-safe.** No embedding key → keyword search; a failed port → a clear error result, never a crashed turn.

## 5. The tool catalogue

20 new tools (17 in Phase 1, 3 in Phase 3), 4 upgraded, 7 unchanged. ★ = needed by Phase 2's first agents.

### 5.1 Read

| Tool | Status | Args (beyond `response_format`) | Returns | Ports | Replaces |
|---|---|---|---|---|---|
| ★ `canon_read` | new | `name_or_code`, `episode?` | the card; with `episode`, the look worn then | canon | `get_canon`; a separate look tool |
| ★ `canon_find` | new | `kind?`, `query?`, `page` | code, kind, name per entity | canon | the whole canon in prompts |
| ★ `memory_search` | new | `query`, `k` ≤ 8 | remembered decisions with citation ids | search | the memory half of `search_production`; `memory` lists |
| ★ `questions_read` | new | `status` (open) | open structure questions | structure | `list_open_questions` |
| ★ `shot_read` | new | `shot`, `scene?` | intent, design summary, latest prompt version, pins, out-of-date flag | scenes | "why is S03 like this" needing the whole plan |
| `scene_reading_read` | new | `scene?`, `from_block?`, `to_block?` | the reading (turns, holds) and the staging map for those blocks | scenes | packed `reading` text |
| `episode_read` | new | `episode?`, `around_scene?` | synopsis, scene list, the scenes either side | structure | `context` / `neighbours` strings |
| `frame_read` | new | `shot?` or `code?` | frames and reference sheets: status, accepted, out of date (never a URL) | files | — (new capability) |
| `glossary_read` | new | `language`, `names?` | fixed spellings of people and places in that script | canon, scenes | — (translator consistency) |
| ★ `scene_read` | upgrade | `scene?`, `include[]`, `shots?` range | only the parts asked for | scenes | today returns everything |
| ★ `search_kb` | upgrade | `query`, `corpus?` (enum, within scope), `k` ≤ 8 | passages with source labels and citation ids | search | the documents half of `search_production` |
| `technique_lookup` | upgrade | `intent`, `k` ≤ 6 | techniques that deliver it | search | — |
| `dialogue_read` | unchanged | | | | |

### 5.2 Check (effect `read`, no model)

| Tool | Status | Args | Returns | Wraps (step) |
|---|---|---|---|---|
| ★ `plan_try` | new | `ops[]` (the kernel's closed op set), `scene?` | per op: applied or refused (a sentence a person can read), the new timing summary, the ripple (shots touched or in doubt). Nothing saved. | `scene_kernel`, `refusal_screen`, `ripple` |
| ★ `timing_check` | upgrade | `scene?`, `shots?`, `fixed_seconds?` | fit report; also each line's start (absorbs `get_shot_timing`) | `contracts.shotplan.fit` |
| `plan_score` | new | `shots[]`, `scene?` | the kernel score and its parts (lower is better) | `kernel_score` |
| `staging_check` | new | `shots?`, `scene?` | teleports, crossed lines, broken eyelines | `stage_check` |
| `dialogue_check` | new | `ops[]` | which dialogue ops use words the person did not write | `verbatim_check` (the person's words come from `RunContext`) |
| `continuity_check` | new | `shot`, `scene?` | end of shot N against start of N+1: positions, props, look, eyeline | new step `shot_joins` |
| `prompt_check` | new | `shot`, `version?` | missing sections, length, dialogue not verbatim, rules from the Veo guide | new step `prompt_lint` |
| `veo_fit` | unchanged | | | |

### 5.3 Stage (effect `stage`, a person accepts)

| Tool | Args | Does |
|---|---|---|
| `change_propose` | `ops[]`, `summary` | Stages a change to the scene as a pending card (the existing `add_pending` path), after `plan_try` would apply it. The only way a model asks to change a plan. |
| `memory_propose` | `rule`, `scope` (scene / production) | Stages "remember this" as a card; accepted, it becomes a `memory_items` row. |

### 5.4 Unchanged write tools (systems only)

`scene_write`, `shot_write`, `canon_write`, `structure_write`, `image_generate`: called by systems in code, never
listed on an agent.

### 5.5 Phase 3 tools

| Tool | Effect | Does |
|---|---|---|
| `job_start` | stage | Asks to re-split, re-produce or re-paint a scene; staged as a card; the API dispatches it when accepted. |
| `frame_inspect` | read | A vision look at an existing frame against its shot or look (see decision D5). |
| `tool_search` | read | Returns tool definitions by need; only if an agent ever needs more than 8 tools. |

## 6. Phase 0: setup

Make the framework ready so every tool in Phase 1 is built the same way and can be measured.

1. **Manifest** (`core/manifest.py`): `effect` (replacing `writes`, with a one-release alias), `guide`,
   `max_result_tokens`, `examples` (paths). `validate`:
   - refuses an agent that lists an `effect: write` tool;
   - refuses a tool whose id is taken by another kind;
   - refuses more than 8 tools on one agent;
   - checks every tool has a `guide` that names when not to use it.
2. **Tool runtime** (`core/tooling.py`):
   - description = `summary` + `guide`;
   - `response_format` handled once for all tools;
   - result size budget with the "narrow it" hint;
   - `ToolRefused(message, how_to_fix, example)` → structured error;
   - "closest names" helper (uses `contracts.canon.name_key`);
   - one telemetry event per call (tool id, ms, result tokens, error).
3. **RunContext** (`core/context.py`): `scene_id` (the scene in scope, from the trusted payload) and `said` (the
   person's own words this turn, for `dialogue_check`). Systems fill them; tools default to them.
4. **Ports** (`core/ports.py`, `core/fakes.py`, `adapters/`):
   - `CanonStore.looks(production_id)`;
   - `Search.memory(query, embedding, production_id, k)`;
   - `StructureStore.open_questions(production_id)`;
   - `FrameStore.frame_status(production_id, shot_ids | codes)`;
   - `DirectorStore.add_pending` reachable from a `stage` tool (a `Staging` port: `add(card)`).
5. **`react` middleware** (`core/middleware/react.py`), new names:
   - `limits`: `ToolCallLimitMiddleware` (run limit 6) and `ModelCallLimitMiddleware` (run limit 4), values per
     agent in the manifest;
   - `clear_old_results`: `ContextEditingMiddleware` with `ClearToolUsesEdit` (keep the last 3);
   - `tool_retry`: `ToolRetryMiddleware` on `read` tools only.
   - `hitl` now gates `stage` tools only where a system asks for it (a staged card is already a person's gate).
6. **Prompt caching**: the tool list of an agent is sorted by id and built once per agent; `static_first` checks
   the tool block too, so a changed description shows as a drifting prefix in tests.
7. **Measuring**:
   - `token_usage` gains `component` (agent id), `component_version`, `prompt_hash`, `tool_calls`,
     `tool_result_tokens`. This is a Database change: the `schema_v10.sql` / `upgrade_v9_to_v10.sql` pair, a
     migration and RLS test rows (ask before touching the hosted project).
   - `hiru-ai eval` reports per agent: score, input / cached / output tokens, model calls, tool calls, tool errors.
     `--ab old,new` compares two manifests on the same cases.
   - Eval cases can script tool calls (`tool_calls:` with expected args) so CI checks a `react` agent without a
     model.
8. **Scaffolding**: `hiru-ai new tool <id> --effect read --wraps <step>` writes the folder with the contract filled
   in; `hiru-ai run tool <id> --format concise|detailed`.
9. **Docs site**: `caps.ts` / the tools foundation page show `effect`, `uses` and "used by agent".

**Exit:** `validate`, the contract tests and the eval report all run on the 11 existing tools with the new fields;
the `token_usage` columns exist locally; no agent's behaviour changed (parity fixtures green).

## 7. Phase 1: create all tools

Build the 17 Phase 1 tools of §5.1–5.3 and the 4 upgrades. No agent uses them yet; each one runs alone.

Order (each group is one PR):

1. **Ports of the director's read tools**: `canon_read`, `memory_search`, `questions_read`, the `search_kb`
   and `timing_check` upgrades. Then `steps/scene_kernel/tools.py` calls these tools by id instead of its own
   definitions (one path; `tests/parity` must stay green).
2. **Scene reads**: `scene_read` upgrade, `shot_read`, `scene_reading_read`, `episode_read`, `canon_find`.
3. **Checks over existing steps**: `plan_try`, `plan_score`, `staging_check`, `dialogue_check`.
4. **New logic**: steps `shot_joins` and `prompt_lint` with their unit tests (cases taken from today's shot critic
   and frame inspector failures), then the tools `continuity_check` and `prompt_check`.
5. **The rest**: `frame_read`, `glossary_read`, `technique_lookup` upgrade.
6. **Stage tools**: `change_propose`, `memory_propose` on the `Staging` port. Accepting a card goes through the
   existing pending-action route; no new API route unless `memory_propose` needs one (decision D4).

For every tool: `examples/basic.json`, unit tests for concise / detailed / paging / not found / refused, contract
tests, a `hiru-ai run tool` example against fakes, and a `--live` read-only run on the dev database (ask first).

**Exit:** 28 active tools (the 11 existing, 4 of them upgraded, plus the 17 new); `hiru-ai catalog` current;
every tool's concise result for its example is under its budget; parity fixtures green.

## 8. Phase 2: assign tools to agents

Switch agents to `react` one at a time, each behind an A/B in `hiru-ai eval --live` (a person runs it; it costs
model calls). An agent switches only if it is **at least as good** on its eval set **and** cheaper or more capable
in a way the cases show. The old manifest stays in git; going back is one line.

| Order | Agent | Shape change | Tools | What leaves its prompt |
|---|---|---|---|---|
| 1 | `chat_answerer` | text → react (streamed) | `scene_read`, `shot_read`, `canon_read`, `memory_search`, `search_kb`, `questions_read`, `timing_check` | the full shot list (a one-line scene summary stays) |
| 2 | `options_writer` | structured → react | `plan_try`, `timing_check`, `canon_read`, `memory_search` | the memory list |
| 3 | `translator` | structured → react | `dialogue_read`, `glossary_read`, `veo_fit` | nothing; it gains consistency |
| 4 | `shot_critic` | structured → react | `prompt_check`, `staging_check`, `continuity_check`, `shot_read` | nothing; fewer missed problems |
| 5 | `shot_writer` | A/B only | `technique_lookup`, `canon_read` | the technique palette, if the A/B wins (it is cached today) |
| 6 | `canon_extractor` | A/B only, long bibles | `search_kb`, `canon_find` | the full bible text, if the A/B wins |

**Stay single calls** (decided, not forgotten): `conductor` (cheap router), the four board crafts and `advisor`
(parallel; code settles and checks them), `scene_planner`, the three plan critics, `stager`, `scene_reader`,
`beat_finder` (code fits and scores their output), the doc-ingest and structure agents. Their checks keep running
**in code** inside their systems. `plan_try` and `continuity_check` are available to them later if an eval shows a
need.

System changes in this phase:

- `director_chat` fills `RunContext.scene_id` and `said`, streams the `react` reply the way `reply_writer` streams
  today (`stream_mode="custom"`), and turns `change_propose` / `memory_propose` results into the cards it already
  shows.
- Citations from `memory_search` and `search_kb` reach the reply as today's `search_production` citations do.
- Each switched agent gets eval cases that need a tool (a question about a shot outside the summary, an option that
  the kernel would refuse, a name with a fixed spelling) and cases that need none (must not call a tool).

**Exit:** the four agents in rows 1–4 run as `react` with green scripted evals in CI and a recorded live A/B in
IMPLEMENTED.md; the §1 targets are met or the reason they are not is written down.

## 9. Phase 3: everything else

1. **`job_start`, `frame_inspect`, `tool_search`** (§5.5), each with an agent that needs it before it is built.
2. **MCP server** (PLAN 2026-11-03 §8): expose the `read` and `stage` tools over MCP, with `readOnlyHint` from
   `effect`, `outputSchema` from `Result`, and the same `RunContext` scope from the caller's token. Write tools are
   never exposed.
3. **Tracing** (ADR 0008): a span per tool call with id, version, effect, tokens, error.
4. **Review loop**: a monthly look at tool errors and repeated calls in traces. Repeated narrow calls mean a tool
   needs paging or a bigger default; repeated errors mean its guide or args need work.
5. **The API's own model calls** (`/ask`) may use the same read tools once the API carries LangChain (still your
   decision, PLAN 2026-11-03).
6. **Retire** `steps/scene_kernel/tools.py`'s hand-written definitions and the legacy `director_chat/engine/tools.py`
   with the Phase 8 removal of the legacy engines.

## 10. Decisions

| # | Decision | Default |
|---|---|---|
| D1 | Agents never hold `write` tools; models change data only by `stage` | **yes (default)** |
| D2 | Per-agent limits: 6 tool calls, 4 model rounds | **(default)**, tuned per agent from evals |
| D3 | Concise result budget | **1,500 tokens (default)** |
| D4 | `memory_propose` accepted through the existing pending-action route | **(default)**; a new route only if that route cannot hold it |
| D5 | `frame_inspect` calls the vision tier from a tool (a tool calling a model) or runs as an agent-as-tool | **agent-as-tool (default)**; not built, no agent needs it yet (IMPLEMENTED.md, Phase 3) |
| D6 | `glossary_read` builds from canon names plus accepted translations, no new table | **(default)**; a `glossary` table only if people need to edit it |
| D7 | `token_usage` columns in `schema_v10` | **(default)**; ask before running on the hosted project |
| D8 | Models stay OpenAI only (CLAUDE.md) | unchanged |

## 11. Risks

| Risk | Guard |
|---|---|
| Tool loops cost more than one packed call | A/B gate per agent; limits; cached prefix; switch back is one line |
| Slower replies in chat | stream the reply; read tools are fast DB reads; 4-round cap |
| A model reaches outside its production | scope only from `RunContext` (unchanged); contract test that a tool uses only declared ports |
| Prompt injection through document text in tool results | `untrusted_text` middleware wraps tool results from documents the same way it wraps prompts |
| Dialogue changed by a tool path | no tool writes a line; `dialogue_check` and `language_guard` unchanged |
| Tool descriptions drift and break the cache | sorted, stable tool block; `static_first` checks it |

## 12. Sources

- Anthropic, *Writing effective tools for AI agents*: https://www.anthropic.com/engineering/writing-tools-for-agents
- Anthropic, *Effective context engineering for AI agents*:
  https://www.anthropic.com/engineering/effective-context-engineering-for-ai-agents
- Anthropic, *Building effective agents* (appendix on tool design):
  https://www.anthropic.com/engineering/building-effective-agents
- Anthropic, *Code execution with MCP*: https://www.anthropic.com/engineering/code-execution-with-mcp
- OpenAI, *Function calling*: https://developers.openai.com/api/docs/guides/function-calling
- OpenAI, *Prompt caching*: https://developers.openai.com/api/docs/guides/prompt-caching
- LangChain, *Built-in middleware*: https://docs.langchain.com/oss/python/langchain/middleware/built-in
- Model Context Protocol, *Tools* (2025-06-18): https://modelcontextprotocol.io/specification/2025-06-18/server/tools
- OWASP Top 10 for LLM Applications, Excessive Agency (LLM06:2025; 2026 edition ranks it 3rd)
