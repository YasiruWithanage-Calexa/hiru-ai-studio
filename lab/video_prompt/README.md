# Video prompt lab (2026-11-20)

One agent writes the direction of EVERY video clip; code keeps the facts. Why: findings/issues/2026-11-20/NATURAL-DIALOGUE.md
(today's prompt gives the video model camera and safety text and a bare `X says, "..."`; lab/natural_dialogue showed a
director's prompt makes a scene, not an interview). See `run.py`'s docstring for how it works.

- `system.md`: what the agent knows (drama, delivery, listeners, the planner's decisions it keeps, hard rules).
- `cards/*.md`: short craft cards code picks per clip (dialogue, phone, silent, detail, sinhala_voice).
- `run.py`: brief → gpt-5-mini (low effort, structured answer) → gates → one repair → assembly. Dry by default.

Scene: Api Denna v2 E01-S04, Raphael's saved run (18 clips). The packet already has, for every line, who it is said to
(`addressee`), its `intent` and a `delivery_hint` ("Genuine gratitude with mild surprise"). Today's prompt uses none of
them.

## Found while building (dry, free)

- Today's serializer writes a line as SPEECH in a clip whose sound mode says nobody speaks: S15 (Kasun's CU) says
  `Anudi (...) says, "..." — only Anudi's lips move` and then `No dialogue. Nobody speaks on camera.`; S05 (Anudi's POV)
  does the same with an off-screen voice. The lab speaks a clip's lines only in dialogue / voiceover / sung clips.
- Every Raphael clip of this scene is `locked_off`. The agent keeps it (gate), so the "steady frame" stays.

## Runs 001-003 (2026-11-20): three models, low effort, the same 18 briefs

| Run | Model | Spent | Clean first time | Repaired | Fell back | Seconds a clip |
|---|---|---|---|---|---|---|
| 001 | gpt-5-mini | $0.042 | 13 | 4 | 1 (a false alarm, see below) | 16 |
| 002 | gpt-6.1-terra | $0.070 | 17 | 1 | 0 | 7 |
| 003 | gpt-6.1-sol | $0.168 | 15 | 3 | 0 | 10 |

Read `runs/<run>/prompts.md` (new prompt per clip, today's under it) and `gates.md`.

- **gpt-6.1-sol: the best direction.** Reads the line's meaning and writes how it turns inside the line ("thanking him
  with mild surprise … easing into a slightly sheepish admission"; the father "an initial questioning lift settles into
  firm parental expectation"); listeners react to what is said; stays inside the planner's facts. A little wordy.
- **gpt-6.1-terra: faithful, fast, plain.** Never invents; delivery and listener are good but short, and silent clips are
  close to Raphael's own beats. Best price for quality.
- **gpt-5-mini: lively but drifts.** Adds events the planner did not give (4H-1: "he watches her walk away" in a 4 s
  reaction), writes notes to us into the prompt ("her departing words are heard in the edit…"), slowest.
- Gate fault found: "a heard-only person is never in `people`" fired on "Father (heard only, never in frame)" (mini 4G-1
  fell back for it; sol and mini repaired other clips for it). Fixed after the runs: naming them AS heard is allowed.

## Takes (2026-11-20): 4A-2 (the exchange) from terra and from sol

`render.py`: Omni Flash 1.2, 360p, 16:9, 6 s, text to video (no frame or sheets in the lab, so the citation lines are
left out; the rest is the assembled prompt as is). ~12.3k video tokens and ~34 s each.

| Run | Speech (measured) | Picture |
|---|---|---|
| 002 terra | 0.4–4.9 s, 2 pauses | two-shot in the rain, facing each other |
| 003 sol | 0.9–4.95 s, 2 pauses | the same, warmer smiles; **a "Colombo / Colomban" caption top right** |

Takes: `runs/<run>/takes/4A-2/take.mp4`; frames side by side: `runs/compare_4A-2.png` (top terra, bottom sol). The
voice is the person's to judge. The caption came although the prompt says "no captions"; terra's prompt names Colombo
too and has none, so it may be chance. Watch for it: `contracts/on_screen_text.VIDEO` ("Text the description spells
out … is rendered exactly as written") may invite lettering of a place name.
