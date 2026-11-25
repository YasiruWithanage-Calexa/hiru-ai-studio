"""plan/2026-11-25 B0: does the board check see a third arm? PAID (the person's yes, 2026-11-25), cap $0.50.

Runs `board_inspector` on the ten panels `export.py` saved, three times each, in these forms:

  R0  today's check: the product's prompt, schema and words, the pictures at `detail: low`
  R1  R0 with the pictures at `detail: high`
  R2  R1 + count first: a `counts` field (per mannequin: arms, hands, what each hand holds) BEFORE the flags, and the
      LIMBS rule told to trace and count; code also calls more than two arms or hands a fault
  R3  R2 with `reasoning_effort: high`                    (only when R2 misses a bad panel)
  R4  R2 on the next model up                             (only when R3 misses a bad panel)

The call is the product's `Agent._structured` (core/agents.py) with the detail, schema, prompt, model and effort as
the run says: the same system prompt (`Agent.prepare`), the same user message, the same pictures in the same order.

    .venv/Scripts/python.exe lab/board_hands/run.py R0 R1 R2      (or R3 / R4)

Writes `runs/<run>_<repeat>.json` and prints the score; `runs/spend.json` holds the money spent so far.
"""
from __future__ import annotations

import base64
import json
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path[:0] = [str(ROOT / "src" / "libs")]

from hiru_ai.agents.board_inspector.schema import Input  # noqa: E402
from hiru_ai.agents.board_inspector.schema import Output as Today  # noqa: E402
from hiru_ai.core import agents  # noqa: E402
from hiru_ai.core.settings import get_settings  # noqa: E402
from hiru_ai.systems.frame_render.board import _faults  # noqa: E402

CAP = 0.50
REPEATS = 3
PRICES = {"gpt-5-mini": (0.25, 2.00), "gpt-5": (1.25, 10.00)}  # USD per million tokens, input / output
NEXT_UP = "gpt-5"


class Count(BaseModel):
    mannequin: str = Field(description="The mannequin's colour.")
    arms: int = Field(description="Arms of this mannequin you can see, whole or in part, each traced from its "
                                  "shoulder; an arm hidden behind the body or cut by the frame is not counted.")
    hands: int = Field(description="Hands you can see that belong to this mannequin, on its arms or not.")
    hands_hold: list[str] = Field(description="One entry per hand counted: what it holds or does ('the umbrella "
                                              "shaft', 'the phone at the ear', 'empty, at the hip').")


class Counted(BaseModel):
    counts: list[Count] = Field(description="Filled FIRST: one entry per mannequin in the picture.")
    extra_limbs: bool = Field(description=Today.model_fields["extra_limbs"].description)
    floating: bool = Field(description=Today.model_fields["floating"].description)
    ungrounded: bool = Field(description=Today.model_fields["ungrounded"].description)
    hands_match: bool = Field(default=True, description=Today.model_fields["hands_match"].description)
    view_match: bool = Field(default=True, description=Today.model_fields["view_match"].description)
    problems: list[str] = Field(description=Today.model_fields["problems"].description)


TODAY_LIMBS = """- LIMBS. Count the arms and hands of each mannequin you can see. Every mannequin has exactly two arms and two hands
  (and two legs when the legs are in frame). An arm that comes from nowhere, a third hand on a bag or an umbrella, or
  a missing arm that should be in frame is `extra_limbs`. An arm hidden behind the body or cut by the frame edge is
  not a fault."""
COUNT_LIMBS = """- LIMBS. Fill `counts` FIRST, one entry per mannequin in the picture: trace each arm from its shoulder to its hand
  and count the arms and the hands you see, and say what each hand holds. Look hard where a third arm hides: hanging
  beside the hip, flat across the chest, behind a bag or an umbrella shaft, a fist at an elbow. Every hand must join
  an arm that joins that mannequin's shoulder. Every mannequin has exactly two arms and two hands (and two legs when
  the legs are in frame). More than two arms or hands, an arm that comes from nowhere, a third hand on a bag or an
  umbrella, or a missing arm that should be in frame is `extra_limbs`. An arm hidden behind the body or cut by the
  frame edge is not a fault and is not counted."""

# R5/R6 (2026-11-25, the person's yes, a new cap of $0.40): the BLIND count. R0-R3 showed the check copies the
# expected HANDS words back; here the model is told only the mannequins' colours and sees only the panel, and code
# decides: more than two arms or hands, or a held thing in the air, is a fault.
BLIND_SYSTEM = """You look at one panel of a storyboard. The people in it are smooth, faceless artist's mannequins, one solid colour
each; props are plain white clay stand-ins; the place is a real photograph. The panel was painted by an image model,
which sometimes paints a mannequin with three arms or hands, or a thing held up by nothing. Report only what you SEE,
never what a person should have.

For each mannequin in the picture, fill `counts`: trace every arm you can see from where it joins the body to its
hand, and count the arms and the hands. Look hard where an extra arm hides: hanging beside the hip, flat across the
chest, behind a bag or an umbrella shaft, a fist at an elbow, a hand that joins no arm. An arm hidden behind the body
or cut by the frame edge is not counted. For each hand you counted, say what it holds or does.

Then fill `things`: every thing a mannequin holds or carries (umbrella, bag, phone, cup, paper). For each, say where it
is: `hand` when a hand grips it (an umbrella's shaft runs down into a closed hand; a bag's handles are over a hand,
wrist, forearm or shoulder), `surface` when it rests on something, `air` when nothing holds it (a canopy whose shaft
reaches no hand, a phone in the air, a loose piece of a thing)."""


class Thing(BaseModel):
    thing: str = Field(description="What it is: 'umbrella', 'bag', 'phone'.")
    mannequin: str = Field(description="The colour of the mannequin it belongs to, or 'none'.")
    where: str = Field(description="'hand', 'surface' or 'air', as the instructions say.")


class Blind(BaseModel):
    counts: list[Count] = Field(description="One entry per mannequin in the picture.")
    things: list[Thing] = Field(description="Every thing a mannequin holds or carries.")


RUNS: dict[str, dict[str, Any]] = {
    "R0": {"detail": "low", "count": False, "model": "gpt-5-mini", "effort": None},
    "R1": {"detail": "high", "count": False, "model": "gpt-5-mini", "effort": None},
    "R2": {"detail": "high", "count": True, "model": "gpt-5-mini", "effort": None},
    "R3": {"detail": "high", "count": True, "model": "gpt-5-mini", "effort": "high"},
    "R4": {"detail": "high", "count": True, "model": NEXT_UP, "effort": None},
    "R5": {"detail": "high", "blind": True, "model": "gpt-5-mini", "effort": None},
    "R6": {"detail": "high", "blind": True, "model": NEXT_UP, "effort": None},
}
SPEND = HERE / "runs" / "spend.json"
BLIND_CAP = 0.851  # $0.451 spent on R0-R3 + the person's new $0.40 for R5/R6


def spent() -> float:
    return float(json.loads(SPEND.read_text())["usd"]) if SPEND.exists() else 0.0


def add_spend(usd: float) -> None:
    SPEND.write_text(json.dumps({"usd": round(spent() + usd, 6)}))


def call(run: dict[str, Any], case: dict[str, Any]) -> dict[str, Any]:
    from langchain_core.messages import HumanMessage, SystemMessage
    from langchain_openai import ChatOpenAI
    from pydantic import SecretStr

    agent = agents.build("board_inspector")
    shot = case["shot"]
    inp = Input.model_validate({**case["input"], "image_b64": b64(f"shot_{shot}.png"),
                                **({"view_b64": b64(f"shot_{shot}_view.png")} if case["input"].get("view") else {})})
    mc = agent.prepare(inp)  # the product's system prompt, user message and pictures
    system, text, images = mc.system, mc.user, list(mc.images)
    schema: type[BaseModel] = Today
    if run.get("blind"):  # only the colours, only the panel
        colours = [p.split(" is the ", 1)[-1] for p in case["input"]["people"]]
        system, schema, images = BLIND_SYSTEM, Blind, images[:1]
        text = "MANNEQUINS IN THIS PANEL:\n" + "\n".join(f"- the {c}" for c in colours)
    elif run.get("count"):
        assert TODAY_LIMBS in system, "the product's LIMBS rule changed: the lab's words no longer apply"
        system, schema = system.replace(TODAY_LIMBS, COUNT_LIMBS), Counted
    user = [{"type": "text", "text": text},
            *({"type": "image_url", "image_url": {"url": f"data:{mime};base64,{data}", "detail": run["detail"]}}
              for mime, data in images)]
    kwargs: dict[str, Any] = {"reasoning_effort": run["effort"]} if run["effort"] else {}
    model = ChatOpenAI(model=run["model"], api_key=SecretStr(get_settings().openai.api_key.get_secret_value()),
                       timeout=180, max_retries=1, **kwargs)
    runnable = model.with_structured_output(schema, method="json_schema", strict=True, include_raw=True)
    t = time.time()
    raw = runnable.invoke([SystemMessage(system), HumanMessage(content=user)])
    usage = getattr(raw["raw"], "usage_metadata", None) or {}
    pin, pout = PRICES[run["model"]]
    usd = usage.get("input_tokens", 0) * pin / 1e6 + usage.get("output_tokens", 0) * pout / 1e6
    answer = raw["parsed"].model_dump() if raw["parsed"] is not None else {}
    return {"shot": shot, "label": case["label"], "answer": answer, "usage": dict(usage), "usd": usd,
            "seconds": round(time.time() - t, 1)}


def b64(name: str) -> str:
    return base64.b64encode((HERE / "input" / name).read_bytes()).decode()


def faults(answer: dict[str, Any]) -> tuple[list[str], list[str]]:
    """(the product's faults, the count rule's faults: a mannequin with more than two arms or hands)."""
    product = _faults(answer) if answer and "extra_limbs" in answer else []
    counted = [f"{c['mannequin']}: {c['arms']} arms, {c['hands']} hands" for c in answer.get("counts") or []
               if int(c.get("arms") or 0) > 2 or int(c.get("hands") or 0) > 2]
    counted += [f"{t['mannequin']}: the {t['thing']} in the air" for t in answer.get("things") or []
                if str(t.get("where") or "").strip().lower() == "air"]
    return product, counted


def limb_fault(answer: dict[str, Any]) -> bool:
    """The right kind of fault for the bad panels: a limb or a floating thing (by flag or by count)."""
    return bool(answer.get("extra_limbs") or answer.get("floating") or faults(answer)[1])


def main() -> int:
    (HERE / "runs").mkdir(exist_ok=True)
    cases = json.loads((HERE / "input" / "cases.json").read_text(encoding="utf-8"))
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    repeats = 1 if "--once" in sys.argv else REPEATS  # a run that cannot pass any more is not repeated
    if "--bad" in sys.argv:  # the dear model on the four bad panels only (the cap)
        cases = [c for c in cases if c["label"] == "bad"]
    for name in args:
        run = RUNS[name]
        cap = BLIND_CAP if run.get("blind") else CAP
        for rep in range(1, repeats + 1):
            if spent() >= cap:
                print(f"cap reached: ${spent():.4f}")
                return 1
            with ThreadPoolExecutor(max_workers=5) as pool:
                results = list(pool.map(lambda c: call(run, c), cases))
            usd = sum(r["usd"] for r in results)
            add_spend(usd)
            for r in results:
                product, counted = faults(r["answer"])
                r["product_faults"], r["count_faults"] = product, counted
                r["repaint"] = bool(product or counted)
                r["limb_fault"] = limb_fault(r["answer"])
            (HERE / "runs" / f"{name}_{rep}.json").write_text(
                json.dumps({"run": name, "repeat": rep, **run, "usd": usd, "results": results}, ensure_ascii=False,
                           indent=1), encoding="utf-8")
            bad = [r for r in results if r["label"] == "bad"]
            good = [r for r in results if r["label"] == "good"]
            print(f"{name}#{rep}: bad caught (limb/float) {sum(r['limb_fault'] for r in bad)}/{len(bad)} "
                  f"[{' '.join(str(r['shot']) + ('+' if r['limb_fault'] else '-') for r in bad)}]; "
                  f"good repainted {sum(r['repaint'] for r in good)}/{len(good)} "
                  f"[{' '.join(str(r['shot']) for r in good if r['repaint'])}]; ${usd:.4f}; total ${spent():.4f}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
