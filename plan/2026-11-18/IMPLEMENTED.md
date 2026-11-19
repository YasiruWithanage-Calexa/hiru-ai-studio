# plan/2026-11-18 — what is built

Phases 0 to 5 are built offline on 2026-11-18, in both repos, and are uncommitted. No model was called after the lab. Phase 6
(one paid 360p take of Love Hour 4 shot 02 through the product) is the person's.

## Phase 1: capability and picture choice
- `contracts/video_gen.py`: Omni `refs_with_first_frame=True`, `refs_with_last_frame=False`, `max_refs=6`, `max_images=6`
  (the start frame counts), `max_per_person=3`, `max_people_with_sheets=2`, `person_pictures="face_and_look"`. Veo is
  unchanged, and the new fields default to the old behaviour.
- `RefKind` gains `face_sheet`. In `api/services/renders.py`, `canon_sources` gives a card's `face` asset that kind and
  the label "the face sheet for X". `_candidates` passes `face` and the base `sheet` separately. Before this, `sheets[0]`
  could be the face asset, standing in for the sheet.
- `default_references`: start frame, then for each person seen the face sheet (else the base sheet), then the look sheet
  (else the base sheet when a face sheet came first). With a start frame, places and props are left out ("the start frame
  already shows it"). Sheets go to 2 people at most; the others are listed. Without a frame, places and props follow
  within 6.

## Phase 2: the request
- `wire_order`: start frame, then references, then end frame. Veo routes by slot, so nothing changes for it.
- `build_omni_input`: "Reference images, in the order attached:", then one "Image n is …" sentence per picture, by its
  kind (opening frame, closing frame, face sheet, look sheet, other), then a closing line that opens with "Never show
  Images 2, 3…". It opens with "Never" so `cited` counts exactly one sentence per picture. The sentences are constants
  (`OMNI_LINES`), added by code after the prose, so the prompt writer never rewords them.
- `cited` and `tags_of`: "Image n" for Omni, frames included. Veo keeps "image n", "start frame" and "end frame".
- `video_render/engine/omni.py` `_task`: any reference gives `reference_to_video`, start frame included. Frames alone
  give `image_to_video`. `UPSTREAM.md` divergence 12.

## Phase 3: checks
- Fails: more than 6 pictures counting the start frame; references with an end frame on Omni; more than 3 pictures of
  one person or thing. Veo's "start frame or references, not both" stays.
- `check_render`: "Image n is X; the prompt never mentions them" numbers by wire position on Omni. The advisory "X has 2
  reference pictures" is off for engines whose rule is a face and look pair.

## Phase 4: clothes come from the look
- `contracts/canon.py`: `look_outfit` (outfit, with accessories; "None" dropped), `dressed` (removes the planner's
  "wearing / dressed in …" clause and adds the look's), and `wardrobe_by_code`.
- Both serializers (`steps/serialize/logic.py` and its legacy twin `shot_producer/engine/serialize.py`): `Context.wardrobe`
  holds canon code → outfit, and the Subjects line uses `dressed`. Empty means byte-identical output to before.
- Loading: the graph uses `frame_world(row, canon)["looks"]`, the legacy engine the new `Store.scene_looks_in_force`. Both
  use `looks_in_force`, the same rule that picks the look sheet the take attaches.
- Shot 02, checked against live data (GET only): the Subjects line now reads "…low ponytail, wearing dusty-rose
  three-quarter-sleeved blouse tucked into navy ankle-length tailored trousers and tan low-heeled closed shoes, with small
  gold stud earrings, a tan structured handbag and a navy folding umbrella". The video prompt changes only when the
  prompt is written again, so prompt v1 still says blue.

## Phase 5: interface
- `render-types.ts`: `RefKind` gains `face_sheet`; `EngineInfo` gains `refsWithLastFrame`, `maxImages` and
  `maxPerPerson`; the tag comment now names "Image 1". `map-render.ts` maps them, with defaults for an older API. No
  component hard-coded the old tags or the "not both" wording; the panel shows `ref.tag` from the API.

## Deviations from PLAN.md
1. **People order** follows the frame rule's order (`shot_canon_ids`), not `ir.subjects`, so the take and the frame
   agree on who comes first.
2. **Sheets for 2 people** is enforced in Hiru's default list. In a person's own list it is advice, not a fail: Google
   states it as a quality limit, and no 400 has been seen for it.
3. **Wording**: the look's outfit text goes in the Subjects line (Phase 4) rather than in brackets in the look sheet's
   sentence, as the lab had it. The sheet sentences say "that person", so a person's own label can be anything.

## Tests
- Backend: `tests/contracts/test_video_gen.py` (new: order guard over 7 slot mixes, shot 02 shape, base-sheet fallbacks,
  2-people cut, 6 with no frame, singular closing line, carried frame), `tests/contracts/test_canon.py` (dressed,
  look_outfit, wardrobe_by_code), `tests/api/test_renders.py` (face asset → face_sheet), `tests/services/shot_producer`
  (the look dresses the Subjects line), `tests/services/video_render/test_providers.py` (task table).
- Isolation check: these changes alone, applied to HEAD in a worktree, give the same failing set as HEAD (8 tests that
  already failed: 7 parity cases for canon_extract, frame_render and structure_build, plus the shot_producer
  "charter budget"). 848 pass.
- At the time of writing, the working tree also holds someone else's uncommitted edits (`camera_words.py`,
  `serialize/card.py`, `shots.py`, `logic.py`'s static-camera hunks, `holding.py`, the clip schema, Raphael). Those
  move further parity cases (frame_render, shot_producer lighting text) and `test_frame_brief`. They are not part of
  this plan.
- Interface: `npx next typegen && npm run check`: 490 pass, 1 fails (`raphael-panel.test.tsx`, untouched by this
  plan). `prettier --check` passes on the 3 changed files; 96 other files were already unformatted.

## Left for a person
- **Phase 6 (paid, ask first):** write shot 02's video prompt again (so the Subjects line takes the look), then one 360p
  take on Omni 1.2 through the Render button. Compare the request with `lab/omni_refs/runs/003_C/request.json` and read
  the take.
- Shots whose prompt was written before this change keep the planner's clothes until their prompt is written again.
