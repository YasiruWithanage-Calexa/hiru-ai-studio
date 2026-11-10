# Raphael's breakdown: one request before the bin (plan/2026-11-10)

A single chat request gave the person a good director's shot breakdown of scene 1 (12 shots: withheld reveal, feet in
mud, POV, the C-17 key as the hook). Raphael gets the same thing as a new first step: **one model request per scene
writes the breakdown, then Raphael's two stages build from it** (people, props, state, Veo designs, checks, cinematic
clips). No lab: built directly, behind a switch.

## 1. Shape

```
scene pack ──> raphael_breakdown (1 request, no tools) ──> code check ──> stage 1 (must bin) ──> stage 2 (cinematic)
                                                                │
                                                 fails twice ───┴──> stage 1 as today, with a warning
```

- **What the breakdown owns:** the dramatic objective, the shot order, each shot's framing and one action, which line
  falls on which shot, what must be readable, director notes.
- **What Raphael keeps:** take lengths (4 / 6 / 8 s from the clock, never 10), handles, who speaks, people's looks,
  state, Veo design, every check. Raphael may split a breakdown shot over clips to fit the clock; it does not drop or
  reorder one.
- **The breakdown's seconds are advisory.** The `<length>` block and the checks decide.

## 2. The request

New agent `agents/raphael/raphael_breakdown`, `shape: structured` (as `stager`), middleware
`[static_first, usage, production_memory]`, same memory kinds as `raphael_planner`.

- **Input:** the message stage 1 already gets (`pack.message` + `voice_only` + `length_block`): production rules and
  people, episode synopsis, the scenes before and after, place card, the numbered script with the state ledger, the
  person's reading when there is one. So it is not "the scene alone": film-wide facts come with it.
- **Output** (`contracts/raphael/wire.py`, `BreakdownW`), English only, lines by id, never their words:

| Field | Holds |
|---|---|
| `objective` | one sentence: what the scene must do |
| `direction` | palette, camera style, lens language, sound: one short line each |
| `shots[]` | `n`, `blocks` (script block ids), `lines` (line ids), `kind` (`story` / `detail`), `size`, `lens`, `move` (Raphael's camera vocabulary), `action` (ONE action), `why`, `must_read`, `about_s` |
| `notes[]` | director notes ("she does not scream", "reveal the body gradually") |

- **Prompt** (`prompts/system.md`, short): think as the director; one action per shot; hold back a reveal; a `detail`
  shot only where it carries story; no invented story, people, lines or objects; Veo limits (the same list as
  stage 1); voice-only people are never shown; about one shot per 4 to 6 s of the target.
- **Tier** `raphael_breakdown` in `core/models.yaml`, default the same model and effort as stage 1's first turn;
  settings `OPENAI__MODEL_RAPHAEL_BREAKDOWN`, `OPENAI__EFFORT_RAPHAEL_BREAKDOWN`.
- **Money:** the call counts inside `RAPHAEL_SCENE_CAP_USD`.

## 3. Code check of the breakdown (`contracts/raphael/checks.py`, `breakdown_faults`)

Every block is in at least one shot; shots follow script order; every line id exists and sits on exactly one `story`
shot; no voice-only person in `action`; `move` is in the vocabulary; `about_s` in total is within the floor and the
stage 1 cap. On faults: one retry with the faults listed. Still failing: no breakdown, a job warning, stage 1 as today.

## 4. Into stage 1 and stage 2

- `pack.breakdown_block(b)` renders `<breakdown>`; `opening_stage1` adds it after `<length>`, `opening_stage2` adds
  the shot list only. `Planner` (systems `scene.py`) makes the breakdown before stage 1 and carries it.
- Stage 1 prompt, three lines: a `<breakdown>` when given is the director's cut, so the intended cut and the must
  clips follow its shots in its order; its `detail` shots are must clips too (this replaces "inserts are not yours"
  for those shots only); split a shot over clips when the clock needs it and say so in editor notes.
- Stage 2 prompt, one line: the breakdown's shots are already in the bin; add only what it does not have.
- New report (not blocking, so it cannot cause a stuck run): `breakdown:missing`, a breakdown shot with no must clip
  on its blocks.
- `tests/raphael/test_lab_parity.py` allows exactly the new prompt lines.

## 5. Stored and shown

- `StoredRaphael.breakdown: BreakdownW | None` in `scenes.raphael` (JSON, **no schema change**; `STORED_VERSION`
  stays 1, the field is optional). A re-plan with the same input hash reuses the stored breakdown; a changed scene
  makes a new one. `more_cinematic` reads the stored one.
- API: `/scenes/{id}/raphael` returns it with the rest.
- Interface (`src/features/raphael`): `types.ts`, `lib/map-raphael.ts`, and a read-only "Breakdown" table at the top of
  `raphael-panel.tsx` (shot, size / lens, action, line, must read). No costs. No approval step in this version.
- Switch: `RAPHAEL_BREAKDOWN` (default `true`); `false` is today's Raphael exactly.

## 6. Build order

1. `BreakdownW`, `breakdown_faults`, `pack.breakdown_block` + tests.
2. Agent `raphael_breakdown` (schema, prompt, component, eval case, test with a fake model).
3. `Planner`: make, retry, fall back, money, stored field, both openings, prompt lines, `breakdown:missing`, parity.
4. API field + interface table + panel test.
5. Docs: `docs/raphael/README.md`, `IMPLEMENTED.md` here.

All offline with fake models. The first live scene needs the person's yes, as always.

## 7. Decisions (the person's)

- **D1** Approval: runs straight through (this plan), or a person approves / edits the breakdown before the bin.
- **D2** `breakdown:missing` stays a report, or blocks `finish`.
- **D3** The breakdown's model: stage 1's first-turn model (this plan) or a stronger one, since it is one small call.
- **D4** If the breakdown reads well in live scenes, shrink stage 1's own `write_edit_plan` treatment to avoid two
  visions.
