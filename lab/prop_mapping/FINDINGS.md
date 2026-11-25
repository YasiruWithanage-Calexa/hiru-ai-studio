# Prop mapping lab: findings (2026-11-25)

Question: the board paints props as white clay stand-ins; the first frame painted from the panel does not turn them
back into the RIGHT real props. Which way maps them: words (tier 1), numbered marks (tier 2), a props pass (tier 3), or
a colour per prop (D)?

Case: Love Hour scene 4 (de75bc31), board v22, shots 11 and 1. Baseline = the product's own newest frame of each shot
(painted 2026-11-25 04:50 from the same board). Each approach starts from that frame's SAVED prompt and changes only
the prop parts (`run.py`, `swap`). gpt-image-2, medium, one picture per approach per shot.

Money: cap $1.50 (the person's yes), spent **$1.386** (`runs/ledger.csv`). Box finder: gemini-3.5-flash.

## What the baseline gets wrong (the product today)

| | shot 11 | shot 1 |
|---|---|---|
| umbrella | WHITE canopy overhead (the clay's colour) AND a second, folded navy umbrella in her other hand (from the look sheet) | navy, one |
| phone | dark, not the orange sheet phone | dark, not orange |
| why | only the phone sheet attached (umbrella/handbag sheets exist but were not); "white clay" never tied to a sheet; prompt also says "Kasun is not holding the phone. Anudi holds the phone" (ledger) against the board's "Kasun ... gripping the phone" | same |

## Results

| | shot 11 | shot 1 | cost / frame | verdict |
|---|---|---|---|---|
| **A** roster words | navy umbrella once, black curved handle; orange phone; tan handbag; steel flask on the ledge | orange phone in Kasun's hand, Anudi's palm open beneath (as the board); navy umbrella once; tan handbag; steel flask | $0.22 | **all props right, both shots** |
| **B** + numbered marks | same as A; no marks or numbers drawn; but a steel jug AND a red plaid flask on the ledge (one extra) | not run (budget) | $0.22 + $0.003 boxes | no gain over A here |
| **C** + props pass (masked edit, pasted back) | phone sharper (the sheet's camera block); BUT inside the umbrella box her face turned and changed, blouse redrawn | phone most exact; BUT her blouse turned cream (the umbrella box covers her torso); visible seam at the bag box | A + $0.12 | **harmful**: the box mask repaints people |
| **D** coloured props | navy umbrella, orange phone, tan bag, steel flask; no stand-in colour leaked | orange phone (small) in the handoff; umbrella, bag, flask right | $0.23 + $0.013 recolour | as good as A, one extra step |

Pictures: `runs/shot11/compare_shot11.jpg`, `runs/shot1/compare_shot1.jpg` (panel | baseline | A | B | C | D | panels
sent); close-ups `runs/shot11/zoom_anudi.jpg`, `runs/shot11/zoom_flask.jpg`, `runs/shot11/zoom_A_vs_C.jpg`,
`runs/shot1/zoom_props.jpg`.

## Read

1. **The fix is the words and the sheets, not the picture tricks.** A alone fixed every fault of the baseline in both
   shots. Its changes: every prop the panel shows gets its sheet (umbrella, handbag; never the "bag" document case),
   one sentence per stand-in tying it to its image number by holder, hand and side, "white is never a prop's colour",
   one state (open), "each prop once: the look sheet's umbrella and bag are these same things", and ONE hands
   sentence (the ledger line that contradicted the board removed).
2. **Marks (B)** did not help on a case words already solve, and the model drew no marks (good). Untested on a scene
   where words are ambiguous (two similar props in one hand area). The box finder worked: 4/4 stand-ins on the panel
   and 4/4 props on frames, first try, $0.002-0.003 each.
3. **The props pass (C) as built is not usable**: a box around an umbrella covers the person under it, and the edit
   redraws whatever is in the box. It would need a tight per-object mask (segmentation, not boxes) and still risks
   seams. It gave the most exact phone, so a phone-only pass on small held objects could be a later option.
4. **Colours (D)** work as well as A: the recolour edit kept the panel's layout and the frame left no colour behind. It
   adds a board change (props painted in colours) for no gain over A on these two shots.

## Limits

One picture per approach per shot; two shots of one scene; B only on shot 11. The roster was written by hand (as
`shot_props` would give it); the flask has no sheet in either run. The D panel was recoloured by an edit, not painted
coloured by the board painter.

## If built

Tier 1 (A) as the product change: the per-shot prop roster (`contracts.props.shot_props`, one resolver for board and
frame), sheets for every prop the panel shows, the binding sentences, one hands source. Keep the box finder in mind for
the frame check (counting the right prop in the right hand), not for painting.
