# Sable: what is built (plan/2026-11-08)

Built 2026-11-08, offline. **No model was called** (every test uses fake models) and **nothing was applied to the hosted
database**. Uncommitted in both repos. Zora is untouched: no file under any `zora/` folder, `api/routers/zora.py`,
`api/services/zora.py`, `src/services/zora_chat/` or the interface's `src/features/zora/` was edited
(`tests/sable/test_zora_untouched.py` holds Sable's code to reading `zora.routes_here` and nothing else).

| Phase | State |
|---|---|
| 0 evidence | Done except the question set (step 3 needs your yes to read the dev DB). Findings in PLAN.md "Phase 0 findings" |
| 1 the agent | Done: `agents/sable/sable_agent`, 12 scripted evals pass (`hiru-ai eval sable_agent`) |
| 2 tiers + `tiering` | Done: `core/middleware/tiering.py`, `steps/sable/sable_route`, tiers `sable`/`sable_deep`; 17 two-model tests |
| 3 new read tools | Done: `sable_overview`, `sable_scene_find`, `sable_think_harder` with contract tests |
| 4 lab | **Not run (yours: $3, one yes per paid run).** `lab/sable/` is not written yet: it waits for the question set |
| 5 system + function | Done: `systems/sable/sable_chat`, `src/services/sable_chat` (`hiru-sable-chat`, port 8214) |
| 6 API + schema v18 | Built; **v18 not applied and not yet verified on a local stack** (Docker was not running) |
| 7 interface | Built on D1's suggestion (no Figma frame yet); **not seen in a browser** |
| 8 live check | Yours |

## What exists

**Backend** (`hiru-ai-studio`)

- `agents/sable/sable_agent`: the react agent, 24 tools (19 shared read, 2 shared stage, Sable's 3), knowledge
  `production_docs, cinematography, craft, techniques`, `memory: ["*"]`, tier `sable`, `deep_model: sable_deep`.
  Prompt `prompts/system.md` (static). Output `{text, handoff_scene, handoff_request}`.
- `agents/sable/sable_summary`: folds a long thread's older messages into `chat_threads.summary` (tier `low`,
  absent-safe: no model keeps the old summary).
- `core/middleware/tiering.py` (generic): once per turn, only upward. Signals `route` (the caller started deep), `model`
  (`sable_think_harder` called), `refusals` (two refused lookups in a row), `cap` (`max_tool_calls` used: the answer is
  written deep), `stage` (a card asked for: that round is drafted again deep). Record in `RunContext.tiering`; deep calls
  carry phase `sable.deep` in `token_usage` and the trace tag `sable:deep`. Manifest fields `deep_model`,
  `escalate_tool`, `escalate_on`; `validate` checks them.
- `steps/sable/sable_route`: the closed rule list (`attachment`, `long_message`, `asked_for_depth`, `whole_episode`,
  `many_scenes`), table-driven tests.
- Tools: `sable_overview` (episodes, scene status, planner, shots, open questions; paged), `sable_scene_find`
  (character / place / time of day / episode / text; a person found where they speak or are named), `sable_think_harder`.
- `systems/sable/sable_chat`: read → loop → guard → save. Guard: `guard.py` takes out any line-like quote (Sinhala, or
  4+ words) no tool returned, noted in the record. Cards: a staged change is stored with its ops pinned to shot ids
  (as the classic chat stores an option's); a person without DIRECT gets no card. A handoff card names the scene and its
  episode.
- `contracts/sable/events.py`: events, payloads, card shapes, `TurnMeta`, the status words per tool.
- `core/ports.py` `ChatStore` + `FakeChat` + `adapters/supabase_rest.SupabaseChat`.
- API: `routers/sable.py`, `services/sable.py`, `SableRepo` (+ `SupabaseSable`, `FakeSable`), `Permission.USE_SABLE`
  (every role), `SABLE__ENABLED` (API and function), `task_manager.SABLE_CHAT`, deploy list, `start-functions.ps1`,
  `langgraph.json`, import-linter contracts (incl. "sable never imports zora").
- Schema v18: `Database/schema_v18.sql`, `upgrade_v17_to_v18.sql`, `supabase/migrations/20261108041413_sable.sql`,
  `supabase/tests/database/018_sable.test.sql`.
- Tests: `tests/sable/` (46), the tools' and agents' own tests, `hiru-ai eval sable_agent` 12/12, `sable_summary` 2/2.

**Interface** (`hiru-ai-studio-interface`)

- `src/features/sable/` (`client.ts`, `types.ts`, `lib/thread.ts`, `lib/events.ts` + tests, `components/`).
- `components/ui/sheet.tsx`: shadcn's Sheet API on the Radix Dialog, written by hand (the shadcn registry could not be
  reached from this machine; re-add with `npx shadcn@latest add sheet` and re-theme if you prefer the stock file).
- `components/layout/app-header.tsx` mounts `SableLauncher`: an "Ask Sable" button on every production page, only
  when `GET …/sable` says enabled; it opens a side sheet that knows the scene in view from the URL.
- Cards: change ("Apply it" / "Not now"), memory ("Remember it" / "Not now"), handoff ("Open E1S2 in Zora" or "in the
  director chat"): writes the request with `writeDraft("scene.<id>")`, the key Zora's and the classic chat's composers
  already restore, then opens the scene's Director page. Quoted lines are drawn with `spoken()`. Status words while it
  works; Stop. No tier, model or cost anywhere.

## Deviations from the plan (each is a decision you may reverse)

1. **Agent id `sable_agent`**, not `sable`: a grouped part's id must start `sable_` (`hiru-ai new … --group sable`).
2. **`tool_cap: 24`** (new manifest field, max 24): `validate` capped every agent at 8 tools (`MAX_TOOLS`), which the
   plan did not mention. The global cap is unchanged; only a manifest that says so may see more.
3. **`group.yaml` `shared:`** (new): a grouped part could only name its own group's parts. Sable's agents group lists the
   21 shared tools and 4 knowledge bases it uses as they are, instead of copying them. Planner groups are unchanged.
4. **`max_model_calls: 10`**, not 6: with 6, a turn that asks one tool per round ends before the 8-lookup cap, so the
   `cap` signal could never fire and the turn would end with no answer; 10 = 8 lookups + a card re-drafted + the answer.
5. **The turn's record is in its own table `chat_turn_meta`** (admin-read only), not `chat_messages.meta`: members can
   read `chat_messages` through RLS and realtime, which would have shown tiers and tool names (rule 1).
6. **`chat_threads.summarised`** (new column): how many of the oldest messages the summary covers, so it is not redone.
7. **Older messages are summarised by a small agent (`sable_summary`)**, not `SummarizationMiddleware`: the thread goes in
   the user message as text, not as LangChain messages, so the middleware has nothing to work on.
8. **Event `delta`**, not `token` (Phase 0: Zora and the classic chat use `delta`). The reply is sent in word chunks after
   the guard has read it whole, not token by token while the model writes (the structured answer arrives whole).
9. **Per-person privacy**: the classic chat's `GET|DELETE …/threads/{id}/messages` now 404 a Sable thread
   (`routers/director.py: _scene_chat`); without it, anyone in the production could read a Sable thread by its id.
   v18's read policies make Sable threads and their messages the creator's only.
10. **Takes are not counted** by `sable_overview` (no port carries them); it says shots.
11. **Handoff target** is resolved by the API when a thread is read (`zora.routes_here`); a card that arrives on the
    stream has `target: ""` and is labelled "the director chat" until the thread is read again. Both open the same
    Director page, which already picks Zora or the classic chat.

## Measured (Phase 0)

- Cached prefix: **about 9.8k tokens** (24 tool definitions 8.6k, system prompt 1.2k) against the plan's ~6k target. The
  biggest are Sable's own `sable_scene_find` (570) and `sable_overview` (465), then the shared `scene_read`, `plan_try`,
  `timing_check`. Trimming the shared guides would change other agents' prompts, so it is left to you.

## Open for you

- **Phase 0 step 3**: your yes to read (read-only) the dev DB's director/Zora `chat_messages` for 30–50 real questions,
  or write them yourself. The lab (`lab/sable/run.py`) is written once the set exists.
- **Phase 4 lab** ($3 proposed, one yes per paid run): arms A/B/C, your blind grades, the gate (C within 1 point of B,
  at most half B's cost, p90 under 25 s). It also decides D2 and which escalation signals stay (`escalate_on`).
- **Schema v18**: verify the three ways (migration-built, v18 on empty, v17 + upgrade) with Docker running, run
  `npx supabase test db` (`018_sable.test.sql`), then apply `upgrade_v17_to_v18.sql` to the hosted project when you choose.
- **D1** (a Figma frame for the panel), **D3–D8** are taken as the plan suggests; change any.
- **Phase 8**: `SABLE__ENABLED=true`, start `hiru-sable-chat` (`scripts/start-functions.ps1`), ask the lab set, read the
  Langfuse traces (`sable:deep` tag, `sable.deep` phase).
- Not built: `hiru-ai review` does not read `chat_turn_meta` yet; `jonathan_plan_read` (D6) is not built.

## Checks at the end

- Backend: `ruff check src tests scripts` clean; `mypy` clean (971 files); `hiru-ai validate` 0 errors; `hiru-ai catalog`
  regenerated; `scripts/lint_imports.py`: Sable's contracts kept; one contract broken that was broken before this work
  (`david agents never import each other`: `david_author` → `wire_schema`). Full `pytest -q`: 4921 passed, 34 failed;
  after the fixes that followed (roles table, removal lists), the Sable-caused failures are gone except **one waiting for
  you**: `tests/zora/test_removal.py` needs `Database/schema_v18.sql` in its `MAY_NAME_IT` (a whole schema repeats Zora's
  tables; v15 to v17 were added the same way), which is a Zora-folder edit (rule 10). The rest come from the local `.env`
  (`READER__ENABLED=true`: reader + parity; `ADAM_MODE=take`: Adam's system tests; the API's port 8001: handoff, looks,
  production frame links) or were failing before (`tests/adam/test_score_mutations.py`; 3 parity cases fail with Sable
  set aside too).
- Interface: `npm run check` passes (355 tests; one lint warning in `script-edit-form.tsx`, not Sable's).
  `format:check` fails on 21 files unchanged in git (line endings); every Sable file passes Prettier.
