# Production memory: what is built

Plan: [PLAN.md](PLAN.md). Built 2026-11-05, phases 0 to 4, **offline**: every model answer in the tests is scripted. Nothing was
run on a real model, nothing is deployed, nothing was run against the hosted database, and the migration is **written, not
applied**. Work is uncommitted. Phase 5 (the live check) is a person's because it costs model calls; Phase 6 (the interface)
waits for it (D4).

Decisions D1 to D4 were taken as the plan says: **D1** a new table; **D2** agents use draft entries, each labelled `(draft)`;
**D3** `memory_reader` is an agent of its own; **D4** the interface after the live check.

## Where things stand

| Phase | State | What is open |
|---|---|---|
| 0. The yardstick | **Built** | `tests/fixtures/memory/`: the plan's example bible (13 entries), a **synthetic** phone-call direction file (the real bible was not on this machine; its two sections are written in the layout the plan describes) and the real 3-episode drama's "Visual Style" line. `expected.json` holds the entries a person expects, quotes included, and a test holds the quotes to the documents. |
| 1. Reader and check (M1, M2) | **Built** | The real prompt has never met a real document. |
| 2. Store, port, ingest (M3, M4) | **Built** | **The migration is not applied.** Until it is, the ingest does not ask the model (see below) and the memory is empty. |
| 3. Middleware and subscriptions (M5, M6) | **Built** | |
| 4. Conflicts (M8) | **Built** | The "two documents disagree" rule is a heuristic (see Known limits). |
| 5. Live check | **Not done** | A person: ingest the example bible and one script, build one love scene and one action scene (pass conditions in PLAN §6). |
| 6. Interface (M7) | **Not built** | After the live check (D4). The entries are visible on the ingest job's events until then. |

## What changed

- **`contracts/memory.py`** (new): `MemoryEntry`, the starter topics, strengths, `parse_target` / `target_text` (the five forms
  of `applies_to`: `production`, `place:`, `character:`, `episode:<n>`, `when:`) and `topic_key` (lower case, words joined by `_`).
- **`agents/memory_reader`** (new): `Input{filename, text}`, `Output{entries[{topic, applies_to, says, quote, strength}]}`, tier
  `high`, phase `doc_ingest.memory`, middleware `[static_first, usage, absent_safe, untrusted_text]`. The document goes in as
  data (the `documents` hook; `untrusted_text` wraps it), cut at 60 000 characters. No fallback: with no model nothing is read.
- **`steps/memory_check`** (new, no model): an entry is kept only when its quote is in the document (`verbatim_check.flat`:
  case, quote style, spacing; a quote cut short with an ellipsis, or skipping a stretch with one, is read by its pieces in
  order; fewer than 6 characters is refused), `says` is not empty, the strength is must/prefer/fact and `applies_to` is one of
  the five forms. Topic and target are written in one shape. Exact repeats are merged; more than 80 entries from one document are
  cut. Every drop is a warning on the ingest job (ten shown, then a count).
- **`steps/memory_conflicts`** (new, no model): reports (a) two entries on the same topic and target from **different** documents
  that say different things (the newer document's entry is suggested, a person chooses), (b) a lens that is not in
  `CAMERA_OPTIONS` (28 / 35 / 50 / 85 mm: so the example's 24 mm), (c) a shot or take length Veo cannot make (not 4 / 6 / 8 s),
  said as an exact claim ("a 10 second shot"; "under 10 seconds" is a limit and is left alone).
- **Store**: `MemoryStore` port (`entries`, `replace_from`, `upsert`), `Ports.memory`, `FakeMemory` (in `ports_from` under
  `memory`), `SupabaseMemory`. `replace_from` removes the document's **reader drafts** and writes the new ones; an entry a person
  approved, rejected or edited (`source` becomes `person`) is kept, and a new entry that says what one of those already says is
  not added again, so a rejected direction does not come back as a draft.
- **Migration** `supabase/migrations/20261105090000_production_memory.sql` and test `supabase/tests/database/012_production_memory.test.sql`
  (constraints, read-only RLS by `can_view_production`, cascade with the document and the production). Because v12 is unreleased
  the table is **folded into `Database/schema_v12.sql` and `Database/upgrade_v11_to_v12.sql`** (re-runnable: `if not exists`,
  `drop policy if exists`); `Database/README.md` says so. Re-run the upgrade on a project that already ran the v11 to v12 step.
- **`doc_ingest`**: a `memory` node after `story`. It asks nothing without a model, a memory port, or a readable table (it reads
  the production's entries first, so a database without the migration costs no model call and the ingest succeeds). A failing
  reader leaves the document's earlier entries as they are. Progress "Read the direction in X: n entries", the check's warnings,
  and the conflicts the new entries are part of go on the job's events.
- **`core/memory.py`** (new): `read` (reader + check), `entries(ctx)` (the production's draft and approved entries, once per run,
  cached on `RunContext.memory_cache`; empty if the table cannot be read), `fresh`, `key`, `genre`, `conflicts`, `report`.
- **Middleware `production_memory`** and **`memory:`** in the agent manifest. Validation refuses topics without the middleware
  (in the form that runs and in the tools form) and topics that are not lower-case words or `*`. The block is appended to the END of
  the user message (system prompt and cached prefix untouched); no entries gives a call identical byte for byte (tested for all 14
  subscribed agents, with no port, no production, an empty store, a missing table and only rejected entries). `fact` and `must`
  entries reach every subscribed agent; `place:` / `character:` entries are matched to canon with `match_location` /
  `match_speaker` (aliases count; with no canon the two names are compared by the same rule); `episode:` by number; `when:` always
  stays. At most 40 entries per call (`must` first, then the narrowest scope, shown in document order). The same direction from
  two documents is said once. A closing tag inside an entry is defused.
- **Subscriptions** as the plan's table, plus **`adam_critic`** (the one-call critic of plan/2026-11-05) with `*`, because in
  `ADAM_MODE=take` it replaces `adam_critic_fidelity`. `adam_critic_fidelity` and `adam_critic` got one prompt bullet: a `must`
  entry the plan breaks is a (fidelity) note; a `prefer` entry ignored is at most a low one. `chat_answerer` is subscribed in both forms.
- **`memory_scope`** hooks on `adam_dramaturg`, `adam_director`, `adam_shot_designer` return `{place, people, episode}`. **The plan
  says all three are already in the agents' `Input`; the episode number was not**, so `Context.episode` (dramaturg) and
  `Input.episode` (director, shot designer) were added, defaulted, and `Scene.context_of` / the two call sites fill them. They are
  not part of any user message.
- **`shot_producer`** passes the genre a `fact` entry gives (`memory.genre`) to the technique lookup instead of the constant, which
  stays the default. `memory.report` puts the conflicts on the job events at the start of a `shot_producer` run and an Adam plan.

## Tests

`tests/hiru_ai/test_production_memory.py` (43 tests: yardstick, reader, ingest, store, middleware, scope, cap, byte-identity,
conflicts), `steps/memory_check/tests`, `steps/memory_conflicts/tests`, `agents/memory_reader/tests`, plus the generated contract
tests, which pick the three new parts up by themselves. On the plan's example: **13 of 13** entries reach the store checked, an
invented one is dropped, 24 mm is reported, and a `place:` entry reaches only scenes at that place.

## Known limits

- **Disagreement is a heuristic.** Code cannot read meaning, so it reports "different words about the same topic and target from
  different documents" and a person decides. Two documents that complement each other will be reported too. Within one document
  entries are never reported against each other.
- **The reader and the check cannot tell a direction from a story line that happens to be quoted**: the quote is real, so the entry
  stays (a draft). The prompt keeps character looks out; the live check counts what slips in.
- **`when:` entries are never narrowed by code**, on purpose: whether this scene is a "love scene" is the agent's to see.
- **`adam_take`, `adam_moment_writer` and the other Adam agents have no `memory_scope`**, so a `place:`, `character:` or `episode:`
  entry reaches them for every scene. Only the three the plan names narrow.
- A deleted document takes its entries with it (`on delete cascade`), including ones a person approved. A person's own entries
  (no document) stay.
- The conflicts are re-reported on every job (a re-delivered Cloud Task repeats them); the events are warnings, not blocks.
- Character canon is read once per run for the `place:` / `character:` match; a canon built mid-run is not seen until the next one.
- **`supabase test db` was not run** for `012_production_memory.test.sql`, and the three-way schema dump comparison was not made:
  Docker is not running on the machine this was built on. Run both before applying the migration.

## What waits for a person

1. Apply the migration: run `Database/upgrade_v11_to_v12.sql` (it is re-runnable) on the hosted project, or the whole
   `schema_v12.sql` on a new one. Until then the ingest reads no direction and every agent's call is as it was.
2. The live check (Phase 5): `hiru-ai` ingest of the example bible and one script, then a love scene and an action scene.
3. Then Phase 6, the memory panel and "remember: …" in the director chat.
