# Sable as a lightweight shot editor: lab results (2026-11-13)

The person's target (2026-11-13): **Sable is the lightweight shot editor** (quick, cheap, exact shot edits and answers;
Zora is the director chat for craft). The lab ran the same twelve messages on two arms, one thread each, on the Zora
lab's scene (Hiru Short Combined 2, Scene 03: 7 blocks, 20 overlapping Raphael clips, lines on S05 / S08 / S11), with no
database (the repo's test fakes, filled from `lab/zora_rows/input/…json`).

- **Arm T, today's Sable:** its real code unchanged (`systems/sable/sable_chat`, the react agent with 25 tools, tiers
  `sable` gpt-5-mini low and `sable_deep` gpt-5 medium).
- **Arm L, the lightweight editor** (`light.py`): code reads plain commands; ONE gpt-5-mini minimal call understands
  anything else and, for a question / a craft request (handed to Zora) / "not here" / "unclear", writes the reply too;
  edits go through the Zora lab's coverage kernel, checks and risk rule (Accept / Reject); a short gpt-5-mini minimal
  reply; no author (a new clip's picture is left for Zora); $0.005 cap a turn; code checks (incl. silent shots with a
  line) shown to the model every turn.

Spent: **$0.351** of a $1.00 cap (one paid run, the person's yes). Page: https://claude.ai/artifact/RtRC67sjLcca1enS2TAuYy

## Found before any model ran ($0)

Today's Sable's edit path (`change_propose` → `core/trial.py` → the classic `scene_kernel`) and its `timing_check` read
the scene through `contracts.shotplan.fit`, whose rule is "every block in exactly one shot": **it sees 7 of the 20 clips**
(42 s instead of 120 s of takes; S03, an insert, "carries 11 words"). `change_propose` refuses "there is no shot 8" /
"no shot 13"; a size change on S01 also "touches S02". On a Raphael scene, today's Sable cannot edit S08 onward.

## Run 1

| Message | Today's Sable | Lightweight editor |
|---|---|---|
| How many shots, which carry dialogue? | "17 shots" (wrong) · $0.0014 | 20 shots, S05 / S08 / S11 with who · $0.0007 |
| Who is on screen in S07? | right · $0.0012 | right · $0.0008 |
| Make S01 a wide, 6 seconds | a card (right) · **$0.028**, 5 calls | saved (code read it) · $0.0006 |
| Shorten S13 to 6 seconds | "there is no S13" · $0.0014 | saved · $0.0016 |
| Make S10 a close-up and S12 an MCU | "no S10 or S12" · $0.0036 | saved · $0.0019 |
| Move S15 before S14 | "only S01–S07" · $0.0008 | asked to clarify (fixed after: code reads moves) · $0.0011 |
| Drop S08 | "there is no S08" · **$0.055** | card: L3 moves to Dinu's single · $0.0008 |
| [Accept] | (a product button, not a turn) | saved, revision · $0.0008 |
| Undo that | "nothing to undo" · **$0.037** | restored · $0.0007 |
| Insert the key after S15 | "no S15" · $0.0035 | new INSERT S16, picture left for Zora · $0.0018 |
| Make S08–S13 tenser | a craft plan, offered to stage · **$0.205**, 9 calls, 10 minutes | handed to Zora · $0.0011 |
| Silent shots with a line? | "no" · $0.0019 | "no", with which clip carries each line · $0.0008 |
| **Total** | **$0.338**, 11 turns, $0.031 a turn | **$0.013**, 12 turns, **$0.001 a turn** |

Lightweight arm, after the run (offline, $0): moves "before / after" read by code (`quick_move`); a waiting card's reply
written by code from the card (the model had said "I removed S08" while nothing was saved). Lab artifact: run 1 shared
one card store across Arm T's turns (each product turn has its own); the page shows each card once; fixed for later runs.

## What it means for Sable

1. **Today's Sable cannot edit a Raphael scene** (its kernel is single-cut). Any Sable that edits must use the coverage
   kernel (plan/2026-11-13 phase 8).
2. **As a lightweight editor, one cheap call is enough**: about $0.001 a message, every answer right, every edit landed,
   risky ones carded. Today's react loop costs 30x more on average and up to $0.20 a message, mostly on gpt-5 medium.
3. **Craft goes to Zora.** Sable's deep tier is where the money went ($0.20 for "tenser"); the lightweight editor hands
   it over for $0.001.
4. Sable's production-wide strengths (search across episodes, documents, canon, the knowledge base) were not in this
   test: the lightweight editor covers the open scene. Keeping the react loop for production-wide questions, on a budget,
   is a separate choice for the person.

## Production suite, run prod1 (2026-11-13, the person: "Sable works within the scene, aware of the production; warn on a
## story conflict, the person may override")

The "test" production in the new database is a traffic seed (twelve scenes of the same filler). Exported READ-ONLY
(`export_prod.py`), then a small story written into the LAB COPY only (`story.py`): Dilini (21) is accepted to the
Colombo Medical Faculty (E1S2), Nimal pins the letter up (E1S3), she packs anatomy books (E2S2, the open scene), Sahan
gives her a stethoscope (E2S4). Twelve messages on E2S2. Page: https://claude.ai/artifact/Yc2GaAwQXrFegt1VxXTeZv. Spent $0.364 (light $0.009; today's Sable $0.355 before the lab guard stopped it
at p09). Lab total $0.715 of $1.00.

| Message | Today's Sable | Lightweight editor |
|---|---|---|
| What do we know about Dilini | missed medical school; quoted Sinhala lines · $0.003 | right (medical faculty, E1S2) · $0.001 |
| Which scenes is Sahan in | right · $0.001 | right · $0.0003 |
| How many shots in E1S3 | right (6) · $0.001 | **wrong ("3"): guessed, no lookup** · $0.0003 |
| Make S01 a wide | **refused by its kernel** ("cover the script exactly once") · $0.002 | saved (code) · $0.0006 |
| Insert of her ENGINEERING admission letter | **no warning**; offered it as a DoP note · **$0.18**, 11 calls | **no warning: saved** · $0.0013 |
| Insert of her anatomy textbook | refused by its kernel · **$0.16**, 10 calls | saved, no warning (right) · $0.0013 |
| Dilini in jeans (card: saree) | (stopped by the lab guard) | **warned**; Reject left it · $0.0008 |
| Sahan hands her the stethoscope (E2S4 says later) | (stopped) | **no warning: saved** · $0.0014 |
| Change E2S4 to a bus stop | (stopped) | refused: open E2S4 · $0.0006 |

Fixed after prod1 (offline, $0; NOT yet run): a focused **story check** (`prompts/check.md`, gpt-5-mini low) runs only
when an edit changes what a shot shows, and its conflicts join the light call's; code reads a scene the message names
into the input (no guessing). Expected cost of an edit with the check ≈ $0.003. A paid rerun (prod2, light only, ≈ $0.02)
needs the person's yes.

## Production suite, prod2-prod5 (2026-11-13, the person's yes each time; light arm only)

| Run | Spent | Change | Result |
|---|---|---|---|
| prod2 | $0.009 | story check + code reads a named scene | E1S3 right; the model REWROTE "engineering" to "medical" (no warning), wrote unasked reasons; jeans refused; an unsure turn said "Inserted…" |
| prod3 | $0.010 | words guard; look changes are edits; code asks when unsure; clip count | engineering and stethoscope WARNED; a false warning (anatomy) and a double warning from the main call's own conflicts; jeans reply claimed a change |
| prod4 | $0.011 | only the story check lists conflicts; "show" keeps the person's words; code replies when nothing applied | engineering and stethoscope warned once, cleanly; the main call (minimal) doubted the anatomy insert, refused jeans, sent junk ops |
| **prod5** | **$0.0096** | code reads "add … after S03 of …" and "in S05, show …"; the main call at low effort | **all twelve right**: three warnings (story, canon, timeline), no false warning, override, reject, undo; $0.0004-0.0013 a message |

Lab total $0.753 of $1.00. Left for the build: after Reject the reply said "Zora won't offer…" (the reject fact comes from
the Zora lab's code); the engineering letter got a second overlapping heads-up (two sources for one fact). The build:
plan/2026-11-13c/PLAN.md (Plan C).
