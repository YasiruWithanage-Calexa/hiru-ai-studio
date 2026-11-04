# Tools agents use: what is built

Plan: [PLAN.md](PLAN.md). Updated at the end of each phase. Phases 0 to 3 are built (2026-11-04). **Nothing changes in the
running system until someone sets `AGENT_TOOLS`**, and the plan says nobody should before the live A/B in "Open items" has
been run and read: that run costs model calls and a person starts it.

## Exit checks

| Phase | Exit condition | State |
|---|---|---|
| 0 | `validate`, the contract tests and the eval report run on the 11 existing tools with the new fields | done: `effect`, `guide`, `max_result_tokens`, `examples` on all of them; scripted eval cases pass with tokens, model calls, tool calls and tool errors reported |
| 0 | the `token_usage` columns exist locally | `upgrade_v9_to_v10.sql` was run on the hosted dev database by the owner (2026-11-04); the migration, `schema_v10.sql` and the pgTAP test were **not** run or compared (no `supabase start`); `USAGE_DETAIL` is still `false` |
| 0 | no agent's behaviour changed (parity fixtures green) | done: `tests/parity` and the director's system tests pass |
| 1 | 28 active tools (the 11 existing, 4 upgraded, plus 17 new) | done: `hiru-ai list tool` shows 28 |
| 1 | `hiru-ai catalog` current | done; the tools table has an `effect` column, the agents table says which have a tools form |
| 1 | every tool's concise result for its example is under its budget | done, one test per tool; none of the examples is cut |
| 1 | parity fixtures green | done |
| 2 | the four agents of rows 1 to 4 run as `react` with green scripted evals in CI | **done as a switchable form**: each has a `with_tools` form, its own prompt and 5 or 6 scripted cases (3 that call tools, 1 that must not) that run in CI; the form is off until `AGENT_TOOLS` names the agent |
| 2 | a recorded live A/B in this file; the §1 targets met or the reason written down | **not done**: a live A/B costs model calls and is a person's to start. What I could measure offline is in "Prompt size", and it says the 30 % target for `chat_answerer` may not be met |
| 3 | `job_start`, `frame_inspect`, `tool_search` each with an agent that needs it | **not built**, by the plan's own rule: no agent needs them (see "Phase 3") |
| 3 | MCP server, a span per tool call, the review loop | done (`hiru-ai mcp`, `core/telemetry.tool_span`, `hiru-ai review`) |
| 3 | `/ask` on the read tools, retire the hand-written definitions | **not done**: both wait on decisions outside this plan (see "Phase 3") |

## Phase 0: setup

1. **Manifest** (`core/manifest.py`): `ToolManifest` gains `effect` (`read` / `stage` / `write`), `guide`, `max_result_tokens` (default
   1,500) and `examples`. `writes: true|false` still loads, as a one-release alias, and `manifest.writes` is a property. An
   `AgentManifest` gains `max_tool_calls` (6), `max_model_calls` (4) and `gate` (stage tools that stop for a person). A step may
   name `tools:` it reaches by id. `validate` (`core/registry.py`) refuses: an agent that lists a `write` tool, more than 8 tools
   on one agent or a tool twice, a `gate` entry that is not one of its stage tools, a tool whose id is also another kind's, a
   tool with no `guide` or a guide that does not say when NOT to use it, a missing example, and a `stage` tool without the
   `staging` port.
2. **Tool runtime** (`core/tooling.py`): the description is `summary` + `guide`; `ToolArgs` (`response_format`) and `Paged`
   (`page`, `page_size` up to 30) are the bases of a read tool's arguments; a result is cut to `max_result_tokens` by dropping the
   tail of its biggest list (then shortening its longest text) and ends with `truncated: {shown, hint}` naming the argument that
   narrows it; `ToolRefused(message, how_to_fix, example)` answers `{"error", "how_to_fix", "example"}`; a failed port answers
   "That lookup is not available right now." and the loop goes on; `closest()` / `not_found()` give the 3 nearest names;
   `shot_number`, `shot_code`, `scene_label` and `scene_in_scope` ("E1S2", "2", or the run's scene) speak in codes; one
   `ToolEvent` (tool, ms, result tokens, error) per call is appended to `RunContext.tool_events` and logged. `tokens_of` (in
   `core/tokens.py`) is an offline estimate (Latin 4 characters a token, Sinhala 1.5): it errs high on purpose.
3. **RunContext**: `scene_id`, `said`, `usage_detail`, `tool_events`, `citations`, and a `staging` port. `hiru-ai run tool` fills
   them from a case file (`scene_id`, `said`).
4. **Ports**: `CanonStore.looks`, `Search.memory`, `StructureStore.open_questions`, `FrameStore.frame_status` (counts and states, never a
   path), `Staging` (`add`, `staged`; `core/staging.py` `StagedCards` is the real thing and the fake: a list the director's turn
   reads back), and one the plan did not list, `SceneStore.latest_prompts`, which `shot_read` and `prompt_check` need. Fakes and
   the Supabase adapters are written for all of them.
5. **`react` middleware**: `limits` (tool-call and model-call caps from the manifest), `clear_old_results` (keeps the last 3 tool
   results once a thread passes 3,000 tokens), `tool_retry` (read tools only). `hitl` gates the manifest's `gate` list.
6. **Prompt caching**: `Agent.tools()` builds the tool list once, sorted by id; `Agent.tool_block()` is what `static_first` checks
   (sorted, and the same bytes on every call for the same agent and version).
7. **Measuring**: `UsageCallback` writes `component`, `component_version`, `prompt_hash`, `tool_calls` and `tool_result_tokens` when
   `RunContext.usage_detail` is on. `hiru-ai eval` reports per agent the score, input / cached / output tokens, model calls,
   tool calls and tool errors; `--ab old.yaml,current` runs the same cases through two manifests; a `react` agent's case can script
   `tool_calls:` (with `expect:` on the answer), `expect_no_tools:` and `allow_tool_errors:`, and runs without a model.
8. **Scaffolding**: `hiru-ai new tool <id> --effect read --wraps <step>`; `hiru-ai run tool <id> --format concise|detailed` also prints
   the tokens a model would read.
9. **Database (schema v10)**: `supabase/migrations/20261104024457_token_usage_component.sql`, `Database/schema_v10.sql`,
   `Database/upgrade_v9_to_v10.sql`, a pgTAP test (`supabase/tests/database/010_token_usage_component.test.sql`) and the README
   section. `USAGE_DETAIL=false` (default) keeps writing v9 rows, so the code can ship before the SQL is run.

## Phase 1: the tools

New (17): `canon_read`, `canon_find`, `memory_search`, `questions_read`, `shot_read`, `scene_reading_read`, `episode_read`,
`frame_read`, `glossary_read` (reads); `plan_try`, `plan_score`, `staging_check`, `dialogue_check`, `continuity_check`,
`prompt_check` (checks, no model); `change_propose`, `memory_propose` (stage). Upgraded (4): `scene_read` (`scene`, `include[]`, `shots`
range), `timing_check` (`scene`; also when each line starts), `search_kb` (`corpus`, `cite`), `technique_lookup` (`intent`).
Two new steps hold the new logic: `shot_joins` (positions, side of frame, props, join size, canon cards across a cut) and
`prompt_lint` (missing sections, duration, dialogue not word for word, length, failed stored checks). `core/views.py` and
`core/trial.py` hold what several tools share (a tool never imports another tool).

The director's four read tools now go through the parts (`steps/scene_kernel/tools.py`): `get_canon` is `canon_read`,
`list_open_questions` is `questions_read`, `get_shot_timing` is `timing_check`'s formatter over the kernel as it stands mid-turn.

## Phase 2: the four agents get their tools

**How it is switched.** An agent's manifest carries a `with_tools:` block (`core/manifest.ToolsForm`): its tools, its own prompt
(`prompts/system.tools.md`), the middleware and loop caps. `Agent(registry, id)` runs the `react` form when `AGENT_TOOLS` names the
agent, else the manifest as it was; `Agent(..., with_tools=True|False)` forces one (evals, tests). `validate` holds the form to the
rules of a react agent (at most 8 tools, none that writes, a prompt of its own). This is the plan's "going back is one line",
and it is how a form can be built, tested and measured before it replaces anything. The director chat runs on `AI_ENGINE=graph`
only; the legacy engine is untouched.

| Agent | Tools | What left its message |
|---|---|---|
| `chat_answerer` | `canon_read`, `memory_search`, `questions_read`, `scene_read`, `search_kb` (the `production_docs` base), `shot_read`, `timing_check` | the shot list; a one-line summary of the scene stays (`turn.scene_brief`) |
| `options_writer` | `canon_read`, `memory_search`, `plan_try`, `timing_check` | the memory list (`Models.options` empties it when the form is on) |
| `translator` | `dialogue_read`, `glossary_read`, `veo_fit` | nothing; it gains consistency |
| `shot_critic` | `continuity_check`, `prompt_check`, `shot_read`, `staging_check` | nothing; the checks code can make are made by tools |

System changes:

- `director_chat` (`systems/director_chat/turn.py`) puts `scene_id` and `said` in the context every model of the turn gets, runs
  the answerer as a tool loop when its form is on (the answer comes back whole, as the old `tool_rounds` answer did), and merges
  the search tools' citations into the stored message (`turn.cited`, each passage once, at most 8).
- Staged cards (`systems/director_chat/staged.py`): after the reply the turn reads `staging.staged()` and shows each card as an
  option of the options card. A `change` card carries the kernel-confirmed operations pinned to the shots' ids, so accepting it
  is the code path of a button press; a `memory` card is a message to the board ("Remember from now on: ..."), D4's existing
  route. A card for another scene, or of an unknown kind, is dropped. No agent has a stage tool in Phase 2 (the plan's table gives
  none), so this is ready and tested but nothing produces cards yet.
- `shot_producer` reviews a scene's designs before they are saved, so the critic's tools would have read last time's design. The
  critic gets the drafts through an overlay of the scenes port (`systems/shot_producer/drafts.py`; writes refuse).
- `dialogue_read` takes its scene optionally (the run's scene by default, "E1S2" or an id), because the translator does not know
  scene ids. Version 2. The wording of a refused scene changed to "'x' is not a scene".
- `hiru-ai eval`: cases may say `variant: tools|base`, and `example: <tool>` borrows that tool's example world instead of a
  fixture dozens of lines long. `hiru-ai eval` runs both forms of an agent that has one; `--tools` only the form;
  `--ab base,tools [--live]` compares the single call with the form.
- `hiru-ai run`, `eval` and the others print UTF-8 on Windows consoles (they raised on a Sinhala line or an arrow).

### Prompt size (offline, `core/tokens.tokens_of`, a 4-shot fixture scene)

| `chat_answerer` | Tokens |
|---|---|
| single call: system + one turn (the shot list is 130 of them) | about 930 |
| tools form, fixed prefix: system 1,050 + 7 tool definitions 2,460 (cacheable) | about 3,510 |
| tools form, per turn (no shot list) | about 93, plus every extra model round resends the thread |
| `options_writer` tools form: tool definitions | about 1,480 |

The shot list is a small part of this prompt on a scene this size, so removing it saves little; the tool definitions are the
cost. The form is cheaper only if the 3,500-token prefix is served from OpenAI's cache (the single call's roughly 800-token
system prompt is below the 1,024 minimum and is not cached) and a turn needs one round or none. **I do not expect the 30 % cut
in input tokens to hold for `chat_answerer` as written**; the gains to look for are in capability (questions about a shot, a
name, a decision the single call could not answer) and in the options writer's refused-after-offer rate. If the A/B agrees, the
fix is shorter tool guides and fewer tools on this agent, not a different design.

## Phase 3: everything else

Done:

- **MCP server** (`cli/mcp.py`, `hiru-ai mcp`): stdio, newline-delimited JSON-RPC, protocol 2025-06-18, no SDK dependency
  (the `mcp` package is not installed here and adding a dependency is the owner's call). It lists every active `read` and
  `stage` tool with `inputSchema` from `Args`, `outputSchema` from `Result`, `readOnlyHint` from `effect`; a `write` tool is never
  listed and a call to it is an unknown tool. A refused call or bad arguments is a tool error (`isError`) carrying
  `how_to_fix`. The scope is the launcher's command line (`--production`, `--scene`, `--corpora`, or `--fixtures` for an offline
  run), not the caller's. This is local stdio with the process owner's database access: the "scope from the caller's token" of
  the plan needs an HTTP transport and authentication, which is a decision for the owner.
- **Tracing**: every tool call is an OpenTelemetry span (`core/telemetry.tool_span`: id, version, effect, ms, result tokens, error,
  truncated; never the arguments). Only the OpenTelemetry API is used, so nothing is exported until a person installs an
  exporter, which ADR 0008 reserves for them. Without the package the span is a no-op.
- **Review loop** (`cli/review.py`, `hiru-ai review <log>`): per tool, calls, refused, failed, cut answers, mean result tokens, p95
  ms, and what to look at (over 5 % errors: the guide or arguments; over 20 % cut: page it or narrow the default; never called:
  take it off the list). It reads the `hiru_ai.tool` log lines; it cannot see repeated narrow calls in one run because the
  log has no run id.

Not done, with the reason:

- **`job_start`, `frame_inspect`, `tool_search`**: §9.1 builds each "with an agent that needs it", and none does. `job_start` also
  needs an API route that dispatches a job from an accepted card; `frame_inspect` needs a way to read a frame's image from a
  tool (the `FrameStore` port deliberately returns no storage path); `tool_search` is only for an agent that would need more
  than 8 tools, and none does. Build them when the first agent asks.
- **`/ask` on the read tools** (§9.5): waits on the API carrying LangChain, the owner's decision.
- **Retire the hand-written definitions** (§9.6): `steps/scene_kernel/tools.py` still serves the single call and
  `director_chat/engine/tools.py` the legacy engine; both go with the removal of the legacy engines (plan 2026-11-03 Phase 8).
- **Docs-site pages** (`caps.ts`, the tools foundation page): another repository, not touched.

## Deviations and things to know

- **`search_production` is still the director's one combined search** for the single call. The tools form replaces it with
  `memory_search` + `search_kb`, which is the split of Phase 2; the single call keeps the old path so the parity fixtures stay
  as they were.
- **Argument renames.** `scene_read` / `timing_check` take `scene` ("E1S2" or an id a system passes), not `scene_id`;
  `technique_lookup` takes `intent`, not `query`. `dialogue_read` still takes `scene_id`, now optional.
- **Out of date means pins.** `shot_read` and `frame_read` say a design, prompt or frame is out of date by its pins (shot version,
  script, canon card versions). They do not repeat the API's other reasons; the API stays the authority.
- **`glossary_read`** builds from canon names and aliases plus the accepted translations of the scene in scope (D6).
- **`plan_try` and `change_propose` try operations as the conductor's**, so an operation only a person may make (the script, the
  cast, checks) is refused, and `change_propose` stages nothing unless every operation lands.
- **`hiru-ai eval` used the real model for `model: unavailable` cases** when a developer's `.env` held a key: those cases are now
  answered by a model that cannot be reached, as in the tests. (Before the fix, a few runs of `hiru-ai eval` on the dev machine made
  a handful of real calls.)
- **The six `tests/api` failures** seen on the dev machine were its `.env` setting `API__PUBLIC_URL` and `API__INTERNAL_URL` to port
  8001 while the tests expect 8000. With both set to 8000 the suite is green; no code changed for it.

## Open items

- **The live A/B, per agent** (a person runs it; it costs model calls). For each of `chat_answerer`, `options_writer`,
  `translator`, `shot_critic`: `OPENAI__API_KEY=<key> hiru-ai eval <agent> --ab base,tools --live`, read the score, tokens, model
  calls, tool calls and tool errors, and record the result here. Put the agent in `AGENT_TOOLS` only if the form is at least as
  good on its cases. Then compare the real traffic with `token_usage` once `USAGE_DETAIL=true` (group by `component`).
- Set `USAGE_DETAIL=true` where the API and the functions run (the SQL is applied). Not verified: the migration file, `schema_v10.sql`
  and the pgTAP test against a local `supabase start`, and the dump comparison in `Database/README.md`.
- `hiru-ai run tool <id> --live` on the dev database for each read tool, and a first `hiru-ai mcp --production <uuid>` against
  it (both read-only, both on the hosted dev database: ask first).
- Install an OpenTelemetry exporter once ADR 0008 is decided.

## Verified

`ruff check src tests scripts`, `mypy` (558 files), `python scripts/lint_imports.py` (19 contracts kept), `hiru-ai validate` (103 parts,
0 errors), `hiru-ai catalog --check`, `hiru-ai eval` (80 of 80, scripted, both forms), and the whole `pytest` run (2,760 passed;
the dev machine's `.env` must have `API__PUBLIC_URL` and `API__INTERNAL_URL` on port 8000 for `tests/api`).
