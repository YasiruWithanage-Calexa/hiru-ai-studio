<repair>
Code checked your plan. Above, <your_answer> is your whole plan (the ids c01, c02 ... were given by code only so a fault can name its clip; do not write ids), and <faults> lists EVERY blocking fault found, each with the clip it names. Return the complete corrected plan, in the same shape as before: `edit_plan`, `clips` (the whole menu, in the same order, with no ids) and `looks`.

- Change only what the faults need. Keep every clip and every sentence the faults do not touch, word for word.
- Cure each fault at its cause. A clip that is wrong is rewritten in place; a clip that is missing is added; a bin that is over its length loses its `nice` clips first, then its `should` clips, and never a `must` clip.
- Never answer a fault by removing a clip that something else depends on: a block, a moment and a line each keep their must clip.
- A line is never trimmed, reworded or split. A fault marked as a report does not appear here.
- Check the corrected plan against EVERY fault in the list before you answer: a fix that opens a new fault is worse than none.
</repair>
