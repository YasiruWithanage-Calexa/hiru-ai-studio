# Shot Planner David: the plan in plain words

This is the simple version of [PLAN.md](PLAN.md). Nothing is built yet.

---

## 1. The problem in one sentence

**One message to ChatGPT plans a scene as well as Adam does with about 12 model calls, so we are paying for many calls
that make the result worse, not better.**

## 2. What we found

- ChatGPT, in one message, scored **100 %** on Adam's own scorecard. Adam scored **92.2 %**.
- Adam splits one creative job across five big-model "experts". Each one starts again from zero, and ideas get lost
  between them.
- After Adam has chosen the camera, the shot producer chooses the camera **again** with more big-model calls.
- What keeps Adam safe (no invented story, lines word for word, the Veo clock, continuity) is **plain code**, and code
  is free.

## 3. The idea: one author, code checks, narrow repair

```
  what we know (characters, looks, places, rules, where the last scene ended)
        ↓
  ONE strong model call writes the whole scene: shots + camera + sound + where people stand + how it ends
        ↓
  code checks it (free)  →  code fixes what it can (free)
        ↓
  only if something is still wrong: the same model gets the exact problem and fixes only those shots
  (at most 2 times, then it is shown to you, never hidden)
        ↓
  saved; you review on the David tab
```

**About 1 call per scene instead of about 15**, and the camera is decided only once.

## 4. The rules every new AI system will follow

1. One creative job = one model call. No chains of "experts".
2. A second call only when the input is too big, it needs an image, many later calls reuse its answer, or the parts can
   run at the same time.
3. Code checks facts. People judge taste. No AI critic can block a plan.
4. Fix only what is broken. Never redo the whole thing.
5. Memory goes in, "where things stand now" comes out.
6. A small answer format: only fields something reads.
7. Agents with tools only where a person is talking to them (director chat).
8. A new step must win a blind test on real Hiru scenes. Quality problems are fixed in the prompt, never by adding agents.

## 5. Continuity

- **Inside a scene:** one model writes all 10–15 shots, so it remembers its own ideas.
- **Between scenes:** when a scene carries straight on from the one before (same place, "CONTINUOUS"), it gets the last
  scene's ending: who is where, wearing what, holding what, and the last shot's description word for word, so the
  jacket and the light are described the same way.
- **Strict or fast (D5):** either only those scenes run in order and the rest at the same time (fast, but a costume
  change in scene 3 is only flagged in scene 6), or every scene runs in order from the one before (strict, same cost,
  slower: about as long as Adam takes today).
- **Look changes:** if someone changes clothes or gets hurt during a scene, that is saved as a new entry with the scene
  number. The character card is never edited.
- **Many episodes at once:** even in strict mode, different episodes run at the same time, so a whole drama takes
  about as long as its longest episode.
- **Editing one scene:** the scenes after it are planned again only until one comes out with the same ending, so one
  edit does not redo the whole episode. An approved scene is never redone.
- **Across the series:** the canon and looks in the database, as today.

## 6. Cost (estimate until we measure it)

| | Adam today | David |
|---|---|---|
| Model calls per scene | about 12, then 2–3 more for the camera | 1, sometimes 2–3 |
| Tokens read per scene | about 36,000 (measured) | about 6,000–10,000 |
| Tokens written + thought per scene | about 48,000 (measured) | about 14,000–23,000 |
| Cost per scene | $0.52 (measured), camera extra | about $0.17–0.27, camera included |

Costs appear only in the test scripts, never in the app.

## 7. How we decide

**Early (the first test run, about $5–10):** you paste ChatGPT's answer for each test scene, and see it beside David's.
If David is clearly behind, we improve the prompt before building the rest.

**At the end:** a Hiru director looks at shot lists for 10 scenes from **David, Adam, the classic planner and
ChatGPT**. The names are hidden. David must be at least as good as Adam and ChatGPT, with no invented story. If it is
not, we improve the prompt. We do not add more agents.

## 8. What you need to decide

| | Question | My suggestion |
|---|---|---|
| D1 | The camera is designed inside David's one call (no second camera designer) | yes |
| D2 | The model writes the format directly, or writes freely and a small model converts it | the test decides |
| D3 | Which model David uses | the test decides (gpt-5 now; try the newest one too) |
| D4 | "Hard for Veo" warnings are only shown at first, not fixed automatically | yes |
| D5 | Only "carry straight on" scenes in order (fast), or every scene in order (strict) | build both; strict by default if the test shows one scene takes 6 minutes or less |
| D6 | Which 5 or more real Hiru scenes we test on, and which director judges | yours |
| D7 | The database change goes into version 12 if v12 is not applied yet | yes |
| D8 | The next scene gets the last shot's description word for word | yes |
| D9 | Clothing and injury changes are saved per scene, and the character card is never edited | yes |
| D10 | The first test run also shows ChatGPT's answers beside David's, and stops early if David is behind | yes |

## 9. What it costs you to try

- The first test run (Phase 2) is about **$5–10** of model calls, and only you start it. Pasting the ChatGPT answers
  takes about 10 minutes.
- The blind comparison needs about an hour of a director's time.
- Adam and the classic planner stay as they are until David wins. Then a separate plan removes the loser.
