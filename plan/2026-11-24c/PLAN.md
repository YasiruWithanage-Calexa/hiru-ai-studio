# Place views by type: three answers pick one of four fixed templates (plan/2026-11-24c)

Revision 2 (2026-11-24). Nothing in this plan is built. It changes the location views of plan/2026-11-24, which IS
built and committed (2d4a986, `plan/2026-11-24/IMPLEMENTED.md`). Proven in `lab/place_views` (r1 + r2, $0.466 of
$0.80, `FINDINGS.md`) and, with plan/2026-11-24b, in `lab/final_views` (a board and four frames of Love Hour scene 2,
$0.674, `FINDINGS.md`). Revision 2 adds what the final lab found: sheets in dry, even light (§2.4) and the board's
view check (§2.7). Read this file whole, then `lab/place_views/FINDINGS.md` and `run.py` (the words to port:
`TEMPLATES`, `SYSTEM`, `Written`, `sheet_prompt`), `src/libs/hiru_ai/agents/views_writer/` (schema, prompt),
`src/libs/hiru_ai/systems/frame_render/views.py` (`render_views`), `src/libs/contracts/canon.py`
(`views_sheet_prompt`, `views_asset`, `VIEWS_COUNT`) and the API route `POST .../canon/{id}/views-sheet`
(`views_context`). Build this BEFORE plan/2026-11-24b (vehicles), which relies on §2.4.

## 0. Rules for the chat that builds this

- **Port the lab exactly.** The four templates, the writer's rules and the sheet prompt's new sentences are the lab's
  r2 words (`lab/place_views/run.py`). List any change of words before making it. Do not edit or re-run the lab.
- **Ask before every paid call**, each time. Tests run with `OPENAI__API_KEY=` blank and fakes only.
- **No enable switches.** **Never stash or reset** the person's tree. **Never edit an applied migration** (none is
  expected: the answers, the template and the empty spaces are fields of the `views` reference asset's JSON).
- Two repos: the backend (this one) and `..\hiru-ai-studio-interface` (its `CLAUDE.md` binds).

## 1. What is wrong with the built views, and what the lab showed

The person's rule (2026-11-24): the views sheet is made at CANON time, before shots exist, so it covers the place's
MAIN POSSIBLE views; a later camera finds a view facing roughly its way. The kinds of place never end (a road, a
restaurant, a bedroom, a car, a bus, a temple), so the AI decides within fixed rules, not a template per kind.

The built sheet (plan/2026-11-24):

1. **One template for every place**: Front wide, Looking left, Looking right, Reverse, two details. Right for a road;
   wrong for a room (it has walls, not "along"), a restaurant (outside AND inside) or a car (outside AND seats).
2. **Things that come and go are painted in.** `views_context.within` puts the places named in the scenes into the
   sheet with their plates: the food three-wheeler becomes a fixed part of "Colombo roadside", so a scene where it is
   elsewhere (or a frame that attaches its own plate, plan/2026-11-24b) fights the sheet.
3. **A place with no plate is refused** (`render_views`: the first picture must be the location plate). The lab painted
   the restaurant and the prep room from their card's words, as well as the two with plates.
4. **The writer is trusted.** The lab's writer broke soft rules: it invented sign text and chose a plain table as a
   detail; only the painter's no-text rule saved the sign.

The lab (Love Hour, one place of each type; writer gpt-5-mini, sheet gpt-image-2 MEDIUM 1536x1024):

| Run | Place | Template picked | Result |
|---|---|---|---|
| r1 | Colombo roadside (plate) | outside | one place in all six; left/right faced the same frontage; the three-wheeler bay painted as a full stall |
| r1 | KASUN'S Restaurant (words only) | both | the best: maroon front, cane lamps, steel counter, lattice the same in all six; "Inside reverse" looks out of the entrance |
| r1 | Kasun's small food preparation workspace (words only) | inside | the four walls fit: desk left, shelves and stove right, window far, door opposite |
| r1 | Family car, BMW 520d (plate) | vehicle | front 3/4, side, rear 3/4, inside forward to the right-hand wheel, inside back to the beige bench, dashboard |
| r2 | roadside, one anchor spot + `empty` | outside | turns FIXED (frontage at the right edge looking left, left edge looking right, out of frame in the reverse); the bay listed empty and nothing parked, but not drawn as a clear bare space |
| r2 | restaurant, details rule | both | counter detail good; the second detail still a plain table; the writer invented sign text (the painter left the sign blank) |

All templates were picked right and all six sheets cut clean.

## 2. The design

### 2.1 Three answers and four templates

- The views writer first answers about the place: `sides` (outside | inside | both), `moves` (a vehicle or not),
  `size` (small | room | long), `why` (one sentence). Code picks the template: `vehicle` when it moves, else by sides.
- `contracts.canon.VIEW_TEMPLATES`: the lab's `TEMPLATES` word for word (slot name, what it shows), always six slots,
  one 3x2 sheet (`VIEWS_COUNT` stays 6, the cutter unchanged):
  - outside: Wide · Looking left · Looking right · Reverse · Detail 1 · Detail 2 (the first four from ONE anchor spot,
    turned 0 / 90 left / 90 right / 180, each saying where the main frontage is in the picture);
  - inside: Wide from the door · Opposite wall · Left wall · Right wall · Detail 1 · Detail 2;
  - both: Outside wide · Entrance · Inside wide · Inside reverse · Detail 1 · Detail 2;
  - vehicle: Front three-quarter · Side · Rear three-quarter · Inside from the rear · Inside from the front · Detail.
- The views keep their slot names on the sheet ("Detail 1" is shown with what it is: the writer's `sees` starts with
  the thing's name). `Panel.view` (the board's view number) is unchanged.

### 2.2 The writer

- `views_writer` schema becomes the lab's `Written`: `answers`, `layout`, `empty`, `views[{slot, camera, sees}]`, plus
  the built `light`. Its prompt becomes the lab's `SYSTEM` (r2) with the built prompt's two good lines kept (follow the
  storyboards' geography when there is one; name the same things with the same words in every view).
- Its input: the card's look, the spots, the plate as a picture when there is one (the lab gave it to the writer), the
  scenes set there (text, as the lab), and the boards' geographies when they exist. `within` keeps only places that are
  NOT vehicles (a spot of another set, a kiosk that is its own set); vehicles go to the writer as "things that come and
  go here" so it can list their spaces in `empty`.
- A person's answers win: the canon page may set the three answers before writing (§2.5).

### 2.3 Code checks after the writer (new; the lab showed the prompt alone is not enough)

`contracts.canon.view_findings(written, card, scenes)`:
1. the slots are the template's, in order (the lab's `check`);
2. no quoted text and no sign wording in a view or the layout unless the card's look has those words;
3. each detail names a thing found in the card's look or a scene set there (a word match after folding plurals);
4. each `empty` space says where it is (a side or a neighbour) and what its ground looks like.

On findings: ONE re-ask with the findings as a list; still failing, the views are stored with the findings shown on
the canon page (the person edits or paints anyway). Never silent.

### 2.4 The sheet

- `views_sheet_prompt` gains the lab's sentences: the type's head ("location" or "vehicle reference sheet"), the
  answers' template, `empty` ("These spaces are EMPTY in every view, bare, with nothing standing in them ... Leave out
  anything image 1 shows standing in them."), "No vehicle is parked anywhere in the place", and for a vehicle "The
  vehicle stands alone on a plain, empty, light-grey concrete floor of a large covered parking area for every outside
  view; nothing else is near it."
- **Dry, even light** (`lab/final_views` fault 3): the sheet is painted in soft, even, DRY daylight with dry ground,
  whatever the plate or the scenes show ("Light (every view): soft, even, dry daylight that shows the place clearly;
  dry ground, no rain, no puddles, no reflections"); the built `light` line of the writer is no longer painted into the
  sheet (it stays in the board's world line, where each scene sets its own weather). The roadside r2 sheet was wet,
  and the dry shots 2 and 4 of the final lab came out damp although each view's job said "not its light, weather or
  wet ground".
- The view's job in the frame (`VIEW_JOB`) adds "not its light, weather or wet ground" (the final lab's words).
- **No plate needed**: a place without a plate is painted from its card's words ("There is no picture of this place:
  paint it from these words: ..."), as the lab's restaurant and prep room.
- Vehicles' plates are NOT attached to a place's sheet any more (§1.2).
- The stored `views` asset gains `answers`, `template` and `empty`.

### 2.5 The interface

- Canon page, `LocationViewsSection`: the three answers shown (and settable before "Make location views"), the
  template's six slot names over the six views, the findings of §2.3 when there are any, and the empty spaces listed.
- A vehicle card gets the same section ("Make vehicle views").

### 2.6 Existing sheets

A sheet made by the built code stays as it is (boards pinned to it keep their view numbers); "Remake" makes the new
kind as a new version. No migration.

### 2.7 The board keeps each panel's view (`lab/final_views` fault 1)

In the final lab, panels 2 and 3 named view 4 "Reverse" (across the road) but the board painted the frontage, the
sheet's most distinctive side, and the frames followed the board. The background stayed consistent, but not the view.

- **The writer's rule:** a panel names the view its camera FACES, read from its camera line: a camera on the pavement
  looking out at the road faces the Reverse; one on the road looking at the shops faces the Wide. The writer's bundle
  gives each view's `camera` and `sees` words (today only the name and `what`), so it can match.
- **The board picture:** each PANEL line's "Background view" names the view AND its key words ("view 4 (Reverse): the
  road and the far side, the frontage out of frame"), so the painter knows what NOT to show.
- **The check:** the built board inspector (`agents/board_inspector`, one vision call per painted panel, which
  already finds extra limbs, floating props and wrong hands and repaints that panel) gains `view_match`: given the
  panel's view (name and `sees` words) and the view crop beside the panel, "does this panel's background show the
  view's things on the view's sides?". A mismatch goes the built way of its other faults (the panel repainted once
  with the fault named, `fixed` on the cell), and shows on the board card if the repaint still misses.

## 3. Decisions (the person's; recommended)

- D1 **Who sets the three answers:** the writer, with the person able to set them first on the canon page.
  Recommended.
- D2 **Check failures:** one re-ask, then store with the findings shown. Recommended.
- D3 **The three-wheeler already in a built roadside sheet:** remake the sheet after this ships (the person's paid
  step, about $0.09). Recommended.

## 4. Phases (offline, $0, then the person's live check)

1. **Contracts:** `VIEW_TEMPLATES`, the answers → template rule, the `views` asset's new fields, `view_findings`,
   `views_sheet_prompt`'s new sentences, the no-plate path. Tests from the lab's six written answers
   (`lab/place_views/runs/r1/written`, `r2/written`): the right template each, the r2 restaurant's sign text and plain
   table found, the r2 roadside's empty bay accepted.
2. **Agent:** `views_writer` schema and prompt (the lab's words), its input (plate picture, scenes, vehicles as things
   that come and go), the re-ask. Evals: the four lab places as offline fixtures.
3. **System + API:** `render_views` (no-plate path, vehicles not attached, answers from the request), the route's
   `ViewsRequest` gains optional answers, `views_context` splits vehicles out of `within`.
4. **Board (§2.7):** the writer's view rule and the views' `camera`/`sees` in its bundle, the panel line's view key
   words, the inspector's view question and the board card's finding. Tests: the final lab's panels 2 and 3 (named
   Reverse, painted the frontage) found from fixture crops.
5. **Interface:** the answers, slot names, findings and empty spaces on the canon page; the vehicle card's section;
   the board card's view finding. `npx next typegen && npm run check && npm run format:check`.
6. **Docs:** `docs/scene_board/README.md`, the catalog, IMPLEMENTED.md.
7. **Live check (paid, the person's):** remake the views of Colombo roadside, KASUN'S Restaurant, Kasun's small food
   preparation workspace and Family car (about $0.08 each and a cent for each writer call). Measured as the lab: the
   right template, one connected place, the roadside bay empty, no invented text, details from the card or scenes.
   Then Update board for Love Hour scene 2 (LOW, about $0.07): panels 2 and 3 show view 4 (Reverse) or the inspector
   finds it; every sheet dry.
