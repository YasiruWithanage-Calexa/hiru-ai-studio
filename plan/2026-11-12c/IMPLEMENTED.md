# plan/2026-11-12c: what is built

## Phases 1 to 7 and Track B, built offline 2026-11-12 (both repos, uncommitted, $0, no model called)

Phase 0 (the lab) was done before. Phase 8 (the live check) is the person's. D2 to D7 were open; each is taken as the
plan RECOMMENDS, listed at the end so the person can overturn any of them.

### Phase 1: contracts

- `contracts/canon_refine.py`: the canon call's answer (`Answer`: people, places, things; every fact a `Value` with
  `script` + line or `inferred` + reason), its strict schema, the message (`message`, `build`: each entity's card lines
  and the lines of every scene it is in, numbered as the breakdown numbers them, gaps shown as `…`), the split
  (`parts`: all at once under 40k tokens, else people, then places and things, then halves), the checks (`check`:
  missing / unknown / duplicate ids, script values against their line, gender from a gendered word, short age, no id or
  reasoning word inside a value, no person named in a place look, a set's look long enough to paint, a spot's parent a
  set or vehicle, safe depiction), `repair_message` (the failed ids only), `merge`, `join`, `canon_map`, and `versions`
  (the answer as new canon versions with rebuilt pins and reference prompt, provenance, `expected_version_id`, class
  and parent; a set's region is its parent). The looks were dropped from this answer (the plan's separate call).
- `contracts/scene_looks.py`: the looks call (`LooksAnswer`: story time, looks, who wears what with the scene's
  condition), `from_breakdown` (presence known: the checks hold the answer to it) and `from_tables` (D4), the split by
  episode with earlier looks carried, the checks (fix vs review), `repair_message`, `join`, and `rows` (draft
  `canon_looks` with episode ranges from the scenes each look is worn in; `scene_looks` by look name).
- Fixtures `tests/fixtures/canon_refine/` (Ekama's memory, lines and canon; run1, run2 and looks1 answers). run2: 0
  findings. run1: the 8 id mentions (7 findings: one field writing the same id twice is one) and the reasoning in the
  garage look. looks1: nothing to fix.
- Raphael already writes `pins.canon` (through `serialize.design_row` → `pins_for`): nothing to add.

### Phase 2: schema v23 (APPLIED to the hosted project by the person 2026-11-12; not verified locally: no Docker)

`Database/upgrade_v22_to_v23.sql`, `Database/schema_v23.sql`, `supabase/migrations/20261112102303_canon_refine.sql`:
`canon_versions.source` gains `refine`, `canon_versions.provenance`; `canon_entities.class` (checked list) and
`parent_id`; `canon_looks.origin`; `scene_looks.condition`, `why`, `origin`; `canon_refine_apply(uuid, jsonb)` (one
transaction, service role only). A version with the same `card_hash` is reused, so a re-run inserts nothing.
`supabase/tests/database/021_canon_refine.test.sql` (13 checks). The three-way dump comparison and `supabase test db`
were NOT run. v22 must be applied first.

### Phase 3: agents and H-14

`agents/breakdown/breakdown_canon/` and `agents/breakdown/breakdown_looks/` (tier `breakdown`, 240 s, house rules
`[wardrobe]`), the lab's prompts adapted (ids only in id fields, the safe-depiction line word for word), evals with the
lab's real answers, tests. `house_rules/working_dress.md` (H-14, topic `wardrobe`, default). `hiru_ai validate` clean;
`docs/AI_CATALOG.md` regenerated.

### Phase 4: the system

`systems/breakdown/breakdown_canon_refine/` (in the breakdown group: a system outside it may not name its agents):
load, refine (canon call, checks, one repair for the failed ids; looks call per episode part, checks, one repair),
apply (`CanonStore.refine_apply`). Split into `answers` (calls only) and `payload_of` (mapping to the canon as it is
now), which phase 7 needs. No breakdown → looks only, from today's tables, with a warning (D4). A failed canon call or a
missing v23 function fails the job and writes nothing; a failed looks call keeps the cards. The fake store mirrors the
SQL rule for rule. `fill.canon_cards` drops a summary wider than `SUMMARY_MAX_LINES`; `reference_sheet_prompt` never
paints a place from its summary. `JobKind.CANON_REFINE` is served by `hiru-canon-extract` (its handler branches on the
kind; same port 8205, same deploy entry).

### Phase 5: API

- `POST /canon/refine` (EDIT_CANON) → the job. The lock is in `task_manager.dispatch` (`refuse_busy`): a refine is
  refused while a build, a plan or another refine of the production is pending or running; every PLANNING kind
  (script_split, shot_produce, the five planner kinds) and a structure build are refused while a refine runs; 409 via
  the app's `Busy` handler. Frames and renders are not held.
- `GET /canon/proposals`, `POST /canon/{id}/versions/{v}/accept` (409 while locked: unlock first, as for any change),
  `POST .../dismiss` (deletes the never-current version).
- `CanonEntity` carries `canon_class`, `parent_id`, `no_plate`; `CanonVersion.provenance`; `CanonLook.origin`.
  `reference-sheet` is refused for a region, spot, unseen place or mentioned thing, and for a place with no look.
- Scene looks carry `condition`, `why`, `origin`; `PATCH /scenes/{sid}/looks/{eid}/condition`. A person's pick is
  written `origin: person` (only once v23 is there: before it the column is not named).
- The frame brief's People line adds "in this scene: <condition>" (both frame engines, `CastMember.condition`,
  `contracts.canon.scene_conditions`; `scene_looks` read with `*` so nothing breaks before v23).

### Phase 6: interface (uncommitted, not seen in a browser)

Canon page: a "Canon from the breakdown" card with **Refine canon** (waits through `waitForJob`, then reloads the
server page), the job's counts and review list, and the proposals banner (Accept, disabled while locked; Dismiss).
Tiles show **Refined** and the class ("Region", "Spot", "Not seen", "Mentioned only"). An entity page lists where each
refined field came from ("Age: from the script, line 17" / "Wardrobe: inferred (…)") and shows why there is no plate
instead of the sheet button. Looks drafted by the refine carry "From the breakdown". The scene's Canon tab shows and
edits each picked person's condition ("In this scene"). No costs anywhere.

### Phase 7: the fork–join

`breakdown_build`: `breakdown → fill` and `breakdown → refine` run in parallel, `[fill, refine] → refine_apply → END`.
`refine` makes the two calls only (a fresh build has no canon entities until fill writes them); `refine_apply` loads
the memory fill saved, maps the answers to the canon fill left and writes them all at once. Any error there is a
warning "Canon kept as extracted (…)", never a failed build. `BREAKDOWN__REFINE` (default true) switches the branch off.

### Track B

`Breakdown.canon_ids` (breakdown id → canon id) is kept by fill (`canon_map`: a mapped id that still exists is kept,
the rest matched by kind and name). Each packet carries `canon` by id: place, people on screen (a body too), things a
camera sees (hero, used, worn, dressing) and spots. `objects_of` in Adam, David, Jonathan and Raphael takes the scene's
things by id when the stored packet has them (`core/packets.canon_things`), else whole-word names
(`contracts.canon.props_in`, `named_in`: "photo" no longer matches "photographs"). The scene view's canon adds the
brief's people and things by id (`briefed_ids`), unless a person removed them from the shots.

### Not done (left for the person or a later pass)

- A region's look as the style note of its sets in the frame brief and packet: the region is stored as the set's
  `parent_id`, but nothing reads it yet.
- The scene's condition into the STAGER's input (only the frame brief reads it).
- "Worn in" scenes listed under each draft look (the panel marks refine drafts only).
- A shot's place from the event's spot through the map (Track B's last bullet).
- "Planned on old canon: re-plan" wording: the existing out-of-date counts already flag shots pinned to an older card.
- The request-hash cache of a call within a job (a re-delivered job calls again; the write is idempotent).

### Checks (2026-11-12)

Backend: `ruff check src tests scripts`: only the 3 pre-existing E501s. `mypy`: clean. `scripts/lint_imports.py`: the
two contracts that were already BROKEN before (api → hiru_ai rag, david agents) and nothing new. `hiru_ai validate`: 0
errors; `catalog --check`: current. pytest: every new and touched test passes; the failures left (parity ×8,
removal tests that list schema v19+, shot_producer prompt hygiene, three API files that expect port 8000,
`test_looks` edit, `test_scene_canon` removal, Raphael API/checks) fail identically without these changes.
Interface: `npx next typegen`, `npm run check`: lint (1 pre-existing warning), typecheck clean, tests 451 of 452 (the
failing Raphael panel test fails without these changes too); `format:check`: these files pass, 29 others did not
before.

Full run afterwards (contracts, api, breakdown, hiru_ai, services, every part's own tests): 4548 passed, 14 failed.
Two were mine (each new agent needs two eval cases: a small hand-made second case added to each) and the new system
was missing from `langgraph.json` (added; `test_dev_tools` now passes whole). The other 11 fail identically without these changes (handoff ×2, thumbs,
looks edit, production ×3, scene_canon, reader_ingest off-graph, shot_producer).

### Decisions taken as recommended (the person may overturn)

- D2: a locked or person-written card gets a proposal (stored, not current), never skipped.
- D3: the scene's condition is `scene_looks.condition`.
- D4: looks from tables are allowed for productions without a breakdown; canon cards need the breakdown.
- D5: looks are drafts; no sheet is painted until a person makes one ready.
- D6: 240 s per call (the agents' `timeout_s`).
- D7: `canon_extract` and `look_drafter` stay for productions without a breakdown.

### Phase 8 (the person's, paid)

Apply v22 then v23; "Refine canon" on Ekama (expect about 14 switched, 8 proposals for the locked cast and the
person-written places, a few draft looks); one new build of a short production with `BREAKDOWN__ENABLED` (the fork–join);
reference sheets only if asked. Cap $1.00, about $0.30 expected.

## Phase 8, part 1: the refine on Ekama, LIVE (2026-11-12, the person's yes)

`scripts/canon_refine_live.py 96c4a5b7-… --yes` (the product's system, the hosted database, a real `jobs` row
`3723b5f2-1478-4f9f-87e7-b2ae49a9f6d5`, a $1.00 cap). Before/after and the result are in
`lab/canon_refine/runs/live_20261112_165039/` (`before.json` is the whole canon as it was, to undo by hand).

- **$0.0688, 108 s**: canon call 84 s ($0.050), looks call 23 s ($0.018); no repair needed (0 fix findings).
- 12 cards switched, 8 proposals (Dinu, Aruni, Nimal, Colombo, the canal, the van, the medical bag, the key: locked),
  2 unchanged (the two unseen places: same card), 0 changed since the read. 3 draft looks, 5 scene looks; the 3 looks a
  person made earlier are untouched.
- Cards: ages are numbers; every person has a gender and a distinct face (Aruni and Nimal share features); H-14 shows
  (Aruni a white nurse's dress, Inspector Ruwan police khaki with his rank, Dinu a work uniform). 2 regions, 2 sets, a
  vehicle, 2 spots under the canal, 2 unseen; the gun and Rs. 300 million `mentioned`. Colombo Garage is a place, no
  longer Scene 03's text.
- Conditions: Aruni "dress soaked by heavy rain…", Nimal "lies still near the canal gate, eyes closed…" (out of the
  outfit, as designed).
- One review line: "Nimal wears C03-1 on day 1 (E01-S03) and again on day 2 (E01-S01)". That is the story (found in
  the clothes he was last seen in): the across-a-new-day check flags it by design; a person reads it.
- Part 2 (one new build through the fork–join) waits for the person to name the production.
