"""Series block lab (2026-11-12): does the drama's identity (genre, tone, world, theme, premise) reach the planner's packet?

One reader call on the PDF finds the series block; code checks every value (quote in its lines, no numbers or
durations, no safe-depiction words, facets in their quote); code then adds `J_series` to every scene packet, built on
the breakdown memory of the last pipeline run of the same PDF, and writes Raphael's real opening message with the series
section placed inside <packet>. Nothing in src/ is changed.

    python lab/series_block/run.py <pdf>                 dry: the message, its size, the worst case (free)
    python lab/series_block/run.py <pdf> --yes           ONE paid call (the person's yes first), hard cap CAP_USD
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / "lab"), str(ROOT / "lab" / "two_memories"), str(ROOT / "src" / "libs"), str(ROOT / "src")]

from contracts import safe_depiction  # noqa: E402
from contracts.breakdown import memory, packet  # noqa: E402
from contracts.breakdown.schema import Breakdown  # noqa: E402
from hiru_ai.core.tokens import tokens_of  # noqa: E402

LAB = Path(__file__).resolve().parent
MEMORY = ROOT / "lab" / "two_memories" / "runs" / "pipeline_ekama_sakshiya_screenplay_clean" / "07_memory.json"
MODEL, EFFORT = "gpt-6.1-sol", "medium"
PRICE = (2.00, 0.10, 10.00)  # $/1M: input, cached input, output (contracts/raphael/money.py)
MAX_OUT = 8_000
CAP_USD = 0.25

_FIELD = {"found": {"type": "boolean"}, "says": {"type": "string"}, "quote": {"type": "string"},
          "line_from": {"type": "integer"}, "line_to": {"type": "integer"}}


def _obj(props: dict[str, Any]) -> dict[str, Any]:
    return {"type": "object", "additionalProperties": False, "properties": props, "required": list(props)}


SCHEMA = _obj({
    "genre": _obj({**_FIELD, "facets": {"type": "array", "items": _obj({
        "name": {"type": "string"}, "weight": {"type": "string", "enum": ["main", "thread"]}})}}),
    "tone": _obj(dict(_FIELD)),
    "world": _obj({**_FIELD, "places": {"type": "array", "items": {"type": "string"}}}),
    "theme": _obj({**_FIELD, "language": {"type": "string"}}),
    "premise": _obj(dict(_FIELD)),
    "left_out": {"type": "array", "items": _obj({"quote": {"type": "string"}, "line_from": {"type": "integer"},
                                                 "line_to": {"type": "integer"}, "why": {"type": "string"}})},
})
FIELDS = ("genre", "tone", "world", "theme", "premise")
_NUMBERS = re.compile(r"\d|\b(minutes?|seconds?|hours?|episodes?|runtime|running time)\b", re.IGNORECASE)


def norm(s: str) -> str:
    return " ".join(s.split()).casefold()


def doc_lines(pdf: Path) -> list[str]:
    from live import extract  # the two-memories pipeline's own extraction (the product's document reader)

    return memory.strip_furniture(memory.clean_lines(extract(pdf)))


def message(lines: list[str]) -> str:
    return "DOCUMENT (numbered lines)\n" + "\n".join(f"{i}: {t}" for i, t in enumerate(lines, 1))


def check(ans: dict[str, Any], lines: list[str], bd: Breakdown) -> tuple[dict[str, Any], list[str]]:
    """Code's checks. -> (the series block with only the values that passed, the findings)."""
    findings: list[str] = []
    out: dict[str, Any] = {}
    places = {norm(e.name): e.id for e in bd.entities if e.kind == "place"}
    for key in FIELDS:
        f = ans[key]
        if not f["found"]:
            out[key] = {"empty": "not stated"}
            continue
        lo, hi = f["line_from"], f["line_to"]
        span = norm(" ".join(lines[lo - 1:hi])) if 1 <= lo <= hi <= len(lines) else ""
        if not span or norm(f["quote"]) not in span:
            findings.append(f"{key}: quote not found in lines {lo}-{hi}; dropped")
            out[key] = {"empty": "quote did not check"}
            continue
        if _NUMBERS.search(f["says"]):
            findings.append(f"{key}: `says` holds a number or duration ({f['says']!r}); dropped")
            out[key] = {"empty": "says held a number"}
            continue
        if safe_depiction.blocking(f["says"]):
            words = ", ".join(x.word for x in safe_depiction.blocking(f["says"]))
            findings.append(f"{key}: `says` holds a gated word ({words}); dropped")
            out[key] = {"empty": "says held a gated word"}
            continue
        item: dict[str, Any] = {"says": " ".join(f["says"].split()), "quote": f["quote"], "lines": [lo, hi]}
        if key == "genre":
            kept = []
            for fc in f["facets"]:
                if all(w in norm(f["quote"]) for w in norm(fc["name"]).split()):
                    kept.append({"name": fc["name"].casefold(), "weight": fc["weight"]})
                else:
                    findings.append(f"genre: facet {fc['name']!r} is not in its quote; dropped")
            item["facets"] = kept
        if key == "world":
            item["places"] = [{"name": p, "id": places.get(norm(p), "")} for p in f["places"]]
            for p in item["places"]:
                if not p["id"]:
                    findings.append(f"world: place {p['name']!r} matches no place card (kept, no id)")
        if key == "theme":
            item["language"] = f["language"]
        if key == "premise":
            item["planner_only"] = bool(safe_depiction.blocking(f["quote"]))
        out[key] = item
    out["left_out"] = ans["left_out"]
    return out, findings


def series_for(series: dict[str, Any], p: dict[str, Any]) -> dict[str, Any]:
    """`J_series` of one packet: the production's block plus where this scene sits in it."""
    block = {k: v for k, v in series.items() if k != "left_out"}
    block["this_scene"] = {
        "place": p["C_place"].get("id", ""),
        "scoped_rules": [r["id"] for r in p["G_direction"] if r["applies"] == "scoped"],
        "mood": p["F_feeling"]["mood"],
    }
    return block


def render(j: dict[str, Any]) -> str:
    """How the lab shows `J_series` to a planner (the product's own rendering is a later decision)."""
    out = ["SERIES (what this drama is; play every scene as part of it)"]
    g = j["genre"]
    if "facets" in g:
        out.append("Genre: " + ", ".join(f"{f['name']} ({f['weight']})" for f in g["facets"]) + f"  [{g['quote']}]")
    for key, label in (("tone", "Tone"), ("world", "World"), ("theme", "Theme"), ("premise", "Premise")):
        v = j[key]
        if "says" in v:
            extra = ""
            if key == "world":
                extra = " Places: " + ", ".join(f"{x['name']} [{x['id']}]" if x["id"] else x["name"] for x in v["places"])
            out.append(f"{label}: {v['says']}{extra}")
        else:
            out.append(f"{label}: ({v['empty']})")
    t = j["this_scene"]
    out.append(f"This scene: place {t['place'] or '?'}; scoped direction {', '.join(t['scoped_rules']) or 'none'}; "
               f"mood {t['mood']}. Read the scene's mood and its scoped direction through the genre and tone: the "
               "direction sets the look, the genre sets the tension.")
    return "\n".join(out)


def call(system: str, user: str) -> tuple[dict[str, Any], dict[str, Any]]:
    from cinematic.run import client

    worst = (tokens_of(system) + tokens_of(user)) * PRICE[0] / 1e6 + MAX_OUT * PRICE[2] / 1e6
    if worst > CAP_USD:
        raise SystemExit(f"refused: worst case ${worst:.4f} passes the ${CAP_USD:.2f} cap")
    started = time.monotonic()
    resp = client().responses.create(
        model=MODEL, instructions=system, input=user, max_output_tokens=MAX_OUT, reasoning={"effort": EFFORT},
        text={"format": {"type": "json_schema", "name": "series", "schema": SCHEMA, "strict": True}})
    u = resp.usage
    cached = int(getattr(getattr(u, "input_tokens_details", None), "cached_tokens", 0) or 0)
    dollars = (u.input_tokens - cached) * PRICE[0] / 1e6 + cached * PRICE[1] / 1e6 + u.output_tokens * PRICE[2] / 1e6
    meta = {"model": MODEL, "effort": EFFORT, "status": resp.status, "seconds": round(time.monotonic() - started, 1),
            "input_tokens": u.input_tokens, "cached_tokens": cached, "output_tokens": u.output_tokens,
            "dollars": round(dollars, 4), "worst_case": round(worst, 4), "cap": CAP_USD}
    if resp.status != "completed":
        raise SystemExit(f"answer {resp.status}: {meta}")
    return json.loads(resp.output_text), meta


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("pdf")
    ap.add_argument("--yes", action="store_true")
    args = ap.parse_args()
    sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
    lines = doc_lines(Path(args.pdf))
    bd = Breakdown.model_validate_json(MEMORY.read_text(encoding="utf-8"))
    d1 = next(r for r in bd.rules if r.id == "D01")
    aligned = norm(lines[d1.lines[0] - 1]).startswith(norm(d1.text)[:20])
    print(f"{len(lines)} lines; breakdown memory {MEMORY.parent.name}: D01 at line {d1.lines[0]} "
          f"{'matches' if aligned else 'DOES NOT match'} this text")
    if not aligned:
        return 1
    system = (LAB / "prompt.md").read_text(encoding="utf-8")
    user = message(lines)
    tin = tokens_of(system) + tokens_of(user)
    print(f"message {tin} tokens; worst case ${tin * PRICE[0] / 1e6 + MAX_OUT * PRICE[2] / 1e6:.4f} (cap ${CAP_USD:.2f})")
    out = LAB / "runs" / time.strftime("ekama_%Y%m%d_%H%M%S")
    if not args.yes:
        print("dry: no call. --yes for the one paid call.")
        return 0
    out.mkdir(parents=True)
    (out / "00_message.txt").write_text(user, encoding="utf-8")
    ans, meta = call(system, user)
    print(f"call: {meta}")
    (out / "01_reader_answer.json").write_text(json.dumps({**meta, "answer": ans}, indent=1, ensure_ascii=False),
                                               encoding="utf-8")
    series, findings = check(ans, lines, bd)
    (out / "02_series_checked.json").write_text(json.dumps({"series": series, "findings": findings}, indent=1,
                                                           ensure_ascii=False), encoding="utf-8")
    from contracts.raphael.packet import opening

    packets, texts = {}, []
    for sc in bd.scenes:
        p = packet.assemble(bd, sc.id)
        p["J_series"] = series_for(series, p)
        packets[sc.id] = p
        text, _scene, _ids = opening(p)
        text = text.replace("<packet>\n", "<packet>\n" + render(p["J_series"]) + "\n\n", 1)
        texts.append(f"##### {sc.id}\n\n{text}")
    (out / "03_packets_with_series.json").write_text(json.dumps(packets, indent=1, ensure_ascii=False), encoding="utf-8")
    (out / "04_raphael_openings.txt").write_text("\n\n".join(texts), encoding="utf-8")
    print(f"findings: {findings or 'none'}")
    print(f"saved in {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
