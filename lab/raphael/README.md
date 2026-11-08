# Raphael lab

Phase 0 of [plan/2026-11-08e/PLAN.md](../../plan/2026-11-08e/PLAN.md): DaVinci's raw-coverage result, planned by ONE model with
code tools only. Nothing under `src/` changes, no database row is written, DaVinci and the other planners are untouched, and
deleting this folder removes the lab.

**Status (2026-11-08):** phase 0a built; phase 0b's three paid runs done ($1.18 of $5.00), all reached `finish` in 4-7
turns. Results: [plan/2026-11-08e/RESULTS.md](../../plan/2026-11-08e/RESULTS.md). A fourth run waits for the person's read.

## Run it (from the repo root)

```
.venv/Scripts/python.exe -m pytest lab/raphael/tests -q                  # the offline tests
OPENAI__API_KEY= .venv/Scripts/python.exe lab/raphael/run.py dry          # the prompt, first message, tools and the price; calls nothing
OPENAI__API_KEY= .venv/Scripts/python.exe lab/raphael/run.py rehearse     # the whole loop with NO model; writes runs/rehearsal/bin.html
OPENAI__API_KEY= .venv/Scripts/python.exe lab/raphael/run.py pick         # the small part for the post team
.venv/Scripts/python.exe lab/raphael/run.py paid --yes --hypothesis "…"   # a REAL run: the person's yes first, `dry` first
```

## What is here

| File | What it is |
|---|---|
| `schema.py` | `ClipW`: DaVinci's clip plan (`MenuW`) + its Veo design (`ir`, `sound`) + `id` ("" = new); `put_schema()` |
| `agent.py` | the loop; tools `write_edit_plan`, `put_clips`, `remove_clips`, `read_bin`, `finish`; every write returns the report |
| `prompts/raphael.md` | the one prompt: DaVinci's director prompt minus delegation, plus the clip writer's design rules, plus the length target |
| `rehearsal.py` | DaVinci's hand-written Episode 1 tables through the real loop: edit plan, three sequences, a refused `finish`, ONE batch repair of two clips, `finish` accepted (7 turns) |
| `render.py` | DaVinci's page, titled Raphael, with seconds against the target and the cap, and the turns used |
| `run.py` | `dry`, `rehearse`, `paid`, `pick`, `ledger` |

Imported from `lab/davinci` (R2, one copy): `checks` (all of them, including the 1.5x length cap), `state.Bin` (ids, slates,
replace keeps must), the edit-plan shape, `money.Meter`, `brain.OpenAIBackend`. Raphael has its **own** ledger
(`runs/ledger.csv`): its own $5 lab budget; each run stops at $5.

## Choices the plan left open

- **The report** lists blocking faults first (at most 30, the rest counted), then code's reports, then `Seconds: … target 60 s,
  cap 90 s` and `Turns left after this one`. A fault is marked STILL FAILING only when it was in the last report and the
  last write replaced one of its clips, so a hole not yet built is never marked.
- **`put_clips` is all or nothing on the schema** (a call that does not fit changes nothing); an unknown id is named and skipped.
- **D1 (stop early)**: the lab saves everything, marked INCOMPLETE on the page and `complete: false` in `outcome.json`.
- **Model**: `gpt-5` high (D7's lab recommendation), `max_output` 48k, turn cap 20 (R1). `paid` refuses a fourth run until the
  person's read (`--past-read`).
