# Omni reference images lab (2026-11-18)

Question: when the request carries the first frame **and** the people's face and look sheets, cited in plain words by order
("Image 1 is the opening frame… Image 2 is the face sheet for Anudi…"), does a person keep the sheet's face and clothes
once more of them comes into view? Today the product sends the first frame only (`refs_with_first_frame=False`).

Google's Omni page (read 2026-11-18) says the `<FIRST_FRAME>` / `<IMAGE_REF_0>` control strings are deprecated: "Describe
how each image or video should be used in natural language instead." Limits for gemini-omni-1.2-flash: 6 reference images,
at most 3 per character, 2 characters. `gemini-omni-1.1-flash` routes to 1.2 from 2026-12-03.

```
.venv/Scripts/python.exe lab/omni_refs/fetch.py --shot <shot id> --name shot02   # GET only
.venv/Scripts/python.exe lab/omni_refs/run.py --name shot02                      # dry: requests only
.venv/Scripts/python.exe lab/omni_refs/run.py --name shot02 --variants A,B,C --yes   # PAID, one take each
```

| Variant | Images | `task` | Prompt citation |
|---|---|---|---|
| A | first frame | image_to_video | today's `<FIRST_FRAME>` block (the product's own `build_omni_input`) |
| B | frame, face + look sheet per person (≤ 6) | none | "Image N is …" sentences |
| C | same as B | reference_to_video | same as B |

All at 360p, gemini-omni-1.2-flash, the shot's own prose, aspect and length. `run.py` prints a ceiling at the 720p rate
in `contracts/costs.py` ($0.10/s, marked "confirm").

## shot02 (Love Hour 4, scene with Anudi's car drop-off)

Input: the accepted first frame (dusty-rose blouse, tan handbag), Anudi's face sheet + "office-day separates" look,
the driver's face sheet + "working clothes" look. **The prose describes Anudi in "a muted blue blouse, charcoal trousers
and flat black shoes"**, which contradicts both the frame and the look sheet; B/C say "the pictures win". What to read in
the stills: t03 to t06 (she steps out: trousers, shoes, umbrella, bag) and t06 to t08 (her face as she turns to nod).

## Results: runs 001 to 003 (2026-11-18, 360p, one take each, ~45 s per take)

Each take used 15,448 video output tokens. Input was 1,977 tokens for A and 6,649 for B and C (5 images = 5,400 image tokens).
To compare: `runs/compare.png` (t00 to t08, rows A/B/C), `runs/opening.png` (frame vs each t00), `runs/faces.png`.

| | Opening matches the frame | Anudi's clothes once out | Face |
|---|---|---|---|
| **A** frame only, `<FIRST_FRAME>` | yes, closest | **wrong**: grey-blue blouse, black trousers, black flats, which is the prose's "muted blue blouse" winning over the frame's rose blouse | can't judge at 360p, mostly profile |
| **B** frame + sheets, no task | **no**: a new street (glass office block), new car framing | right: rose notch-neck blouse, navy trousers, tan heels, tan bag, umbrella | rounder and softer than the sheet |
| **C** frame + sheets, `reference_to_video` | close but re-framed: same street, pole and buildings; the car sits a little further right and the three-wheeler moves into view | right: matches the sheet down to the notch neckline and the gold watch | closest to the sheet of the three |

Reading: the sheets fix the wardrobe drift, and that is exactly the failure today's request (A) shows. With no `task` (B), Omni treats
image 1 as one more reference and invents its own opening. `reference_to_video` (C) keeps the place and the layout, but the
opening is not pixel-literal, so a cut from the shot before will jump a little.
