# shot_prompts lab (2026-11-20)

ONE agent writes a shot's FIRST FRAME prompt and its VIDEO prompt together, from one OPENING STATE (who is where,
facing what, hands, expression, background, light), so the take starts from the frame and both prompts say the same
thing. The person's ask (2026-11-20): "combine both first frame and video prompt generation ... more connected and
error free ... agent aware of both". Decisions: nothing spends without a click; a new plan replaces plan/2026-11-20b's
video prompter and the prompt writer's frame rewording; prove it here first.

Separate from every build: nothing in `src/` changed, nothing written to the database (reads GET only, `fetch.py`).
Scene: the person's own "SEE AI IN ACTION" (scene 48fbb071), with the Camera agent's designs from
`lab/camera_moves/runs/db_url_scene`. Caps: OpenAI $0.60, Omni $2.00.

| File | What |
|---|---|
| `system.md` | the agent: opening state → first frame (camera height/angle in physical words, framing at the move's start, a still has no motion) → video (situation, people, flow with lines by id, sound); the video prompter's drama rules kept |
| `run.py` | brief (scene script, shot facts, the Camera agent's design), the agent (gpt-6.1-sol medium, structured), checks (same people, same sides, the design's angle and opening size in the frame, no motion in a still, no gear, lines once each, no speech in a silent clip), assembly (frame: the product's style line + reference citations + identity lines + rules; video: the product's sections, exact words by code, the Camera agent's sentence), paint (the product's `OpenAIImages`, gpt-image-2 medium, face + look sheets + location plates), render (omni_refs variant C: frame + sheets, reference_to_video, 4-minute limit) |
| `fetch.py` | GET only: today's frame and its prompt (comparison only), the sheets and location plates |

## Spend: OpenAI $0.37 of $0.60; Omni $1.80 of $2.00 (720p ceiling rate)

Agent: 2A-1 $0.018 (clean first time), 2B-1 $0.023 (one repair: the low angle was missing from the frame text),
2H-1 $0.018 (one repair, from a check false alarm on "Nobody speaks", fixed in the check). Frames: $0.12, $0.09, $0.09.
Takes: 2 min 16 s, 1 min 11 s, 59 s (an earlier attempt hung 29 min on Google's side and was stopped; not charged).

## Results

Watch `runs/takes.mp4`. Per shot: `runs/<slate>/today_vs_new.png` (today's frame | the new frame) and
`runs/<slate>/take/frame_open_end.png` (the new frame | the take's first frame | its last frame);
`runs/frame_open_end_all.png` all three.

| Shot | Design | New frame | Take |
|---|---|---|---|
| 2B-1 | slightly low, chest height; push MS → MCU | camera low, looking up at her, waist-up on the left third (today: eye level, knee-up) | push performed (72 px + size): opens wider than the frame, lands chest-up looking up |
| 2A-1 | eye-level two-shot; push then hold | waist-up two-shot, workstation foreground (today: wide full figures) | push performed (size grows, monitor fills the foreground); opens near the frame |
| 2H-1 | waist-up; pull back to MWS | waist-up, left third, monitor right (today: full figure) | pull back performed (43 px + size): opens TIGHTER than the frame, ends knee-up |

## Findings

1. **One writer keeps both prompts in step.** In all three the frame and the video name the same people on the same
   sides, facing the same way, the same hands and clothes; the takes keep them. The check caught the one miss (the
   design's low angle not written into the frame) and the repair fixed it.
2. **The design now reaches the picture.** The new frames carry the Camera agent's angle, height and opening framing
   (2B-1 is visibly low; 2H-1 starts tight enough to pull back) instead of the old flat eye-level wide.
3. **All three moves were performed from the first frame**: a push on a single, a push on a two-shot, a pull back.
4. **Open: Omni treats the first frame as a reference, not the literal opening, in reference_to_video.** The takes
   open NEAR the frame but re-fit it for the move (2B-1 wider before a push, 2H-1 tighter before a pull; also
   lab/camera_moves 2I-1). People, clothes, place and the angle are kept. Next test: the same shots with variant A
   (image_to_video, frame only: literal opening, no sheets) to see which the product should send.
5. The video text still slips in clock words ("three-quarters of a second into the shot") and capitalises a delivery
   mid-sentence: two small checks for the product.

## Google's closing line + two more shots (2026-11-20, $0.020)

`GOOGLE_LINE` ("Use the images as references to generate the video.", from Google's reference-to-video template) is
now the last line of every Omni prompt the lab sends (`omni_request`; `--omni` writes `runs/<slate>/omni_prompt.txt`
free). The agent wrote 2I-1 (the visitor's reaction close-up) and 2D-1 (the screen insert): both clean first time
($0.013, $0.007). Both are holds in the Camera agent's design. The 2D-1 screen text is the planner's own (its beats).
Code faults seen in the lab's frame assembly for a shot with NO people (2D-1): it still says "faces come only from the
face sheets" and writes an empty "Who they are: ." line. To fix in the product's assembly, not the agent.
2I-1 rendered at the person's ask (360p, the lowest; frame $0.095, take 52 s, Omni cap raised $2.00 -> $2.40 for it):
the take keeps the frame's person, shirt, office and his three-quarter-left eyeline; the camera holds as designed;
it opens a little tighter than the frame (the same re-fit as before, smaller). `runs/2I-1/take/take.mp4`,
`runs/2I-1/take/frame_open_mid_end.png`. Spend now OpenAI $0.484 of $0.60, Omni $2.20 of $2.40.
