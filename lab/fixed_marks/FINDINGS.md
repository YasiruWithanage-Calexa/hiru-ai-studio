# Fixed marks lab: findings (2026-11-24)

The person's rule: a person who does not walk or travel stays on ONE ground spot for every shot (the spot in the
place, its landmarks and the gap to the other person, not the side of the picture); small steps keep the mark within
a small radius (0.5 m here); only a walk or travel moves it. Case: Love Hour scene 4, board v18 part 1 (shots 1-6, the
board the person showed), its saved prompt and pictures, plus the same MARKS words in every arm. Budget $0.60, spent
$0.306 (one run per arm).

| run | adds | $ | result |
|---|---|---|---|
| v18 (product) | nothing | – | the three-wheeler is behind Kasun in 1 and 3 (he stands IN FRONT of it); in 2, 4 and 5 it becomes a counter with a flask under the awning, and he stands against it; what is behind each person changes with the camera |
| A_001 | words only | 0.075 | Kasun beside the three-wheeler's rear, its hatch and flask behind him in 1, 3 and 4, its dark roof behind him in 2 and 5; Anudi in front of the green building and pale wall in all five; the gap reads the same |
| B_001 | words + floor plan | 0.092 | as A; the three-wheeler hatch directly behind Kasun in 2 and 4 too; no dot, ring or arrow painted. Anudi has more pale wall than green behind her |
| plate | the blocking plate (for C) | 0.048 | a clean wide: three-wheeler in the bay, Kasun just right of it in front of the green building, Anudi to his right with the pale wall beginning at her right; the gap is about 2 m (asked 1.2) |
| C_001 | words + blocking plate | 0.091 | the steadiest: every panel is the plate's place, the green building flat behind both, the three-wheeler at frame left behind Kasun; the gap is the plate's (wider than asked) in every panel |

What holds in all three arms: the panels keep v18's sides, hands, umbrella, bag and the insert (panel 6); nobody's
feet travel; in the wides (1 and 3) Kasun stands beside the end of the three-wheeler, not in front of its body as in
v18, and in the closer panels the three-wheeler is behind him because the camera is closer, not because he moved. **The words do most of the work**: A alone fixes what the
person showed. B adds nothing visible over A on this scene. C makes the place itself steadier (the panels read as one
continuous take) but the plate decides the gap, so the plate must be right; and it costs a call.

Faults to carry into a plan:
1. **The marks must use the vehicle's real geometry.** The words said "the hatch at the rear"; the vehicle sheet has it
   on the SIDE. Every arm painted the sheet's side hatch facing the road. The marks must name landmarks as the sheet
   shows them (the views sheet's `layout` and `empty`, the vehicle sheet), never as the writer imagines them.
2. **C's gap is the plate's, not the words'.** One run each: a second run of A and C is needed before choosing (the
   difference between A and C may be luck).
3. **The insert (panel 6)** names Anudi's mark but shows only pavement; nothing to check there.

## Second runs (the person's yes, 2026-11-24; ledger $0.472 of $0.60)

| run | $ | result |
|---|---|---|
| A_002 | 0.075 | steady WITHIN the sheet (the three-wheeler behind Kasun, the green building and pale wall behind Anudi, in all five), but a DIFFERENT spot from A_001: Kasun stands at the hatch, against the vehicle's rear, and the gap is about 1 m, not A_001's 1.5 m |
| C_002 (same plate) | 0.091 | the same spots as the plate and as C_001 (Kasun just clear of the three-wheeler in front of the green building, Anudi ~2 m right, the pale wall at her right); but the GRID broke: panels 1 and 2 painted wide (two columns each), 5 cells, so the product's cut check fails the part (`two panels in one crop`) |

What the second runs settle:
1. **Words hold a mark within one sheet, not between sheets.** A scene's board is painted in parts (scene 4: three),
   each its own picture, so the words alone let part 2 put Kasun somewhere else than part 1. Same words, two runs, two
   spots. Within a part both A runs held.
2. **A picture holds it between sheets.** Both C boards put the people where the plate does. So the plate is what
   carries one mark across the parts (and later to the first frames).
3. **A wide plate pulls the layout.** C_002's first row copied the plate's 16:9 shape. The plate should be painted at
   the panels' shape (9:16 for a vertical production), or the board told once more that every panel is the same tall
   size; to test before trusting C.

## The tall plate (the person's yes, budget raised to $0.75; ledger $0.611)

| run | $ | result |
|---|---|---|
| plate_tall (9:16) | 0.048 | the three-wheeler in the bay under the awning, Kasun just clear of its end, Anudi ~1.2 m to his right in front of the pale wall (here painted IN FRONT of the green building's lower half), the green above it; but Anudi's bag is a handbag hanging from her forearm, not on her shoulder as asked |
| T_001 (tall plate) | 0.091 | **the grid holds** (6 cells, cut clean). The spots are the plate's in all five panels: the three-wheeler's end behind Kasun, the pale wall with the green above behind Anudi, the same gap. But the board took the plate's handbag on the forearm too, against the panels' "on her left shoulder" |

What it settles:
1. **Paint the plate at the panels' shape.** The tall plate keeps the grid; the wide one broke it once in two.
2. **The plate carries more than the marks.** "Not its framing, its light or its poses" did not stop the board taking
   the plate's bag. So the plate is a picture every later panel copies: it must be right before it is used (a
   person approves it, as a board) and be painted from the same hands and props words as the panels.
3. **Two plates of one moment differ in the place's details** (the wide had the green building and the pale wall side
   by side, the tall one the pale wall in front of the green). Each plate is consistent with itself, and that is what
   the boards follow; one plate per stretch, never one per part.

What this suggests for the product (to discuss; nothing is planned):
- A staging mark gains a GROUND spot: a landmark of the place's views sheet + a side + a distance ("half a metre in
  from the drain, one step right of the three-wheeler"), and the gap to each other person in the same zone.
- Code carries the spot forward block to block until a block where the person walks or travels (`posture` walking,
  a `move:<who>` bridge, a zone change); a small step, turn or lean keeps it (radius 0.5 m).
- The board prompt gets a "Ground marks" paragraph built by code from those spots, and a marks line per panel
  saying what is behind each person; the board writer no longer re-decides where anyone stands.
- The blocking plate (C): one per stretch of unmoving marks, painted ONCE and attached to every part of the board (and
  later to the shots' first frames) that falls in that stretch; a new plate only after someone walks or travels. A
  person sees and approves it like a board. It must be painted at the panels' shape (fault 3 above).

## Phase 0 of plan/2026-11-24d: the next parts of the chain, and a walk (the person's yes; ledger $0.799 of $0.92)

Scene 4's board is painted in three parts; T_001 was part 1 against the tall plate. R and W paint parts 2 and 3 the way
the product chains them (each gets the previous LAB part's last panel), against the SAME tall plate, with the plan's
code words (`stretch_marks`, the generic `PANEL_LINE`), not hand-written panel lines. Scene 4 has no walk on its board
(all 14 shots stand; the walk-off of block 18 comes after them), so W adds two panels from the script's own block 18.

| run | $ | result |
|---|---|---|
| R_001 (part 2: shots 6-11) | 0.093 | Anudi's singles from Kasun's end, camera looking obliquely along the pavement: behind her the pale wall, the green above it and the shutters receding, which is what her spot gives from that side; shot 11's two-shot is T_001's: Kasun just clear of the three-wheeler's end, Anudi before the pale wall, the same gap |
| W_001 (part 3: shots 11-14 + 15, 16) | 0.095 | shots 11-14 the same spots and gap as T_001 and R_001; **shot 15: Kasun stays on his mark and Anudi walks away screen right, two metres beyond hers** (the plate did not hold her); **shot 16: Kasun at the three-wheeler's counter, the pavement empty** (a one-shot stretch, words only, no plate, worked) |

What phase 0 settles:
1. **One plate holds the spots across all the parts of a scene** (T_001, R_001, W_001: three separate pictures).
2. **A camera that is not the plate's keeps the spot**: the oblique singles show what stands behind her from that
   side, not the plate's view.
3. **A plate does not freeze people**: when the panel says someone walks or a new stretch starts, they leave the mark.
   The walk panel and the new stretch's first panel need their own marks line (the generic "on the ground marks of
   shots 1 to 15" would contradict them): code can write both from the stretches.
4. **The plate's hand faults go everywhere again**: the handbag on the forearm in every single, and in R's singles the
   umbrella's shaft beside her with no hand on it (`floating`, the panel check already catches it). The plan's plate
   hands from the first panel and the inspector on the plate are needed, not optional.
5. **Blocks do not line up**: scene 4's script has blocks 0-18 but shots 11-14 open at blocks 19-22. The stretches
   must be found through the map's anchors (`SceneStaging.placed`, `reading.resolve`) against the shots' items, never
   by raw block numbers.
