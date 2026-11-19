# Accidents as coverage: shoot a small accident the way TV dramas do (plan/2026-11-18b)

Revision 2 (2026-11-18). Phases 1 to 8 are BUILT, found or covered offline (uncommitted, see
[IMPLEMENTED.md](IMPLEMENTED.md)); phase 9 (paid) is the person's. The lab that proved it is `lab/coverage/` (read its `README.md`; $0.26 spent). Read this file whole
before building anything here.

## 0. Rules for the chat that builds this (read before anything)

- **Only Shot Planner Raphael stays** (the person, 2026-11-18). Adam, David, Jonathan and DaVinci are being removed:
  do not test them, do not build for them, ignore their test failures.
- **No paid call without the person's yes, each time** (model, image or video). Tests run with `OPENAI__API_KEY=`
  blank and fakes only.
- **Two serializer copies.** `src/libs/hiru_ai/steps/serialize/` (the graph engine) and
  `src/services/shot_producer/shot_producer/engine/` (legacy) must write the same prompt: `tests/hiru_ai/
  test_steps_parity.py` and `tests/parity` compare them. Change both, or the parity tests fail.
- **Parity recordings**: `PARITY_UPDATE=1 pytest tests/parity -k <case>` re-records; read the diff before keeping it.
  On 2026-11-18 the graph `frame_render` cases were already failing (other work): never re-record them blindly, the
  recording would keep a failed frame.
- **Other work is uncommitted in the same tree.** Read `git status` / `git diff` of a file before editing it.
- **A rule is guidance, a check is code.** What must hold whatever a model writes belongs in code; a house rule says
  how to plan.

## 1. What happened: five Omni Flash takes of one phone drop

Api Denna, Episode 1, Scene 3: Anudi walks past Kasun's three-wheeler in the rain, tries to put her phone in her
handbag, it slips and falls, she does not notice and walks on. Five Omni Flash takes of the shot, read by the person:

**What it got wrong**

| Failure | What we saw |
|---|---|
| Safety lines beat the action | "each hand keeps its own, neither is put down" and "objects stay put" won over the drop: in takes 1 and 2 Anudi stopped, and the phone appeared on the ground without ever falling |
| The first frame beats the text | an open umbrella in the image and "closed" in the text: the model did not close it, it deleted the umbrella within half a second (take 3) |
| Camera words in the action freeze people | "unchanged", "hold composition", "tableau" inside the action beats made her stop and stand |
| The camera drifts unless told firmly | "locked-off" alone still gave a slow push-in (take 3); it held only after "mounted on a tripod, does not move at all: no push-in, no pan, no drift" |
| A hand action pulls the eyes down | tucking the phone into the bag made her look at the bag, so she seemed to see the drop (take 4); a place to look (up the road for a three-wheeler) fixed it (take 5) |
| Empty time becomes a pause | any stretch with no action she filled by stopping, which reads as "she noticed"; she needs an exact exit time |
| Small objects disappear | the phone landed, stayed visible about 0.7 s, then vanished (take 5): small, dark, on dark wet ground near the drain |
| The drop has no motion | phone from hand to ground with no visible slip (take 3): "it slips" is not enough, it needs a physical cause (half into the pocket, it tips out as the bag swings) |
| One clip cannot hold all the beats | walk, tuck, look away, slip, keep walking, phone stays: too many things for one 6 s generation |

**What it handled well**: faces, wardrobe, location, rain and light stayed true to the first frame in every take;
Kasun stayed put; the umbrella held once the prompt matched the first frame; moving her gaze to the road worked.

## 2. The workaround: coverage, the way TV dramas shoot it

Real dramas almost never catch a small accident in one wide shot. They break it into coverage and let the edit sell
the moment. Each generation gets one simple job, which is exactly what avoids the weak spots above.

1. **Insert close-up of the accident itself**: only the hand, the bag and the phone, 2-4 s. The prop is big in the
   frame so the model cannot lose it, and the slip has the whole shot to itself, with a physical cause.
2. **Wide (or medium) of the reaction or non-reaction**: she walks away and never looks back. The prop is **already on
   the ground in the first frame**. A prop that exists from frame one stays put far more reliably than one the model
   has to create mid-shot. She has something to do, somewhere specific to look, and an exact exit time.
3. **Optional lingering shot on the prop**: the phone alone on the wet pavement, static, 2 s. Easy for the model, and
   the classic drama beat that says "she's going to miss this".
4. **Let the cut do the work**: shot 1 shows the drop, shot 2 shows she did not notice; the viewer joins them.

**General rule for the team**: if a moment depends on a small object, a precise cause and effect, or a character NOT
reacting, split it into insert + wide instead of asking for it in one take. One action and one camera setup a shot,
2-4 s. Any beat where something is dropped, slipped, passed, spilled or knocked over is planned as coverage from the
start, not fixed afterwards.

How to work with the limits, in every prompt:
- the text never contradicts the first frame;
- no safety line in a shot that has an accidental action;
- no camera note in the action beats;
- a timed exit and something to look at;
- key props large in the frame (see D3 on colour);
- compound moments split into insert + wide, the prop already in the first frame of the second shot.

## 3. Where our own prompts caused it (found 2026-11-18)

Most of section 1 was not the model alone: our serializer wrote the contradictions.

| Failure | Our cause (before the fix) |
|---|---|
| Safety lines beat the drop | `physics` put "Objects stay put unless someone deliberately moves them" in EVERY shot (`serialize/logic.py` `_guard`); `contracts/holding.py` said "each hand keeps its own, neither is put down" in the same prompt as "During the shot Anudi lets go of the smartphone" |
| Camera words freeze people | `_beats_section` put each beat's camera note in front of its action; only the exact word "unchanged" was dropped ("WIDE unchanged, grounded phone remains visible" got through) |
| Locked-off drifts | the static camera said "Static: a steady, locked-off frame" only |
| The action happens twice | `raphael_write` gives every shot even windows (0-3 / 3-6 s); `fit_beats` filled each window with the beat that overlapped it most, so a long middle beat filled BOTH windows (the phone fell twice, Kasun picked it up twice) and the short beats ("the phone rests on the roadside") were lost |
| The text contradicts the first frame | when two clips play the same script block (the insert and the walk-on), the hands ledger gave the walk-on the state from BEFORE the drop: "Anudi holds the smartphone ... lets go", over Raphael's "the phone already lies on the road"; the first frame (`frame_compose`) read the same ledger |
| Too many beats in one clip | Raphael was free to put walk, tuck, slip and walk on in one 6 s master |

Found on the way, same scene:
- "During the shot Kasun takes the anudi": the stager wrote "smartphone, held out toward Anudi" and the ledger read
  "Anudi" as a thing.
- A rain scene with no rain: Raphael's `silence: true` (meaning "nobody speaks") became "Silence, no room tone".
- "Day, window light" on an open road: the heading ("SCENE 03 - THE UNEXPECTED ENCOUNTER") names no INT or EXT, so the
  lighting preset guessed interior.
- "music: None.." and ".." in the sound and grade lines.

## 4. What the lab showed (`lab/coverage/`)

Api Denna v2 (`~/Downloads/Api_Denna_Script_v2.pdf`), E01-S03, from the saved breakdown memory and packet of
`lab/llm_reader/runs/e2e`. Nothing written to the database.

| Arm | What | Cost | Result |
|---|---|---|---|
| `today` | the saved Raphael plan through today's serializer | $0 | all 7 shots had a problem: 2 contradictions, camera words in 5, actions twice in 2, soft static camera in 7, the drop compound in one wide |
| `today` + fixes | the same plan, serializer fixed | $0 | 5 of 7 clean; left: the plan itself (walk + slip + "without looking" in one wide), which code cannot fix |
| `coverage` | Raphael re-plans with the rule (then H-90, now H-15) | $0.17 | the drop split: **3A-1** insert 6 s (the rim catches the phone, the bag swings, it tips out; ends on the phone alone on the road), **3B-1** medium 4 s (the phone already on the road, eyes up the road, exits right at 3.5 s); all 8 prompts clean with the fixes |
| board | the coverage plan's Scene board at LOW | $0.09 | shot 2 shows her walking on with the phone already on the road behind her: the split reaches the picture |

The board is `lab/coverage/runs/coverage/board/sheet.png`.

## 5. Phases

| Phase | What | State |
|---|---|---|
| 1 | Serializer and ledger fixes, both copies (section 3) | **built** 2026-11-18 |
| 2 | House rule H-15 "Accidents are coverage", topic `coverage`, Raphael planner + cinematic only | **built** 2026-11-18 |
| 3 | Tests (`tests/raphael/test_accident_coverage.py`), parity re-recorded, lab README, this plan | **built** 2026-11-18 |
| 4 | Shot order: a stage-2 clip whose blend note says it OPENS a moment ("Open moment 1 before c01") is ordered before its anchor, not after. On the board the establishing wide is shot 3, between the walk-on and the pickup | **built** 2026-11-18 |
| 5 | Board writer state: in the two-shot (3E-1) Anudi is painted still walking right; the plan says she has stopped and turned left. Check what the writer reads for a person who turns inside a shot (the opening state vs the action) | **found** 2026-11-18: not a fault (the panel is the opening picture; see IMPLEMENTED.md) |
| 6 | Handbag side: the plan says left shoulder, the board shows right. Find whether the stager, Raphael's geography or the board writer drops it | **found + writer rule** 2026-11-18; paid board to prove |
| 7 | Report-only checks in Raphael's code checks: an accident block (drop, slip, spill, knock, pass) planned in ONE clip together with the person moving on; a camera word in a beat's action; a "does not notice / without looking" negative with no gaze target or exit time. Reported back to Raphael like the other checks, never blocking | covered, **blocking**, by plan/2026-11-18c phase 2 |
| 8 | Sable and Zora edits keep the split: an edit that moves or merges the walk-on must keep or clear `card.after` correctly (today only `raphael_write` sets it) | **built** 2026-11-18 |
| 9 | **Live proof**: render 3A-1 and 3B-1 in Omni Flash from the coverage plan and read them against section 1 (the phone stays, she does not stop, the camera holds) | open, **paid, the person's** |

## 6. Decisions

| # | Question | Answer |
|---|---|---|
| D1 | Raphael splits accidents on its own, or only suggests it? | On its own (built as a `default` house rule: a production's direction can override it) |
| D2 | Omni Flash only, or every video model? | Every model: the contradictions were bugs whatever the model |
| D3 | Make key props large or brightly coloured? | Large: yes, by the insert. Colour: **open, the person's**. Changing a story prop's colour changes canon; today we leave canon alone |
| D4 | Edit the prop into the walk-on's first frame with Nano Banana or similar? | Not needed so far: the state ledger puts the phone on the road in the walk-on's first frame (fix 5); revisit after phase 9 |

## 7. Known limits of what is built

- `mark_after` marks only a MUST clip whose blocks an earlier must clip plays, ending on the same block, where the
  ledger has a change inside those blocks. A split the planner makes another way is not marked (phase 8).
- `fit_beats._placed` leaves a window empty when no beat lands in it (a long 0-6 s beat on 0-3 / 3-6 windows fills the
  first only); the prompt then skips that window. Better than saying the action twice; worth watching in phase 9.
- The lighting change is general: every prompt where the planner wrote its own light now says "Day: <light>" instead
  of "Day, window light: <light>" (also first frames). The preset's source half was a guess from the heading.
- The tripod sentence is added to every static shot, in both serializers.
