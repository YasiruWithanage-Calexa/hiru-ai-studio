# 0010. One author per creative unit, code checks, narrow repair

Status: accepted (2026-11-05, plan/2026-11-05e; the person agreed in the conversation that produced the plan).

**Context.** One ChatGPT message planned a scene as well as Adam's whole pipeline (100 % against 92.2 % on Adam's own
score), and slightly better. Adam takes about twelve model calls a scene; five gpt-5 agents each re-read the scene and the
previous agent's JSON, 69 % of the bill is hidden reasoning, intent is lost between agents ("held stillness as she goes"),
and the camera is designed twice (Adam's cards, then the shot producer's DoP and critic). Three live runs "passed every
code check and got worse" ([plan/2026-11-04c §1](../../plan/2026-11-04c/PLAN.md)). What makes Adam safe is code, not stages.

**Decision.** Systems follow [the Hiru AI pattern](../AI_PATTERN.md): one strong-model author call per creative unit that
returns its work and an end state; code checks facts and mends what it can; the same model repairs only the exact problems
it is shown, with a patch, at most twice, then the rest is reported; the end state goes back to memory for the next unit.
Eight rules; the last says a quality problem is fixed in the prompt, the pack or a code check, never by adding an agent.

**Consequences.** Shot Planner David is the first system built this way, beside the classic planner and Adam, which do not
change. A system that wants a second call has to say which of rule 2's four reasons it meets. A new stage is accepted only
after a blind comparison on at least five real scenes. Adam and the classic planner's model calls are retired by a later
plan if David passes its gate, not by this one.
