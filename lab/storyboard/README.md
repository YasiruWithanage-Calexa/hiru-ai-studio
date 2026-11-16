# Storyboard lab

Question: can ONE storyboard image, painted from a scene's shot PLANS (not the first-frame prompts) plus every reference
picture, keep a scene consistent (same people, clothes, light) while each shot gets its own camera position, so a walk
and its destination are different but connected backgrounds? If yes, each panel later becomes the composition guide
("approved draft") for that shot's real first frame.

Nothing under `src/` changes and nothing is written to the database (`fetch.py` only sends GET requests). Deleting this
folder removes the lab.

## Run it (from the repo root)

```
.venv/Scripts/python.exe lab/storyboard/fetch.py --scene <scene id> --name scene1   # read-only: input/scene1/
.venv/Scripts/python.exe lab/storyboard/run.py dry  --input scene1                    # the request + worst case; no call
.venv/Scripts/python.exe lab/storyboard/run.py paid --input scene1 --hypothesis "..." # writer + one image (a person's yes)
```

| File | What it is |
|---|---|
| `fetch.py` | scene, shot plans (black plates left out), people with this scene's look, place + spots, props, reference pictures |
| `prompt/system.md` | the writer's prompt: geography as a path, a later reveal is not seen earlier, screen direction, safe depiction |
| `run.py` | writer (`gpt-6.1-sol` high, JSON schema) → board prompt built by code (references cited from the attached list) → safe-depiction scan → `gpt-image-2` `images.edit`, high, 1536x1024 → panels cropped by an even grid |
| `runs/ledger.csv` | every paid call; `LAB_BUDGET_USD` = $1.00 is checked against each call's worst case before it is sent |
| `runs/run_NNN/` | `writer_input.txt`, `writer_output.json`, `board_prompt.txt`, `board.png`, `panels/`, `summary.json` |

Image tokens are booked at $10 / $40 per 1M (above the repo's provisional $8 / $30 seed), so the ledger over-states.

## Runs

- **run_001** (2026-11-13, $0.395 booked): 9 panels from scene 1 (Mahawewa canal). See the session notes for the read.
- **run_002** (2026-11-13, $0.399 booked; ledger $0.794 of $1.00): option B. `fetch.py` reads `dialogue_lines`; writer prompt gained screen direction (cross the frame, never into depth), one landmark carried across a move, camera height follows the eyes, who is speaking. Read in plan/2026-11-13e PLAN.md §6b.
- **run_003** (2026-11-14, $0.122 booked; ledger $0.916): `image --from run_002 --quality low`: run_002's board prompt, image only, low quality. New: `sheet.png` = every shot of the scene in order, numbered by code (black plates as black cells with their line), `shots/shot_NN.png`, `sheet.json`; crops follow the painted gutters.
- **run_004** (2026-11-14, $0.199 booked; ledger $1.115 of $1.30): scene 02 (cash van, night), 16 shots, medium quality, one full run (writer + image). Cap raised 1.00 → 1.30 for it.
- **run_005** (2026-11-14, $0.567 booked; ledger $1.681 of $1.80): `frame.py --run run_004 --shot 7`: two HIGH first frames from the panel (approved-draft wording): `panel` (sheets + panel) and `board` (+ whole board, unlabelled). Cap raised 1.30 → 1.80.
- **run_006** (2026-11-14, $0.226): `faces.py --input scene2 --person Dinu`: face sheet (6 views, neutral + serious) from the look-sheet portrait → `input/scene2/refs/face_Dinu.png`. An earlier `--fidelity high` attempt was refused by the API (gpt-image-2 has no input_fidelity), nothing charged.
- **run_007** (2026-11-14, $0.144; ledger $2.052 of $2.30): `image --from run_004 --faces Dinu --rebuild --quality medium`: the scene 02 board with the face sheet first.
- **run_008** (2026-11-14, $0.097; ledger $2.149 of $2.30): run_007 + a general `BODIES` line in the board prompt (body faces the task, no posing, head and eyes together), LOW. Partly fixed; the writer's own camera text overrides it. Writer rule "CAMERA AND BODY AGREE" added to `prompt/system.md` (not run yet).
- **run_009** (2026-11-14, $0.149): `paid --input scene2 --quality low --mannequins`: writer (poses only, with CAMERA AND BODY AGREE) + LOW board of colour-coded faceless mannequins (no face/look sheets sent to the image).
- **run_010** (2026-11-14, $0.127; ledger $2.425 of $2.60): `frame.py --run run_009 --shot 1 --quality medium --faces Dinu --mannequins`: MEDIUM first frame, red mannequin replaced by Dinu. (A first attempt failed on a network error, nothing charged.)
- **run_011** (2026-11-14, $0.127; ledger $2.552 of $2.80): `frame.py --run run_009 --shot 7 --quality medium --faces Dinu --mannequins`: MEDIUM close-up from a mannequin panel. Cap 2.60 → 2.80.
- **run_012/013** (2026-11-14, $0.062 each): `faces.py --input scene1 --person Aruni|Nimal --quality medium` (gender-neutral prompt).
- **run_014** (2026-11-14, $0.168): `paid --input scene1 --quality low --mannequins` (Nimal red, Aruni blue; close-up + same-side rules).
- **run_015** (2026-11-14, $0.193; ledger $3.037 of $3.20): `frame.py --run run_014 --shot 4 --quality medium --faces Aruni,Nimal --mannequins`: two-person MEDIUM frame. Cap 2.80 → 3.20.
- **run_016** (2026-11-14, $0.194; ledger $3.231 of $3.40): run_015 again with the shot plan's per-person opening picture in the frame prompt. Cap 3.20 → 3.40.

**In the product** (plan/2026-11-14): the Scene board is built from this lab: `contracts/board.py` (prompts, crops, pins),
the `board_writer` agent (this `prompt/system.md`, moved unchanged), `hiru_ai/systems/frame_render/board.py` and
`faces.py`. Read `docs/scene_board/README.md`.
