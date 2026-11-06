# Cinematic David lab

Proves a cinematic shot planner on Episode 1 before anything moves into the product
([plan/2026-11-06/PLAN.md](../../plan/2026-11-06/PLAN.md), plain words in [human-read.md](../../plan/2026-11-06/human-read.md)).
Nothing under `src/` changes, no database row is written, and deleting this folder removes the lab.

## Status

Phases 0 to 6b are done and a general **stabiliser** (`run.py auto`) is built and tested on five scenes (2026-11-06): 19 paid calls, **$4.04 of $5.00 spent**. See [RESULTS.md](RESULTS.md): the runs, the evidence, what it does not prove, the gate and the person's decision. The blind page for a re-read is `runs/17-gpt_5-high/side_by_side.html`.

## Run it (from the repo root)

```
.venv/Scripts/python.exe -m pytest lab/cinematic/tests -q            # the offline tests
OPENAI__API_KEY= .venv/Scripts/python.exe lab/cinematic/run.py dry   # the exact message, schema and price; calls nothing
OPENAI__API_KEY= .venv/Scripts/python.exe lab/cinematic/run.py offline   # check + render the hand-written answer
.venv/Scripts/python.exe lab/cinematic/run.py models                 # list the account's models (free; reads .env)
.venv/Scripts/python.exe lab/cinematic/run.py paid --yes --hypothesis "…"   # a real call; read `dry` first
```

Blank `OPENAI__API_KEY` for everything but `paid` and `models`: only those two read `.env`. `offline` writes
`runs/offline/plan.html`; `compare` writes the blind page `side_by_side.html` beside it.

The stabiliser, for any scene (costs about $0.2 a call, 1 to 3 calls):

```
.venv/Scripts/python.exe lab/cinematic/run.py auto --yes --scene arrival --passes 2
```

## The money rules (they are code, in `run.py`)

- `BUDGET_USD = 5.00`, a constant. A call is refused when the ledger total plus its **worst case** (input tokens at the input
  price + `max_output_tokens` at the output price; default 40,000, reasoning included) would pass it.
- A model with no entry in `PRICES` is refused. `gpt-5`, `gpt-5-mini` and `gpt-5-nano` are listed (the list prices
  `scripts/david_spike.py` uses); read any other model's price off OpenAI's pricing page and add it first.
- A failed call is entered at its worst case; a cut-off call at its reported usage.
- The same request (system prompt + example, user message, schema, model, effort) reuses its saved answer for free.
- After the first run, `--hypothesis` is required and saved in `runs/<n>/notes.md`: one change per paid run, at most 4
  improvement runs, then stop (plan §2.7).

## What is here

| File | What it is |
|---|---|
| `input/story.txt` | Episode 1, copied from `tests/fixtures/prose/three-episode-drama.txt` |
| `input/reading.yaml` | the corrected reading: one scene, Kasun's thought as a voice-over (L3), the narrator's line (L22), the father on the phone (L16), the people's essence, the style and the time policy |
| `input/second_scene.yaml` | the overfit guard: the gold `phone_call` scene (replace with a real Hiru scene if you choose) |
| `input/chatgpt.md` | ChatGPT's 19-shot answer (pasted 2026-11-06) |
| `input/david_today.json` | David's stored plan (read from the hosted database, read-only, 2026-11-06), as `[{"scene": {…the scene's raw yaml dict…}, "stored": {…scenes.david…}}]` |
| `prompt/system.md`, `prompt/example.json` | the team prompt and ONE worked example (`refuses_money`, not Episode 1) |
| `schema.py` | `CinemaWire`: treatment, sequences, 11 sizes, angle, lens, `use_s`; its strict JSON schema |
| `pack.py` | reads an input yaml; builds the user message (essence, style, time policy, heard lines marked) |
| `checks.py` | the existing David checks + the lab's hard checks + the craft measures |
| `mend.py` | what code fixes, with the split fix (F8) |
| `render.py` | `plan.html` and the blind side-by-side |
| `run.py` | dry run, paid run, budget, cache, ledger, offline check |
| `fixtures/build_fixtures.py` | writes `prompt/example.json` and `fixtures/fake_answer.json` (a hand-written Episode 1 plan: 25 shots, 5 sequences, no model) |
| `rubric.md`, `RESULTS.md` | how to score a plan; where the runs, the gate and the decision are written |

## What differs from the plan's text, and why

- **`mend.py` does not call `contracts.david.mend.mend`.** That is one function over a `DavidWire`, so it cannot keep the
  new fields and the split fix cannot be put inside it. The lab's `mend()` does the same four steps in the same order with
  the same building blocks (`addition_fault`, `free_text`, `strip_speech`, the clock, `split_items`).
- **A beat that straddles a cut goes to the part that holds its midpoint**, never to both (a beat copied into two parts is
  the F8 bug). A split part's `first_frame` is still the original's: code cannot know a later part's opening frame.
- **A heard-only voice is judged by its lines** (`checks.heard_names`: every line of theirs is heard), because
  `contracts.david.scene.heard_only` also needs that no action block names them, so a script that says "It is her father"
  hides the father and the old check would let him into a frame.
- **Craft measures are rules of thumb** (a size list, a name in the subjects, a word in the text). They point the reader's
  eye; the rubric is the judge.

## Still needed from the person

1. The decision in RESULTS.md. Gate point 2 is met (second read: lab 9, ChatGPT 8.5, David today 6); open are a read by someone who has
   not seen the plans, the second scene's rating (point 4) and the stabiliser's repeatability (point 3).
2. $0.96 is left; nothing more is spent until you say.
