# Shot Planner DaVinci: lab results (plan/2026-11-08d, phase 0)

Written 2026-11-08. What was built for the lab is in [IMPLEMENTED.md](IMPLEMENTED.md) and `lab/davinci/README.md`; this file is
what the lab **found**: two paid runs of the orchestrator on one scene, what each cost and did, what went wrong, what was
changed between them, and what is still unknown. Every number below was read from the lab's own files
(`lab/davinci/runs/ledger.csv`, `runs/<run>/trace.jsonl`, `bin.json`, `outcome.json`, `usage.json`), not remembered.

## 1. Summary

| | Run 1 | Run 2 |
|---|---|---|
| Folder | `runs/1-gpt_5_episode1` | `runs/2-gpt_5_episode1` |
| What changed since the last run | nothing: the first run | the length limit (given length + 50%), `replace_clip`, refused removals, a `<voice_only>` block, new prompts |
| Outcome | **did not finish**: all 40 turns used | **did not finish**: all 40 turns used |
| Model calls / cost | 87 calls / **$0.9254** | 59 calls / **$0.8079** |
| Wall clock | 29 min (14:18 to 14:48) | 15 min (15:09 to 15:25) |
| Final bin | 21 clips, **130 s** of takes (15 must, 4 should, 2 nice), all 21 designed | 14 clips, **88 s** of takes (14 must), only **7 of 14 designed** |
| Blocking faults at the end | 14 (+1 report) | 9 (+2 reports) |
| Inside the person's length rule (60 s + 50% = 90 s) | no (the rule did not exist yet) | **yes** (88 s) |

**Lab total: $1.7333 of the $5.00 budget** (the cinematic lab's own ledger is separate). No run produced a result `finish`
would accept, so **phase 0 has no usable DaVinci bin yet**, and nothing was given to the post team.

What the two runs do show: the orchestrator loop runs end to end on a real model (tool calls, parallel workers, the checks,
the ledger and the cap all worked); the person's length rule can be met (88 s); the two failure modes that the first run
exposed were reduced but a new one replaced them. What they do not show: that the director can converge to a finished bin,
anything about the quality of the pictures (see section 7), or anything about a second scene.

## 2. What was tested

- **One scene, one time.** Episode 1 of the lab's story as the cinematic lab corrected it (`lab/cinematic/input/reading.yaml`):
  one scene, 23 script blocks (b0 to b22), 8 lines (L3, L7, L9, L11, L13, L16, L19, L22), three people (Kasun, Anudi, and the
  Father who is only a voice on the phone), a narrator, heavy rain, a given length of **60 s**. The second scene
  (`second_scene.yaml`) was not used. There was no multi-scene or whole-script run, and no repeat of the same run.
- **Models (D7 not yet decided by the person; the lab's defaults):** director `gpt-5`, effort medium; coverage planner and clip
  writers `gpt-5-mini`, effort medium. Both are in the price table (`cinematic/run.py` `PRICES`): gpt-5 at $1.25 / $0.125 cached /
  $10.00 per million tokens in / cached in / out, gpt-5-mini at $0.25 / $0.025 / $2.00.
- **Limits in force:** run cap $5.00 (stops after the call that reaches it), lab budget $5.00 (refuses a call whose worst case
  could pass it), 40 director turns, director `max_output_tokens` 16,000 and worker 20,000 (reasoning included), 4 worker
  threads, at most 6 clips per clip-writer call.
- **Authorisation:** each paid run was started only after the person's explicit yes (run 1: "yes do it"; run 2: "yes do real
  run"). The first `dry` showed the worst case of one director turn at $0.17 and a guess of $0.60 for a whole run; the real
  runs cost $0.93 and $0.81.
- **The orchestrator** (`lab/davinci/orchestrator.py`): a director in a tool loop; workers `coverage_planner` and `clip_writer`
  called like tools; code tools `read_bin`, `check`, `finish` (which refuses until the checks pass); run 2 added `replace_clip`
  and made `remove_clips` refuse a removal that opens a coverage hole. No continuity critic, no `entity_state` (left out on
  purpose; section 8).

## 3. The person's decisions during the lab

1. **Length (2026-11-08):** "30-40 clips for a 60 s video is too much ... the total shot length should not exceed the given
   length + 50%, so maximum 90 s, because we don't need to add multiple shots for every shot or every action." Built as a
   blocking check (`checks.length`, `LENGTH_MARGIN = 0.5`): the sum of `take_s` over the bin is at most the scene's `guide_s`
   x 1.5. It replaces the plan's "coverage multiplies cost 2 to 4x" (risk 5) and answers D4 in part (a total, not a level);
   `PLAN.md` §7 and §9 were edited to say so.
2. **Build the fixes (2026-11-08):** `replace_clip`, a removal that cannot open a coverage hole, and the voice-only rules were
   built on the person's "yes do it".
3. Still open: D1 (what to save at the cap), D2 (the director followed the recommendation, master and the speaker's single
   perform; the person has not confirmed it), D3, D5, D6, D7, D8; and whether the bin should hold alternates (section 6).

## 4. Run 1: the first run

**Setup.** Hypothesis: "the first run: gpt-5 director, gpt-5-mini workers, Episode 1". No length limit existed; the prompts
said the bin is bigger than the cut by design.

**What the model did.** Director turns 40, `write_edit_plan` 1 (10 moments in 7 sequences), `plan_coverage` 1 (24 clips, one
call, $0.0184), `add_clips` 7, `write_clips` 19, `remove_clips` 7, `check` 5. Clip ids reached c55. Seven removals deleted 35
clips in total (1, 9, 6, 1, 13, 1 and 4 at a time), so the bin was torn down and rebuilt several times. (An earlier chat
message said 33; the trace says 35.)

**Cost by slot.**

| Slot | Calls | Dollars | Input tokens | Output tokens | of which reasoning |
|---|---|---|---|---|---|
| director | 40 | $0.3914 | 928,149 | 22,578 | 14,464 |
| coverage_planner | 1 | $0.0184 | 4,441 | 8,624 | 5,568 |
| clip_writer | 46 | $0.5156 | 235,321 | 248,049 | 138,432 |
| **total** | **87** | **$0.9254** | | | |

Every call status was `done`: no failure, no cut-off, nothing entered at a worst case.

**The checks over time** (the director called `check` five times in 40 turns):

| Turn | Clips in bin | Blocking faults |
|---|---|---|
| 13 | 29 (17 must, 10 should, 2 nice) | 27 (+15 reports) |
| 19 | 30 | 13 |
| 26 | 31 | 16 |
| 33 | 31 | 16 |
| 39 | 25 | 12 |

**End state.** Stopped by the turn limit. 21 clips, 130 s, 15 must / 4 should / 2 nice, all designed. 14 blocking faults:

- 8 coverage faults: blocks b3, b9, b11, b17 and all of moment 2 had no must clip; lines L3, L9, L11 were carried by no must clip.
  These are the director's own removals: it removed clips (including a must clip) and did not replace them.
- 4 design faults: the voice-only father in the subjects or first frame of c37 and c52; "calls out" and "speaking" written into
  c51 and c55 (clips that perform no line).
- 2 consistency faults: Kasun and Anudi described two different ways in moment 10 (clip c53).
- 1 report: c43 asked for fast hands (a Veo limit, advisory).

**Diagnosis.** (a) No rule told the director that removing a must clip opens a coverage hole, and it repaired design faults by
removing the clip. (b) It checked rarely (5 of 40 turns) and rebuilt the bin repeatedly. (c) The clip writers kept breaking
two rules that were in their prompt (the voice-only person, speaking verbs in silent clips). (d) The bin was 130 s for a 60 s
scene, 2.2x the cut, which the person judged too much.

## 5. Run 2: after the fixes

**Setup.** Hypothesis: "second run: length limit 90 s, replace_clip, refused removals, voice_only block". Changes since run 1:
the `<length>` note (limit and seconds left) in the director's and planner's messages; prompts say one clip per beat, extra
angles only where the story turns, and check after every change; `replace_clip` (keeps id, a must clip stays must, clears the
design); `remove_clips` refuses a removal that would open a coverage hole; the clip-writer prompt's two hard rules and a
`<voice_only>` block (code lists Father, from the script) in every clip-writer message.

**What the model did.** Director turns 40, `write_edit_plan` 1 (6 moments in 5 sequences), `add_clips` 3 (the director planned
the coverage itself and **never called `plan_coverage`**), `write_clips` 4, `check` 4, **`replace_clip` 26**, `remove_clips` 2.

**Cost by slot.**

| Slot | Calls | Dollars | Input tokens | Output tokens | of which reasoning |
|---|---|---|---|---|---|
| director | 40 | $0.5312 | 1,249,980 | 28,998 | 21,056 |
| clip_writer | 19 | $0.2767 | 94,221 | 134,243 | 79,488 |
| **total** | **59** | **$0.8079** | | | |

Again every call was `done`. The director cost more than in run 1 (a longer context at every turn: an average of about 31,000 input tokens a turn against
about 23,000, mostly cached), the clip writers less (19 calls against 46).

**The checks over time.**

| Turn | Clips in bin | Blocking faults |
|---|---|---|
| 4 | 17 (13 must, 4 should) | 16 (+9 reports) |
| 14 | 15 (all must) | 4 |
| 21 | 14 (all must) | 11 |
| 33 | 14 (all must) | 7 |

The first check came at turn 4 (turn 13 in run 1), and the director never re-planned from scratch. Faults fell from 16 to 4,
then rose to 11 at turn 21 (the trace cuts results at 600 characters, so I did not verify why; the likely cause is
`replace_clip` clearing designs that were not yet re-sent).

**End state.** Stopped by the turn limit. **14 clips, 88 s, all must** (takes of 4 to 8 s; see `bin.json`), **7 of 14 designed**. 9 blocking faults:

- 2 coverage faults: **L16** (the father's call) and **L22** (the narrator) are carried by no must clip. Clips c12 (b15-b16) and
  c16 (b22) cover those blocks but list no line id.
- 7 design faults: c03, c11, c12, c14, c15, c16, c18 "have no design yet". They were replaced (which clears the design) in the
  last turns and never sent to `write_clips`.
- 2 reports: c05 and c07 matched the "screen text" keyword (an advisory).

**What improved against run 1.** The length is inside the limit (88 s against 130 s). No removal opened a coverage hole (the
refusal rule held; only 2 `remove_clips` calls were needed). None of the 7 designed clips has the voice-only father, a speaking verb in a silent
clip, or a consistency fault. That is thin evidence for the clip-writer fixes: the other 7 clips were never designed, so the
rules were tested on half the bin. The clip writers ran 19 calls instead of 46. The run
took half the time (15 min against 29) and cost slightly less.

**What went wrong.** The director spent 26 of its 40 turns on one-at-a-time `replace_clip` calls, which each clear a design,
and had too few turns left to send the 7 replaced clips back to `write_clips` and check. It also reached for "all must" (14 of
14), so the bin has no alternates at all.

**One observation worth keeping.** Clip c06 (moment 3) covers b7 to b12 and the three lines L7, L9 and L11 in a single 8 s
two-shot. The repo's clock calls that 7.0 s of need, so the check passes (handles 1 + 1 + (7.0 - 1) = 8), but it is a dense
take; whether Veo can perform three lines and two actions in 8 s is not something any check can say. It is one of the
things a Veo trial should test.

## 6. Findings

1. **The loop works on a real model.** Strict function schemas were accepted, the director called tools correctly in both runs
   (no malformed call), workers returned valid schema answers every time, parallel clip-writer calls ran, the ledger and
   worst-case guard worked, and `finish`'s gate was never bypassed (it was not reached).
2. **Convergence is the open problem, and it is mostly tool design.** Run 1 lost its turns to destroy-and-rebuild; run 2 to
   26 single replacements. A model given only per-clip tools spends one turn per clip.
3. **The person's length rule is meetable** (88 s) but costs the alternates: with long lines the must clips alone are about
   76 s of a 90 s bin, and the director, told to be short, chose all-must. The post team's wish for angles, reactions and
   inserts is in tension with a +50% cap; with this scene there is room for about 14 s of extras, which is about three 4 s
   clips. The phase-0 sample (one moment x 3 angles, a transition pair, a drone clip) needs roughly 20 to 25 s of extras, which does
   not fit; `pick` says so rather than inventing clips. This needs the person's decision (section 8).
4. **A fault that names its owner works; a fault that names the whole group does not.** The consistency check was changed (before
   either paid run) to name only the clips that differ from the majority wording, so a repair re-sends one clip.
5. **Replacing is not editing.** `replace_clip` discards the design, so a one-word fix (adding a line id) costs a full
   re-design. A lighter patch tool is the clear next change.
6. **Cost is small.** $0.8 to $0.9 for a 60 s scene run to the turn limit, against a $5 cap. Time, not money, is what scales:
   about 15 to 30 minutes for 60 s of story, mostly waiting for clip writers (30 to 80 s per call) and director turns.

## 7. What is not known

- **Whether the director can finish.** No run reached `finish`. Run 2's faults at the end were simple (send seven clips to
  `write_clips`, add two line ids), so it was a few turns short, not hopelessly off, but that is a reading of the trace, not a
  test.
- **The quality of what was written.** I read one design in detail (c06 in run 2): the two people's looks are copied word for
  word from the production, the voice-only father is absent, handles are described as real time in the take, and it names its
  lines by id. I did not read the other 20 designs or the 21 of run 1, did not open either `bin.html` in a browser, and did not
  judge the camera choices. The checks pass or fail them; they do not say they are good.
- **Whether Veo can cut between these angles** (the plan's first risk) and whether the post team can use the bin. Nothing has
  been generated; no post-team input exists.
- **Repeatability and other scenes.** One scene, two attempts with different rules. The two bins differ (21 and 14 clips,
  10 and 6 moments), so a same-rules repeat would very likely differ again.
- **The comparison with Jonathan.** The page shows Jonathan's numbers (run 17 of the cinematic lab: 25 shots) next to each bin,
  but no blind read has been done, and with no finished DaVinci bin it would be premature.

## 8. Next steps and decisions

Not yet built (the person has not said yes to the third run, and these precede it):

1. **Batch and patch editing:** `replace_clips` taking a list, and `edit_clip` for small changes (a line id, a take, a handle)
   that keeps the design when the picture does not change.
2. **State in every tool result:** blocking-fault count, clips without a design, and **turns left**, so the director sees time
   running out.
3. **A finishing order:** with about 8 turns left, the loop tells the director to stop replacing, write the clips, check, finish.
4. **Alternates:** once the must clips fit, use part of the leftover seconds on should clips (or let the person set the split).

Decisions for the person:

- **Alternates inside the +50%:** how many seconds of the extra 30 are reserved for should / nice clips, or whether the sample
  (pair, drone) is allowed to exceed the cap for the lab only.
- **D7:** keep `gpt-5` / `gpt-5-mini`, or try a stronger worker for the clip writers (their rule-breaking in run 1 may be the model).
- **D1, D3, D5, D6, D8** as in PLAN §7.
- **A third run (about $1 by the evidence: $0.93 and $0.81)** needs the person's yes after the fixes above.
- Whether a **continuity critic** is worth adding: not before a bin finishes and the post team's cut shows drift code cannot see.

## 9. Money

| Run | Calls | Dollars | Lab total |
|---|---|---|---|
| 1-gpt_5_episode1 | 87 | $0.9254 | $0.9254 |
| 2-gpt_5_episode1 | 59 | $0.8079 | **$1.7333** |

`runs/ledger.csv` holds every call (time, run, slot, model, effort, tokens, dollars, status, hypothesis). The rehearsal's
dollars are pretend and live in `runs/rehearsal/pretend_ledger.csv`, never the lab's. $3.27 of the $5.00 lab budget is left;
nothing more is spent without the person's yes.

## 10. Reproduce and read

```
.venv/Scripts/python.exe -m pytest lab/davinci/tests -q                      # 44 offline tests
OPENAI__API_KEY= .venv/Scripts/python.exe lab/davinci/run.py rehearse        # the free scripted run: 14 clips, 90 s
OPENAI__API_KEY= .venv/Scripts/python.exe lab/davinci/run.py dry             # prompts, tools, the price (calls nothing)
.venv/Scripts/python.exe lab/davinci/run.py ledger                           # every paid call
```

Read: `lab/davinci/runs/<run>/bin.html` (the intended cut, the bin by moment, the checks), `trace.jsonl` (every call and tool
result, results cut at 600 characters), `work_log.json`, `outcome.json`, `edit_plan.json`, `bin.json` (the full designs).

## 11. Run 3: the staged runner (PLAN-B), 2026-11-08

Folder `lab/davinci/runs/3-gpt_5_episode1_staged`. Hypothesis: "staged: one plan call, at most 2 repairs, all designs in parallel, looks by code". Same scene and models as runs 1-2 (Episode 1, gpt-5 / gpt-5-mini medium). The person said yes to the run.

| | Run 1 | Run 2 | **Run 3 (staged)** |
|---|---|---|---|
| Finished | no | no | **yes, 0 blocking faults** |
| Model calls | 87 | 59 | **6** |
| Wall clock | 29 min | 15 min | **4.7 min** (15:59:57 to 16:04:40) |
| Cost | $0.9254 | $0.8079 | **$0.2801** |
| Bin | 21 clips, 130 s | 14 clips, 88 s | **11 clips, 66 s** (9 must, 1 should, 1 nice), all designed |

Pass criteria (finish, 10 min or less, $1 or less): **met**. Lab total now **$2.0134 of $5.00**.

By stage (measured): plan 160 s, 1 call, $0.158 (mend made 3 fixes; 1 blocking fault left); repair 52 s, 1 call, $0.068 (1 -> 0, kept); design 72 s, 4 parallel calls, $0.054 (0 design faults); re-design 0 calls. The look sheet left no consistency fault and no clip needed re-sending.

**What the run does not show.** It passes the checks; it has not been read. At the end: 5 reports (not blocking): three lines longer than the longest take (c03 L16 needs 9.4 s in 8 s, c08 L22 needs 11.4 s in 8 s, c07 L3 needs 6.7 s in 6 s; the rule is to split such an exchange into overlapping clips, the director did not) and two screen-text advisories (c04, c11). The bin is nearly all must: 9 of 11, one insert and one atmosphere clip, so the post team gets about one angle per beat (the run-2 weakness, now with only 66 s of the 90 s used). The quality of the plan and the pictures, Veo cutting between angles, and a second scene are untested. `bin.html` has not been opened by the person.

Next: the person reads `bin.html`; decide the alternates share (stage-1 prompt) and whether an overrun should block; then `pick`, Veo, the post team.
