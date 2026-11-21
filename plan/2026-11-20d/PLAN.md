# One Shot prompt agent writes the first frame and the video together (plan/2026-11-20d)

Revision 1 (2026-11-20). Agreed with the person in chat on 2026-11-20. Building status: IMPLEMENTED.md (phases 0-6 built offline 2026-11-20; 7 lab code only; 8 open).
Builds on plan/2026-11-20c (the Camera agent, built) and replaces parts of plan/2026-11-20b (the video prompter).

Why: the first-frame prompt and the video prompt are written apart, by different code and agents at different times,
from overlapping facts. The frame is drawn at eye level while the video says "low angle"; a person faces left in the
frame and front-on in the take; nothing marks a frame out of date when the camera changes. The person asked for ONE
agent that writes both, "more connected and error free … aware of both".

Proof, read first: `lab/shot_prompts/README.md` (the agent on the person's own scene "SEE AI IN ACTION": 5 shots
written, 4 frames painted, 4 takes; frames carry the Camera agent's angle and opening; every move performed; prompts
consistent) and `lab/camera_moves/README.md` (the Camera agent made cinematic by logic; first-frame renders; an arc
performed when the sentence names the visible result).

## 0. Rules for the chat that builds this

- **No paid call without the person's yes, each time** (model, image, video). Tests run with `OPENAI__API_KEY=` blank.
- **Nothing spends without a click.** A change that makes a frame or a prompt out of date MARKS it (with the reason
  and a Redraw / Rewrite button); it never redraws or rewrites by itself.
- **No enable switches** (the person, 2026-11-20): the agent runs whenever a model can be called.
- **Only Shot Planner Raphael stays.** Do not build for Adam, David, Jonathan or DaVinci; ignore their test failures.
- **Never write or translate a spoken line.** The agent refers to lines by id; code puts the exact words in.
- **Never name camera gear** in any prompt (the models draw it).
- **Both trees have uncommitted work** (plans 20b and 20c are built and uncommitted). Read `git diff` of a file before
  you edit it. Never stash; use a worktree to compare.
- **The labs are the reference.** Port `lab/shot_prompts/system.md`, its `check()` and its assembly, and
  `lab/camera_moves/system.md`; do not rewrite them from memory. Where this plan and a lab differ, this plan wins.

## 1. What the person asked for

1. **One agent writes both prompts of a shot**: the first frame (a still for the image model) and the video (for
   Omni, starting from that frame). Both come from ONE opening state, so they agree.
2. **It replaces** plan 20b's `video_prompter` and the prompt writer's first-frame rewording (`design.frame_polish`).
3. **When the camera changes the picture** (angle, height, framing, lens, composition, opening), the first frame is
   marked out of date with a Redraw button; nothing redraws by itself.
4. **The Omni request stays as it is** (confirmed 2026-11-20): first frame + each person's face and look sheets as
   references, attached in the order the prompt names them ("Image 1 is the opening frame…", "Image 2 is the face
   sheet for …"), plain-language citations, task `reference_to_video`; plus Google's closing line.
5. **The Camera agent gets the camera_moves logic**: cinematic by moment, intensity and power; angle and height by
   power; sentences that name the visible result (section 6).

## 2. Decisions

| # | Decision | Why |
|---|---|---|
| D1 | New agent `shot_prompter` (`libs/hiru_ai/agents/shot_prompter/`) + new pure step `shot_prompt` (`libs/hiru_ai/steps/shot_prompt/`: brief, checks, frame assembly, store). The `video_prompt` step (20b) stays for the VIDEO assembly, the packet rules (D5/D6 of 20b) and the line pairing; it takes the new agent's video part | The house pattern; reuse what 20b built and proved |
| D2 | Tier `shot_prompter` in `core/models.yaml`: `gpt-6.1-sol`, effort `medium`, timeout 120 s, retries 1, structured output, max output 12,000 | The lab's model/effort; $0.01–0.02 a shot |
| D3 | **One answer, three parts**: `opening` (each person in frame: side, facing, posture, hands, expression; background; light), `frame` (`composition` with camera HEIGHT and ANGLE in physical words and the framing at the move's START, `people`, `background`, `light`; no motion), `video` (`situation`, `people`, `flow` of action/line steps with `to`/`how`/`listener`, `sound`). The video's camera line stays code's (the Camera agent's sentence, plan 20c D13) | `lab/shot_prompts/system.md` |
| D4 | **When it runs**: (a) **"Draw first frame"** (the click): if the shot has no current shot prompt, the frame job calls the agent first, stores the result, then paints; (b) **"Generate video prompt"**: if the stored shot prompt is current, the video is assembled from it with NO call; if only the video part is out of date (D8), ONE call in **video-only mode** with the stored `opening` and `frame` given as fixed; (c) **"Rewrite prompts"** on a shot, and the scene's "Write prompts for all shots" (the old batch button), call it for each shot | One click, one cost; the video always starts from the frame that was drawn |
| D5 | **Storage, no migration**: `shots.design.shot_prompt` = `{opening, frame, video, pins, model, job_id, written_at}`. The frame part REPLACES `design.frame_polish` as the words `contracts/frame_brief.frame_prompt` uses for its composition, people, background and light sections; code keeps the style line, the reference citations, the identity lines (cards + looks), hands, the place, the rules and the format. The video part feeds the `video_prompt` assembly; each "Generate video prompt" still writes a NEW `video_prompts` version (as today) | The frame brief already merges an agent's words into code's sections (`polished=True`); no new column |
| D6 | **Checks** (port `lab/shot_prompts/run.py check()`): the opening's people = the shot's people in frame; frame and video name every one of them on the SAME side; the Camera agent's angle is said in physical words in `frame.composition`; the planner's opening size is said; a still has no motion words; no gear; no Sinhala, line ids or quotes in the agent's text; every line of the clip once, in order; no speech in a silent clip (negations such as "Nobody speaks" are allowed); safe depiction; NEW: no clock or edit words in the video text ("three-quarters of a second", "six-second shot", "handle", "cut"). A failed answer gets ONE repair; still failing → nothing stored, the job's WARNING names the faults, the old prompt/frame stay | The lab's gates; the two slips the lab saw |
| D7 | **Assembly fixes** found in the lab: a shot with NO people writes no face/look-sheet sentence and no "Who they are" line; a delivery phrase is lower-cased after "to X," | `lab/shot_prompts` 2D-1 and 2B-1 |
| D8 | **One picture pin, two out-of-date rules.** `Pins` gains `picture` (a hash of the camera fields that shape the still: framing/opening size, angle, height, lens, aperture/focus, composition, axis, `opens_on`, lighting; plus the shot prompt's `opening`) and `motion` (move, speed, timing, trigger, `lands_on`, end size, the camera sentence). A FRAME is out of date when `picture` moved: "The camera changed: angle eye level → low; height eye → hip" (named fields, before → after). A VIDEO PROMPT is out of date when `picture` or `motion` moved, or a line's words/delivery changed. A shot prompt is out of date when `picture`, `motion`, the script hash, the cast or the looks moved | The person: "it should be re-rendered if angle or framing or height changed"; a move-only change keeps the frame |
| D9 | **Redraw, never automatic**: the frame card shows the reason and its existing Redraw action; the scene gets "Redraw out-of-date frames (n)" with a count. A Camera agent run, an Ask Camera, or a person's camera edit only marks | "Nothing spends without a click" |
| D10 | **The Omni request** (`contracts/video_gen.build_omni_input`, `video_render/engine/omni`) is unchanged except Google's closing line after the citation block: "Use the images as references to generate the video." (Google's reference-to-video template). A test holds the attached order = the "Image n" order | Confirmed correct 2026-11-20; Google's docs: plain language, tags deprecated |
| D11 | **Removals**: `agents/video_prompter/` (its system prompt's drama rules move into `shot_prompter`), the prompt writer's FIRST-FRAME path (`polish_frame`, the `frame_prompt` job mode, `design.frame_polish` reads after D5 lands; the writer agent itself stays only if something else still uses it, else removed), and their manifests, evals, catalog rows | The person: replace, not patch |
| D12 | **Cost rows**: estimate `shot_prompt` $0.02 a shot (replaces `prompt` $0.01 and the frame polish). Admin price list only; never in the UI | The lab: $0.007–0.023 a shot |
| D13 | **Line parts** (plan/2026-11-20): a shot planned in parts is briefed with its part ids and the part's exact words (as `video_prompt` does today); the agent's `flow` uses the part ids | `lab/shot_prompts`: the person's scene is planned in parts |

## 3. The agent

`libs/hiru_ai/agents/shot_prompter/`:
- `component.yaml`: `id: shot_prompter`, `kind: agent`, `model: shot_prompter`, `shape: structured`,
  `phase: shot_prompter.write`, middleware as `video_prompter` had (`static_first, usage, untrusted_text,
  absent_safe`), `writes_dialogue: false`.
- `prompts/system.md`: `lab/shot_prompts/system.md`, plus the video prompter's cards (`dialogue`, `phone`, `silent`,
  `detail`, `sinhala_voice`) picked by the step as 20b does, and the safe-depiction line word for word.
- `schema.py`: `Person`, `Opening`, `Frame`, `Step`, `Video`, `ShotPrompts` (the lab's); `Input` = `scene` (cache
  prefix, the same for every shot of the scene), `shot` (the facts), `camera` (the Camera agent's design for the
  shot), `cards`, `mode` (`both` | `video_only`), `fixed` (the stored opening + frame in video-only mode), `repair`.
- `evals/`: the lab's five answers (2A-1 two-shot dialogue push, 2B-1 low-angle push, 2H-1 pull back, 2I-1 reaction
  hold, 2D-1 screen insert) as cases.

## 4. Phases

| # | What | Done when |
|---|---|---|
| 0 | Read-only: every reader of `design.frame_polish`, `video_prompter`, the `frame_prompt` / `prompt` job modes, `Pins`; where "Generate video prompt" and "Draw first frame" start; the scene batch buttons; how a frame's Redraw reads its reasons | A list in IMPLEMENTED.md |
| 1 | Contracts: `Pins.picture` / `Pins.motion` + the field-diff reason text (D8); Google's line (D10) + its order test | Tests |
| 2 | Agent `shot_prompter` + tier + evals | Offline tests |
| 3 | Step `shot_prompt`: brief (scene, shot facts, the camera design, line parts), checks (D6), store (D5), the frame sections for `frame_brief` (replacing the polish merge), assembly fixes (D7) | The lab's five answers pass; good/bad pair per check |
| 4 | Wiring (D4): the frame job calls the agent before painting when needed; "Generate video prompt" assembles from the stored part or runs video-only; "Rewrite prompts" per shot and per scene; out-of-date marks from Camera agent runs, Ask Camera and camera edits (D8, D9) | System tests with a scripted model |
| 5 | Removals (D11), cost row (D12), catalog regenerated | Full suite: no new failures |
| 6 | Interface: the frame card's reason text for camera changes; "Redraw out-of-date frames (n)" on the scene; the prompt pane shows the opening state and the frame text beside the video prompt (read-only); "Rewrite prompts" | `npx next typegen && npm run check && npm run format:check` |
| 7 | **Camera agent update** (section 6) in `lab/camera_moves` first, then ported | The lab's checks pass on the chase, Ekama S03 and the person's scene |
| 8 | **Live (paid, the person's yes each time)**: one scene end to end in the product (Raphael → Camera agent → Shot prompt agent → frames → takes), at 360p | Frames carry the design; takes start near the frame and move as designed |

## 5. What stays the same

- The Camera agent (plan 20c) designs the camera for the whole scene; this agent turns one shot's design into the two
  prompts. The video's camera line is the Camera agent's sentence (or code's after a person's edit).
- The image model call (`adapters/images.OpenAIImages`, gpt-image-2, references = sheets + location plates), the
  frame inspection, black plates, boards and drafts.
- The Omni request shape and task (D10), the take flow, versions of prompts and frames.

## 6. Camera agent update (from lab/camera_moves)

1. **Cinematic by logic**: for each clip the agent names the dramatic MOMENT (reveal, confrontation, realisation,
   pursuit, arrival, departure, isolation, intimacy, threat, tension, establishing, transition, dialogue), its
   INTENSITY 1–5 on the scene's arc, and who holds the POWER; the move, angle and height follow from the moment table
   in `lab/camera_moves/system.md`. Bold moves (whip, dolly zoom, crash zoom, orbit, dutch, urgent handheld) only at
   intensity 4–5; the scene's peak gets its strongest camera (checked). Not limited to a restrained drama style.
2. **Angle and height by power**, set per setup; shot/reverse tells the power story; at least one setup off eye
   level in a scene with a turn or a power shift (checked as a share, per 20c deviation 5).
3. **Sentences name the visible result** ("the office sliding past behind them", "the view rises until she is small"):
   measured, a sideways drift without it rendered still, an arc with it moved 126 px. Every sentence has "the camera"
   as its subject.
4. **Variety counted by family** (push_in + push_then_hold + slow_creep are one family), not by move name.
5. **The Omni table**: arc/lateral → measured works (with a visible result); pushes and pull back from a first frame →
   works; floats/shakes/sideways drift → render still.
6. **Open**: does the production's own camera direction ("Locked-off frames" for Ekama's village) win over
   cinematic-first? The lab obeyed it (16 holds of 17). The person decides (Q1).

## 7. Not in this plan

- Making Omni open on the EXACT first frame: in `reference_to_video` the frame is a strong reference and the take
  re-fits it slightly for the move (wider before a push, tighter before a pull). The person accepted this as the right
  mode (2026-11-20).
- A last frame (20c deviation 4).
- Raphael's own prompts.

## 8. Open for the person

- **Q1**: the production's own camera direction vs cinematic-first (section 6.6).
- **Q2**: in video-only mode (D4 b), when the frame was drawn from an older shot prompt, rewrite only the video (keeps
  the frame, proposed) or offer "Redraw frame too"?
- **Q3**: the scene batch "Write prompts for all shots": keep it (one click, ~$0.02 a shot) or only per shot?
