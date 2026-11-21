# Timecodes lab (2026-11-21)

**Question.** Google's Omni guide lets a prompt time its events ("[0-5s] …", or "After 3 seconds …") and says Omni makes
"a few different shots" unless asked for one ("In a single continuous shot", "No scene cuts"). Our video prompt gives
the flow in order with no times (the shot prompter is barred from clock words) and ends "Ends on a cut." Does Google's
timecode syntax make Omni place the action and the spoken line where we ask?

**Design (A/B, nothing written to the database).**
- A = today's product take of the shot (360p, `scripts/camera_live.py`, SCENE 03 of Love Hour 4).
- B = the same stored render spec (`video_renders.spec`: frame, face/look sheets, settings, 360p) sent through the
  product's own `contracts.video_gen.build_request` and `video_render.engine.omni.generate`, with only the prompt
  changed: each step of ACTION & DIALOGUE prefixed "[a-bs] ", and the FORMAT line "A single continuous shot, no
  scene cuts." instead of "Ends on a cut." The delivery, listener, register paragraph, CAMERA, SOUND are unchanged.
- The ranges: one gpt-6.1-sol call per shot (the shot prompter's system prompt + the timing rule in `run.py`), given
  the shot's own flow, take length, speech seconds (`speech_s`) and camera timing. Code checks them: 0 to the take
  with no gaps, a line's range ≥ its speech time − 0.5 s, steps ≥ 1 s, whole or half seconds, ≤ one step per 1.5 s.
  ONE repair.
- Measured by `measure.py` (no model): speech start/end from the audio over its floor, scene cuts from frame jumps,
  camera path by phase correlation.

## Results

| Shot | Take | Asked ranges | Speech bursts (audio) | Cuts | Camera path |
|---|---|---|---|---|---|
| 3D-1 (6 s, one line, ~4.5 s of words) | A | none | 1.95-2.2, 2.5-2.8, 3.1-3.9 s (1.95 s in all) | none | 199 px |
| 3D-1 | B | 0-1, **1-5**, 5-6 | 1.75-2.0, 2.85-3.1, 3.8-4.65 s (2.9 s in all) | none | 124 px |
| 3C-1 (4 s, silent, three beats) | A | none | (no speech) | none | 37 px |
| 3C-1 | B | 0-1.5, 1.5-3, 3-4 | (no speech) | none | 42 px |

Frames at 1 / 2 / 3 / 3.9 s, A above B: `runs/<slate>/AB_times.png`.

1. **The line follows its range.** A crammed the 4.5 s line into ~2 s (1.95-3.9 s). B spread it over 1.75-4.65 s,
   ending near the asked 5 s: about 50 % more time for the same words, less rushed.
2. **The beats follow their ranges.** 3C-1 A runs ahead of the plan (Anudi gone by 1 s, Kasun bent by 2 s) and ends
   with a SECOND phone on the ground. B: Anudi still leaving at 1 s, gone by 2 s, Kasun reaching at 3 s, lifting at
   3.9 s, one phone. The timeline matches the asked ranges.
3. **No scene cuts** in any take (A or B); the single-shot line did no harm. The camera moves were still performed.
4. **The agent's ranges were sensible**: 3D-1 needed one repair (it gave a 0.5 s last step); 3C-1 passed first time.

Caveats: one take per arm (Omni varies take to take); the speech measure is audio energy over rain, rough to ~0.25 s;
the "single shot" line and the timecodes were tested together.

## Money

OpenAI $0.0116 of $0.10 (3 calls). Omni $1.00 of $1.20 counted at the 720p ceiling (2 takes at 360p; one 503 "high
demand" from Google on the first try, nothing made, retried).

## Port (proposed, not built)

- `shot_prompter` schema: `Step.start_s`, `Step.end_s`; its prompt gains the timing rule ("Timing" in `run.py`); the
  ban on clock words in the prose stays.
- `steps/shot_prompt.check`: the range checks above (one repair, as today).
- `steps/video_prompt.logic`: each flow step's block prefixed "[a-bs] "; FORMAT "A single continuous shot, no scene
  cuts." instead of "Ends on a cut."
- A stored shot prompt without ranges (made before) is assembled as today (no brackets).
