# plan/2026-11-18 — Omni takes carry the first frame AND the people's sheets

**Goal.** An Omni Flash take is sent the accepted first frame plus each on-screen person's face sheet and look sheet, in
one request, cited in plain words by order ("Image 1 is the opening frame… Image 2 is the face sheet for Anudi…"). A
person then keeps their sheet's face and clothes once more of them comes into view, which a frame alone cannot promise.

## 1. Why (evidence)

**Today.** `ENGINE_CAPABILITIES["omni_flash"].refs_with_first_frame = False`: when a shot has a frame, every sheet is
dropped ("takes a start frame or reference pictures, not both"). Only the frame goes, with `<FIRST_FRAME>`, task
`image_to_video`.

**Google's Omni page (read 2026-11-18, aistudio.google.com/docs/omni.md):**
- "Do not include control strings (such as `<FIRST_FRAME>`, `<LAST_FRAME>`, `<IMAGE_REF_0>`, or `<VIDEO_REF_0>`)…
  These tags are deprecated and unsupported in future models. Describe how each image or video should be used in natural
  language instead."
- "Gemini Omni 1.2 Flash supports up to 6 reference images per request (up to 3 images per character for up to 2
  characters)."
- `task` is a fallback; "Setting `task` adds strict constraints, such as limiting input images or locking how multiple
  media inputs combine."
- `gemini-omni-1.1-flash` routes to `gemini-omni-1.2-flash` from 2026-12-03.

**Lab (`lab/omni_refs`, runs 001 to 003, 2026-11-18).** Love Hour 4, shot 02 (Anudi gets out of the car), 360p, Omni 1.2,
one take each. See `lab/omni_refs/README.md`.

| | Opening = frame | Clothes once out of the car | Face |
|---|---|---|---|
| A: today (frame only, `<FIRST_FRAME>`, image_to_video) | yes | **wrong**: followed the prose's "muted blue blouse" | n/a |
| B: frame + sheets, "Image N" words, no task | **no**: a new street | right | softer |
| C: frame + sheets, "Image N" words, `reference_to_video` | close (same place, slight re-frame) | right, down to neckline and watch | closest |

**C is the method.** B shows that without a task Omni treats image 1 as one more reference.

**Root cause of A's wrong clothes, found on the way.** The video prompt's SUBJECTS line comes from the planner's
`ir.subjects[].description` ("muted blue blouse, charcoal trousers, flat black shoes"). It never reads the scene's look
("dusty-rose blouse, navy trousers, tan shoes"). Phase 4 fixes this for every engine.

## 2. Existing productions (checked 2026-11-18, read-only)

All ten productions use `omni_flash`. No shot has a saved picture list (`video_settings.references` is null everywhere),
so the new default applies to every shot at once. No schema change is needed.

| Production | Face sheets | Base sheet only | No sheet | Looks with a sheet |
|---|---|---|---|---|
| Love Hour 4 | 3 | – | 4 | 5/10 |
| hiru short 4 | 3 | – | 3 | 3/3 |
| Hiru Short 3 | – | 3 | 3 | 3/3 |
| the other 7 | – | – | all | 0 |

With no sheets, only the frame is sent: the request is today's, apart from the wording (§3.3). Takes already made keep their stored
spec (`video_renders.spec`, the picture list as sent) and are untouched. A render that is retried or resumed after the
change is rebuilt from its old spec, so it keeps its old pictures (frame only) and gets only the new wording and task.

## 3. Design

### 3.1 Capability (`contracts/video_gen.py`)
- `omni_flash`: `refs_with_first_frame=True`, `max_refs=6` **counting the start frame** (the lab's reading; safe).
- New fields on `EngineCapability`: `max_per_person: int = 0` (0 = no limit) and `max_people_with_sheets: int = 0`.
  Omni: 3 and 2. Veo: unchanged (0, 0).
- `last_frame` stays exclusive: a first + last frame pair carries no sheets (not tested; §6 D3).

### 3.2 Which pictures Hiru picks (`default_references`, `renders._candidates`)
`SheetCandidate` gains `face: RefSource | None` (the card's `face` asset) beside `sheet` (the `sheet` asset) and
`look_sheet`. For an engine with `refs_with_first_frame`:
1. The start frame (accepted, else carried) is **image 1**.
2. For each person the camera sees, in the frame rule's order: **face sheet** (else the base sheet), then **look sheet**
   (when the scene has one with a picture). With neither a face nor a look, the base sheet alone.
3. **Places and props are left out when there is a start frame** (the frame already shows them); without a frame,
   today's order (people, place, props) within the cap.
4. Caps: total ≤ `max_refs`, ≤ `max_per_person` images of one person, sheets for ≤ `max_people_with_sheets` people.
   Who wins when there are more: the people in the shot's `ir.subjects` order (the planner's order, lead first). Every
   picture cut is listed in `left_out` in plain words, as today.

`RefSource.kind` gains `"face_sheet"` (a face asset), so labels and checks can tell it from a full sheet. The asset
`kind` is already stored in `reference_assets`; `canon_sources` reads it. `RefKind` in the interface's
`render-types.ts` gains the same value.

### 3.3 Order and words in the request (`wire_order`, `build_omni_input`)
- Omni wire order: **start frame first**, then references in the list's order, then the end frame. Veo keeps its own
  layout (separate slots), so `wire_order` takes the engine.
- The citation block (replaces `<FIRST_FRAME>` / `<IMAGE_REF_n>` / `<LAST_FRAME>`):

  ```
  Reference images, in the order attached:
  Image 1 is the opening frame of this shot. The video starts exactly on this picture: the same framing, people,
  place, weather and light, and everything that happens grows out of it.
  Image 2 is the face sheet for Anudi: … her face, age, skin tone and hair come only from this sheet …
  Image 3 is the look sheet for Anudi: exactly what Anudi wears in this shot, head to toe (<outfit; accessories>) …
  Images 2 to N are references only: never show a sheet, its grey backdrop or its panels in the video, and never cut
  to them. Where the words above describe someone's clothes or face differently from these pictures, the pictures win.
  ```

  The sentences live in ONE place (constants in `video_gen.py`), word for word as in `lab/omni_refs/build.py` (the
  tested text). An end frame reads "Image N is the closing frame …".
- `cited()` reads "Image N" citations. `tags_of()` returns `Image 1`, `Image 2`, … for Omni (Veo keeps `image n`).
- **Guard:** the n-th "Image n" sentence must name the n-th image part. A test builds requests for every slot mix and
  checks it.

### 3.4 Task (`video_render/engine/omni.py` `_task`)
| Pictures | task |
|---|---|
| start frame only | `image_to_video` |
| start frame + references | `reference_to_video` (lab C) |
| references only | `reference_to_video` |
| start + end frame | `image_to_video` (no references, §3.1) |

`UPSTREAM.md` for `video_render` records the divergence.

### 3.5 Checks (`validate_render`, `check_render`)
- Fail "takes either reference pictures or a start frame, not both" only when the engine says so (Veo), and for an end
  frame with references on Omni.
- New fails: more than `max_per_person` pictures of one person; sheets for more than `max_people_with_sheets` people.
  `max_refs` counts the start frame when `refs_with_first_frame`.
- Advisory (exists): a person on screen with no picture.

### 3.6 Interface (`hiru-ai-studio-interface`)
- The tag beside each card comes from the API (`ref.tag`), so it becomes "Image 1", "Image 2"… with no logic change.
- `render-types.ts`: the `tag` comment (`<IMAGE_REF_0>` → `Image 1`), `RefKind` gains `face_sheet`, the label for it
  ("Face sheet").
- Any hard-coded "start frame OR references" wording is removed (search `refsWithFirstFrame`).
- `map-render.test.ts` fixtures move to the new tags.

## 4. Phases

| # | What | Where | Done when |
|---|---|---|---|
| 0 | Lab done (this plan's evidence). | `lab/omni_refs` | ✓ 2026-11-18 |
| 1 | Capability + picture choice (§3.1, §3.2), `face_sheet` kind, fallback to base sheet. | `contracts/video_gen.py`, `api/services/renders.py` | unit tests: Love Hour 4 shot 02 shape → frame, face, look, face, look; base-sheet-only and no-sheet cases; caps and `left_out` |
| 2 | Request: order, "Image N" words, `cited`/`tags_of`, task (§3.3, §3.4). | `contracts/video_gen.py`, `video_render/engine/omni.py`, `UPSTREAM.md` | the order guard; `build_omni_input` for shot 02 equals lab C's prompt block; provider tests updated |
| 3 | Checks (§3.5). | `contracts/video_gen.py` | tests for each fail and for Veo unchanged |
| 4 | **Clothes come from the look.** For each subject whose person has a look for this scene, the SUBJECTS line describes the clothes from `canon_looks.outfit` + `accessories` instead of the planner's description (face and body words stay). | `steps/serialize/logic.py` + its twin `services/shot_producer` engine (parity), the loader that knows the scene's looks | parity test passes; shot 02's prose says "dusty-rose…"; a person with no look is unchanged |
| 5 | Interface (§3.6). | `features/handoff` | `npx next typegen && npm run check && npm run format:check` |
| 6 | **Paid, the person's yes first:** one 360p take of shot 02 through the product's Render button. Compare its request with lab C and read the take. | localhost | the request matches; clothes and face hold |

Phases 1 to 5 are offline (no model call). Each phase updates `IMPLEMENTED.md` in this folder.

## 5. Out of scope
- Veo's request (it has its own reference slots; unchanged).
- Making face or look sheets for productions that have none (that is the canon refine flow).
- Re-rendering old takes.
- Prompt writer wording (`prompt_writer` rewords the prose; the citation block is added after it, by code, so it is
  never reworded).

## 6. Decisions (defaults in bold; the person may change any)
- **D1** At most **2 people** get sheets in one take (Google's limit); the others are listed as left out. Lead first by `ir.subjects` order.
- **D2** Clothing text: **(a) replace the clothes words with the look's** (Phase 4). (b) Drop clothes from the line
  instead. (c) Later.
- **D3** End frame + sheets: **not allowed** until a lab shows it works.
- **D4** Places and props with a start frame: **left out**. A person can still add one by hand on the panel (counts
  toward the 6).
- **D5** Phase 6 paid take: **ask first**, 360p, about $0.80 at most at the 720p list rate.
