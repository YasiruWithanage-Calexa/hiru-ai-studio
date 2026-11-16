# plan/2026-11-13e — implemented

- 2026-11-13: research done (PLAN.md §3). Lab built: `lab/storyboard/` (`fetch.py`, `prompt/system.md`, `run.py`,
  `README.md`). No change under `src/`, no database write.
- 2026-11-13: run_001 paid ($0.3948 booked of $1.00). Board: `lab/storyboard/runs/run_001/board.png`. Result and read in
  PLAN.md §6.
- Open: the person's choice among A / B / C (PLAN.md §7); `fetch.py` does not read `dialogue_lines` yet; the guard's
  `IMAGE_WORST_OUT` must be lowered before a second full run fits the remaining budget.
- 2026-11-13: option B chosen by the person. `fetch.py` reads `dialogue_lines` (speaker, text, delivery per shot as
  `spoken`); `prompt/system.md` gained four principles (screen direction across the frame, one landmark carried across a
  move, camera height follows the eyes, who is speaking), examples from other stories only; guard caps set from
  run_001's measurements (`WRITER_MAX_OUT` 16000 → 10000, `IMAGE_WORST_OUT` 10000 → 6500). run_002 paid, $0.3991;
  ledger $0.7938 of $1.00. Read in PLAN.md §6b.
- 2026-11-14: the person asked for (1) shot numbers for identification and (2) every shot of the scene on the board,
  tested at low quality. `fetch.py` keeps `all_shots` (painted or black plate); `run.py` gained `--quality`,
  `image --from <run>` (reuse a run's writer output + board prompt, no writer call), gutter-aware cropping, and
  `scene_sheet()` → `sheet.png` / `shots/shot_NN.png` / `sheet.json`. Numbers are drawn by code, never by the image
  model. run_003 paid $0.1222 (low: 158 output tokens; the 6 reference pictures' input is ~95 % of the cost). Ledger
  $0.9160 of $1.00. Read in PLAN.md §6c.
- 2026-11-14: the person allowed one medium-quality run on scene 02 (`8f7f085e-…`, INT. CASH VAN, 16 shots, 3
  references). `LAB_BUDGET_USD` raised 1.00 → 1.30 to fit it. run_004 paid $0.1987 (writer $0.0704, image $0.1283);
  ledger $1.1147 of $1.30. Read in PLAN.md §6d.
- 2026-11-14: frame-from-panel test (the person's go-ahead; cap 1.30 → 1.80). New `lab/storyboard/frame.py`: paints one
  shot's first frame with the product's `references_block` wording, the code-cut panel as "the approved draft of this
  frame", optionally the whole board (unlabelled) with its row/column; drops the World paragraph's board sentences.
  run_005: shot 7 of scene 02, `panel` $0.2752 and `board` $0.2915; ledger $1.6814 of $1.80. Read in PLAN.md §6e.
- 2026-11-14: face drift traced. `input_fidelity` is not the cause: `gpt-image-2` rejects the parameter (400, nothing
  charged; the product does not set it either). Cause: every look/character sheet holds ONE face, front-on, smiling,
  studio-lit (the other views are headless), so serious / turned / night faces are invented; the writer's face words
  add to it. Built: `faces.py` (a 6-view face sheet from the look-sheet portrait), `run.py --faces <people>` (face
  sheet first; the look sheet's job becomes clothes only; World sentences describing that person's face are dropped;
  a "Faces:" line), `--rebuild`. Cap 1.80 → 2.10 → 2.30 on the person's go-ahead. run_006 face sheet $0.2261,
  run_007 board $0.1443; ledger $2.0519 of $2.30. Read in PLAN.md §6f.
- 2026-11-14: the person flagged unnatural posture / facing in run_007 (medium/low only, minimal budget). Added a
  general `BODIES` line to the board prompt; run_008 (LOW, image only, $0.0973; ledger $2.1491 of $2.30): partly fixed.
  Added the writer rule "CAMERA AND BODY AGREE" to `prompt/system.md` (examples from other stories); not run yet.
  Read in PLAN.md §6g.
- 2026-11-14: the person's idea: people on the board as pose markers, one colour each, replaced by the real person at
  the first-frame step. Built as faceless colour-coded mannequins (`run.py --mannequins`: the writer describes poses
  only; the board image gets place/prop sheets only; `frame.py --mannequins --faces --quality`: the mannequin panel as
  the draft, "Dinu is the red mannequin … replace", mannequin words turned back into names). Cap 2.30 → 2.60.
  run_009 (writer + LOW board) $0.1494, run_010 (MEDIUM frame, shot 1) $0.1269; ledger $2.4254 of $2.60. §6h.
- 2026-11-14: close-up test (cap 2.60 → 2.80): run_011, shot 7 MEDIUM from its mannequin panel, $0.1267; ledger
  $2.5521 of $2.80. Face right; he stares into the lens; window side flipped vs the master. §6i.
- 2026-11-14: scene 01, two people (cap 2.80 → 3.20). Writer rules CLOSE-UPS DO NOT LOOK INTO THE LENS and SAME SETUP,
  SAME SIDE; frame line "Nobody looks into the lens unless this shot says so"; mannequin note: people inside photos stay
  real; `faces.py` gender-neutral + `--quality`. run_012/013 face sheets (medium) $0.0616 each, run_014 board $0.1683,
  run_015 two-shot frame $0.1932; ledger $3.0369 of $3.20. §6j.
- 2026-11-14: state fix (cap 3.20 → 3.40): in mannequin mode `frame.py` adds the shot plan's own `opening_picture`
  (per person, this shot only) + "keep each body as flat/bent/upright as its mannequin". run_016, shot 4 MEDIUM,
  $0.1939; ledger $3.2308 of $3.40. §6k.
- 2026-11-14: the product plan is written: `plan/2026-11-14/PLAN.md` (Scene board). The lab stays as the reference.
