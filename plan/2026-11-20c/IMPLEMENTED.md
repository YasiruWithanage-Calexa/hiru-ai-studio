# plan/2026-11-20c: what is built (2026-11-20)

Phases 0–6 are built offline in both repos, uncommitted. Phase 7 is built as far as code goes (the §6.1 prompt line
and gate); its lab run is paid. Phase 8 is paid. No model was called: every test ran with `OPENAI__API_KEY=` blank.
**No switch (the person, 2026-11-20, replacing D17):** the Camera agent runs wherever a model can be called. With no
key it cannot run, and the rule camera stands (D10's fallback), as before.

## Phase 0: what reads the camera today (read-only)

**"Recommend settings for all shots" for Raphael shots.** `POST …/scenes/{id}/design` starts `shot_producer` in mode
`design`. A Raphael shot's design is pinned by `raphael_write`, so `design_stale` is empty and the job does nothing
for it, unless the person presses "again" (`force`). Then the DoP (`shot_writer` through the `shot_review` panel)
rewrites the IR and the recommendation of every shot, `planner: "model"`, and Raphael's IR is lost. The workspace
button sends no `force`; the batch dialog's "again" does.

**Who reads `design.recommended`, `CAMERA_OPTIONS` or the five moves:**

| Reader | What it does | After this plan |
|---|---|---|
| `api/services/production.scene_states` | `CameraSettings.model_validate(design.recommended)`, + `camera_overrides` | old words map (D6) |
| `api/routers/production` | `CameraView`, `storyboard_note`, `PATCH …/camera` (`CameraUpdate`) | + `agent` view, `camera_language`, trigger in the note |
| `steps/frame_compose` (+ `services/frame_render` copy) | the frame brief from the panel; `default_camera` fallback | opens on `opens_on` (D14) |
| `contracts/frame_brief` | `camera_words(still=True)`, `nearest_option` over the lens/stop lists | wider lists; agent's opening |
| `contracts/camera_words` | every prompt's camera words; `"Static"` / `"Handheld"` special cases | rewritten (D13) |
| `steps/serialize` (`shots.recommendation`, `logic`, `schema`, `card`) + `services/shot_producer` copy | the DoP's enum, `"Static"` speed rule, the old prompt's camera | `is_hold`; DoP enum = the eight core fields |
| `steps/video_prompt` (`facts.locked_off`, the locked-off gate, the Camera section) | the agent wrote the camera | code's sentence (D13) |
| `contracts/staging` | coverage variety (same lens + movement + angle) | unchanged (labels compare equal) |
| `steps/memory_conflicts` | lens list for "the panel has no such lens" | wider list (fewer conflicts) |
| `steps/raphael/raphael_write.camera_hint` | `move_of` → 5 moves, else `Static` | only with the switch off (see deviation 1) |
| `contracts/coverage/scene` (Zora/Sable rows) | `ir.cinematography.movement` (the planner's words), not the panel | unchanged: follow-up below |
| `contracts/costs` `designed` | counts designed shots for the scene cost | unchanged |
| interface `camera-options.ts`, `camera-section.tsx`, `camera-settings-card.tsx`, `lib/prompt.ts`, mocks | the panel | mirrored (phase 6) |
| Adam / David / Jonathan / DaVinci | own `camera_hint`s | left alone (Only Raphael stays) |

**Old values in the live data (counts only).** Not read: this chat has no database access. The query, read-only:

```sql
select design->'recommended'->>'movement' as move, count(*) from shots group by 1 order by 2 desc;
select camera_overrides->>'movement' as move, count(*) from shots where camera_overrides ? 'movement' group by 1;
```

Every old value ("Static", "Dolly in", "Dolly out", "Pan", "Handheld") validates through `contracts.camera.normalise`.

## Phases 1–6: where things are

- **1 Catalogue.** `contracts/camera.py`: 51 moves (slug, label, family, KB term, Omni status, least length, fast,
  prompt words), 15 supports, speeds, 11 sizes, 8 angles, 8 heights (+ shoulder, §6.1), 13 lenses, 6 stops, focus,
  composition, time, axis; the old-value map; the KB mapping (`OWN`, `VARIANT`, `FOCUS_TERM`); the Omni table and its
  brief. `contracts/producer.py`: `CameraField` + `support/height/focus/composition/time` (optional, "" = not set),
  `CAMERA_OPTIONS` built from the catalogue, `CORE_FIELDS`, `is_hold`, `storyboard_note(camera, trigger)`.
  `contracts/camera_words.py` rewritten (`move_phrase`, `sentence_from_fields`, `camera_line`, no gear).
- **2 Agent.** `agents/camera_agent/` (manifest, `system.md` = lab run 4 + §6.1 + D15 + one-clip mode, schema with
  the Literals spelled out and held equal to the catalogue by a test, 5 evals from the lab's answers). Tier
  `camera_agent` (gpt-6.1-sol, medium, 180 s, 1 retry); the caller caps output at 16,000.
- **3 Step.** `steps/camera_design/` (`facts`, `brief`, `kb`, `gates`, `merge`, `words`, `step`); fixture: lab run 4
  (18 clips) and the connected run (22), both pass the gates; one good/bad pair per gate.
- **4 Wiring.** `core/camera.py` is the one door (brief → call → gates → ONE repair → merge; D10 fallback per clip).
  (a) Raphael: the write and the camera call run in the worker thread, so scenes are designed side by side.
  (b) `core/coverage_rows.finish_designs`: the clips a save changed, ONE one-shot call. (c) the design job: shots
  with a planner's IR go to the agent (IR kept and refitted), the rest to the DoP. (d) `POST …/shots/{id}/camera/ask`
  → mode `camera_ask`. No switch (D17 dropped). Estimates `camera` $0.10 and `camera_ask` $0.04 in
  `UNSEEDED_PRICES` (D18; no migration).
- **5 Downstream.** `video_prompt`: the Camera section is code's sentence (the agent's while no camera field changed,
  else `sentence_from_fields`); `locked_off` reads the panel; the locked-off gate is gone; `video_prompter` no longer
  has a `camera` field or rule. Frame brief: opens on `opens_on` with the design's lens, angle, height, composition.
  Tile note: "35mm · slow push, then hold on L4".
- **6 Interface.** `camera-options.ts` mirrors the catalogue (+ `CAMERA_GROUPS`, `isHold`, old-word mapping); the
  workspace's camera section is grouped (Move & timing · Lens & focus · Angle & height · Composition), shows the
  agent's why, timing and sentence (or why it could not design), the scene's camera language, and an **Ask Camera**
  box (a job through the workspace's `run`, read back into the cache; no `router.refresh()`). A hold reads "Hold",
  never "Static". The older Production panel card gets the same values.

## Deviations from the plan (decide or accept)

1. **D17 dropped (the person's choice).** No `CAMERA_AGENT__ENABLED`: the agent runs whenever a model can be
   called. `camera_hint` (D12) is used only when no model can be called, to seed the rule camera Raphael's shots get
   then.
2. **D11 (a) timing.** The plan says "before `raphael_write`". `raphael_write` is pure, so the call runs right after
   it on its rows and before they are saved. The result is the same, and it runs in the scene's worker.
3. **One-shot mode takes several slates** (`Input.focus`), so a chat turn that changes three clips is one call.
4. **Last frame (D14).** Nothing paints a last frame today; `lands_on` is stored for when one does.
5. **§6.1 gate as written is weak.** The connected run had 21 of 22 clips at eye level (one insert slightly high)
   and passes "not every clip". Consider a share ("at most two in three at eye level") in phase 7.

## Open for the person

- Q1–Q4 of the plan (fallback, effort, rollout, the moving scene).
- **Zora's $0.02 turn cap.** A Zora or Sable save that changes a clip's IR now makes a Camera agent call (~$0.04),
  counted in the turn's spend but not refused by its budget. Keep it, or design those clips at the next "Recommend
  settings" instead?
- **Zora's rows** still print the planner's movement words (`ir.cinematography.movement`), not the agent's move.
- Phase 7 lab (paid): run `lab/camera_agent` with the §6.1 line on S04 + S01, and a moving scene (Q4).
- Phase 8 (paid): the product's Raphael → Camera agent on S04 and a moving scene; 3 Omni takes with the first frame.
- Before the first live run: the knowledge base's ideas need `craft_techniques` indexed with embeddings (they are
  absent-safe: no index, no ideas, the menu still goes).

## Tests

Backend (offline): the agent (8), the step (34), the system with a scripted model (8), Raphael wiring (1), the row
kernel (3), the API (3 new + 1 updated), video prompt / prompter updated for D13. Interface: `camera-section.test.tsx`
(6) and one matcher made exact (`/^35mm$/`, since "135mm" now exists). Failures that are not this plan's are listed in
the chat's report (the `.env` switches, the files URL port, the Raphael panel's cap list).

## Full backend suite (2026-11-20, a clean worktree with no `.env`)

Baseline (HEAD): 53 failed. With this plan: the same failures and no new ones, after these updates. The catalog
wording changed on purpose ("Static" → "Hold", "Dolly in" → "Push in", the wider lens list), so those tests were
updated. Nine parity fixtures were re-recorded; their only differences are those words, the new optional camera fields
(stored as ""), and the hold line in the frame and prompt text. `docs/AI_CATALOG.md` was regenerated. The Raphael
isolation test caught `usable_packet` ("sable") in Raphael's graph, so the lookup moved to `core/camera.packet_of`.
In the person's own tree, the `.env` (`RAPHAEL_LINE_PARTS`, `RAPHAEL_PACKET`, the files URL port) fails further tests
on clean HEAD as well.
