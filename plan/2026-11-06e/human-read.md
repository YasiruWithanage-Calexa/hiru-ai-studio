# Zora, the new director chat, in plain words (plan/2026-11-06e)

## The problem

The director chat we have today was copied from an early version of PromptMotion's chat in October. It can change a
scene's shot list: make S03 a close-up, split a shot, add a reaction.

Two things happened since:

1. **PromptMotion's Nova chat got much better** (eight rounds of fixes, W1 to W8). It learned to say exactly what it
   changed, to notice when it changed nothing, to check that what you asked for really happened, to offer a rebuild
   instead of wrecking a plan, and to give you options you can use with one click. Our chat has none of that.
2. **Our scenes are now planned by Jonathan**, with a treatment (logline, arc, approach, colours, geography, key image),
   sequences, and shots with lens, angle and a reason. **The chat cannot see any of it.** It edits the shot rows, and the
   Jonathan plan is left out of date.

## The idea

A new chat, **Zora**. It is Nova's chat copied and changed for Hiru:

- It works on **Jonathan's whole plan**: treatment, sequences, shots, who stands where, how the scene ends.
- You can ask at any level: "make the approach colder", "her reaction before his line", "S03 on an 85 mm", "two ways to
  open the scene".
- **Code does the bookkeeping, one strong model does the creative work.** A small model only writes down what you asked
  for. Code applies it, works out what else is now out of date, and gives that to one strong model (Jonathan's own) to
  fix, in one call.
- **Jonathan's own checks run after every change.** If an edit brings back a mistake (someone teleports, a crossed
  line, a shot too short for its line), code fixes what it can and the model gets at most two tries. A chat edit can never
  leave the plan worse than Jonathan left it.
- **It tells the truth about each message:** what changed, "nothing changed", what you asked for that did not happen,
  and what it was not allowed to do.
- **Undo and redo.** Every change is saved as a version.
- **A big change is offered, not done:** "This would change most of the scene. Re-plan with Jonathan?"
- Things you set yourself are **locked**: the chat may not change them.
- Our rules stay: dialogue is never rewritten or trimmed by the AI, line changes are a card you accept, too-long lines
  are reported with a way out (longer take, split), no costs shown.

## What it does not copy from Nova

- Nova uses 12 small AI "seats" per message. Our rule is one author per creative job, so Zora uses one strong model.
  We test both in a small lab first and keep the seats only if they clearly win.
- Nova trims dialogue to fit. Zora never does.
- Nova shows credits per message. Zora does not.

## The steps

| # | Step | Costs money? |
|---|---|---|
| 0 | Run 10 real requests through today's chat on scenes the lab already planned, write down what goes wrong | no |
| 1 | The plan as an editable document, and the edit rules | no |
| 2 | What goes out of date, the "what changed" report, the "did it happen" check | no |
| 3 | The lab: try the prompts, one model vs Nova's seats, **$3 cap, your yes before each run** | yes, small |
| 4 | Build the chat system (switched off by default) | no |
| 5 | Saving, undo, seams with the next scene (you apply the database change) | no |
| 6 | Treatment mode and "Plan shots from this treatment" | no |
| 7 | The API | no |
| 8 | The screen (needs Figma frames) | no |
| 9 | A director tries it on five real scenes, then we decide the default | yes, your call |

## What you decide

One model vs seats (the lab decides), Zora only for Jonathan scenes at first, a database table for
undo, treatment mode in the first version, the lab budget, and the Figma frames. The full list is §7 of
[PLAN.md](PLAN.md).
