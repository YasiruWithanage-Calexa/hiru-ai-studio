# Camera agent lab (2026-11-20)

ONE reasoning agent decides everything the camera does for a whole scene; the planner keeps the story (size, people,
action, lines, take); code checks the answer. Why: takes come out static (Raphael writes most coverage `locked_off`, the
panel knows 5 moves and maps everything else to Static, the prompt says "a steady, locked-off frame").

- `system.md`: what the agent knows (alive by default, motivated moves, lip-sync safety, cut grammar, fields, the
  camera sentence rules).
- `omni.md`: what Omni 1.2 does well / risky. PROVISIONAL: not measured with renders.
- `run.py`: brief (scene + every clip in cut order) -> gpt-6.1-sol medium, structured answer -> code checks -> one
  repair -> report. `--ask <slate> --note "..."` redoes one clip with the scene's answer as context. Dry by default;
  lab cap $1.00 across all runs (`runs/spend_total.json`).

Scenes: Api Denna v2 E01, Raphael's saved runs, loaded through lab/video_prompt (nothing in src/ changes).

## Runs (2026-11-20): $0.159 of $1.00

| Run | Clips | Spent | Time | Checks | Today (panel) | Agent |
|---|---|---|---|---|---|---|
| E01-S04 scene | 18 | $0.087 | 90 s | 0 faults, no repair | 18 Static | 1 hold, 12 breathing/drift, 5 moves |
| E01-S04 ask 4C-1 | 1 | $0.038 | 16 s | 0 faults | | drift -> visible slow push MS -> MCU |
| E01-S02 scene | 7 | $0.035 | 43 s | 0 faults, no repair | 7 Static | 1 hold (car mount), 3 breathing/drift, 3 moves |

Read `runs/<scene>/report.md` (today's panel and prompt camera vs the agent's, clip by clip).

## Found

- Today's panel is Static on EVERY clip of both scenes, including the clips Raphael planned to move (S04 4G-1
  slow_creep, 4I-1 dolly_out; S02 2C-1 tracking, 2E-1 tracking, 2F-1 lead). Their prompts say "Static: a steady,
  locked-off frame. As planned: tracking..." (the contradiction).
- The agent designs the scene, not clips: S04 eases closer as interest grows, stops dead on the caller display (4J-1),
  gives the strongest push to the father's demand (4E-2), pulls out at the end. S02 holds inside the car, then tracks
  and leads her walk in the rain. The "Ask Camera" redo kept the scene logic ("without rivaling the later call").
- TOO TIMID: 12 of 18 S04 clips are "breathes very gently / almost imperceptibly". Omni may render that as static,
  which is the problem we started with. Needs a stronger default (a visible operated float) or an energy setting, and a
  render to see what Omni does with each wording.
- Camera sentences re-tell the action and add non-camera rules ("exclude mirrors", "no people enter the frame"): they
  may clash with the video prompter. In the product the sentence should be camera only, anchored to what happens.
- The agent changes lens/stop (50 -> 65 mm, 85 -> 100 mm): the frame brief must use the agent's lens, or the first frame
  will not match the move.
- Size list needs MWS (S02 2C-1).
- Reasoning tokens are tiny at medium (82-288): the answer is mostly direct writing.

## Run 2 (2026-11-20, after the fix): E01-S04 again, $0.084, 77 s; lab total $0.244

Fix: dialogue default is a VISIBLE handheld float ("never 'imperceptible'"), at most 1 hold in 5, at least a third of
the clips with a real move, sentence camera only and at most 200 characters, keep the planner's lens; code checks each
(timid words, picture rules in the sentence, hold and move shares). Run 1 kept in `runs/E01-S04_run1/`.

- 0 faults first time. 1 hold (the caller display), 10 visible floats/drifts, 7 real moves (was 5): push in on her
  curiosity (4C-1, MS -> MCU), push in on his story (4B-2, MCU -> CU), push in through the father's demand (4E-2),
  creep (4G-1, 4L-1), a short move left with the phone (4K-1), pull out at the end (4I-1).
- Sentences are short and camera only, in words a video model acts on: "Eye-level waist-up two-shot, subtle handheld
  camera gently floating and swaying through the handover and thanks". No "imperceptible" anywhere.
- Lens "changes" are the lab's list, not the agent: the planner wrote 40mm, 32mm, 75mm, "85mm macro", which are not in
  the lens list, so the agent had to pick the nearest. The product list needs those (or the planner's lens kept as is).
- Left: sentences still use edit words the video model does not know ("handle", "before the cut", "through the middle
  two seconds"). Next fix: ban them, say it by what happens on screen.

## Run 3 (2026-11-20): the cinematography knowledge base as the toolbox; lab total $0.387

`kb.py` reads src/libs/hiru_ai/knowledge_bases/cinematography/sources (629 terms; nothing written): A) `<moves>`, one
line per catalogue move with its effect and use case from the base (6 moves the base lacks are written in `OWN`);
B) per clip, 4 "ideas" by keyword search over tags/effect/use case (no Supabase, no embeddings), with ideas that cannot
fit removed (fast moves on a speaking face, aerials off exterior masters, moves longer than the take). Also: lens list
+32/40/75 mm, edit/clock words banned in the sentence (checked), `runs/coverage.md` (moves used across runs).
S04 run 2 kept in `runs/E01-S04_run2/`.

| Run | Clips | Spent | Faults | Held | Floats | Real moves | Took a KB idea |
|---|---|---|---|---|---|---|---|
| E01-S04 | 18 | $0.090 | 0 | 1 | 9 | **8** (run 1: 5, run 2: 7) | 5 |
| E01-S01 | 10 | $0.053 | 0 | 0 | 4 | **6** | 3 |

- New moves where they fit: a pan with the phone (4K-1), a reframe as the ringing phone rises (4D-1), push-then-hold on
  the father's demand (4E-2) and on Kasun's ambition (1E-1), a tilt up with the lifted cup (1I-1, a KB idea), a pan
  into the cramped service area (1D-1), the planner's crane kept as a slow rise (1H-1).
- No edit words left; lenses kept (40/32/75 mm now on the list; only "macro"/"close focus" differ).
- The keyword ideas are weak (truck/tracking offered to people standing and talking, because the "dialogue" tag is on
  the crab shot; whip pan, arc). The agent rejected those and took the good ones (8 of 28). In the product use the
  base's embedding search (`technique_lookup` / TechniqueRetriever), not keywords.
- Across all runs 15 of 51 moves used. Never: arc, follow, orbit, whip, tilt reveal, rising reveal, rack focus,
  aerials... These four scenes are calm talk, routine and a walk; none has a confrontation, chase, reveal or an
  exterior establishing. To see the rest we need a scene that calls for them.

## Renders (2026-11-20): 3 Omni Flash 1.2 takes, 360p, text to video; ceiling $1.80 of the person's $2.00

`render.py`: lab/video_prompt run 003's prompt for the clip, word for word, with ONLY its `Camera:` line swapped for
the Camera agent's sentence (run 3). 4A-2 already had a take of the same prompt with today's camera. Watch
`runs/E01-S04/all_takes.mp4` (24 s: today 4A-2, then the three agent takes, labelled) and
`runs/E01-S04/takes/4A-2/before_after.mp4` (side by side). Frame strips: `takes/<slate>/strip.png`.

Camera motion measured on the background (phase correlation, 8 fps, top 40% of the frame):

| Take | Asked for | Motion | Result |
|---|---|---|---|
| 4A-2 today | steady frame on a tripod | 12 px | still |
| 4A-2 agent | subtle handheld frame gently floating and swaying | 16 px | **ignored: as still as today** |
| 4C-1 agent | slowly pushes toward a medium close-up as she asks | 87 px + MS -> MCU | **clear push** |
| 4E-2 agent | slowly pushes closer as her father's demand unfolds, then comes to rest | 72 px, then settles | **clear push, then hold** |

- Omni performs a NAMED move (push) well and ignores a soft "float/sway". The "living" default for dialogue (half of
  every scene) does not work as written. Try: "handheld camera" stated plainly, or replace the float with a real small
  move (a slow drift sideways, a slow creep in), and measure again.
- 4E-2 opened at a medium shot, not the planner's close-up: text to video has no first frame; in the product the first
  frame fixes the opening size.
- Not camera: Anudi smiles through her father's urgent demand (4E-2); invented logos top right (both 4A-2 takes).
- Lip-sync during the 4C-1 push: listen to the take (not measured).

## Float re-worded (2026-11-20): 2 more 4A-2 takes, ceiling $1.20 (the person's yes)

`render.py --variants`: same prompt, only `Camera:` changed. Watch `runs/E01-S04/4A-2_four_ways.mp4` (2x2 grid).

| 4A-2 camera line | Motion |
|---|---|
| today: "a steady frame on a tripod" | 12 px (the floor: rain, cars, people) |
| agent: "subtle handheld frame gently floating and swaying" | 16 px |
| "handheld camera with a slight natural shake ... never still, like a documentary filmed by hand" | 19 px |
| "the camera drifts slowly sideways to the right through the whole exchange, one gentle continuous move" | 20 px |

All four look still. Omni will not move the camera in this two-person dialogue shot for a float, a shake or a sideways
drift, while it clearly pushes in on one face (4C-1 87 px, 4E-2 72 px). `omni.md` now says so (measured rows). Not
tried: a push or creep on a two-shot; a stronger "clearly visible" sideways move; the same with a first frame
(reference_to_video), which may behave differently from text to video.

## Run 4 (2026-11-20): dialogue default = real slow moves; S04, $0.092, 88 s; lab total $0.479

Instructions: floats render still (measured), so dialogue life comes from slow creeps/pushes/pull-outs tied to the line,
varied; floats count as holds; holds + floats at most 1 in 4; no move on more than about a third; a notice for three
in a row. Run 3 kept in `runs/E01-S04_run3/`.

- 0 faults first time. 3 holds (the phone ringing 4D-1, the caller display 4J-1, the departure wide 4F-1), 0 floats,
  **15 real moves** (run 3: 8): slow creep x5, push then hold x3, pull out x3, push in x2, pan x1, slow pan reveal x1.
- Shape: the camera moves closer through the warm exchange, the strongest push into an ECU on the father's demand
  (4E-2), then it pulls back as her smile fades (4E-3), as she takes her leave (4A-3) and as they part (4I-1).
- Open: 10 of the 15 moves go forward; a push on a TWO-shot is not measured yet (only on one face); small pushes that
  "remain in close-up" (4H-1, 4G-1) may come out as still as the float did. One render of 4A-2 (now push_then_hold on
  the two-shot that stayed still four times) would answer both.

## Render: run 4's 4A-2 (push on the two-shot), ceiling $0.60; Omni ceiling total $3.60

"In an eye-level waist-up two-shot, the camera slowly pushes closer to both of them through his answer and her next
question, then comes to rest." PERFORMED: the first frame shows both full figures, the last frame both waist up and
much larger; it pushes through the first two-thirds and settles. Motion 28 px (sideways part only; a push is mostly
scale). The two-shot that stayed still four times (tripod, float, handheld shake, sideways drift) moves when the
move goes FORWARD. Watch `runs/E01-S04/4A-2_today_vs_push.mp4` and `takes/4A-2_push/first_last.png`.
- It opened wider than the planned waist-up (text to video, no first frame), as 4E-2 did.
- Not camera: a figure sits in the three-wheeler cab behind Kasun (not in the plan).

## Connected run (2026-11-20): fresh Raphael -> Camera agent, S04, no video; lab total $0.884 of $1.00

`connected.py`: the product's raphael_shot_planner on the packet path (both stages, lab/two_memories `raphael_one`,
cap $0.30), then `run.py --raphael <its json>` on that result. Folder `runs/connected_E01-S04/` (Raphael's own json/txt
in `12_raphael/`, the Camera agent's brief/answer/report beside it).

- Raphael: done, 8 calls, 425 s, $0.306; 22 clips (a different plan from the e2e run's 18), 19 of them `locked_off`.
- Camera agent: $0.099, 87 s, 0 faults first time. 18 real moves, 4 holds, 0 floats; 8 different moves: slow creep
  x6, pull out x4, push in x3, push then hold x2, pan right (her look to the business), tilt up (she raises the phone),
  follow pan (he turns back to the business). Holds: the phone insert, the grip ECU, "she quietly agrees", her
  lingering smile.
- Shape: small approaches through the curiosity, the strongest push on the marriage demand (4B-4, MCU -> tight CU),
  then pull-outs as she says goodbye and the scene ends on an extreme wide.
- Limits seen: 15 of the 18 moves are forward/back (by design: measured, Omni ignores floats/drifts; it is a standing
  talk); every clip eye level (angle/height never varied); arc/track/crane not exercised (nothing in the scene asks).
