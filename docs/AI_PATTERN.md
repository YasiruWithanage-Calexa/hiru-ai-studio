# The Hiru AI pattern

Source: [plan/2026-11-05e §2](../plan/2026-11-05e/PLAN.md). Decision: [ADR 0010](adr/0010-one-author-pattern.md). Shot Planner
David ([docs/david/README.md](david/README.md)) is the first system built on it. Every later system follows it; a system that
breaks a rule says which rule and why in its plan.

```
          MEMORY (database; written by code or a person): canon cards · looks · production rules · state from before
                                            │  code builds the CONTEXT PACK (no model)
                                            ▼
 ① AUTHOR   one call, strong model: writes the WHOLE creative unit, small format + free text + END STATE
                                            ▼
 ② CHECK    code: pass or fail, each failure an exact sentence
                                            ▼
 ③ MEND     code fixes what code can (split a crowded shot, renumber, pick the take length)
                                            ▼
 ④ REPAIR   only what code cannot: the same strong model gets the exact problems and the shots involved,
            answers with a PATCH; code checks the whole plan again; at most 2 rounds, then it is REPORTED
                                            ▼
 ⑤ SAVE     plan + END STATE back to memory; a person reviews; their change is a card they accept
```

## The eight rules

1. **One author per creative unit.** A creative unit is the smallest thing that must be imagined as a whole: a scene's
   shots, or one document's story. One call does all of its thinking. No role-play stages.
2. **A second call is allowed only when:** (a) the input does not fit in one call; (b) the step needs a different kind
   of input (an image); (c) many later calls reuse the result (the canon); (d) independent units run at once (scenes,
   episodes). "Another specialist's view" is not a reason. *Exception, if a spike asks for it:* a small model may
   change a free-text answer into the format, because code can check that it changed nothing.
3. **Code judges facts; people judge taste.** No model critic can block a plan. No code score chooses between two
   creative versions.
4. **Repair, don't redo.** Code first, then the same strong model with the exact problem. A small model never reviews or
   fixes the big model's creative work.
5. **Memory in, state out.** Code builds every call's input from the database. Every author call returns an end state
   (who is where, wearing what, holding what; the time and the light) for the next unit.
6. **Small output format.** A field exists only if code or the interface reads it. Creative content stays free text.
   The model writes its notes first and the fields after.
7. **Agent loops with tools only where a person leads** (director chat, search). Production jobs are straight calls.
8. **One path per job, proven on real scenes.** To add a stage or an agent, it must beat the simpler version in a blind
   test on at least 5 real Hiru scenes, judged by a director. **A quality problem is fixed first in the prompt, the
   context pack or a code check, never by adding an agent.**

## Call budget per job

A job that would go over its budget reports it and does not spend more.

| Job | Model calls |
|---|---|
| Shot plan + camera design for one scene (David) | 1 author + at most 2 repairs |
| A seam between two linked scenes | at most 1 repair |
| Director chat message | 1 agent with tools, at most 6 tool calls (a later plan) |

## How a system follows it

| Step | In David | Where |
|---|---|---|
| context pack | `david_pack` | `steps/david/david_pack` |
| author | `david_author` | `agents/david/david_author` |
| check | `david_check` | `steps/david/david_check` |
| mend | `david_mend` | `steps/david/david_mend` |
| repair | `david_repair` | `agents/david/david_repair` |
| save | `david_write` | `steps/david/david_write` |
| end state | `end_state` in the author's answer, checked against the scene's own shots | `contracts/david/wire.py` |
