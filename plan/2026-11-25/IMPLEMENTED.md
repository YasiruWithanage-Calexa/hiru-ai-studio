# Board hands: what is built (plan/2026-11-25)

| phase | status |
|---|---|
| A1 the side rule, the one-arm example, evals, prompt test | done 2026-11-25 (offline) |
| B0 `lab/board_hands` | run 2026-11-25, $0.451 of $0.50: NO run passes (R0-R3 catch 0/4); R4 not run (cap); see `lab/board_hands/FINDINGS.md` |
| B0+ R5/R6 blind count | run 2026-11-25, $0.344 of a new $0.40: R5 (blind, gpt-5-mini) catches 1-3 of 4, no false alarm, $0.004 a panel; R6 (gpt-5) 3/4 but 3/6 false alarms, $0.023; no form passes |
| B (the blind count, R5) | built 2026-11-25 (offline), the person's choice; see below. R1-R3 and R6 are not built |
| 5 live check | the person's |

## A1 (2026-11-25)

`src/libs/hiru_ai/agents/board_writer/prompts/system.md`, the words as built:

- **A BODY SIDE IS ALSO A SCREEN SIDE**: "someone in profile facing screen right shows their RIGHT side to the camera,
  so their right-hand things are on the near side, toward the lens, and their left-hand things on the far side,
  partly hidden by the body; someone facing screen left shows their LEFT side, so their left-hand things are on the
  near side and their right-hand things on the far side; facing the camera, their left is frame right; with their back
  to the camera, their left is frame left. Check every panel against this: a person facing screen left who holds a
  thing in the left hand holds it on the near side, never "far-side left hand"; a person facing screen right who holds
  a thing in the right hand holds it on the near side, never "far-side right hand"." The postman example is turned:
  "the satchel on his far side, mostly hidden behind his body". The waiter example is kept.
  Changed from the plan's draft (§2.2): the back-to-camera clause is added; the self-check is the two "never" phrases
  (board v21's own wrong words) instead of one sentence; the postman's words are shorter (no strap).
- **TWO HANDS** gains: "A bag on the forearm of a hand that also grips something belongs to that ONE arm: say both in
  one phrase about that arm, the grip first and the bag "over the same wrist", so the image model gives the bag no
  hand of its own." and the example "a market woman facing screen right with a parasol and a basket has "her far hand
  grips the parasol handle at her shoulder, the basket's handle hooked over the same wrist; her near hand free,
  reaching for the fruit"".

Evals: `board_writer/evals/cases.yaml` gains two recorded answers ("a left-hand thing faces the lens when the person
faces screen left", "a right-hand thing faces the lens when the person faces screen right"); other stories (a post
office veranda, a town street), not Anudi.

Tests (`board_writer/tests/test_agent_board_writer.py`): `test_a_body_side_is_turned_the_right_way` (the old sentence
and the near-side postman never come back; the new rule, the two "never" phrases and "over the same wrist" are there),
`test_the_recorded_side_answers_put_the_facing_hand_near`.

Not changed: the agent's `version` (the prompt's words only; the board pins are built from the panel words, so saved
boards are not marked stale by this). A saved board keeps its old words until **Rewrite and repaint**.

Checks: board writer tests 11 passed; `ruff` clean; `hiru_ai eval board_writer` 6/6 (offline); `hiru_ai catalog
--check` current; `hiru_ai validate` 202 parts, 0 errors; every test with "board" in its name (205) passed.

## B: the blind count (2026-11-25)

The person chose to build R5 (lab/board_hands) although it catches about half the bad panels. Built offline; the live
check (phase 5) is the person's.

- **B1, the picture detail per agent**: `AgentManifest.image_detail` (`low` | `high`, default `low`),
  `ModelCall.image_detail`, `Agent.prepare` passes it, `Agent._structured` sends it. Every agent but the counter keeps
  `low`.
- **The new agent `board_counter`** (tier `vision`, `image_detail: high`, phase `frame_render.board_count`): the lab's
  R5 words and schema, unchanged (`BLIND_SYSTEM` → `prompts/system.md`; `Count`, `Thing`, `Blind` → `schema.py`
  `Count`, `Thing`, `Output`); the user message is the lab's ("MANNEQUINS IN THIS PANEL:" and "- the <colour>
  mannequin" lines); the panel only. Line breaks of the prompt differ from the lab's string, the words do not.
- **`contracts.board.count_faults`**: the lab's code rule (more than two arms or hands; a thing `where: air`), the
  same fault words ("blue: 3 arms, 3 hands", "blue: the umbrella in the air").
- **`frame_render.board._check_panel`**: two looks, the inspector as before and the counter (only when the panel shows
  a mannequin); either may fail alone; both failed = no check, as before. `_faults` = the inspector's faults, then the
  count's. A count fault goes the built way: one repaint alone, told the fault (`fix_line`), checked again; still wrong
  = named in `conflicts`. The blocking plate's check goes through `_check_panel`, so it gets the count too.
- `frame_render/component.yaml` lists the agent; `docs/AI_CATALOG.md` regenerated; `docs/scene_board/README.md` gains
  the blind count.

Deviation from the plan: §0 said "no new agent"; the blind look needs its own prompt and schema (the expected words
must not be in the call), so it is its own agent beside `board_inspector`, which is unchanged.

Cost: about $0.004 a panel more (lab R5), plus the repaints it sends.

Tests (fakes only): `board_counter/tests` (4: the prompt never asks what should be there; the message is the colours
only and the panel only; the eval replies; `high` for the counter, `low` for the inspector);
`tests/hiru_ai/test_board_check.py` (3: a third arm the inspector passes is found by the count and painted again,
the call carries no expected words and one picture at `high`, the inspector still `low`; a clean count keeps the
panel; `_faults` with and without counts). Evals: `board_counter` 2/2 (recorded).

Checks: `ruff` clean on the changed files; `mypy` clean; `hiru_ai validate` 203 parts, 0 errors; `catalog --check`
current after regenerating; `lint_imports` 49 kept, 3 broken, none in this change (`core.camera` → `rag`, the API's
`file_cache` / `media_thumbs` → `core`, the David agents' `wire_schema`).

Full suite (2026-11-25): 6,449 passed, 29 skipped, 70 failed. The same 70 fail on a clean HEAD (checked in a
throwaway worktree, its own code imported): Raphael, David, Jonathan, Adam, Zora removal, script_split, the API's
8001 port and canon cases, three parity recordings. None is this change's.
