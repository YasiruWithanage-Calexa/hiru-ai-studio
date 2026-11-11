# Two memories: what is built (plan/2026-11-11)

> Run log. The current plan, decisions and what is left are in [PLAN.md](PLAN.md) (revision 2, end of 2026-11-11). The early
> "For the person" list below is history: D1 to D7 are decided and phase 0 is done.

Status 2026-11-11: **phase 0 built offline, the free half only.** No model was called, nothing was applied or deployed,
nothing is committed. Phases 1 to 7 are not started.

## Built: `lab/two_memories/` (13 tests, `.venv/Scripts/python.exe -m pytest lab/two_memories/tests -q`)

| File | What |
|---|---|
| `lines.py` | Numbered lines and word spans; the one place a pointer becomes text (rule 1: the model points, code copies) |
| `ids.py` | Id registry and validation: `C01 L01 P01 D01 T01 E01 E01-S03 E01-S03-B04 E01-S03-B04-e2` (rule 2) |
| `schema.py` | Wire shapes for the split (step 1) and the episode (step 4), all pointers; the stored breakdown memory with `script` / `inferred` / `person` provenance, owner and version |
| `build.py` | Step 2: ids, cards cut by code, rules with scope resolved to ids, scenes cut; `apply_episode` numbers blocks and events and cuts their words |
| `checks.py` | §8: words (no gap, no overlap, a `speech` event must sit in a dialogue block: Astra's miss), ids, sources, presence, hand-over continuity (report), direction scope, length (report) |
| `packet.py` | §7: the scene packet A to I from the memory, and `incomplete()` (planning waits). Only the scene's people are shown (D3); a region's direction rule follows its sets |
| `rehearsal.py` | The draft gold for Ekama (clean): the split for all 9 scenes, the episode answer for scenes 1 to 3 (Aruni voice message, Mudalali on the phone cut out of an action line, Mudalali not in S03). A person must correct it before it judges anything |
| `prompts/split.md`, `run.py` | The split prompt; `run.py dry` (size and the most a call could cost: 2.3k tokens in, under $0.09) and `run.py rehearse` (build, checks, three complete packets of 1.1k to 1.5k tokens) |

## Not built (waits)

- **Paid runs.** The cache, the $8 ledger and the `paid` command are written with the first paid run, which waits for the
  person's yes. Prompts for continuity and the episode call are not written yet.
- The packet lacks what only the paid steps give: story order, time, threads, irony, looks, in/out states (stager),
  weather and light sources. Its size is therefore a lower bound (D4 expects 3 to 8k tokens).
- Phases 1 to 7 (contracts in `src/libs/contracts`, agents, schema v21, the retire switch, edits, interface, live check).
- Pages mode (Avasana) is untouched.

## For the person

1. Correct the draft gold in `rehearsal.py` (scenes 1 to 3), then say yes to a first paid split run on Ekama (about $0.09 at most).
2. D1 to D7 in the plan are still yours.

## Update 2026-11-11 (later): first paid split run, $1.00 hard cap

- **Cap:** `lab/two_memories/paid.py` refuses any call whose worst case would take the ledger past **$1.00 for the whole lab**
  (the person's order, replacing the plan's $8); answers are cached on disk by request hash; `run.py split --yes --hypothesis "…"`,
  `run.py ledger`. Model `gpt-6.1-sol`, effort medium.
- **Run 1 (Sol medium, split of Ekama): $0.0575.** All 9 scene cuts (heading and last line) equal the hand gold. It also found
  direction notes inside scenes (30 rules vs the gold's 9) and more cards (42 vs 22), some with word spans outside the document
  (code flagged 11: the checks work). Two faults of ours, not the model's:
  1. `name` was free text, so the model wrote pointers (`"29:0-1"`). Fixed: a card's name, `within` and a rule's scope are now
     pointers (`name` span, `within` / `scope_card` card index, `scope_number`); code cuts the name.
  2. The text sent still had the form-feed page furniture (the "clean" cleaner missed `\x0c`), so the run read the uncleaned text.
     Fixed in `rehearsal.doc()`. Run 1's saved answer is for the old text and is not comparable; the next run is a new request.
- Spent: $0.0575 of $1.00. Next paid run waits for the person's yes.

## Decisions (person, 2026-11-11)

D1 yes (breakdown memory is the one source; today's columns are filled from it). D2 to D7: the recommendations (D2 hands and
posture only where they change; D3 full cards for the scene's people, names only for the rest; D4 no packet size limit; D5 split
effort decided by the lab; D6 lab cap: **$1.00 hard cap**, not $8; D7 JSON documents per production and scene plus filled columns).

## Run 2 (Sol medium, split of the cleaned Ekama text): $0.0808, total $0.1383 of $1.00

- 9 of 9 scene cuts equal the gold. Names, `within` and scopes now resolve through code (1 build finding, a field span outside the
  document; was 11). Region palettes scope to the right places (Colombo L01, Mahawewa L02); lens/lighting/sound rules inside the
  table are scoped `all`.
- **Faults of the model's reading to fix in the prompt (one change per run):** (a) it over-extracts things (41 cards vs 22:
  "canal", "container", "chain", "cash"); the prompt should say a thing is a card only when the story uses it or a
  direction note names it as a prop, and a place is a card only when it is a set, spot, vehicle or region; (b) it splits one
  table row into several overlapping rules (D18/D19, D20 to D23: the same lines under palette, lens, lighting and sound),
  where one rule per table row was wanted; (c) `seen` is true on every card, including places only spoken of (Old Port
  warehouse in S02 is a set in S04, so right there; the village bus stop in S02's photo is a miss to test in the next run).
- Next (free): write the continuity and episode prompts and wire shapes. Next paid run (about $0.08) waits for the person's yes.

## Run 3 (prompt: card criteria, one rule per table row, whole sentences; code widens fields): $0.0573, total $0.1956 of $1.00

- Code (free): `lines.sentence_spans` widens a card field to its whole sentence inside the card's lines (`age`/`gender` stay literal;
  a one-word label line such as the name is never part of the sentence); `checks.cards` reports (never fixes) a thing spanning
  over 10 lines, a name inside another card's name, the same detail text on two cards, a spot with no set, a set no heading names.
- Result: cards 41 to 31 (6 people, 2 regions, 8 sets/vehicles... 11 things, all real props), rules 30 to 15 (8 direction rows, 7 notes
  from scene prose with scenes named), build findings 11 (run 1) to 1 to 2 (two fact spans outside the document, reported).
  Still weak: wide pointer ranges on moving things (red thread 54 lines, cash bag 37) and `seen` is true on every card.

## Cards approved; step 3 (continuity) built offline

- The person approved run 3's cards (2026-11-11): saved as `lab/two_memories/gold/split_ekama.json`, the Ekama cards gold.
- Built free: `ContinuityW` in `schema.py` (timeline, synopses, arcs, knowledge, threads, looks, relationships, direction scopes,
  every item `script` with lines or `inferred` with a reason), `prompts/continuity.md`, `prompts/episode.md` (written, not yet run),
  `inputs.py` (roster, rules and the story under scene ids), `run.py continuity` (dry) and `run.py continuity --yes --hypothesis "…"`.
  Dry: 2,850 tokens in; the most one call could cost $0.17. Waits for the person's yes.

## Run 4 continuity ($0.0757) and run 5 episode E01-S01..S03 ($0.0714): total $0.3427 of $1.00

- **Continuity (Ekama):** no unknown ids; S03 first as a flashback anchored to S02 ("Six hours earlier"); the key's journey a thread
  with the unexplained return to Nimal's fist left open; the "key falling" slow-motion moment reported as not in the script (not
  invented); direction rules scoped to scenes. Watch: S01 placed 5th after S05 with its own note "unresolved" (a person edit would
  say after S04); one knowledge item without a person (the village); thin arcs for Suren and Mudalali.
- **Episode (S01 to S03, `run.py episode`):** zero blocking findings, all three packets complete. Every word of every scene is in
  exactly one block; Aruni's S02 line is `voice_message`, Mudalali's call is its own `phone` dialogue block cut out of the action
  line; Mudalali is not listed in S03; Nimal is `body` in S01. Same as the hand gold, from a model.
- **Change from this run:** a card field that points outside the document is now dropped and reported (non-blocking). It had
  blocked all three packets because of the split's bad P08/P09 field, which is not a fault of the scene.

## Packet fixes (free, no model): continuity, names, withheld facts, direction labels

`packet.assemble(bd, scene, cont)`: (1) continuity enters section A in STORY order (time, the scene before and after with how
it ends and opens, threads with earlier/this/later beats, irony, knowledge, looks, relationships up to this scene, a rule's named
moment); (2) a card `summary` shows only when its range is at most 6 lines; (3) ids in a model's sentences become names (`Name [id]`
when two cards share a name), ids stay in every structured field and `ids` maps them; (4) each direction rule says `scoped`,
`general` or `conditional` (lens rules with no place or scene scope); (5) a card fact from another scene's lines is withheld.
S02's packet: about 2.8k tokens, complete. The saved model answers used as test fixtures are in `lab/two_memories/gold/`
(`split_ekama.json`, `episode_ekama_s1_s3.json`, `continuity_ekama.json`). 20 tests.
Still prompt work (a paid run): scene titles that are summaries, the `inferred:` prefix inside mood and intent text, and the
episode call saying which conditional rules a scene meets.

## Run 6: episode prompt fixes ($0.0754), total $0.4181 of $1.00

Prompt and schema: noun-phrase titles (now "The Canal Discovery", "The Route Change", "The Garage Handover"), no `inferred:` text
prefix (`source` on the brief and on each block; the packet shows `purpose_source` and `intent_source`), and `rules_met` (the
conditional direction rules a scene meets; the packet drops a conditional rule the scene does not meet). Result: S01 to S03 still
complete with no blocking finding, no prefix left in any packet, no lens rule in any of the three scenes (none is a love or action
scene). One model slip: S01's `rules_met` lists D01 and D02, which are scene-scoped rules, not conditional ones; the packet ignores it.
The saved episode answer in `gold/episode_ekama_s1_s3.json` is now this run's.

## Run 7: the other six Ekama scenes ($0.1425), total $0.5606 of $1.00

One call for S04 to S09 (`run.py episode --scenes … --cap 32000`). 7 of 9 packets complete; the checks stopped two:
- **S07:** the model skipped one word ("sound" in "temple sound system"): the words check caught it.
- **S08:** the model made three dialogue blocks out of the narration "Mudalali and Ruwan's own voices play across the village",
  two of them one word long (the speaker's own name). Presence flagged Mudalali (seen fighting AND heard on the recording) as a
  fault: that check was too strict and now allows a person who is also seen in the scene. A new words check blocks a dialogue
  block that is only its speaker's name.
- Still open: S07 and S08 need the repair step (plan §4.4: the same model is shown the exact problems and returns a patch, at
  most twice); the prompt needs "a dialogue block holds only spoken words; audio that is heard but not quoted is a `sound` block".

## Run 8: the repair step ($0.0589), total $0.6195 of $1.00

`run.py repair --yes --hypothesis "…"` (plan §4.4, §8): for each scene with a blocking finding the same model is shown its own
answer and the exact problems and returns the scene again; at most two tries; a patch that is not better is not kept. Result: S07
and S08 each fixed in ONE try (1 problem each, 0 after), all 9 Ekama packets complete. The repaired scenes are saved in
`gold/episode_ekama_s99_repairs.json` (applied after the others). The episode prompt now also says a dialogue block holds only
spoken words.
Phase 0 on Ekama is done offline and cheap: split $0.14, continuity $0.08, episodes $0.29 (9 scenes in two calls and a repair),
repair $0.06, about $0.62 with the lab runs. Not done: the person's read of the packets against the stop rule, the missing
packet parts (positions and hands from the stager, weather and light, extras, safe depiction), pages mode and Avasana.

## Step 6, the stager (built offline; run 9 on S08: $0.0195), total $0.6390 of $1.00

`stage.py` (the product stager's prompt and output shape, input built from the scene's blocks and people, presence marked "heard
only"), `stage_run.py` (`run.py stage --scenes … [--yes --hypothesis …]`; marks saved in `gold/stage_ekama_<scene>.json`).
Invalid entries are dropped and reported (a person not in the scene, a block that does not exist, an unknown zone); marks are
expanded per block by code ("the last mark holds", D2); a disagreement with the episode call about who holds a thing at the end
is a finding. The packet gains `stage`: zones, each person's in and out state, the blocks where a state changes, loose props.
S08 (the hardest scene): 4 zones, marks for the five people, packet complete. Weak spots: hands and condition are almost all
empty (the stager keeps to what the script says: nobody's hand is named, Mudalali's gun is only a prop after it is kicked);
Aruni has no in-state (her first mark is block 5); the crowd (Villagers, Police) is dropped as not in the scene's people, so the
packet still has no extras. 25 tests.

## Run 10: stager prompt fixes on S08 ($0.0191), total $0.6581 of $1.00

Lab prompt: `holding` is filled when the script has a person use, raise or carry a thing; every on-screen person is marked at the
first block. Packet: `stage.not_placed` says who has no position before which block. Result on S08: Mudalali now holds "gun" from
block 9 (run 1 had it only as a prop), Aruni still has no mark before block 5 (the prompt rule did not move the model; the packet
now says so: "no position before block 5"), the crowd is still dropped. Known limit: the stager can clear a hand only by a prop
row, which is dated the same block as the raise, so code keeps Mudalali holding the gun after it is kicked away; ordering inside
one block needs a decision. Run 1's answer is kept in `runs/stage_S08_run1.json`.

## Run 11: the stager on all nine Ekama scenes, total $0.7275 of $1.00

All nine scenes staged (S08 again, the other eight new, about $0.09 together); every packet is complete with `stage`
(2.7k to 5.5k tokens; S08 largest). Hands filled in 7 of 9 scenes. `not_placed` names who has no mark at block 0 in six scenes.
Cross-check findings (report only), all in S04: the episode call says Dinu ends the scene with the cash bag, the stager's last
state has him holding the chain or Nimal's phone (the same one-state-per-block limit as S08). Dropped as not people with
cards: "Masked men" (S04), "Villagers" and "Police" (S08): the extras gap. Saved in `gold/stage_ekama_<scene>.json`.

## Raphael's first agent reads the packet (person's go, 2026-11-11; built offline, not wired)

- `src/libs/contracts/raphael/packet.py`: `opening(packet)` -> the first message, `SceneS` and the id map. The model gets the
  WHOLE packet (`<packet>`), then `<timing>` (the clock per block, Raphael's own code), `<voice_only>` and `<length>`. Raphael's
  tools and checks read `SceneS` built from the packet: cast = people seen, plus heard people who speak (so the voice-only rule
  still finds them); a line's delivery from its presence (`is_heard` is exact); objects = the packet's things; opening state and
  each block's `now` from the stage; an action's events count from the packet's events. `b4 = E01-S08-B05` maps the tools' ids
  back to the packet. Replaced on this path: `present()`, `objects_of()`, `others_of()`, `mark_recorded`, the stager call, the
  breakdown call.
- `raphael_planner`: five `- PACKET (plan/2026-11-11).` prompt lines (how to read the packet, ids, presence, the state ledger and
  NOT PLACED, direction in scope; purpose and turns replace a breakdown); `agent.input_from_packet(packet)` builds its `Input`.
  `tests/raphael/test_lab_parity.py` lists the five lines.
- `tests/raphael/test_packet_input.py` (6 tests, fixtures `tests/fixtures/raphael/packet_ekama_s02.json` / `_s08.json`): nothing in
  the packet is lost (every text value reaches the message, except a written LEFT_OUT list); S02 hears Aruni AND Mudalali (today's
  path catches Aruni only); Raphael's own Stage1Session reports on the packet scene (10 blocks, lines L2 L3 L8, 180 s target).
- Not wired: the graph still builds today's message. The packet path needs the packet stored (phases 1 to 3) and its lines as
  `dialogue_lines` rows. 9 tests in tests/raphael and tests/parity fail before AND after this change (pre-existing).
- Messages for reading: `lab/two_memories/runs/raphael_packet_message_s02.txt`, `_s08.txt`.

## Phases 1 to 6 built offline (2026-11-11, later): no model was called, nothing applied, nothing committed

Spent on this work: **$0** (every test scripts its model; the lab ledger is unchanged at $0.7275 of $1.00).

### Phase 1: contracts (`src/libs/contracts/breakdown/`, pydantic + stdlib only)
- The lab's modules moved: `lines`, `ids`, `schema`, `build`, `checks`, `inputs`, `packet`, `render`, `stage` (the stager's
  answer is read by attribute, so contracts never imports `hiru_ai`; its wire shape is `schema.StagerW`).
- New: `memory.py` (several documents laid end to end into ONE numbered text: `shift`, `merge`, `doc`; a generic
  page-furniture stripper that gives exactly the lab's lines on Ekama; the same person, place or thing on two documents'
  cards is one card, and a fact they state differently is a creation question, §4.2), `run.py` (the creation run as pure
  code with its calls passed in: split per document and episode calls four at a time, ONE continuity call, checks, repair
  at most twice with a worse patch never kept; absent-safe at every step; `refresh_scene`, `mark_stale`, `handover` for
  phase 5), `fill.py` (D1: the resolved structure for `structure_write`, canon cards, `production_memory` rows,
  `scenes.staging`, the line map).
- Stored shapes: `Breakdown` gains `documents`, `person_lines` (a person's edited lines are appended, never written over a
  document's), `continuity`, `version`; `Scene` gains `row_id`, `line_map`, `script_version`, `stale`, `edited`;
  `SourceMemory` is new. A stale scene's packet waits (`incomplete`), and an edited scene's lines are its own only.
- Episode calls: each episode's scenes shared evenly over as few calls as six scenes a call allows (Ekama: 5 + 4).
- Tests: `tests/breakdown/test_lab_port.py` (the lab's 26 tests), `tests/breakdown/test_breakdown_run.py` (14: the whole
  creation on the lab's saved answers, every Ekama packet complete, S07 and S08 repaired, the absent-safe paths, two
  documents, the fill, staleness, the one-scene refresh). Fixtures: `tests/fixtures/breakdown/` (the lab's gold answers).

### Phase 2: agents and the creation run
- `agents/breakdown/`: `breakdown_split`, `breakdown_continuity`, `breakdown_episode`, `breakdown_repair`,
  `breakdown_stager` (the lab's prompts, plus one line that the document is data; every message is built in
  `contracts.breakdown.run`). Tier `breakdown` = `OPENAI__MODEL_BREAKDOWN` (default `gpt-6.1-sol`) at
  `OPENAI__EFFORT_BREAKDOWN` (default medium), as the lab ran.
- `systems/breakdown/breakdown_build/graph.py`: read → breakdown → fill, with progress on the job's stages and events;
  `packet_for` (the stager runs ONCE per scene before planning; its map is saved under a lock because planners run scenes
  in parallel); `refresh` (phase 5). Settings `BREAKDOWN__ENABLED` (default **false**) and `BREAKDOWN__WORKERS` (4).
- The structure_build handler runs it when `BREAKDOWN__ENABLED` (or for a `breakdown_refresh` delivery). With the switch on,
  doc_ingest and canon_extract run their graphs, where the absorbed steps are retired: the story reader and the memory
  reader at ingest, and canon_extract (the breakdown writes the canon and the direction from its cards and rules). Off:
  nothing changes (the parity fixtures are untouched).
- Tests: each agent's own (5 each, two eval cases each); the system's 7 on fakes (creation fills today's columns, the
  memories and packets are kept, a second build keeps the rows, no model fails clearly, a stale packet waits, the stager
  runs once, the refresh).

### Phase 3: storage (schema v21, NOT applied)
- `supabase/migrations/20261111113728_breakdown_memories.sql`, `Database/schema_v21.sql`,
  `Database/upgrade_v20_to_v21.sql`: `source_memories` (one per document, written once), `breakdown_memories` (one per
  production), `scene_packets` (each scene's packet, `waits`, the `script_version` it was built for). RLS on, read
  policies on `can_view_production`, no write policies. `supabase/tests/database/020_breakdown.test.sql`.
- **Not verified against a local stack** (Docker was not running here): `npx supabase test db` and the three-way dump
  comparison are still to do before applying.
- Port `BreakdownStore` (`core/ports.py`), `SupabaseBreakdown`, `FakeBreakdown`. Today's columns are filled through
  `structure_write`'s own plan (ids kept, approved scenes never rewritten), so every dialogue block is a real
  `dialogue_lines` row and the memory records which.

### Phase 4: Raphael reads the stored packet (behind `RAPHAEL_PACKET`, default false)
- `raphael_shot_planner`: with the setting on, a scene with a complete, current packet is planned from it: stage 1's
  opening is the packet (`contracts.raphael.packet.opening`), the line ids are the scene's rows matched by order, and there
  is no stager call and no director's breakdown (§6). Anything else (no packet, stale, waits, a line count that differs)
  plans as today and the job says why. Reached by id (`parts.module("system", "breakdown_build", "graph")`); an
  import-linter contract forbids any planner importing the breakdown system. `tests/raphael/test_packet_wiring.py` (3).

### Phase 5: a person's edits
- Staleness is read, not written: a packet records the script version it was built for, and a scene whose version moved
  on is stale (the API says so; planners do not use it). `POST …/scenes/{id}/breakdown/refresh` (EDIT_SCRIPT) dispatches a
  structure_build delivery with `breakdown_refresh`: the person's lines (from `scenes.script` + `dialogue_lines`) are
  appended to the memory, that one scene goes through the episode call, checks and repair, its map is cleared (made again
  before planning), its line ids are read again, and the hand-over to the next scene in story order is checked (a
  finding). Nothing writes the scene's script: the edit is the person's (decision 6).

### Phase 6: API and interface (no costs anywhere)
- API `routers/breakdown.py`: `GET …/scenes/{id}/packet` (VIEW: `scene_key, packet, waits, stale, ready`) and the
  refresh; `PacketsRepo`. `tests/api/test_breakdown.py` (7, including "no money and no model in the answer").
- Interface `src/features/breakdown/`: the read-only packet view under the shot list panel's **Scene** tab (a server
  slot, like the planner tabs), with "Refresh breakdown" for people who edit the script when the packet is stale. Spoken
  lines use `spoken()`. Creation progress and creation questions use the existing build screens (the breakdown writes the
  same stages, events and `questions` rows). `packet-view.test.tsx` (8). Not seen in a browser.

### Checks run
- Backend: `ruff` clean on every changed file (one pre-existing E501 in `tests/api/test_production.py`), `mypy` clean (the
  whole tree, and the structure_build, canon_extract and doc_ingest services), import-linter: the two new contracts kept
  (2 pre-existing broken), `hiru-ai validate` 0 errors, `docs/AI_CATALOG.md` regenerated, the graph snapshot written.
- Full backend `pytest`: 5,469 passed; the 35 that fail also fail on the untouched tree (adam system, api handoff/looks/
  production/thumbs, the four other groups' removal lists, parity, raphael api/checks, shot_producer hygiene,
  reader_ingest, `raphael_breakdown`'s single eval case). Two failures this work caused were fixed (the tier table in
  `tests/hiru_ai/test_core.py`, `langgraph.json` regenerated).
- Interface: `next typegen`, lint (one pre-existing warning), typecheck, tests (one pre-existing failure in
  `raphael-panel.test.tsx`), format clean on every file touched.

### For the person
1. Apply schema v21 after `npx supabase test db` passes on a local stack (Docker), then turn on `BREAKDOWN__ENABLED`.
2. Phase 7, the live check: Ekama full and Avasana (pages mode, never run). It will pass the lab's $1.00 cap; the budget is
   yours.
3. `RAPHAEL_PACKET=true` only after a Raphael comparison on the packet (open decision 5, up to $5 a run).
4. Still open from §11: long action blocks, extras, S01's story order, `seen: false`.
