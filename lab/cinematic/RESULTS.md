# Results of the cinematic lab (plan/2026-11-06)

Status 2026-11-06 (later): phases 0 to 6b done, then a general stabiliser built and tested on five scenes. **$4.04 of $5.00 spent**, 19 paid calls. The first blind read (ChatGPT 9, this lab 7.5, David today 4, out of 10) was on a page that hid the lab's camera detail; on the fixed page the second read is lab 9, ChatGPT 8.5, David today 6, so gate point 2 is met. The stabiliser (draft, then up to two revise passes from code's findings) took every one of five scenes to zero faults and at most one craft gap. The decision (phase 7) is the person's.

## Ledger

`python lab/cinematic/run.py ledger`: $4.04 of $5.00. One extra call is outside it: the real Story Reader on `story.txt`
(phase 6), a few cents at its own `high` tier, not metered by the lab.

## Runs

"Faults" are the hard checks that are not keyword advisories; "reports" are the existing feasibility notes (`mirror`, `screen
text`, `touching`), which only report. Water reflections in a rain scene trip `mirror`, so reports are counted apart.
Kept = the seconds the edit keeps (`use_s`); the guide is 60 s.

| Run | Model, effort | Change | Shots | Kept | Faults | Reports | Craft met | $ |
|---|---|---|---|---|---|---|---|---|
| 1 | nano, low | schema smoke (phase 2) | 10 | 57 s | 34 | – | 5/8 | 0.002 |
| 2 | gpt-5, high | baseline: new prompt + `CinemaWire` | 22 | 94 s | 5 | 1 | 5/8 | 0.27 |
| 3 | gpt-5, high | I1: the length is a budget (within 20%), not "may run longer" | 22 | 75 s | 9 | 6 | 7/8 | 0.23 |
| 4 | gpt-5, high | I2: the author sees `[move]` blocks; the real teleport rule | 19 | 70 s | 5 | 2 | 6/8 | 0.25 |
| 5 | gpt-5, high | I3: thought is no listener shot; heard-only never named; end state complete | 16 | 65 s | **0** | 3 | 3/8 | 0.22 |
| 6 | gpt-5, high | I4: the budget is kept with 2 s cutaways, never with fewer pictures | 22 | 72 s | 1 | 5 | 5/8 | 0.22 |
| 7 | gpt-5, high | stability: run 6 asked again (`--repeat 1`) | 18 | 69 s | **0** | 2 | 5/8 | 0.21 |
| 8 | gpt-5, high | second scene (gold `phone_call`) | 15 | 60 s | 1 | 5 | 5/8 | 0.18 |
| 9 | gpt-5.5, high | flagship: run 6 on `gpt-5.5` | 17 | 66 s | 1 | 2 | 5/8 | 0.69 |

Run 1's 34 problems are the nano model failing the schema's rules; it proved only that the API accepts the strict schema.

## What moved the result

1. **The length rule did the most for the plan's shape.** With "it may run longer" the team wrote 94 s for a 60 s scene.
   Called a budget, kept in `use_s`, it lands at 65 to 75 s. One bad overcorrection (run 5: "do not give a transition its own
   shot") cut coverage to 16 shots; run 6's wording (save time with 2 s cutaways, list what is never dropped) restored it.
2. **The author could not see which blocks move a person.** The teleport check lets a zone change only across a `screen: move`
   block, but the script listing never showed the kinds (the product's `listing` does not either). Showing `[move]` and stating the
   rule took teleports from 3 per run to 0 or 1.
3. **Three rule misreadings were cheap to clear** (run 5): a voice-over *thought* is not a listener shot (the pack called it
   "heard not seen", so the author set `over` on the speaker); "listens to her father" names a heard-only person in the picture;
   the end state forgot the voice-only father. A one-paragraph prompt edit plus a pack label removed all of them.
4. **The model is not the lever.** `gpt-5.5` at $0.69 gave the same shape and one fault of the same kind as `gpt-5` at $0.22.

## Findings that the next plan must carry

- **The teleport rule trades geography for safety.** To avoid a teleport the author put Anudi's car on the stall side ("we've
  staged the car pull-up on the stall side", run 7's advice), though the script says "across the road". A script that gives no
  move between two places is the real fault; the product's answer (an implied `move` step, `bridges.move_block`) belongs
  before David plans, in the reader, not in David's prompt. Run 6 and the second scene still left one teleport each.
- **`end_state.where` must equal the staging zone's name to the letter** ("off screen phone" vs "off screen, on the phone" fails
  run 9). Code should compare loosely or fill it in.
- **The `mirror` and `screen text` advisories misfire on rain** ("reflections" on wet asphalt, "text" inside "context"). They
  only report, but the person sees five of them. `contracts.david.checks` should look at objects, not the word.
- **Reader gaps (phase 6).** The real Story Reader keeps Kasun's thought as a spoken line "to himself" (good) and marks the
  father voice-only (good). The narrator's closing sentence is prose, so it is not a spoken line and nothing in the reading
  keeps it as a narrator voice-over; the database run also split the rain into its own 4 s scene. Both belong to the
  scene-splitting step, not to David.
- `price_of` matched models by prefix, so `gpt-5.5` and `gpt-5-pro` would have been billed as `gpt-5` and the $5 cap would have
  been wrong. Fixed in this lab (exact name or dated snapshot only); the same pattern is worth a look in `scripts/david_spike.py`.

## The gate (plan §7)

| # | Point | Met? |
|---|---|---|
| 1 | Zero hard problems in Episode 1 and in the second scene | **Partly.** Runs 5 and 7 have zero faults on Episode 1; runs 6 and 9 have one each (a teleport; a zone-name mismatch). The second scene has one teleport. About one run in three leaves a staging fault. |
| 2 | Blind read: at least equal to ChatGPT on Episode 1 | **Not met, narrowly.** Blind read 2026-11-06 of `runs/7-gpt_5-high/side_by_side.html`, an overall score out of 10 (not the 8-line rubric): ChatGPT 9, this lab's plan 7.5, David today 4. The lab's plan is 3.5 points above David today and 1.5 below ChatGPT (about 3.6 of the rubric's 24), outside the 2-point band for "equal". |
| 3 | A repeat run scores within one rubric point and still passes 1 | **Partly.** Runs 6 and 7 are the same configuration: 22 vs 18 shots, 72 vs 69 s, both 5/8 craft; faults 1 vs 0. Needs the rubric. |
| 4 | The second scene passes 1 and is rated at least as good as David today | **Open.** Valid plan, 15 shots, 60 s, one teleport; needs the person's rating against David today. |
| 5 | Cost and time recorded per scene | **Met.** gpt-5 high: $0.18 to $0.27 and 3 to 4 minutes a scene. gpt-5.5 high: $0.69 and 5 minutes. Never shown in the app. |

## Against the two other plans (an informal read, not the rubric)

David today gave 12 shots, no treatment, no added shots, one flat grade, and the 4 s rain scene alone. The lab's plan (run 7) has a
treatment (logline, key image, geography, advice), four sequences, a colour script that moves, 18 shots with the phone, the
ring and the stall as inserts, the call held 8 s on Anudi's face, and a close on Kasun for the narrator. ChatGPT's list has
more insert and coverage detail (a tea pour, the pick-up, Kasun's smile as the ending) and a stated geography; it also invents a
line, runs 70 to 80 s and uses 2 to 3 s takes Veo cannot make. The lab's plan has no invented line and respects 4/6/8.
Run 7 gives the pick-up one shot (the compound action b6 is not split), has only 4 of 6 listener reactions and no tea close-up: that is where it is still behind ChatGPT.

## The blind read (2026-11-06)

Key: X = this lab's plan (run 7), Y = ChatGPT, Z = David today. Scores given by the person as a whole-plan mark out of 10:

| Plan | Score |
|---|---|
| Y, ChatGPT | 9 |
| X, this lab (run 7) | 7.5 |
| Z, David today | 4 |

Read: the lab already closes most of the distance from David today to ChatGPT (3.5 of the 5 points), but does not yet reach it. The earlier informal read named where it is thinner: listener reactions (4 of 6), the pick-up as one shot, no tea close-up. The person's own reasons for the 1.5 points are not recorded yet.

## Generalisation and the stabiliser (2026-11-06, after the blind read)

The person's feedback on the blind read: plan Y (ChatGPT) was richer in fine-grain detail, a story purpose for each shot ("the
contrast between the two characters' lifestyles"), the camera following the action (tilt with the phone as it drops), an
extreme close-up on the ring. The person's brief for the next phase: **do not train for this case; make the engine general so
that any scene gets this kind of camera work and cinematic output, reliably.** Three things were done.

**1. The read was not like for like.** The blind page printed only a shot's first action and a one-line "why" for the lab's plan
and David today, but the full camera, framing, movement and purpose for ChatGPT. Every plan is now printed as the same
`shot_card`. (Scores in the table above were given on the old page, so they probably understate the lab's plan.)

**2. The prompt carries principles, not a story.** The camera and purpose rules are general craft: *motion follows meaning* (the
camera follows a fall or a travel, and locks off only for stillness), a story object's event gets a close shot where the camera
does something with it, and each `why` starts with the shot's story function. Wording that came from Episode 1 (the phone, the tea,
the umbrella, "picks it up and runs after her", "a ringtone cuts the music", the vow/smile/call/goodbye) was replaced; a test
now fails if a name or an object of any one story is in `prompt/system.md`.

**3. The stabiliser is code.** `run.py auto --yes --scene <name>`: the author writes a draft; code checks it (hard faults and craft
measures); while a fault or a craft gap remains, the author gets **its own best draft back with the findings** and returns the
corrected plan (at most `--passes`, default 2); a pass that is worse is never built on; the best plan is kept. Scenes load by
lab key, gold-scene name or yaml path, so the same engine runs on any scene. The new `motion` measure is general (a falling or
racing thing is not locked off; negations, small gestures and static wides are exempt).

### Evidence on five different scenes (gpt-5, high effort; 14 paid calls, $1.78)

Faults = real hard problems; gaps = craft measures missed. The three gold scenes other than `phone_call` were never used to tune
anything.

| Scene | Draft (new prompt) | After revise pass 1 | After pass 2 | Calls, $ |
|---|---|---|---|---|
| Episode 1 (run 10, 14, 17) | 1 fault, 2 gaps | 0 faults, 2 gaps | **0 faults, 0 gaps** (21 shots, 75 s) | 3, $0.58 |
| Arrival (run 11, 15) | 0 faults, 3 gaps | **0 faults, 1 gap** | not needed | 2, $0.33 |
| Father refuses (run 12, 16) | 1 fault (teleport), 0 gaps | **0 faults, 0 gaps** | not needed | 2, $0.32 |
| Silent morning (run 13) | **0 faults, 0 gaps** | not needed | not needed | 1, $0.18 |
| Phone call (run 18, 19; `auto`) | 0 faults, 3 gaps | **0 faults, 0 gaps** | not needed | 2, $0.35 |

What this says:

- The draft alone is not stable (faults in 2 of 5 scenes, gaps in 3 of 5). The draft plus the revise pass was clean or one gap
  from clean in all five, and no revision made a fault worse. That is the argument for a system, not a better prompt.
- A second pass converges rather than oscillating (Episode 1: pass 1 fixed the two gaps it was told about but broke two others;
  pass 2 cleared all). Two passes is the limit worth paying for.
- The user's phone drop: the old prompt locked it off in runs 2, 4 and 7; the new prompt's draft (run 10) follows it. The measure
  that catches it is now general, and it was made more precise after it flagged "he doesn't rush to speak" and "his gaze drops".

### What this does not prove

- **Craft measures are rules of thumb the lab wrote.** The stabiliser optimises them; whether the plans are *more cinematic to a
  person* is the blind read. Run `17-gpt_5-high` (the best Episode 1 plan) is on a rebuilt `side_by_side.html` for a re-read.
- One `auto` run per scene: the stabiliser's own repeatability (does it reach clean every time) is not measured. Cost per scene
  was $0.18 to $0.58 on gpt-5; a clean plan took one to three calls.
- The motion check was refined after seeing false positives in these runs; it was not tuned to pass them.
- The worked example in the prompt still uses characters from the same drama universe (a different scene).

### Gate after the stabiliser

| # | Point | Met? |
|---|---|---|
| 1 | Zero hard problems in Episode 1 and in the second scene | **Met on one `auto` run each** (runs 17 and 19: 0 faults). Repeatability not yet measured. |
| 2 | Blind read at least equal to ChatGPT on Episode 1 | **Met, with a caveat.** Re-read 2026-11-06 of `runs/17-gpt_5-high/side_by_side.html`: lab 9, ChatGPT 8.5, David today 6 (out of 10). The reader had seen the first key, so it was not fully blind. |
| 3 | A repeat scores within one rubric point and still passes 1 | **Open** for `auto` (one run per scene). The draft alone was not stable (runs 6, 7 differed). |
| 4 | The second scene passes 1 and is rated at least as good as David today | **Passes 1** (run 19). Rating is the person's. |
| 5 | Cost and time recorded | **Met.** $0.13 to $0.27 and 2 to 4 minutes a call; $0.18 to $0.58 a scene with `auto`. |

### Second read (2026-11-06)

Key: X = this lab's plan (run 17, the stabiliser's best Episode 1), Y = ChatGPT, Z = David today. Whole-plan marks out of 10 by the person:

| Plan | First read (summary page) | Second read (same shot cards) |
|---|---|---|
| This lab | 7.5 | **9** |
| ChatGPT | 9 | 8.5 |
| David today | 4 | 6 |

Two things moved the numbers: the page now prints every plan with the same detail (David today went 4 to 6 with no change to its
plan, ChatGPT 9 to 8.5), and the lab's plan is run 17, which has the general camera and purpose rules and two revise passes. The
person's note on David today: "technically good but I don't see much creativity". Caveat: the person knew the first key, so this
read is not fully blind; a read by someone who has not seen the plans (a Hiru director) would settle it.

## Decision (phase 7): the person's

$0.96 is left; nothing more is spent until the person says.

- **The re-read is done and gate point 2 is met** (lab 9, ChatGPT 8.5, David today 6). Open: a read by someone who has not seen the plans, the second scene's rating (point 4), and the stabiliser's repeatability (point 3).
- **Next**: write the product plan (§9). What moves, general and not tied to a story: the prompt (`prompt/system.md`), the
  `CinemaWire` fields, the `[move]` marker and the `a thought` label in the script listing, the `use_s` time policy, the craft
  measures (including `motion`), and the **stabiliser** (draft, then up to two revise passes with code's findings, best kept) as
  a step after David's author. Fix the car-across-the-road teleport at the reader (an implied move step), not in the prompt.
  The David tab's treatment card, colour strip and sequence view in the interface are already there to receive it.
- **If it is not**: the thin spots are in the person's reasons for the gap. One more change worth a run is the two-call variant
  (treatment first, then the shots from it). Stop rule: the budget is nearly spent; raising `BUDGET_USD` is the person's decision.
