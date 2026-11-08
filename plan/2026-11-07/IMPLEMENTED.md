# Chats on assistant-ui: what is built (plan/2026-11-07)

Status 2026-11-08: **phases 1 to 5 built offline, in both repos (backend `hiru-ai-studio`, interface
`hiru-ai-studio-interface`); phase 6 deliberately not built.** No model was called, nothing was deployed, nothing is
committed, and no chat has been seen in a browser yet. Phase 0's browser look, the live checks of Stop, Edit and Ask
again, and the decisions D1–D5 are the person's. Plain words: [human-read.md](human-read.md).

## Read this first

1. **Restart the API and every function before trying it.** Phase 4 changed `contracts.director` (`TurnRequest`,
   `TurnPayload`, a new block kind), which both the API and the chat functions import. An old function refuses the new
   payload (`extra="forbid"`) with "bad payload".
2. **Stop on Cloud Run.** Phase 2 makes a function finish a turn after its client has gone. With request-only CPU, Cloud
   Run may throttle it once the response closes. If a stopped turn's reply never lands there, set "CPU always
   allocated" on the two chat functions; it is a deploy setting, not code.
3. **Ask again and Edit are model calls.** Each press runs a whole turn. The interface offers Ask again only where the
   turn changed nothing, so it can never change the plan twice.
4. **No schema change.** Phase 3's `used` block and Phase 4's `replaces` block live in `chat_messages.blocks` (JSON).

## Decisions taken (defaults unless the person said otherwise)

| | Decision | Built as |
|---|---|---|
| D1 | Stop: stream only, or also cancel server work | Stream only. The server finishes the turn, so a turn is saved whole or not at all |
| D2 | Ask again: append, or branches with a picker | Append. The earlier answer stays as it was; no branch picker |
| D3 | Build questions as tool calls: later or now | Now, on the person's "complete the plan" (2026-11-08) |
| D4 | Starter prompts and slash command names | As listed in PLAN §1.7–1.8, waiting for the person's confirmation |
| D5 | Which Phase 6 item next | Open. Nothing from Phase 6 is built |

## Phase 1: free wins (interface, 2026-11-07)

All in `src/components/chat/`: `chat-thread.tsx` (built from assistant-ui 0.15.32 primitives, no registry add) and
`chat-tools.ts` (pure helpers).

- Copy under a reply (text parts only; a card is skipped, or the chat names the stored words in `meta.copyText`).
- Quote a selection into the composer as `> …` lines, each line keeping its language (`spoken()`).
- The working line with its seconds; message times on hover and a day separator (the browser's time zone, never
  invented when the API gave none).
- Draft kept per scene in `localStorage` (try/catch), Up arrow recalls the last message sent.
- `/` commands beside `@` (Zora: `/undo`, `/redo`, `/plan-shots`, `/replan`, `/clear`; Director: `/clear`). A typed
  command runs and sends nothing. The old `PLAN_SHOTS` string still works.
- Fixed starter prompts in the empty thread.

## Phase 2: Stop (both repos, 2026-11-07)

- Spike: stopping just after "Saving", before the reply, left the plan saved with no reply message, in both Zora and
  the classic chat. Fixed in both function handlers: `stream()` catches `GeneratorExit`, runs the rest of the turn
  without writing (`finish`), then re-raises. Pinned by `tests/zora/test_stop.py` and
  `tests/services/director_chat/test_turn.py::test_stopping_at_any_frame_still_saves_the_edit_and_its_message`.
- Interface: `browserStream` lets an abort through as itself. `sendZoraTurn` / `sendTurn` take a `signal`, and
  `useChatRuntime({ onCancel })` turns Send into Stop. A stopped reply keeps what streamed, says "You stopped waiting…"
  (never "cancelled"), refreshes the page, and re-reads the thread (`waitForReply`: 2, 4, 8, 15, 30 s) until the stored
  reply takes its place.

## Phase 3: what a reply relied on (both repos, 2026-11-07)

- Spike: Zora's author does read production memory, so the chips cover Zora and the classic graph engine. The classic
  legacy engine reads only its own `memory_items`, so its replies have no chips; that is correct.
- Backend: the `production_memory` middleware records the entries it gave a call (`memory.note_used`), and
  `memory.used_block(ctx)` builds `{kind: "used", memory: [{id, text, document_id, document_title}]}` on the reply.
  `contracts.director.UsedBlock` joins `DirectorBlock`. New route
  `POST /v1/productions/{pid}/production-memory/{entry_id}/reject` (direct only, audited, safe to repeat). It rejects
  and never deletes, because a deleted reader draft would come back on the next reading. `DELETE /memory/{id}` is the
  wrong table (`memory_items`).
- Interface: `features/director/components/used-block.tsx` under a reply in both chats. People with `direct` get a ×
  that asks first and marks the chip "Removed".
- Tests: `tests/zora/test_used_memory.py`, two in `tests/api/test_director.py`.

## Phase 4: Edit and Ask again (both repos, 2026-11-08)

Backend:

| File | |
|---|---|
| `libs/contracts/director.py` | `ReplacesBlock {kind: "replaces", message_id, how: "edit" \| "again"}` in `DirectorBlock`; `TurnRequest.replaces`, `TurnPayload.replaces` (optional); `without_replaced(history, replaces)` drops a replaced person's message and the replies that answered it; `ChangesBlock.lane` |
| `api/services/director.py` | `replaces_blocks`: `replaces` must be the thread's last message from a person, else `NotReplaceable` → 409 "Only your last message can be edited or asked again."; "again" when the words are the same |
| `api/routers/director.py`, `api/routers/zora.py` | Both turn routes check `replaces`, store the block on the new message and pass `replaces` to the function. A refused replace never reaches the function |
| `services/director_chat/.../engine/turn.py`, `libs/hiru_ai/systems/director_chat/turn.py`, `libs/hiru_ai/systems/zora/zora_chat/turn.py` | All three engines read the thread through `without_replaced`, so the models never see the old words and the repeat guards don't answer "you asked that already" |
| `libs/hiru_ai/systems/zora/zora_chat/turn.py` | The `changes` block stores the turn's `lane` |

Interface:

| File | |
|---|---|
| `features/scenes/types.ts`, `lib/map-scene.ts` | `Replaces` on a person's message; `applied` on a reply (classic: `ops` not empty; Zora: `changes.revision > 0`) |
| `features/director/lib/thread-messages.ts` | `toThread`: Edit only on the person's last stored message; Ask again only on the thread's last reply when it applied nothing, wasn't stopped and left no script edit waiting; nothing offered while a turn runs; an edited pair stays greyed ("Edited below", "Replaced by your edit", "… The change it made stays."); the new message is labelled "Edited" or "Asked again" |
| `components/chat/chat-thread.tsx` | `ActionBarPrimitive.Edit` opens assistant-ui's edit composer in place (Cancel / Send); `ActionBarPrimitive.Reload` labelled "Ask again"; faded lines |
| `components/chat/use-chat-runtime.ts` | `onEdit(sourceId, text)`, `onAskAgain(parentId)` |
| `features/zora/components/zora-chat.tsx` | An edit of a message whose turn changed the plan asks first: "Undo it, then send" (nothing is sent if Undo fails), "Keep it and send", "Cancel" |
| `features/director/components/director-chat.tsx` | Edit and Ask again. The classic chat has no Undo, so it sends, and the greyed reply says the change stays |
| `features/director/client.ts`, `features/zora/client.ts` | `sendTurn` / `sendZoraTurn` take `replaces` |

Tests: `tests/contracts/test_replaces.py` (4), `tests/zora/test_replaces.py` (2: the replaced pair never reaches a
prompt; the lane is stored), `tests/api/test_director.py` (2: stored, labelled, nothing deleted; only the last message;
a refused replace never reaches the function); interface `chat-thread.test.tsx` (5), `thread-messages.test.ts` (5).

Gotcha: the edit composer's Send is `type="button"`. As a submit button it sends twice, and the second send throws
"Composer is not available" because the edit has already closed.

## Phase 5: Build questions as tool calls (interface, 2026-11-08)

| File | |
|---|---|
| `components/chat/thread-parts.ts` | `toolCallMessage`: a question is one `tool-call` part; with no `result` the message is `requires-action` |
| `components/chat/use-chat-runtime.ts` | `onToolResult` → the external store's `onAddToolResult` |
| `components/chat/chat-thread.tsx` | `renderTool` (drawn through `tools.Override`); a waiting message is marked `data-requires-action`; "Go to the open question" above the composer while any is open |
| `features/build/components/build-chat.tsx` | `ask_person` calls; `QuestionCard` answers with `call.addResult({value})` → `answerQuestion` (unchanged endpoint); "You chose …" comes from the call's `result`; a failed save opens the question again with the reason; the header counts the runtime's open calls (the build's own count when the questions could not be read) |

Tests: `features/build/components/build-chat.test.tsx` (4).

## Phase 6: not built

Each item needs its own plan, and D5 is the person's:

- Feedback needs each reply linked to its Langfuse trace (not done today) and a write to Langfuse.
- Attachments need a new backend surface.
- Dictation needs a spike on the person's own voice.
- Generated follow-ups need model calls.
- Search in the conversation and resumable streams wait for threads long enough to need them.

## Checks (2026-11-08)

- **Interface:** `npx next typegen`, lint and typecheck pass; 349 tests pass.
  - One lint warning (unused `cn` in `script-edit-form.tsx`) was already there before this work.
  - `format:check` flags 21 untouched files: they were checked out with CRLF line endings by autocrlf, and they pass
    with `--end-of-line auto`. Every file this work touched passes.
- **Backend:** `ruff` and `mypy` pass. 434 tests across contracts, the API director routes, Zora and director_chat pass.
  - The full `pytest -q` run: 4,775 passed, 25 failed. None of the failures are in this plan's code: Adam (13),
    handoff/frames/looks (6: they expect file links on `:8000` and get `:8001`), the document reader and parity (6:
    "no scripted reply left").
  - These look local (`.env`, other uncommitted work) but were not proven against a clean checkout.
- **`lint_imports`:** one broken contract, unrelated to this work. In committed code, two of David's agents import
  `hiru_ai.agents.david.wire_schema`.

## The person's

- Phase 0: open all three chats in a browser and list what looks wrong.
- Live checks, each a model call, after a yes: Stop a real turn and see the reply land (locally and on Cloud Run),
  Edit and Ask again on a real scene. The step-by-step manual guide is in the session notes of 2026-11-08.
- D1–D5.
