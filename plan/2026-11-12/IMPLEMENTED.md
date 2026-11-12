# plan/2026-11-12: what is built

## Phases 1 to 5, built offline 2026-11-12 (both repos, uncommitted, $0, no model called)

Phase 0b (the second lab) was skipped at the person's request: they test on the dashboard instead (phase 6). D2 to D5
taken as recommended: files only, safe depiction later, the cap stays the person's.

### Phase 1: house rules

- `src/libs/hiru_ai/house_rules/` holds the rule files. `implied_things.md` is H-12 v2 (the lab's text plus "close
  enough for the audience to read what it shows").
- `hiru_ai/core/house_rules.py`: `parse` (header checked: exactly id, topics, kind, why, version; id like H-12; kind
  default | must; lower-case topics; text not empty), `load` (sorted by id, unique ids), `rules()` (read once),
  `select(topics)` (`*` = all), `block(rules)` (the heading, then one line a rule).
- `hiru_ai/core/middleware/house_rules.py`: appends the block to the END of the system prompt; records "H-12 v2" on the
  run (`used(ctx)`, only after the call returns) and in the trace metadata (`house_rules`). No topic, no change.
- `ModelCall.house_topics`, `AgentManifest.house_rules`, `Agent.prepare` passes it; the middleware is registered.
- `registry._check_house_rules` (`hiru_ai validate`): a topic no rule has, or `house_rules:` without the middleware, is an
  error; a bad rule file is an error.

### Phase 2: H-12 and its subscribers

`breakdown_episode`, `breakdown_repair`, `raphael_planner`, `raphael_cinematic`: `house_rules: [objects, sound]` and the
middleware. `raphael_breakdown` keeps its own PHONE CLOSE-UPS (not on the packet path; unchanged byte for byte).
`breakdown_episode`'s prompt has one line describing the new `implied` field; the why is H-12's.

### Phase 3: the reader records implied things

- `contracts/breakdown/schema.py`: `ImpliedW {name, holder, where, blocks, why}`, `SceneBriefW.implied`.
- `contracts/breakdown/build.py`: `apply_implied` (called by `apply_episode`): a plain-noun name (`NOUN`, at most three
  words) becomes a thing: an existing thing of that name is reused (canon or an earlier scene; a refresh never doubles
  it), else a new `P` id with a card `summary` (the why) and `details` (where), both `source: inferred`. It joins the
  scene's things (`role: used`, holder only if that person is in the scene, `source: inferred`), names itself as the
  `device` of its blocks ("phone P08"), and joins their events.
- `fill.canon_cards` marks it `inferred`; `breakdown_build.graph.canon_rows` writes the canon version with
  `source: 'inferred'`; `refresh` now also adds a newly implied thing to canon (`inferred_canon`), never touching an
  entry a person has.
- **Schema v22** (`Database/upgrade_v21_to_v22.sql`, `schema_v22.sql`, `supabase/migrations/20261112090000_canon_inferred.sql`):
  `canon_versions.source` may be `inferred`. **Not applied.** Until it is, a build or refresh that infers a thing fails
  to write that canon row.

### Phase 4: the checks (report only)

- `contracts/breakdown/checks.py`: `implied` (a name that is not a plain noun was not recorded) and `devices` (a line heard
  as phone / voice_message / recording names no device among the scene's things). Both land in the packet's `I_open`,
  never in its waits.
- `contracts/raphael`: `BlockS.device` (from the packet, name only); `checks.device_unseen`: a device line with no clip on
  it or on the block before it whose picture or summary names the device; in `check_stage1` (so stage 2 too), `fix:
  report`.

### Phase 5: interface

- Canon: an `Inferred` badge (blue) when the current version's source is `inferred`; the version history says "Inferred:
  the script implies it but does not name it".
- Packet view: a thing with `source: inferred` carries an `Inferred` chip. People who can edit the script also get
  **Read the scene again** on a current packet (the existing refresh job; until now it was offered only when the script
  had changed).

### Tests

- `tests/hiru_ai/test_house_rules.py`: file checks, sort, select, the breakdown subscribers get H-12 at the end and the
  same bytes twice, a non-subscriber unchanged, a failed call records nothing, the manifest checks.
- `tests/breakdown/test_implied.py`: Scene 2 with an implied phone (gold answers + `implied`): thing, holder, device,
  events; reuse; bad holder and block; a bad name reported; the device check; canon `inferred` and a person's entry
  untouched.
- `tests/raphael/test_implied_packet.py`: the packet and Raphael's opening; both Raphael stages get H-12;
  `raphael_breakdown` unchanged (Raphael tests live in its folder: `test_isolation`, `test_removal`).
- `tests/raphael/test_checks.py` (+3): `device_unseen`. `test_removal`: `schema_v22.sql` may name Raphael (a full schema).
- Changed: `test_agents_contract` and `test_production_memory` expect the system prompt as sent
  (`house_rules.appended`), i.e. with the subscribed rules at the end.
- Interface: `packet-view.test.tsx` (+3), `map-canon.test.ts` (2).

Results 2026-11-12: backend full suite 34 failed / 5550 passed before the two test fixes above; the 6 of those that were
this plan's are fixed; the other 28 fail the same on a clean worktree of HEAD (older: parity recordings, api uploads,
removal lists, the cap-1 tests, `raphael_breakdown`'s one eval case, `test_reader_ingest`). ruff (these files), mypy,
`hiru_ai validate`, `catalog --check` clean; import contracts 51 kept, 2 broken (older). Interface: typecheck and lint
clean, these files Prettier-clean; one older test fails (`raphael-panel.test.tsx` caps without 1).

### To test on the dashboard (phase 6, the person's)

1. Apply `Database/upgrade_v21_to_v22.sql` on the hosted project.
2. Restart the backend services (structure_build and shot_planner_raphael read the new code and rule file).
3. Scene 2 → Scene tab → **Read the scene again** (one `breakdown_episode` call). The packet should list `phone ·
   used · Dinu → Dinu` with **Inferred**, the two phone lines `[voice_message, phone P..]` / `[phone, phone P..]`, and
   Canon should have **Phone** with the Inferred badge.
4. Re-plan Scene 2 with Raphael. Expect a clip showing the phone before Aruni's message and before Mudalali's call; if
   not, the plan's checks report "L.. is heard through the phone, and no clip … shows the phone".
