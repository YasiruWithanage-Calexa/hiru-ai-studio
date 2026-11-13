# Zora on the shot rows: lab results (plan/2026-11-12d phase 0)

Scene: Hiru Short Combined 2, Scene 03 (Colombo garage flashback), planned by Raphael: 7 blocks, 20 overlapping clips,
lines L2 / L3 / L4 performed by S05 / S08 / S11. Exported read-only (`export.py`); nothing written to the database or
`src/`. Twelve turns, one thread: a question, an exact change, a craft note, a risky removal accepted then undone, a risky
removal rejected, a script change, an insert, options and "Use this".

**Spent: $1.03 of the $2.00 cap** (six paid runs, the person's yes each time; `runs/ledger.csv`).

| Run | Date | Spent | Change | Page |
|---|---|---|---|---|
| 1 | 2026-11-13 | $0.16 | first run | https://claude.ai/artifact/E8KgPVitgzwhUcm9XYZUDz |
| 2 | 2026-11-13 | $0.35 | run 1's fixes + a friendlier reply, each reply written by gpt-5-mini (A) and gpt-5 (B) | https://claude.ai/artifact/N7TUHS7xWUTdp8DuRYcanc |
| 3 | 2026-11-13 | $0.29 | run 2's fixes, reply on gpt-5 | https://claude.ai/artifact/RdpxZCvW6TGjXndnoWdpBs |
| 4 | 2026-11-13 | $0.036 | the person's cost targets: code reads plain commands, gpt-5-nano conductor and small reply, gpt-6.1-terra author and big reply, a $0.02 cap per turn | runs/run4/index.html |
| 5 | 2026-11-13 | $0.059 | nano out (it misread 5 of 7 messages, unreliable replies): gpt-5-mini minimal conductor and small reply | runs/run5/index.html |
| 6 | 2026-11-13 | $0.033 | every reply gpt-5-mini minimal; a slim scene for whole-scene tasks; honest "no options"; code alone tasks an insert | runs/run6/index.html |

## What the lab proved

- **No planner is needed to edit.** The rows carry enough: every turn worked on clips read from `shots` and
  `dialogue_lines`, with planner-free checks, and the author's craft held up without a planner's prompt (closer sizes and
  shorter holds for "tenser", a speaking single rewritten when the master went, a real key insert).
- **Coverage edits work.** Removing a clip that performs a line moved the line, in code, to the clip that shows the
  speaker (S08 → Dinu's single 3C-3; S05 → Nimal's single 3B-1), and the checks found no new problem.
- **Accept / Reject works as the person asked.** Both removals showed a card with what the change costs; Accept saved
  (revision), Undo restored the exact clips, Reject changed nothing and was not offered again; an Accept on a card made
  before the scene changed was refused (offline test).
- **Models (D9):** conductor gpt-5-mini low (right lane every time, 12/12); author gpt-6.1-sol low (good craft, $0.01-0.05 a
  call); **reply gpt-5 low** (a colleague's voice, about $0.01-0.02 a reply). gpt-5-mini as the reply pasted the fact
  sheet back into the message (run 2): not usable.
- **Cost:** a whole twelve-turn session about $0.29 with gpt-5 replies (run 3); an exact change about $0.01, a craft
  note about $0.07.

## The cost targets (runs 4-6, the person: "a small request under $0.001, at most $0.02")

Per turn, as run 5 and 6 measured them (uncached):

| Turn | Cost | Calls |
|---|---|---|
| "Make S01 a wide, 6 seconds" | $0.0009 | code reads it; reply gpt-5-mini minimal |
| Accept / Undo / Reject | $0.0007-0.0010 | reply only |
| "Use this" | $0.0015 | reply only (a long list of changes to describe) |
| A question about a shot | $0.0017 | conductor + reply, both gpt-5-mini minimal |
| "Change Nimal's line" (not possible here) | $0.0019 | conductor + reply |
| "Drop S08" (a card) | $0.0033 | code reads it; author (the clip that takes the line) + reply |
| Insert a close-up | $0.0073 | conductor + author (terra) + reply |
| Two endings | $0.0114 | conductor + author (terra, slim scene) + reply |
| "Make it tenser" | about $0.015 | conductor + author (terra) + reply |

The whole twelve-turn session: about $0.05 (run 3, the same turns on sol + gpt-5: $0.29).

**Models for the product (D9, final):** conductor gpt-5-mini at minimal; author gpt-6.1-terra at low; every reply
gpt-5-mini at minimal; plain commands (size, take, remove) read by code; a hard $0.02 cap per turn in code.
gpt-5-nano is not usable (run 4). Terra's replies were dry and gpt-5's ($0.006-0.014) do not fit beside the author.

**Still to tidy in the product:** a card reply asks "want me to accept?" (Zora cannot; the person does); the options
reply adds details that are not in the option (give it each option's change list); a "no ADR" mention slipped through
once more ("a replacement audio take"); "Drop S08" can skip the author when the clip that takes the line already shows
the speaker saying it (about $0.002 saved).

## What broke and what the product must keep

| Found | Fix (in the lab) | For the product |
|---|---|---|
| A question answered "nothing changed" (run 1) | the chat lane gets its own instruction | keep |
| The reply claimed refused work, and a card that was not there (run 1) | the author's note is dropped when work was refused; a code guard cuts card words with no card | keep, and the guard must not cut "the script card" (run 3) |
| Robotic replies (the person, run 1) | the reply is a colleague (persona, plain sentences, 12 messages, no list read back: the app shows it), gpt-5 | keep: the reply prompt, `plain()`, gpt-5 |
| The reply pasted its fact sheet (run 2, gpt-5-mini) | gpt-5, and a guard that cuts from the first header | keep both |
| A model-made overrun only reported (run 1) | an overrun is repaired unless a person set the take | keep |
| "Use this" replayed ops one at a time, a change lost (run 1) | replay in the batches they landed in | keep |
| The conductor counted post-op numbers wrong (run 2: S21 for the new S16) | task shots are read as printed, before the ops; code tasks new clips and line takeovers | keep |
| An insert with no size became MS, locked (runs 1-2) | an insert defaults to INSERT; only a size the person gave is locked | keep |
| The conductor wrote long craft briefs (run 1) | one or two sentences in the person's terms | keep |
| Options deleted must clips nobody asked to cut (run 1) | the author's prompt: variants change how clips play | keep |
| A card reply said "I've dropped S08" (run 3) | the prompt: a card is a proposal, conditional | fixed after run 3, not yet run |
| A reply suggested ADR / a recorded take (run 3) | the prompt: every clip is generated, nothing is filmed | fixed after run 3, not yet run |
| The author wrote an edit list into a clip's `why` (run 3) | the prompt: `why` is that clip's story reason | fixed after run 3, not yet run |

## Run it

```
.venv/Scripts/python.exe -m pytest lab/zora_rows/tests -q            # 18 offline tests
OPENAI__API_KEY= .venv/Scripts/python.exe lab/zora_rows/run.py rehearse   # the scenario with no model
OPENAI__API_KEY= .venv/Scripts/python.exe lab/zora_rows/run.py dry        # the price
.venv/Scripts/python.exe lab/zora_rows/run.py paid --yes --run run4      # PAID: the person's yes first
```
