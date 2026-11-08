# Chats: what assistant-ui already gives us (plan/2026-11-07)

Status: written 2026-11-07. Phase 1 built in the interface 2026-11-07. Phases 2 and 3 built 2026-11-07 in both repos
(spike, fix, wire, chips). Phase 4 built 2026-11-08 in both repos, Phase 5 built 2026-11-08 in the interface (see
"Built" under each). All uncommitted, offline only, not yet seen in a browser; no model was called. Phase 0's browser
look and Phase 4's live check are the person's. Phase 6 is not built: each item waits for its own plan (D5).
Plain words: [human-read.md](human-read.md). What is built, file by file: [IMPLEMENTED.md](IMPLEMENTED.md).
Follows: the move of the Zora, Director and Build chats to assistant-ui (interface, uncommitted, 2026-11-07),
plan/2026-11-06e (Zora), plan/2026-11-05d (production memory).
Mostly interface work (`hiru-ai-studio-interface`). Backend changes are small and named per phase.

## 1. Where we are

All three chat columns render one thread, `src/components/chat/chat-thread.tsx`, on `@assistant-ui/react` 0.15.32 with
`useExternalStoreRuntime` (`src/components/chat/use-chat-runtime.ts`). Each chat keeps its own state and API calls.
The runtime only reads `messages` / `running` and hands typed text to `onSend`. The thread uses the stock shadcn
design with colour-only theming from `globals.css`. Markdown is off on purpose. Mentions (`@S03`, sequences) go through
`ComposerPrimitive.TriggerPopover`.

| Chat | File | What a person does | Already has |
|---|---|---|---|
| Zora | `features/zora/components/zora-chat.tsx` | edits Jonathan's plan | Undo / Redo, proposals ("Use this"), re-plan offer, suggestions from `done`, locks, What changed |
| Director (classic) | `features/director/components/director-chat.tsx` | edits shot rows | options, disagreement sides, Delete chat |
| Build | `features/build/components/build-chat.tsx` | answers agents' questions on cards | composer disabled; activity line |

The installed package already exports what Phases 1–5 need. I checked `node_modules/@assistant-ui/*/dist` for
`ActionBarPrimitive.Copy / Edit / Reload`, `SelectionToolbarPrimitive.Quote`, `BranchPickerPrimitive`,
`ThreadPrimitive.Suggestion`, and the external-store `onCancel`, `onEdit`, `onReload`, `onAddToolResult`. **No package
upgrade.**

Facts this plan rests on:

- `browserStream` (`src/lib/api/browser.ts`) already accepts an `AbortSignal`, but no chat passes one.
- The API proxies a Zora turn to the `zora_chat` function (`src/api/services/zora.py: stream_turn`, httpx stream). When the browser
  aborts, Starlette stops `frames()` and the httpx stream closes. **What the function does next is not yet known**
  (Phase 2 spike).
- `DirectorMessage` has no time. The API row has `created_at`, but `toMessage` drops it.
- `MemoryEntry` (`contracts/memory.py`) has a `document_id` but no page number. ~~No Zora step reads production memory
  today.~~ Wrong (Phase 3 spike): `zora_author` is given every topic through the middleware.
  The conductor's answer has a `memory: str` note (`contracts/zora/wire.py`).

## 2. Rules this plan follows

1. **No credits or costs** (interface `CLAUDE.md`). Leave out Cost meter, Quota banner and the token/context rings.
2. **Dialogue is verbatim.** Copy and Quote take the text exactly as stored. A quoted Sinhala line stays Sinhala and is
   rendered with `spoken()`. Nothing re-types or "cleans" a line.
3. **Markdown stays off.** None of these phases needs it.
4. **Never `npx shadcn add` the assistant-ui registry.** It overwrites our themed `ui/button`, `avatar`, `dialog`,
   `textarea` and `skeleton`. Build every element from the **primitives** in our own `chat-thread.tsx`, and copy an element's markup by
   hand when one is useful.
5. **No model call without the person's yes, each time.** Phases 1–3 add **none**. Phases 4 and 6 add calls only
   when a person presses a button, and their live checks are the person's.
6. **Read data only through `features/*/api.ts` / `client.ts`.** React Compiler is on, so no manual `useMemo`. Browser storage
   is wrapped in try/catch and is a convenience only.
7. Before finishing each phase: `npx next typegen && npm run check && npm run format:check`, plus the backend checks
   (`ruff`, `mypy`, `lint_imports`, `pytest -q`) when the backend changed.

## 3. Phases

### Phase 0: See what we have (free, prerequisite)

The thread has only been checked through server-rendered HTML. Before adding anything to it:

- Run the interface against the local API (`:8000`) and open all three chats in a browser: empty state, a long
  thread, streaming, the mention popover, scroll-to-bottom, a narrow column.
- Fix layout bugs found here first, so later phases don't build on top of them.

Done when: the person has looked at each chat and the list of fixes is empty or done.

### Phase 1: Free wins (interface only, no backend, no model)

All in `src/components/chat/` unless named. Each item is on for every chat that can type (Zora and Director). Build gets
only Copy and timestamps.

| # | Item | How | Notes |
|---|---|---|---|
| 1.1 | **Copy** a reply | `ActionBarPrimitive.Root` + `.Copy` under assistant messages, shown on hover/focus, with a copied tick | Copies text parts only. Rich blocks are skipped, so a copy never invents text for a card. |
| 1.2 | **Quote** a selection | `SelectionToolbarPrimitive.Root` + `.Quote` on the viewport | Inserts `> …` plus a blank line into the composer. Test with a Sinhala line. |
| 1.3 | **Working line with elapsed time** | Turn the pending reply's `status` into a small pill: spinner, text, `12s` counter (client clock from turn start) | Replaces the plain status line. |
| 1.4 | **Timestamps** | Map `created_at` in `toMessage` (`features/scenes/lib/map-scene.ts`) and in Build's messages to `createdAt` on `ThreadMessageLike`. Show a hover time and a day separator when the day changes | Uses the browser's time zone. |
| 1.5 | **Draft restore** | Save composer text per thread id (`localStorage`, key `hiru.chat.draft.<threadId|sceneId>`), restore on mount, clear on send | try/catch. Works with storage blocked. |
| 1.6 | **Up arrow recalls the last sent message** | When the composer is empty, ArrowUp puts the last user text in it | Local state only. |
| 1.7 | **Slash commands** | A second trigger (`/`) beside `@`, same `TriggerPopover`, running **existing** actions with no model | Zora: `/undo`, `/redo`, `/plan-shots` (today's magic string `PLAN_SHOTS` moves here), `/replan`, `/clear`. Director: `/clear`. Commands are passed in per chat. |
| 1.8 | **Starter prompts** in the empty thread | `ThreadPrimitive.Suggestion`-style pills in `Welcome`, fixed per chat | Zora: “Explain the approach”, “Two ways to open the scene”, “@S01 on an 85”. These are fixed text, not generated. |

Tests (jsdom, with the ResizeObserver stub): copy skips blocks, quote keeps `lang`, draft survives a remount and is
cleared on send, slash command runs its callback and sends nothing, `/plan-shots` behaves as the old string did.

Done when: every item works in the browser in Zora and Director, and Copy and timestamps work in Build.

### Phase 2: Stop button (interface; backend spike, maybe a small fix)

Interface:

- Each chat creates an `AbortController` per turn and passes `signal` to `browserStream`. `useChatRuntime` gains
  `onCancel` and wires it to `controller.abort()`. The composer's send button turns into Stop while `running`.
- After a stop: keep the partial streamed text as a reply marked **“Stopped”** (the Stopped-run element idea, built
  from our own markup), then re-read the thread and plan (`router.refresh()`), because the server may have saved.

Backend spike (free, local, no model: stub the author with the test fakes):

- Abort a Zora turn and a classic Director turn at three points: before the author, during the author, during the reply.
  Record what the function does in each case: keeps running, or is cancelled. Also record whether the plan, revision and
  message rows end up **all saved or none saved** (never half).
- If any point leaves half a save, make SAVE one transaction, or make the function finish the turn even when the
  client has gone. Whichever is smaller wins. Add a pinned test.

Rule shown to the person: **Stop means “stop waiting”.** An edit that already landed stays and is undoable with Undo. The
UI never says “cancelled” when the plan changed.

Decision **D1**: should Stop also cancel the server's work (saves model spend), or only stop the stream? The default here
is “stop the stream, the turn finishes or rolls back cleanly”.

**Built (2026-11-07).** Spike, on the Zora test world and the classic turn's fake store (no model), stopping a turn after
each frame in turn. How a stop reaches the function: the API's stream closes, the function's next write fails, the
WSGI server closes the response, and `GeneratorExit` is raised at the frame being written. What each point left:

| Stopped | Zora (edit and craft turns) | Classic (legacy engine) |
|---|---|---|
| before the author (first status frames) | nothing saved: clean | — |
| after "Saving", before the reply (`status`, `plan`) | **plan + 2 revisions, no reply message: half** | **shot list saved, no message: half** |
| during the reply | all saved (LangGraph hands over a node's frames when the node ends) | — |

Fix (the smaller of the two): the function finishes the turn when the client has gone. Both handlers'
`stream()` catch `GeneratorExit`, run the rest of the turn without writing (`finish`, never raises), and re-raise. So
D1's default holds: Stop stops the stream, the turn finishes and saves whole. Pinned by `tests/zora/test_stop.py` (every
frame, edit and craft) and `test_stopping_at_any_frame_still_saves_the_edit_and_its_message`
(`tests/services/director_chat/test_turn.py`); both fail without the fix.

Interface: `browserStream` lets an abort through as itself (not "Can't reach the API"); `sendZoraTurn` / `sendTurn` take
a `signal`; `useChatRuntime({ onCancel })`; the round Send button turns into Stop while a reply is on its way. After a stop
the chat keeps what streamed as a reply with a line under it ("You stopped waiting. … its reply then takes this one's
place, and an edit it made can be undone"; never "cancelled"), refreshes the page, then re-reads the thread
(`waitForReply`, plain GETs at 2, 4, 8, 15, 30 s) and swaps in the stored reply when it lands (Zora: Undo and the
suggestions follow its `changes` block). A new turn or closing the chat ends the re-read.

Open: on Cloud Run with request-only CPU, a function may be throttled once its client has gone. The local check is the
person's: stop a real turn and see the reply land. If it does not on Cloud Run, the fix is "CPU always allocated" for the
two chat functions, not code.

### Phase 3: Show what a reply relied on (backend wire + interface, no model)

Goal: under a reply, small chips for **the production-memory entries and documents the turn used**. A person with
`direct` can remove an entry from a chip (`DELETE /memory/{id}` already exists).

- Spike first (free): find where plan/2026-11-05d's middleware injects memory entries into agents, and whether the Zora
  and classic Director turns pass through it. **If Zora does not read memory, this phase covers the classic chat only**
  and records "Zora + memory" as its own follow-up. It does not wire memory into Zora quietly.
- Backend: code (not a model) records the entry ids it injected. They are stored on the reply message as one extra block
  `{kind: "used", memory: [{id, text, document_id, document_title}]}`. The blocks are JSON, so no schema change. Sent
  as-is on `message`. No page numbers, because `MemoryEntry` has none. Page-level citations wait for the document reader
  (plan/2026-11-06f) to store pages.
- Interface: a `UsedBlock` renderer in each chat. The chips show the entry text truncated, and the document title links to the
  Documents page (`routes.ts`). Remove asks for confirmation, then refreshes.

Done when: a turn that used memory shows its chips after a reload, a turn that used none shows nothing, and removing works.

**Built (2026-11-07).** Spike findings that changed the plan:

- **Zora does read memory.** `zora_author` subscribes `memory: ["*"]` (and `chat_answerer` too), so the chips cover
  Zora and the classic chat's graph engine (`AI_ENGINE=graph`). The classic **legacy** engine (today's default) reads
  only its own `memory_items`, never `production_memory`, so its replies show no chips. That is correct, not a gap.
- **`DELETE /memory/{id}` is the wrong table**: it deletes the director's `memory_items`. No API route touched
  `production_memory`. Added `POST /v1/productions/{pid}/production-memory/{entry_id}/reject` (direct only, audited,
  safe to repeat, 404 when the table is missing). It **rejects** instead of deleting: a deleted reader draft would come
  back on the document's next reading, and a rejected one never does (`memory.fresh`) and is never given to an agent.

Backend: the `production_memory` middleware records the entries it gave a call once the call returns
(`memory.note_used`; a failed call records nothing). `memory.used_block(ctx)` builds
`{kind: "used", memory: [{id, text, document_id, document_title}]}` (`text` = `says` as stored, title = the file name).
Zora's and the graph classic turn's reply message append it when there is any. `contracts.director.UsedBlock` joins
the `DirectorBlock` union, so stored messages validate. Repo `direction` (Supabase + fake). Tests:
`tests/zora/test_used_memory.py`, two in `tests/api/test_director.py`.

Interface: `UsedBlock` (`features/director/components/used-block.tsx`) under a reply in both chats: each entry's words
(cut short, whole on hover, `spoken()` for its language), its document linking to the Documents page, and for people
with `direct` a × that asks first, rejects, marks the chip "Removed" and refreshes. `canDirect` comes from the Director
and Shot workspace pages.

### Phase 4: Edit a sent message and regenerate (interface + small backend; model calls on click)

These rewrite history. That is fine for talk, but risky for plan edits, so they are scoped:

- **Edit**: `ActionBarPrimitive.Edit` on the **last** user message only. `onEdit` sends the edited text as a **new turn**
  and marks the old pair “edited” (greyed, kept). Nothing is deleted server-side. If the old turn changed the plan, the
  edit first offers **Undo**, and only then resends. No branching.
- **Regenerate**: `ActionBarPrimitive.Reload` only on replies whose lane changed nothing (`revision == 0`: explain,
  chat, options). It resends the same user text. Each press is a model call, so the button says “Ask again”.
  The branch picker (‹ 1/2 ›) is left out until D2.
- Backend: a `replaces` id on `TurnRequest`, so the stored thread links the new pair to the old one. Additive and
  optional.

Decision **D2**: keep regenerated replies as branches (branch picker, needs branch data stored), or simply append?
Default: append.
The live check (a few turns on the person's scene) is the person's, after their yes.

**Built (2026-11-08)**, default D2 (append), no schema change, no model called.

Backend:
- `TurnRequest.replaces` and `TurnPayload.replaces` (optional). Both turn routes (`/scenes/{id}/chat`, `/zora/turn`)
  check it through `api.services.director.replaces_blocks`. It must be the thread's **last message from a person**,
  or the API answers 409 ("Only your last message can be edited or asked again.") and the function is never called.
  The new message is stored with one `ReplacesBlock` `{kind: "replaces", message_id, how}`. `how` is "again" when the
  words are the same and "edit" when they changed. The block sits in the `blocks` JSON, so no schema change is needed,
  and nothing is deleted.
- `contracts.director.without_replaced(history, replaces)`: all three engines (legacy classic, graph classic, Zora)
  read the thread without a replaced message and the replies that answered it. So the models never see the old words,
  and the repeat guards (`loop.repeated`, `guard.repeated`) don't answer "you asked that already" to an Ask again.
- Zora's `changes` block now names its `lane` (`ChangesBlock.lane`, "" on older messages).
- Tests: `tests/contracts/test_replaces.py`, `tests/zora/test_replaces.py` (the replaced pair never reaches a prompt),
  and two in `tests/api/test_director.py` (stored, labelled, kept; only the last message; refused never reaches the
  function).

Interface:
- `toMessage` reads `replaces` from a person's message and `applied` from a reply. A classic reply is applied when it
  has `ops`; a Zora reply is applied when its `changes` block has `revision > 0`.
- `toThread` (`features/director/lib/thread-messages.ts`) decides what is offered:
  - Edit: only on the person's last stored message.
  - Ask again: only on the thread's last reply, and only when it applied nothing, was not stopped and left no script
    edit waiting.
  - Nothing is offered while a turn is on its way.
  - An edited pair stays, greyed: "Edited below" under the message, and "Replaced by your edit" under the reply
    ("… The change it made stays." when it applied one).
  - The message that replaced it is labelled "Edited" or "Asked again".
- Thread: Edit is `ActionBarPrimitive.Edit`. It opens assistant-ui's edit composer in place (Cancel / Send, "Sends as
  a new message. This one stays, greyed."). Ask again is `ActionBarPrimitive.Reload`, with the label "Ask again".
  `useChatRuntime` takes `onEdit` / `onAskAgain`.
- Zora: an edit of a message whose turn changed the plan first asks "Undo that change before sending your edit?" with
  three buttons: "Undo it, then send" (nothing is sent if Undo fails), "Keep it and send" and "Cancel". The classic
  chat has no Undo, so it sends, and the greyed reply says the change stays.
- Tests: 5 in `chat-thread.test.tsx`, 5 in `thread-messages.test.ts`.

Open: the live check (Edit and Ask again on a real turn, each a model call) is the person's, after their yes.

### Phase 5: Build chat questions in the thread (interface only)

Today a Build question is a card with answer buttons, outside the runtime's knowledge. Render it as a **human tool call**
instead: a `tool-call` part with `status: requires-action`, drawn by our existing card. Answering calls `addResult`,
which reaches `onAddToolResult` → `answerQuestion` (unchanged endpoint). Gains: the thread knows a question is open
(the composer hint, scroll-to the open question, answered state from the runtime instead of local `answers`).

This is a refactor with little visible change. Decision **D3**: do it now, or only when Build needs free-text answers
or approvals? Default: later.

**Built (2026-11-08)**, on the person's "complete the plan" (D3 → now). Interface only, no backend change, no model.

- `toolCallMessage` (`components/chat/thread-parts.ts`): a question becomes one `tool-call` part (`ask_person`, args
  `{title, body}`). With no `result`, the message status is `requires-action`. `useChatRuntime({ onToolResult })` maps
  to the external store's `onAddToolResult`.
- `ChatThread({ renderTool })` draws a tool call through `tools.Override`. A message waiting on the person carries
  `data-requires-action`, and while any question is open the footer offers "Go to the open question" (it scrolls
  there; the Build composer stays closed).
- Build chat: `QuestionCard` answers with `call.addResult({value})`. That reaches `answerQuestion` (unchanged
  endpoint). The answered state is the call's `result`, so "You chose …" comes from the runtime and not from a prop.
  If the save fails, the question opens again with the reason. The header's count is the runtime's open calls (the
  build's own `open_questions` when the questions themselves could not be read).
- Tests: `features/build/components/build-chat.test.tsx` (4).

### Phase 6: Later, each its own plan when wanted

**Not built (2026-11-08), on purpose.** Each row below says it needs its own plan, and **D5** (which comes next) is the
person's. None of them is a free UI win:
- Feedback needs a new link from each reply message to its Langfuse trace (traces are not tied to messages today) and
  a write to Langfuse.
- Attachments need a new backend surface.
- Dictation needs a spike on the person's own voice.
- Follow-ups need model calls.
- Search and resumable streams wait on long threads, which are not here yet.

| Item | Needs | Why it waits |
|---|---|---|
| Attachments (reference image, page, frame) | `AttachmentAdapter`, an upload endpoint, storage, and the turn to accept images | New backend surface. The author must be able to use them. |
| Dictation | Web Speech API (free, in the browser) | Sinhala (`si-LK`) quality is unknown. Needs a small browser spike on the person's own voice first. |
| Thread list (several chats per scene) | persistence adapter over existing `threads` endpoints (list and create already exist) | Want it first. The UI cost is small. |
| Feedback (thumbs + reason) | a feedback endpoint → Langfuse score on the turn's trace | Useful for the Zora lab. Small. |
| Generated follow-ups / thread titles | model calls | Zora already sends suggestions. Only add these if a person asks. |
| Resumable streams | a server stream store | Turns are short. Phase 2 covers the reload case. |
| Search in conversation | UI only | Wait until threads are long enough to need it. |

**Left out on purpose:** Cost meter, Quota banner, context and token rings (rule 1). Read aloud (dialogue must stay
verbatim, and Sinhala TTS is poor). Model picker, MCP panels, code runner, voice orb (no use here).

## 4. Order, size, cost

| Phase | Repo | Size | Model calls |
|---|---|---|---|
| 0 | interface | small | none |
| 1 | interface | medium (8 small items) | none |
| 2 | both | small + spike | none (live stop test reuses a normal turn, after the person's yes) |
| 3 | both | medium | none |
| 4 | both | medium | only when a person presses Ask again or Edit (built 2026-11-08) |
| 5 | interface | small–medium | none (built 2026-11-08) |

Phases 1, 2 and 3 are independent after Phase 0. 4 depends on 2 (Stop and Edit share the turn controller). 5 stands alone.

## 5. Decisions for the person

- **D1** Stop: stream only (default), or also cancel server work?
- **D2** Regenerate: append (default, built), or keep branches with a picker?
- **D3** Build questions as tool calls: later (default), or now? (Built now, on "complete the plan".)
- **D4** Starter prompts and slash command names: confirm the lists in 1.7 and 1.8.
- **D5** Which Phase 6 item comes next, if any.
