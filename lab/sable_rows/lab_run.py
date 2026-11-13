"""Sable as a lightweight shot editor: the lab (2026-11-13). NOTHING reads or writes a database or `src/`.

    python lab/sable_rows/lab_run.py rehearse                    # Arm L with NO model (canned answers): runs/rehearsal
    python lab/sable_rows/lab_run.py dry                         # what a paid run would cost at most
    python lab/sable_rows/lab_run.py paid --yes --arm both       # PAID (the person's yes first): today | light | both

The same twelve shot-editing messages on both arms, one thread each, on the Zora lab's scene (Hiru Short Combined 2,
Scene 03, 20 Raphael clips). Arm T is today's Sable (its real code on test fakes); Arm L the lightweight editor
(`light.py`). Results: runs/<run>/{today,light}.json and index.html, side by side.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path[:0] = [str(HERE), str(ROOT / "lab" / "zora_rows"), str(ROOT / "src" / "libs"), str(ROOT / "lab")]

import agents  # noqa: E402  (lab/zora_rows)
import light  # noqa: E402  (puts lab/zora_rows on the path)
import page  # noqa: E402
import today  # noqa: E402
from coverage import Coverage  # noqa: E402
from turn import Thread  # noqa: E402

SCENARIO = [
    ("m01", "How many shots does this scene have, and which ones carry dialogue?"),
    ("m02", "Who is on screen in S07?"),
    ("m03", "Make S01 a wide, 6 seconds."),
    ("m04", "Shorten S13 to 6 seconds."),
    ("m05", "Make S10 a close-up and S12 an MCU."),
    ("m06", "Move S15 before S14."),
    ("m07", "Drop S08."),
    ("m08", "[Accept]"),
    ("m09", "Undo that."),
    ("m10", "Add an insert of the key in Dinu's palm after S15."),
    ("m11", "Make the argument from S08 to S13 tenser."),
    ("m12", "Are any shots silent but carrying a line?"),
]

# The production suite (2026-11-13, the person: Sable works within the scene, aware of the production; it warns when an
# edit contradicts the story and the person may override). Open scene E2S2 of the lab story copy of "test" (story.py).
PROD_FILE = HERE / "input" / "story_production.json"
PROD_OPEN = "E2S2"
PROD_SCENARIO = [
    ("p01", "What do we know about Dilini so far?"),
    ("p02", "Which scenes is Sahan in?"),
    ("p03", "How many shots does E1S3 have, and who speaks in them?"),
    ("p04", "Make S01 a wide."),
    ("p05", "Add a 4-second insert after S02 of Dilini's engineering faculty admission letter."),
    ("p06", "[Accept]"),
    ("p07", "Undo that."),
    ("p08", "Add a 4-second insert after S03 of Dilini's anatomy textbook."),
    ("p09", "In S05, show Dilini wearing jeans and a t-shirt."),
    ("p10", "[Reject]"),
    ("p11", "Add a shot after S06 of Sahan handing Dilini a stethoscope."),
    ("p12", "Change the tea shop in E2S4 to a bus stop."),
]

# the light arm's money: its own ledger and cache under lab/sable_rows/runs (the Zora lab's stay untouched)
agents.RUNS, agents.LEDGER, agents.LAB_CAP_USD, agents.FIELDS = today.RUNS, today.LEDGER, today.LAB_CAP_USD, today.FIELDS

_NUL = {k: None for k in agents.OP_FIELDS if k != "op"}
REHEARSAL = {
    "m01.light": {"lane": "answer", "confidence": 0.9, "ops": [], "answer": "Twenty clips; S05, S08 and S11 carry the lines."},
    "m02.light": {"lane": "answer", "confidence": 0.9, "ops": [], "answer": "Just Dinu, reacting to Nimal's case."},
    "m04.light": {"lane": "edit", "confidence": 0.9, "ops": [{**_NUL, "op": "retime", "shot": "S13", "take_s": 6}], "answer": ""},
    "m05.light": {"lane": "edit", "confidence": 0.9, "answer": "", "ops": [
        {**_NUL, "op": "set", "shot": "S10", "field": "size", "value": "CU"},
        {**_NUL, "op": "set", "shot": "S12", "field": "size", "value": "MCU"}]},
    "m06.light": {"lane": "edit", "confidence": 0.9, "ops": [{**_NUL, "op": "move", "shot": "S15", "after": "S13"}], "answer": ""},
    "m10.light": {"lane": "edit", "confidence": 0.9, "answer": "", "ops": [
        {**_NUL, "op": "insert", "after": "S15", "role": "insert", "size": "INSERT", "take_s": 4, "first_block": 5,
         "last_block": 5, "who": ["Dinu"], "what": "the key in Dinu's palm"}]},
    "m11.light": {"lane": "zora", "confidence": 0.9, "ops": [], "answer": "That's craft work for Zora."},
    "m12.light": {"lane": "answer", "confidence": 0.9, "ops": [], "answer": "No: every line is on a speaking clip."},
}


_C = {"fact": "", "source": "", "why": ""}
REHEARSAL.update({
    "p01.light": {"lane": "answer", "confidence": 0.9, "lookup": "", "ops": [], "conflicts": [],
                  "answer": "Dilini got into the Colombo Medical Faculty in E1S2."},
    "p02.light": {"lane": "answer", "confidence": 0.9, "lookup": "", "ops": [], "conflicts": [],
                  "answer": "Every tea-shop scene."},
    "p03.light": {"lane": "lookup", "confidence": 0.9, "lookup": "E1S3", "ops": [], "conflicts": [], "answer": ""},
    "p03.light2": {"lane": "answer", "confidence": 0.9, "lookup": "", "ops": [], "conflicts": [],
                   "answer": "Six shots; Nimal and Kumari speak."},
    "p05.light": {"lane": "edit", "confidence": 0.9, "lookup": "", "answer": "", "ops": [
        {**_NUL, "op": "insert", "after": "S02", "role": "insert", "size": "INSERT", "take_s": 4, "first_block": 2,
         "last_block": 2, "who": ["Dilini"], "what": "Dilini's engineering faculty admission letter"}],
        "conflicts": [{**_C, "fact": "accepted to the Colombo Medical Faculty", "source": "E1S2",
                       "why": "the letter would be from an engineering faculty"}]},
    "p08.light": {"lane": "edit", "confidence": 0.9, "lookup": "", "answer": "", "conflicts": [], "ops": [
        {**_NUL, "op": "insert", "after": "S03", "role": "insert", "size": "INSERT", "take_s": 4, "first_block": 3,
         "last_block": 3, "who": ["Dilini"], "what": "Dilini's anatomy textbook"}]},
    "p09.light": {"lane": "edit", "confidence": 0.9, "lookup": "", "answer": "", "ops": [
        {**_NUL, "op": "set", "shot": "S05", "field": "sees", "value": "Dilini wearing jeans and a t-shirt"}],
        "conflicts": [{**_C, "fact": "Wears a saree", "source": "Dilini's card", "why": "jeans and a t-shirt"}]},
    "p11.light": {"lane": "edit", "confidence": 0.9, "lookup": "", "answer": "", "ops": [
        {**_NUL, "op": "insert", "after": "S06", "role": "two_shot", "size": "TWO", "take_s": 4, "first_block": 5,
         "last_block": 5, "who": ["Sahan", "Dilini"], "what": "Sahan handing Dilini a stethoscope"}],
        "conflicts": [{**_C, "fact": "Sahan gives Dilini a stethoscope", "source": "E2S4",
                       "why": "it would happen two scenes early"}]},
    "p05.check": {"conflicts": []},
    "p08.check": {"conflicts": []},
    "p09.check": {"conflicts": []},
    "p11.check": {"conflicts": []},
    "p12.light": {"lane": "cannot", "confidence": 0.9, "lookup": "", "ops": [], "conflicts": [],
                  "answer": "E2S4 is another scene: open it and ask there."},
})


def run_light(backend: object, name: str, suite: str = "scene") -> list[dict]:
    prod = None
    if suite == "prod":
        from prod import Production

        prod = Production.load(PROD_FILE)
        th = Thread(cov=prod.coverage(PROD_OPEN))
        th.open_label = PROD_OPEN  # type: ignore[attr-defined]
    else:
        th = Thread(cov=Coverage.load(today.SCENE_FILE))
    out = []
    for slot, message in PROD_SCENARIO if suite == "prod" else SCENARIO:
        print(f"L {slot}: {message}", flush=True)
        try:
            rec = light.run_turn(th, message, backend, slot, prod)
        except agents.CapError as exc:
            out.append({"slot": slot, "message": message, "stopped": str(exc)})
            break
        out.append(rec)
        print(f"  lane {rec['lane']} · saved {rec['saved']} · card {bool(rec['card'])} · ${rec['dollars']:.5f}")
    return out


def run_today(name: str, suite: str = "scene") -> list[dict]:
    if suite == "prod":
        sable = today.TodaySable(name, production=json.loads(PROD_FILE.read_text(encoding="utf-8")), open_ref=PROD_OPEN)
    else:
        sable = today.TodaySable(name)
    out = []
    for slot, message in PROD_SCENARIO if suite == "prod" else SCENARIO:
        if message.startswith("["):  # a button in the product: an API action, not a Sable turn
            out.append({"slot": slot, "message": message, "skipped": "a button in the product (the API applies the "
                        "card with the classic director function), not a Sable turn"})
            continue
        print(f"T {slot}: {message}", flush=True)
        try:
            rec = sable.turn(slot, message)
        except today.CapError as exc:
            out.append({"slot": slot, "message": message, "stopped": str(exc)})
            break
        out.append(rec)
        print(f"  ${rec['dollars']:.5f} · {len(rec['calls'])} calls · {len(rec['cards'])} cards · {rec['seconds']} s")
    return out


def save(name: str, arm: str, records: list[dict]) -> None:
    d = today.RUNS / name
    d.mkdir(parents=True, exist_ok=True)
    (d / f"{arm}.json").write_text(json.dumps(records, indent=1, ensure_ascii=False, default=str), encoding="utf-8")


def load(name: str, arm: str) -> list[dict] | None:
    p = today.RUNS / name / f"{arm}.json"
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else None


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("mode", choices=["rehearse", "wire", "dry", "paid"])
    ap.add_argument("--yes", action="store_true")
    ap.add_argument("--arm", choices=["today", "light", "both"], default="both")
    ap.add_argument("--run", default="run1")
    ap.add_argument("--suite", choices=["scene", "prod"], default="scene")
    a = ap.parse_args()
    if a.mode == "rehearse":
        save("rehearsal", "light", run_light(agents.Rehearsal(REHEARSAL), "rehearsal", a.suite))
        (today.RUNS / "rehearsal" / "index.html").write_text(page.page("rehearsal", None, load("rehearsal", "light")),
                                                            encoding="utf-8")
        print("rehearsal written: runs/rehearsal/index.html")
        return 0
    if a.mode == "wire":  # today's Sable on the fakes with NO model: the wiring, for $0
        import os

        if os.environ.get("OPENAI__API_KEY", None) != "":
            print("wire runs with no model: start it with OPENAI__API_KEY= (blank)")
            return 2
        save("wire", "today", run_today("wire", a.suite))
        print(json.dumps(load("wire", "today"), indent=1, ensure_ascii=False, default=str)[:3000])
        return 0
    if a.mode == "dry":
        print(f"Lab cap ${today.LAB_CAP_USD:.2f}; spent so far ${today.spent():.4f}.")
        print(f"Arm T (today's Sable): {len([m for _, m in SCENARIO if not m.startswith('[')])} turns, each refused "
              f"before it starts unless ${today.TURN_WORST_USD:.2f} fits under the cap; expected a few cents a turn.")
        print(f"Arm L (light): {len(SCENARIO)} turns, each capped at ${light.TURN_CAP_USD:.3f} in code.")
        return 0
    if not a.yes:
        print("A paid run needs --yes (the person's yes first).")
        return 2
    if a.arm in ("light", "both"):
        save(a.run, "light", run_light(agents.Paid(a.run, models=light.LIGHT_MODELS), a.run, a.suite))
    if a.arm in ("today", "both"):
        save(a.run, "today", run_today(a.run, a.suite))
    (today.RUNS / a.run / "index.html").write_text(page.page(a.run, load(a.run, "today"), load(a.run, "light")),
                                                  encoding="utf-8")
    print(f"{a.run}: written; lab spent ${today.spent():.4f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
