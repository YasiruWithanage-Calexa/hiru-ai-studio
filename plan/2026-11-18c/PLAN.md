# Action budget: a clip holds what a video model can do (plan/2026-11-18c)

Revision 2 (2026-11-18). Phases 1 to 4 and 6 to 8 are BUILT offline (uncommitted, see
[IMPLEMENTED.md](IMPLEMENTED.md)). Phase 9 waits for takes; phases 5, 10 and 11 are paid, the person's. The lab that proved it is `lab/action_budget/` (read its `README.md`; $0.75 spent). Follows
[plan/2026-11-18b](../2026-11-18b/PLAN.md) (accidents as coverage): this plan is the general rule, 18b the first case.

## 0. Rules for the chat that builds this

- **Only Shot Planner Raphael stays.** Adam, David, Jonathan and DaVinci are being removed: do not build for them.
- **No paid call without the person's yes, each time** (model, image, video). Tests run with `OPENAI__API_KEY=` blank.
- **Raphael owns the breakdown** (the person, 2026-11-18). An over-budget clip is a BLOCKING fault Raphael must fix,
  not a warning someone else acts on.
- **The budget counts actions, never seconds** (the person, 2026-11-18). A clip lasts as long as its actions take.
- **Other work is uncommitted in the same tree.** Read `git status` / `git diff` of a file before editing it.

## 1. What happened

Love Hour 4, "Anudi arrives", shot 02 (2B-1): one 8 s wide in which the car stops, she loops the bag, takes the
umbrella, the rear door opens, she steps out, closes it with her forearm, nods and walks off. The video model:
- got out of the FRONT door, or opened the other back door, take after take;
- was also given a first frame that framed her in the FRONT door's window.

The phone drop of Api Denna E01-S03 (plan/2026-11-18b) failed the same way: too much in one clip.

## 2. The budget

| Kind | What | Examples |
|---|---|---|
| **hard** | a change of state the model must invent | a door opens or closes, gets out of a car, sits down or stands up, takes, puts, passes, pours, drops or falls, an umbrella opens, a vehicle stops |
| **move** | a simple visible movement | walks off, turns, looks, nods, smiles, leans, reaches |
| state | something carries on; not counted | keeps, remains, still in her hand, continues |

A clip is OVER when any of these holds:
1. it has more than **1 hard** action;
2. it has more than **3 actions** in all;
3. it has **a hard action while someone travels** (walks, runs, continues right).

A moment that needs more is several clips joined by the cut, and the next clip **opens on the result**: the door
already open, the cup already in his hand.

Two more blocking faults ride with it:
- **A door left open.** A door is opened (or already open) in one clip and closed in none: nobody walks away from an
  open car door.
- **A speaker turned away.** A clip with a spoken line opens with the speaker turned away. Its first frame has no face,
  and the first frame is the video model's picture of that face.

## 3. What the lab showed (`lab/action_budget/`)

| Step | Cost | Result |
|---|---|---|
| Count 572 Raphael clips (6 productions + Api Denna lab plans) | $0 | 40 over (7 %). All 5 cases the person judged agree: the car exit, the umbrella mid-walk and the phone master are over; the coverage insert and walk-on fit |
| Re-plan Api Denna E01-S02 + E01-S01 with the rule and the blocking check | $0.37 | 0 over. The car exit became: the car stops / she gets out by the already-open REAR door / nod and walk. The umbrella and the pour each got their own clip |
| Re-plan E01-S02 with "nothing half done" + two boards | $0.38 | 0 over. She closes the rear door herself (2C-2) before the umbrella and the walk; the board paints the REAR door |

The boards showed three more faults:
- **Rain in every panel.** It rained from the first panel of E01-S02, although the script starts it at the umbrella. The
  product's first frame of the real shot 02 had the same fault (section 4).
- **Kasun's line painted from behind.** Raphael opened the clip with Kasun turned into the vehicle (section 2).
- **Panel 8 painted from behind.** The writer asked for three-quarter, but the faceless mannequin read as a back
  (phase 10).

## 4. Found on the way: where the rain came from

| Where | Cause | Fix (built) |
|---|---|---|
| First frame (`contracts/frame_brief.py`) | the weather was read from the sequence's colour script ("the same sky supports the first sparse rain in the final moment"), which speaks for EVERY shot of the sequence, so the dry arrival got "Weather: rain" | weather from the shot's own words and its clip's sound only |
| Board picture (`contracts/board.py`) | "the same people, props, weather, light and colour grade in every panel" | the weather and the ground are as each panel says |
| Board writer (`agents/board_writer/prompts/system.md`) | `world` (shared by every panel) carried the weather, change included | a rule: weather that changes during a scene is said in every panel's background ("dry pavement, no rain" / "fine rain falling, wet pavement"), never in `world` |

## 5. Phases

| Phase | What | State |
|---|---|---|
| 1 | Lab: counter, corpus, re-plans, boards | **built** 2026-11-18 ($0.75) |
| 2 | `contracts/action_budget.py`, the blocking `checks.action_budget` in stage 1 (stage 2 runs it on the whole bin), house rule H-16 (topic `coverage`: Raphael planner + cinematic), tests | **built** 2026-11-18 |
| 3 | The rain fixes of section 4 (frame brief, board prompt, board writer), tests | **built** 2026-11-18 |
| 4 | Door left open + speaker turned away: H-16 text and the same blocking check | **built** 2026-11-18 |
| 5 | Prove it in the product: plan Love Hour 4 "Anudi arrives" again with Raphael and look at the board | open, **paid, the person's** |
| 6 | Sable and Zora: their edit tools run `contracts.action_budget` on the edited clip and say the fault back (a person's own edit only warns) | **built** 2026-11-18 |
| 7 | Interface: a warning chip on an over-budget shot, and a line in the video prompt's checks ("Actions within budget" or why not) | **built** 2026-11-18 (both repos) |
| 8 | Take reject reasons in the interface (wrong action, too many actions, object vanished, camera moved), so the budget is tuned from real takes | **built** 2026-11-18 (both repos) |
| 9 | Budget per video model (Veo 3.1, Omni Flash 1.1 / 1.2) in config, once takes show a difference | open: waits for takes that show a difference (phase 8 collects them) |
| 10 | Board mannequins whose head direction reads (a faceless head tipped down reads as a back): test a face marker in the board lab | open, paid lab |
| 11 | Render the split car exit (2B-1 / 2C-1 / 2C-2) and read it against section 1 | open, **paid, the person's** |

plan/2026-11-18b phase 7 (report-only checks for an accident in one clip) is covered by phase 2 here, and blocking.

## 6. Decisions

| # | Question | Answer |
|---|---|---|
| D1 | Blocking or report-only? | **Blocking**: Raphael owns the breakdown (the person) |
| D2 | Seconds or actions? | **Actions** (the person) |
| D3 | The numbers (1 hard, 3 in all, no hard while travelling) | provisional: from the person's takes of two scenes; phase 8/11 tunes them |
| D4 | Beat labels (Raphael tags each beat hard/move) on top of the counter? | not built: the counter alone matched every known case and the re-plans. Revisit if the counter misses in practice |
| D5 | A door opened off screen (the cut skips the opening) | accepted in the lab's re-plan (2C-1 opens "beside the already open rear door"); the closing is on screen. **The person's to confirm** |

## 7. Known limits

- The counter reads Raphael's English, not the picture. It is tuned on 572 clips and 5 judged cases. It missed
  "arranges one short eat into the display" (a small put) in the lab.
- When Raphael cannot fix a fault, the existing "stuck" rule stops it after a few reports with no progress. The plan is
  kept and the job carries the fault, the same as any other blocking fault.
- The speaker check reads the clip's opening words ("initially facing into the vehicle"). A turn written another way is
  not caught.
