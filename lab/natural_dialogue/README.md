# Natural dialogue lab (2026-11-19)

Question: does Omni Flash 1.2 speak Sinhala like a teledrama, not an interview, when the prompt gives the situation, the
listener, the mood and how each line is said, with "casual everyday spoken Sinhala" beside the words?

Found first (product prompts, lab/action_budget and lab/coverage): `{delivery}` is empty on every line (the DB's
`delivery` is empty for the whole Love Hour 4 scene), no listener, no situation, internal ids ("L6") in the prose, a
broken speaker tag ("the person in dIRECTOR'S PRODUCTION NOTES…"), the line wrapped `"«"…"»"`, no voice pin, and the
language line ("a native speaker, exactly as written") at the end among the rendering rules.

`run.py` (dry by default, `--yes` pays). Text to video, 360p, 9:16, 10 s, gemini-omni-1.2-flash. Lines verbatim from
lab/sinhala_pace/lines.json (Love Hour 4, father and Anudi).

## Run 1: A and B, ~20k video tokens each, ~37 s each

| | What | Speech (measured) | Picture |
|---|---|---|---|
| baseline | lab/sinhala_pace/runs/002_B (same line as A, plain prompt) | 0.75–6.75 s, 2 pauses | one man, to the side of the lens: an interview answer |
| A | father presses Anudi, over her shoulder | 1.25–6.85 s, 2 pauses | he talks TO her, looks away at the end; she fidgets with her phone |
| B | Anudi's line, father answers | 1.4–9.75 s, 3 pauses, runs to the end of the take | two-shot across the table; she looks down while he speaks |

`runs/compare.png`: one frame a second, rows baseline / A / B. The voice is the person's to judge: listen to
runs/A/take.mp4 and runs/B/take.mp4 against the baseline. B's speech reaches 9.75 s of 10: check the last words are not
cut (12 words + a hand-over is tight for 10 s).
