# Coverage lab (2026-11-18)

Does shooting a small accident "the way TV dramas do" (an insert of the accident, a separate wide of the person moving
on with the prop already where it fell) fix what five Omni Flash takes of the phone drop got wrong? The findings, the
workaround and what was built from it: [plan/2026-11-18b/PLAN.md](../../plan/2026-11-18b/PLAN.md).

Scene: Api Denna v2, Episode 1, Scene 3 (E01-S03), from the saved breakdown memory and packet of
`lab/llm_reader/runs/e2e` (`03_memory.json`, `05_packets.json`). The scene, canon and line rows are built with the
product's own `contracts.breakdown.fill`. Nothing is written to the database.

## Commands

    .venv/Scripts/python.exe lab/coverage/run.py today              free
    .venv/Scripts/python.exe lab/coverage/run.py coverage --yes     paid: Raphael re-plans (cap $0.40)
    .venv/Scripts/python.exe lab/coverage/board.py --yes            paid: board writer + one LOW image

- `today`: the SAVED plan (`lab/llm_reader/runs/e2e/12_raphael/E01-S03.json`) through `raphael_write` and the
  serializer, twice: as the product is, and with the lab's own fixes switched on.
- `coverage`: adds the rule `h90_coverage.md` as a house rule in this process only, then plans the scene again.
  - The rule is now in the product as H-15, so this arm now gives Raphael the rule twice; drop the lab rule before
    running it again.
- `board.py`: paints the Scene board of the coverage plan the way the product does. It uses no reference pictures,
  because no canon sheets exist outside the database.

The lab's fixes in `run.py` (`fixed=True`) are the ones now built in `src/`. On today's code, the `product/`
reports (made with `fixed=False`) are the product's own output.

## Runs

| Folder | What |
|---|---|
| `runs/today/` | saved plan: `plan.txt`, `prompts_today.md` / `checks_today.md` (the serializer before the fix), `prompts_fixed.md` / `checks_fixed.md` (lab fixes); `product/` = today's src |
| `runs/coverage/` | the re-plan: `12_raphael/E01-S03.json` (Raphael's result), `plan.txt`, `prompts_fixed.md`, `checks_fixed.md`, `spend.txt`; `product/` = today's src |
| `runs/coverage/board/` | `sheet.png` (numbered), `board.png`, `cell_NN.png`, `writer.json`, `prompt.txt`, `spend.txt` |

## What the checks look for

`checks_*.md` lists, per shot:
- **CONTRADICTION**: a hand lets go while a constraint says objects stay put or nothing is put down.
- **CAMERA WORDS IN THE ACTION**
- **NOT-NOTICING WRITTEN AS A NEGATIVE**
- **COMPOUND**: the accident and the person moving on are in one clip.
- **REPEATED BEAT**: two windows carry the same text.
- **STATIC CAMERA SAID SOFTLY**

## Money

| Call | Cost |
|---|---|
| Raphael re-plan | $0.1678 |
| Board (writer + LOW image) | $0.0892 |
| Total | $0.257 |
