# Cinematic David: the plan in plain words

The simple version of [PLAN.md](PLAN.md). Nothing is built yet.

## 1. The problem

For Episode 1, David made 12 plain shots and added nothing. One ChatGPT message made 19 shots that feel like a film
crew planned them. We want **the most cinematic version**, but we do not want to build another big system that burns
credits before we know it works.

## 2. The idea: a small lab first

Build the whole new idea as a **small test version in its own folder** (`lab/cinematic/`), outside the real app. Run
it on the Episode 1 story. Look at the result, fix what is wrong, run again. Only when it beats ChatGPT do we move it
into David.

```
  the story (fixed by hand: one scene, Kasun's thought as a voice-over, the narrator's last line kept)
        ↓
  ONE call to a strong model, briefed as a top film team:
  director's treatment → colour plan → sequences → every shot
        ↓
  code checks it (free): nothing invented, every line in order, timing,
  plus film-craft scores (opens on the place, close-ups of the phone, reactions, colour changes ...)
        ↓
  a page you read: treatment, colour strip, sequences, shot cards, and a blind side-by-side with ChatGPT
        ↓
  change ONE thing, run again
```

## 3. How we stop it burning credits

- **Build and test everything for free first**, with a hand-written answer. The first paid call happens only after
  we can see the exact message and its price.
- **A hard limit of $5 for the whole lab.** Every call has a maximum length, so its worst-case price is known before
  it is sent. The run tool refuses any call that could take the total past $5.
- **Never pay twice** for the same question: a saved answer is reused.
- **One change per paid run**, with a written reason.
- **A mid-price model for the tries** (about $0.30–0.50 a run). The most expensive model gets one run at the end,
  only if money is left.
- **Stop after 4 tries**, or when the $5 is used, and think again before spending more.

## 4. What changes from David today

- **The brief:** "a top director, DoP, producer and editor making the most cinematic version", not "a planner using
  few devices".
- **Coverage rules a professional uses:** open on the place, introduce each lead, close-ups of the story's objects,
  reactions to important lines, several shots for a busy action, let big moments breathe, end each sequence on an image.
- **A director's treatment first:** the emotional beats, the visual approach, the colour plan, the layout of the
  place, the key image, and advice for you.
- **More shot sizes** (extreme close-up, extreme wide, medium-wide) and **edit length**: make a 4 s clip, keep 2–3 s.
- **Who the people are**, not only their names: Kasun's ambition, Anudi's world.
- **A stronger model, thinking harder.**
- **The split bug fixed:** a long shot cut in two no longer copies the same action into both halves.
- **Kept:** no invented lines (ChatGPT invented one), every line word for word and in order.

## 5. How we know it worked

1. No hard problems in the plan.
2. You (and a Hiru director if possible) prefer it to ChatGPT's, or rate them equal, without knowing which is which.
3. It is good again on one more run, so it was not luck.
4. It is also good on a different scene, so it was not tuned to this story only.

## 6. Steps

| Step | What | Costs |
|---|---|---|
| 0 | Set up the folder, save the story, ChatGPT's answer and David's plan, write the corrected reading. **You confirm it.** | free |
| 1 | Build everything and test it with a hand-written answer | free |
| 2 | List the models; one tiny test call to prove the format works | up to $0.05 |
| 3 | First real run on Episode 1; we read it together | up to $0.50 |
| 4 | Improve, at most 4 runs, one change each | up to $2.00 |
| 5 | One repeat run and one run on another scene | up to $1.00 |
| 6 | Check whether the real story reader gives this input (one scene, the voice-over thought, the narrator line) | up to $0.20 |
| 6b | One run on the most expensive model, only if money is left | what is left |
| 7 | Decide: move it into David with a new plan, or stop | free |
| | **Whole lab** | **$5 hard limit** |

## 7. What you decide

| | Question | Suggestion |
|---|---|---|
| L1 | Spending limit for the whole lab | **decided: $5, hard** |
| L2 | Which two models (we list what your account has first) | a mid-price one for the tries, the strongest one for one final run if money is left |
| L3 | The corrected story: one scene, Kasun's thought as a voice-over, the narrator's line kept | yes |
| L4 | A second scene to test on | one of your real scenes; our "phone call" test scene if none |
| L5 | The length is a guide; going over is reported; the edit may keep part of a clip | yes |
| L6 | Who judges the blind comparison | you, plus a Hiru director if free |
| L7 | Keep the lab local until it passes | yes |
