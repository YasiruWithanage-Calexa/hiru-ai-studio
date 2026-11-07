# Zora lab

Proves Zora's two prompts (the conductor and the author) on the person's own scenes before the chat system is wired
([plan/2026-11-06e/PLAN.md](../../plan/2026-11-06e/PLAN.md) Phase 3, plain words in
[human-read.md](../../plan/2026-11-06e/human-read.md)). It runs the product's own Zora code (kernel, dependency graph,
board, the planner's gate, delivery check, ledger); only the model calls are the lab's. Deleting this folder removes
the lab (`hiru-ai remove --group zora` lists it).

## Status

Built offline 2026-11-06. **No paid run yet: $0.00 of $3.00 spent.** Every paid run needs the person's yes.

## Run it (from the repo root)

```
.venv/Scripts/python.exe -m pytest lab/zora/tests -q                         # the offline tests
OPENAI__API_KEY= .venv/Scripts/python.exe lab/zora/run.py offline            # every case on recorded answers (free)
OPENAI__API_KEY= .venv/Scripts/python.exe lab/zora/run.py cost --split tune --arms A B   # what a run could cost
OPENAI__API_KEY= .venv/Scripts/python.exe lab/zora/run.py dry --case approach-colder --show   # the exact prompts
.venv/Scripts/python.exe lab/zora/run.py paid --yes --arm A --split tune     # REAL calls (costs money)
.venv/Scripts/python.exe lab/zora/run.py compare --run lab/zora/runs/1-A-tune lab/zora/runs/2-B-tune   # blind page
.venv/Scripts/python.exe lab/zora/run.py ledger
```

Blank `OPENAI__API_KEY` for everything but `paid`: only `paid` reads `.env`.

## The money rules (code, in `run.py`)

- `BUDGET_USD = 3.00` (D10). A call is refused when the ledger total plus its **worst case** (input at the input price +
  `max_output_tokens` at the output price) would pass it. An unpriced model is refused.
- The same request is answered from `runs/cache/` for free: never pay twice.
- A failed call is entered at its worst case.
- After the first paid run, `--hypothesis` is required: one change per paid run.
- Stop when the held-out cases pass at k=3 (`paid --split heldout --k 3`), or when the budget says stop.

What the money buys (estimated 2026-11-06 by `cost`, prices in `run.py`):

| Run | Likely | Worst (first calls) |
|---|---|---|
| arm A, 7 tune cases, k=1 | $0.73 | $1.65 |
| arm B, 7 tune cases, k=1 | $0.22 | $0.54 |
| arm A, 5 held-out cases, k=3 | $1.18 | $2.60 |
| both arms, all 12 cases, k=1 | $1.38 | $3.11 |

So $3 holds one A-vs-B comparison on the tune cases and the held-out check of the winner, with little room for prompt
changes in between. A repair or a re-task adds an author call (each about $0.10, worst $0.16). Raising the budget is the
person's decision.

## The arms (D2)

- **A, one author**: ONE call on the planner's model (`gpt-6.1-sol`, low effort) with Jonathan's own system prompt as the
  primer and `prompts/author.md` after it, for all of the turn's tasks.
- **B, Nova's seats**: today's four `director_board` crafts (cinematography, continuity, sound, timing) as separate
  calls on `gpt-5-mini`, each owning its effects; the same primer, told which seat it is.

Both arms get the case's **recorded** conductor answer (`tests/eval/zora/cases.json`), so the end plans differ only by
the author side. The conductor (`prompts/conductor.md`, `gpt-5-mini`) is run once per case and scored on its own: lane,
ops, declared effects. The reply is not in the lab.

## What is here

| File | What it is |
|---|---|
| `prompts/conductor.md` | the conductor's charter (≤ 7,500 characters, no case wording: `tests/test_lab.py`) |
| `prompts/author.md` | Zora's charter, appended to Jonathan's own author prompt (≤ 3,000 characters) |
| `contracts/zora/wire.py` | the strict answer shapes and their conversion to Zora's operations (moved out of the lab on 2026-11-07, so the lab and the product's agents send the same bytes) |
| `turn.py` | one turn on the product's code: kernel → stale tasks → author or seats → board → kernel → gate (one repair) → delivery (one re-task) → scoring |
| `run.py` | dry, cost, offline, paid, ledger, compare |
| `answers/` | hand-written author answers for three cases (the offline run and the tests; no model wrote them) |
| `build_fixtures.py` | copies three of the cinematic lab's saved plans into `tests/eval/zora/fixtures` (no model call) |
| `RESULTS.md` | where the paid runs, the blind read and the decision are written |
