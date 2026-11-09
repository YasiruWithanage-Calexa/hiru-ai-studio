# Sable edits the open scene: shots, notes and state, pointed at with @ (plan/2026-11-09b)

Status (2026-11-09): **phases 0-6 built offline, uncommitted; phase 7 (the live check) is the person's.** The person asked
for it on 2026-11-09 ("Sable can create, update and delete shots as the user asks: change the car type; Kamal is dead so
he should be lying; point and click with @") and set the boundary: **Sable changes the scene that is open, never the rest
of the production, but it knows what happens outside it.** No phase here calls a model until phase 7, and phase 7 needs
the person's yes and a budget. See "Built" at the end for what landed where and what differs from the text above.

## In plain words

Sable can already *propose* a shot-list change as a card a person accepts (`change_propose`, plan/2026-11-08). Three
things stop it doing what the person asked:

1. Its prompt only lets it propose an operation "the person spelled out"; anything else becomes a handoff.
2. Its operations only reach the **shot list** (framing, length, title, sound, beat lines, add / remove / split / merge).
   "Change the car" and "Kamal is dead, lying" live in what the **prompt** is written from: a shot's DoP note and the
   scene's **state ledger** (`scenes.staging`, plan/2026-11-09). Neither is open to Sable, and the ledger is not open
   to a person either (plan/2026-11-09 D5 left `PUT /staging` for later).
3. It can stage a card for *any* scene (`change_propose` takes a `scene` argument), and a person cannot point at a shot
   or a person; Sable has to guess which "S4" or which "Kamal" was meant.

The fix keeps the rule that a model never writes: **Sable stages, a person accepts, code applies.** It adds the two
missing levels (shot note, scene state), pins every card to the open scene in code, and gives the composer an @ picker
whose chips carry ids.

```
 composer  "@S04 make the car a white van"   "@Kamal is dead from @b12, he lies there"   "delete @S06"
     │  refs [{shot S04 id}]                     refs [{person Kamal id}, {block 12}]        refs [{shot S06 id}]
     ▼
 Sable (reads the whole production) ──► stages ONLY for the open scene ──► card ──► person Accept ──► code applies
                                          │                                                            │
                     shot list ops ───────┤  change_propose (exists)                       director applier (exists)
                     shot note ───────────┤  dop_note.set  (exists in the kernel, person-only today)   │
                     scene state ─────────┘  state_propose (new) ─────────────────► scenes.staging, by: "person"
                                                                                                        ▼
                                                     prompts / frames of the touched shots are marked out of date
```

## 1. What is already there (reuse, do not rebuild)

| Part | Where | What it gives |
|---|---|---|
| Card staging + kernel trial | `tools/change_propose`, `core/trial.py` (`BY = "conductor"`) | an op list tried on a copy; a card only if every op lands |
| Shot-list ops | `steps/scene_kernel/logic.py` `MODEL_OPS`, `views.ToolOp` | set (framing, sound_mode, title), retime, split, merge, regroup, set_join, beat.set (camera, director_line, action), insert, remove |
| Person-only marks | same, `MARK_OPS` / `PERSON_ONLY` | `dop_note.set`, `canon.add/remove`, `check.waive/restore`: refused unless `by="you"` |
| DoP note reaches the prompt | `steps/serialize/shots.py` ("DIRECTOR'S NOTE FOR THE DoP … follow it") | a per-shot instruction the prompt writer obeys |
| State ledger | `contracts/stagemap.py` (`Mark.posture`, `condition`, hands; `POSTURES`), `scenes.staging`, `steps/scene_prep.staging_for` keeps a map `by: "person"` | where people are and how they stand, block by block |
| Ledger checks | `contracts/raphael/checks.py` (a lying person on their feet, …) | report-only verification after the change |
| Accept path | `api/routers/sable.py` `accept` → `director_service.ChoiceApplier`, approved scene refused, audit row | code applies a card; no model |
| Scene in view | `SableTurnPayload.scene_id`, `tooling.scene_in_scope` | the open scene, checked inside the production |
| Scene looks | `api/routers/scene_looks.py` | a scene can pick one ready look of a canon entity |

## 2. Decisions

| # | Question | Recommended | Why |
|---|---|---|---|
| D1 | What may Sable change? | **The open scene only** (the person's rule). Reads stay production-wide | taken |
| D2 | Where does "change the car" / "Kamal lying" go? | **Shot note** (`dop_note.set`) for one shot's look; **state ledger** for a fact that holds from a block on. No direct `ir` edit | `ir` and `design` are rewritten by the planners and the shot producer; a note and a `by: "person"` ledger survive a re-design |
| D3 | `dop_note.set` is person-only. May Sable stage it? | **Yes, as a card only.** Tried with a stage-only author; applied as the person's own words on Accept. Script, cast and check ops stay refused | accepting the card IS the person's words; nothing lands without it |
| D4 | A whole-scene change ("the car is a white van in every shot of this scene") | **One note per shot that shows it**, in one card. If the car has a ready look, Sable may propose the scene look instead (later phase, D9) | stays inside the scene; never touches the canon card |
| D5 | Locked fields (a length or field a person set) | **Respect locks**: the kernel refuses; Sable says it is locked and how to unlock | a person's choice is never undone by a chat |
| D6 | Who accepts | **Unchanged**: `Permission.DIRECT` | plan/2026-11-08 D8 |
| D7 | Ops per card | **8 → 12** | a note on each shot of a scene; still far under the kernel's 40 |
| D8 | Undo after Accept | **Later plan** | the director applier's undo is per turn; a card-level undo needs its own design |
| D9 | Sable proposes a scene look | **Later plan**, after phase 7 shows it is wanted | small, but a second card kind |
| D10 | Does the open scene come from the page or from an @? | **The page.** An @ to another scene is for reading; a change there is a handoff ("open E1S5 with …") | the boundary is visible: what you look at is what can change |

## 3. Phases

Each phase is offline, tested, and leaves the product working. Order: 0 → 1 → 2 → 3 → 4 → 5 → 6 → 7.

### Phase 0: the boundary in code ($0)

- `change_propose`: drop the `scene` argument for Sable runs. A run with `ctx.scene_id` stages only for that scene; a run
  with none raises `ToolRefused("Open the scene first: I can only change the scene that is open.")`. Other callers
  (director chat) keep the argument; the restriction is a `RunContext` flag `stage_scene_only`, set by Sable's turn.
- `turn.guard`: drop any staged card whose `scene_id` is not `req.scene_id` (belt and braces), and log it.
- Prompt (`sable_agent/prompts/system.md`): "you change only the open scene ({scene}); you read everything". With no
  scene open: answer, propose nothing, say "open the scene and ask again".
- Tests: a card for another scene is refused at the tool and dropped at the guard; no scene → no card; reads of other
  scenes still work.

### Phase 1: shot list as the person asks ($0)

- Prompt: Sable proposes add / delete / split / merge / retime / framing / title / sound / beat-line changes from a
  plain request ("delete S06", "add a close-up of her hands after S03", "make S02 a wide"), trying with `plan_try`
  first. The handoff stays only for "re-plan / re-cover the scene".
- `change_propose` `max_length` 8 → 12 (D7).
- `_card` currently drops a card whose op refers to a shot made in the same batch (`pin` → None). Pin new shots by their
  trial handle so "insert, then set its framing" survives as one card.
- Eval cases (`sable_agent/evals/cases.yaml`): delete, insert, framing, retime, locked length refused, approved scene.

### Phase 2: the shot note ($0)

- `core/trial.py`: an author `stage` the kernel treats like `you` for `dop_note.set` only (`PERSON_ONLY` check), so
  the trial confirms the note lands; the stored op carries no author and the accept path applies it as the person.
- `change_propose` guide + prompt: "a change to what a shot shows (a car, a costume, a prop, how a person lies) that the
  shot list cannot say is a DoP note on that shot". Sable writes the note in plain English, never dialogue.
- Card shows the note before / after for each shot.
- Tests: note staged and applied; script / cast / check ops still refused; a note over 600 characters refused.

### Phase 3: the scene state ($0)

- New op family in `contracts/stagemap.py`: `state.set {who, from_block, posture?, condition?, zone?, facing?}`;
  `validate` rejects an unknown person, a block outside the scene, a posture not in `POSTURES`.
- New tool `tools/sable/state_propose` (Sable only, `effect: stage`): reads the ledger, applies the marks to a copy,
  runs the free ledger checks (`checks.py` posture / presence) and stages a `kind: "state"` card listing the shots
  whose opening or closing state changes. Same scene-only rule as phase 0.
- Accept: `api/routers/sable.py` handles `sable_state`: merges the marks into `scenes.staging`, sets `by: "person"`
  (so `staging_for` keeps it on the next plan), audit row `sable.accept_state`. An approved scene is refused.
- Contract `StagedState` beside `StagedChange` in `contracts/sable/events.py`.
- Tests: the plan/2026-11-09 fixture `staging_body.json` (Nimal lying, dead) as the gold case; "Kamal is dead from b12"
  produces marks from b12 on; the posture check reports a later shot that still has him standing.

### Phase 4: @ references in the API ($0)

- `SableTurnRequest.refs: list[Ref]` (max 12), `Ref = {kind: scene|shot|person|prop|place|block, id, label}`.
- API checks every id is in this production (404 otherwise); a `shot` or `block` ref outside the open scene is kept for
  reading and marked `outside: true`.
- The turn gives the agent a `MENTIONED:` section ("S04 = shot <id> in E1S2 (open); Kamal = person KML") so tools are
  called with the right ids and nothing is guessed.
- `GET …/sable/mentions?q=&scene_id=`: the picker's list (the open scene's shots and blocks first, then its cast and
  places, then other scenes), names only, no model.

### Phase 5: the interface (`hiru-ai-studio-interface`, $0)

- `features/sable/components/mention-picker.tsx`: typing `@` in Sable's composer opens the list from phase 4; a pick
  inserts a chip (`Chip`) that carries the ref; chips are sent as `refs`. Built on the existing shadcn `Command` /
  `Popover` (add with `npx shadcn@latest add command popover` if absent, re-themed).
- "Ask Sable" on a shot card, a canon entity in the scene canon panel and a person on the StagingMap: opens the Sable
  sheet with the chip already in the composer.
- Cards: `sable_change` shows each op in words and the note before / after; `sable_state` shows who, from which block,
  and the shots it touches. Accept / Dismiss as today.
- After Accept: update the open scene through `features/scenes/queries.ts` (put the returned view in the cache when the
  API returns one, otherwise invalidate the scene's key from `lib/query/keys.ts`). No `router.refresh()`.
- Tests: picker keyboard flow, chip → refs, card rendering, cache update after Accept.

### Phase 6: out-of-date media ($0)

- Accept returns the shots whose prompt or frames were made from the old version (`ripple.touched` + the shots whose
  ledger state changed); the shot workspace already shows a stale chip for a changed shot; check it fires for a note
  and a ledger change, add it where it does not. Nothing regenerates by itself.

### Phase 7: the live check (needs the person's yes and a budget, ~$1)

- On the person's sample scene: the three requests the person named (car type on one shot, Kamal dead and lying, delete
  a shot) plus add a shot and a request for another scene (expect a handoff, no card). Read the cards; accept them on a
  dev copy; regenerate one prompt to see the note and the posture in it.

## 4. Out of scope

Changing the script or dialogue (Script page / scene chat), canon cards (canon page), other scenes (handoff), direct
`ir` / `design` edits, card undo (D8), scene looks (D9). Zora is untouched (plan/2026-11-08 rule).

## 5. Built (2026-11-09, offline, uncommitted)

Backend (`hiru-ai-studio`), tests in `tests/sable/test_scene_edits.py`, `test_scene_state.py`, `test_api.py`:

- **Phase 0.** `RunContext.stage_scene_only`, set by Sable's turn. `core/trial.run` (so `plan_try` and `change_propose`
  both) refuses with no scene open ("Open the scene first…") and for any scene but the open one (handoff route). The
  `scene` argument stays in the schema (the director chat uses it) and is checked, not dropped. `turn.guard` drops a card
  whose `scene_id` is not the open scene and notes it in `meta.guard`.
- **Phase 1.** `change_propose` takes 12 operations. The plan's "pin new shots by their trial handle" turned out to be
  moot: the kernel addresses shots by their number *before* the batch, so an operation cannot name a shot made in the same
  card (`pin` never sees a `new…` handle). A new shot's framing and description ride on the `insert` itself. Prompt rewritten;
  five scripted eval cases use `plan_try` (a staged card makes the turn draft again on the deep tier, which a one-queue script
  cannot show; the cards are tested in `test_scene_edits.py`).
- **Phase 2.** Trial author `stage` (`logic.STAGE`): may try `dop_note.set` only, over 600 characters refused; everything
  else a person alone makes stays refused. The card carries `notes: [{shot, before, after}]`; Accept applies it as the
  person (the director applier already does).
- **Phase 3.** `stagemap.StateMark`, `apply_state`, `changed_blocks`; tool `sable_state_propose` (named `sable_…` because a
  tool of the sable group must be: validate); card `sable_state` (`StagedState`, with `script_version`). Accept merges the
  marks as `by: "person"`, refuses a changed script, an approved scene, a person or spot not in the scene; audit
  `sable.accept_state`. A dead or unconscious person with no posture lies and later marks cannot stand them up or walk
  them off. The report-only check (`in_doubt`) reuses Raphael's `NOT_WITH` and alive-word rules on the touched shots' own
  words (`checks.alive_word` made public).
- **Agent cap.** 21 shared + 4 own tools = 25 > the old ceiling of 24, so `MAX_TOOLS_WIDE` and the manifest's `le` moved
  24 → 25. Alternative if that is not wanted: drop one tool from Sable.
- **Phase 4.** `SableTurnRequest.refs` (max 12) → `SableTurnPayload.mentions` (resolved by the API; 404 for a thing not in
  this production; `outside` for another scene's shot, block or scene) → `<mentioned>` in the agent's message. `GET
  …/sable/mentions?q=&scene_id=`. A block names no dialogue (who speaks only), so no spoken line is copied outside a tool.
- **Phase 6.** Accept moves the `version` of every shot a note or a state change touches, so what was made from it reads
  "The shot changed" (the existing reason text; a new one would need the frontend's copy to move too). Nothing regenerates.

Interface (`hiru-ai-studio-interface`): `sable_state` card and note before/after; `@` in Sable's composer through the
thread's existing mention popover (rows read once per scene from `…/mentions`), the picked ids kept beside the text and sent
as `refs` only while `@label` is still in it, shown as "Pointing at" chips; `AskSableButton` on each shot in the shots list,
each canon card of the scene and each person on the staging map (opens the sheet with the thing already in the box);
after Accept the card's scene's `scene` and `sceneProduction` queries are invalidated by key
(`useInvalidateScene`), and `useRefreshPage()` stays for the screens the server still draws (the Director page).

Open: phase 7; D8 (undo), D9 (scene look) are still later plans; whether the 25-tool ceiling stays.
