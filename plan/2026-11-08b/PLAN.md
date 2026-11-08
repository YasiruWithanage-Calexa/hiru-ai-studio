# Jonathan length modes: Strict (+10 %) and Guide (today) (plan/2026-11-08b)

Status: written 2026-11-08, not built. Plain words: [human-read.md](human-read.md). Planner: Shot Planner Jonathan only
(plan/2026-11-06b). Adam, David and the classic planner do not change.

## 1. Why

On *Ekama Sakshiya* (the person's 15-minute screenplay), Scene 01 says "1 MINUTE" and has one 6-word line, yet Jonathan
planned about 90 s. Reading the code (2026-11-08) found this is mostly by design, with one real gap:

| Finding | Where |
|---|---|
| The scene's headline total is the sum of **takes** (`take_s`, what Veo makes: 4, 6 or 8 s), not what the edit keeps (`use_s`). A 2 s cutaway still costs a 4 s take. | `steps/jonathan/jonathan_write/logic.py` `fit_report`: `total_s = sum(take_s)` |
| The prompt asks for many short pictures: "a minute of drama … usually holds 15 to 22 shots", "never with fewer pictures", and a budget of about **20 %** over, counted in `use_s`. | `agents/jonathan/jonathan_author/prompts/system.md` line 63; `steps/jonathan/jonathan_pack/logic.py` `time_policy` |
| **No check is about length.** The revise passes only fix what `contracts/jonathan/checks.py` finds (lines, blocks, clock, staging, holding …). An overrun is noted once, after planning, when kept time is above 120 % (`fit_report`, code `envelope`). Nothing pushes back. | `checks.py` (no length code); `logic.py:297` |

The person wants a second mode: **at most 10 % over, strictly checked, with the plan made carefully to stay inside it.**
Today's behaviour stays as the other mode.

## 2. The two modes

| | **Guide** (today, the default) | **Strict** |
|---|---|---|
| Limit | about +20 % of the scene's length, in kept seconds | **+10 %**, in kept seconds (60 s scene → 66 s kept at most) |
| Where the rule lives | the prompt and the note only | the note **and a hard fault in the checks** |
| Revise passes | only for other faults | an overrun is a fault: the existing ≤ 2 revise passes must fix it |
| Still over at the end | an `envelope` issue in `fit_report` (> 120 %) | the best plan is kept, flagged `envelope_strict` with the seconds over |
| Shot count | 15–22 a minute (the lab's rule) | whatever fits; coverage is still preferred, but the limit wins over extra cutaways |
| Under the length | allowed, never stretched | allowed, never stretched |

What does **not** change in either mode (project rules): dialogue is never trimmed; no block is dropped; code reports an
overrun and never cuts a shot itself; the lower limit does not exist (a short scene is never padded).

## 3. Decisions (the person's)

| # | Question | Recommendation |
|---|---|---|
| D1 | Which seconds the 10 % caps: **kept** (`use_s`, screen time) or **takes** (`take_s`, what Veo makes) | **Kept.** It is the scene's real length. A take cap means 12–14 shots a minute and fights the cinematic rules the lab proved. If footage cost matters, add a separate *footage* ceiling later (§9). |
| D2 | Where the mode is set | **Production setting** first (`ProductionSettings.jonathan_length`, in the existing `productions.settings` jsonb: no migration). A per-scene override needs a scene column (a schema version): later, if asked. |
| D3 | The default for new productions | **Guide** until the lab (§7) shows Strict keeps the quality. |
| D4 | The anti-gaming guard's numbers (§4.4) | at most **50 %** of shots at `use_s` 2; every arc turn keeps its full take. Tune in the lab. |
| D5 | Who may change the mode | admin only, like the other `ProductionSettings` (`Permission.MANAGE_PRODUCTION`). |

## 4. Design

### 4.1 The setting

`contracts/production.py`:

```python
jonathan_length: Literal["guide", "strict"] = "guide"   # plan/2026-11-08b
```

The limit is a constant beside it: `STRICT_OVER = 0.10`, `GUIDE_OVER = 0.20` (the guide number moves out of
`fit_report`'s literal `1.2`, so one place holds both). The scene's length stays `scenes.envelope_s` (the reader sets it
from "1 MINUTE"; the production default is 60 s).

### 4.2 The floor, before any model call

Code works out the least the scene can keep without trimming a line or dropping a block:

```
floor_s = Σ over lines   (speech seconds + LEAD_IN_S + TAIL_S)      # contracts.jonathan.scene.line_facts
        + 2 s × each action block not carried under a line           # screen != "with_line"
```

It is a lower bound, computed with the repo's one clock (`contracts.timing`, `contracts.shotplan`); nothing new is
invented. New function `contracts/jonathan/length.py: floor_s(scene) -> float`.

- `floor_s ≤ limit`: plan as normal.
- `floor_s > limit` in Strict: **no model call is saved and nothing is refused**. The plan is made with the limit raised to
  `floor_s` and the scene is flagged: "This scene needs at least 71 s without trimming a line; the strict limit is 66 s."
  The person can raise the scene's length or accept it. (The alternative, stopping, would leave a scene with no plan.)

### 4.3 The note the author reads

`steps/jonathan/jonathan_pack/logic.py` `time_policy(envelope_s, mode)`. Strict writes:

> The length is a strict limit: at most {limit} s kept (`use_s`), the scene's {envelope} s plus 10 %. This overrides
> "about 20 %" and the usual shot count: plan the coverage to fit. Keep every line whole and show every block; spend
> holds where the story turns; cut the cutaways that add least. The least this scene can keep is {floor} s. Code checks
> the total and sends an overrun back.

The system prompt (**the lab's text to the letter**) does not change, so `tests/jonathan/test_lab_parity.py` still holds
(it compares the prompt and the Guide-mode user message; Strict gets its own snapshot test). The prompt already says "If
<scene> gives a note from the owner (the length, a rule), obey it", so the note is the intended door.

### 4.4 The checks

`contracts/jonathan/length.py`, added to `checks.py`'s list **only in Strict**:

1. **`length`** (hard fault, `fix="repair"`): kept > limit. The sentence gives the reviser what it needs to choose, worked
   out by code:
   > The edit keeps 81 s; the strict limit is 66 s (15 s over). Shots with time to give (kept − the least they can keep):
   > S03 4 s, S07 2 s, S11 2 s, S14 4 s … Shots that may go (an added cutaway, no block): S05, S09. Never trim a line.

   Key `length:strict` (stable across rounds, so the stabiliser sees one problem getting smaller, not new ones).
2. **`pace`** (craft gap, the anti-gaming guard, D4): more than half the shots at `use_s` 2, or an arc turn's shot
   (`treatment.arc`) keeping less than its take. Without it, the cheapest fix is every `use_s` set to 2: the check passes
   and the edit is choppy.

Score stays `(faults, gaps)`. A pass that removes the overrun but breaks a hand-over (`holding`) or a line has the same
fault count and is not kept: the stabiliser's rule already protects the other checks.

### 4.5 Revise

No change to `Planner.stabilise` or `MAX_REVISES` (2). The overrun is one more fault in `best.faults`, so the existing
loop sends it. The revise message is the lab's; the length sentence carries the numbers. If two passes do not land it,
the best plan is kept (§2).

### 4.6 What is stored and reported

- `fit_report` gains `mode`, `limit_s`, `floor_s` and, in Strict, issue `envelope_strict` (kept > limit after revise) or
  `floor_over` (§4.2). `total_s` stays the sum of takes (other screens read it); `use_s` is already there.
- `scenes.jonathan.report` keeps the passes as today; each length pass shows before/after kept seconds.
- The delivery's notes (`systems/jonathan/jonathan_shot_planner/graph.py` line ~313) also collect `envelope_strict` and
  `floor_over`.

### 4.7 The interface (`hiru-ai-studio-interface`)

- **Production settings** (admin): a two-choice control "Jonathan length: Guide (about +20 %) / Strict (+10 %)".
  `features/productions/lib/map-production.ts` maps `jonathan_length`.
- **Jonathan tab** (`features/jonathan/components/jonathan-treatment.tsx`): beside "X s kept of Y s" a chip
  `Strict · limit 66 s` or `Guide · about 72 s`; red `<Chip>` when over, with the sentence; a soft note when the floor
  is above the limit. Seconds only: **no costs** (interface CLAUDE.md).
- "Y s of takes" stays visible so the person can see footage against kept time (the source of the 90 s question).

## 5. Phases

| # | What | Model calls |
|---|---|---|
| 0 | **Lab** (§7): Strict as a note + check on the lab's scenes and *Ekama Sakshiya* S01–S03, against Guide. Decides D3, D4. | yes: the person's yes, budget §7 |
| 1 | `length.py`: `floor_s`, the `length` and `pace` checks, constants; unit tests on gold scenes (the gold plan stays 0 faults in Guide). | none |
| 2 | Setting + pack note (`time_policy` with mode); parity test unchanged, Strict snapshot test added. | none |
| 3 | Wire into `checks.py` (Strict only), `fit_report`, delivery notes; system tests with fakes (a fake reviser that cuts S05 → kept under the limit → 1 revise). | none |
| 4 | Interface: setting control, tab chip, mapping, tests. | none |
| 5 | Live trial on the person's production, Strict on, one episode. | yes: the person's |

Checks before finishing (backend): `ruff check src tests scripts`, `mypy`, `scripts/lint_imports.py`, `hiru_ai validate`,
`hiru_ai catalog --check`, `pytest -q`. Interface: `npx next typegen && npm run check && npm run format:check`.

## 6. Tests

- `floor_s` on a dialogue-heavy gold scene > its length → `floor_over`, plan still made.
- Strict, plan at 81 s kept / 66 s limit → one `length` fault naming the shots with time to give.
- A revise that sets every `use_s` to 2 → `pace` gap → not better than a balanced plan at the same fault count.
- A revise that fixes length but drops a hand-over → not kept (score rule).
- Guide mode: every existing Jonathan test and the lab parity test unchanged; the gold plan still makes exactly one call.

## 7. The lab (phase 0, before building)

The person's rule: prove it small, with a hard budget, on their sample. The model is `gpt-6.1-sol` (Jonathan's), high effort.

- Scenes: *Ekama Sakshiya* S01 (60 s, 1 line), S02 (90 s), S03 (120 s, dialogue) + 2 of the lab's five scenes.
- Each scene: Guide once, Strict once (author + up to 2 revises). About 10 plans, ≤ 30 calls.
- **Budget: $5 hard stop** (the run stops before a call that would pass it). Starts only on the person's yes.
- Measured: kept s, take s, shots, revise passes used, faults/gaps left, lines kept whole (must be 100 %), and a
  **blind read** of Guide vs Strict by the person.
- Gate for D3: Strict lands within +10 % on every scene whose floor allows it, in ≤ 2 revises, and the blind read does not
  prefer Guide on more than one scene.

## 8. Risks

| Risk | Answer |
|---|---|
| The cheap fix (every cutaway 2 s, choppy) | `pace` gap (§4.4), tuned in the lab |
| More revise calls a scene (length becomes the commonest fault) | measured in the lab; the cap stays 2 passes |
| A shorter plan breaks continuity (props, hand-overs) | the other checks still run; a pass that adds a fault is not kept |
| The model weighs the lab prompt's "15–22 shots" over the note | the note says it overrides; the hard check catches what it misses |
| A dialogue-heavy scene cannot fit | the floor says so before planning, and the flag names the seconds |

## 9. Not in this plan

A footage (take) ceiling; a per-scene override (needs a schema version); Strict for Adam or David; changing the lab's
system prompt.
