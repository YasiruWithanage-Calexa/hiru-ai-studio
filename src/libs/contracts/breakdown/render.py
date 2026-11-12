"""A plain-text rendering of the scene packet, the way a planner's prompt could show it (the planners' own rendering is
the
person's separate task: this one exists so a person can READ a packet and set it beside what Raphael is sent today)."""

from __future__ import annotations

from typing import Any

from contracts.breakdown.series import render_lines

EMPTY = "empty"


def _v(x: Any) -> str:
    return "" if isinstance(x, dict) and EMPTY in x else str(x)


def render(p: dict[str, Any]) -> str:
    a = p["A_scene"]
    series = render_lines(p.get("J_series"))  # plan/2026-11-12b
    out = [
        *([*series, ""] if series else []),
        f"SCENE {a['id']}: {a['heading']}",
        f"Title: {a['title']}",
        f"Summary: {a['summary']}",
        f"Purpose: {a['purpose']}",
    ]
    t = a.get("time")
    if t and "story_order" in t:
        out.append(
            f"Story time: order {t['story_order']}, {t['kind']}"
            + (f", {t['relative']}" if _v(t["relative"]) else "")
            + (f" (from {t['anchor']})" if t.get("anchor") else "")
        )
    for k, label in (("before_in_story", "Before it in the story"), ("after_in_story", "After it in the story")):
        n = a.get(k)
        if n and "id" in n:
            out.append(
                f"{label}: {n['id']}"
                + (f", ends: {n['ends_with']}" if n.get("ends_with") and k.startswith("before") else "")
                + (f", opens: {n['opens_with']}" if n.get("opens_with") and k.startswith("after") else "")
            )
    for th in a.get("threads") if isinstance(a.get("threads"), list) else []:
        later = "; ".join(f"{b['scene']}: {b['note']}" for b in th["later"])
        out.append(f"Thread ({th['kind']}): {th['summary']}" + (f" Later: {later}" if later else ""))
    for k in ("irony", "looks"):
        for x in a.get(k) if isinstance(a.get(k), list) else []:
            out.append(f"{k.title()}: " + "; ".join(f"{kk} {vv}" for kk, vv in x.items() if vv and kk != "source"))
    out += ["", "PEOPLE"]
    for q in p["B_people"]:
        c = {k: v["value"] for k, v in q["card"].items() if "value" in v and k != "summary"}
        out.append(
            f"- {q['name']} [{q['presence']}] "
            + " ".join(c.values())
            + f" | wants: {_v(q['wants'])} | feels: {_v(q['feeling_start'])} -> {_v(q['feeling_end'])}"
        )
    out.append("")
    c = p["C_place"]
    out.append(
        f"PLACE: {c.get('name', '')} ({c.get('place_kind')})"
        + (f", zones: {', '.join(p['stage']['zones'])}" if p.get("stage") else "")
    )
    if isinstance(p["D_things"], list):
        out += ["THINGS"] + [
            f"- {t['name']} [{t['role']}] start: {t['holder_start']} end: {t['holder_end']}" for t in p["D_things"]
        ]
    out += ["", "BLOCKS"]
    changes = (p.get("stage") or {}).get("changes_at", {})
    for b in p["E_blocks"]:
        who = (
            f" {p['ids'].get(b['speaker'], {}).get('name', '')} "
            f"({b['presence']}{', ' + b['device'] if b['device'] else ''})"
            if b["speaker"]
            else ""
        )
        out.append(f"{b['id']} {b['kind']}{who}: {b['text']}")
        if b["intent"]:
            out.append(f"    intent: {b['intent']}")
        for e in b["events"]:
            if e["change"]:
                out.append(f"    event ({e['function']}{'' if e['visible'] else ', not visible'}): {e['change']}")
        for m in changes.get(b["id"], []):
            out.append("    stage: " + ", ".join(f"{k} {v}" for k, v in m.items()))
    out += [
        "",
        f"FEELING: {', '.join(p['F_feeling']['mood']) if isinstance(p['F_feeling']['mood'], list) else ''}; turns at "
        f"{', '.join(p['F_feeling']['turns'])}",
        "DIRECTION IN SCOPE",
    ]
    out += [f"- {r['id']} [{r['applies'].split(':')[0]}] {' '.join(r['text'].split())}" for r in p["G_direction"]]
    if (p.get("stage") or {}).get("not_placed"):
        out.append("NOT PLACED: " + "; ".join(f"{k} ({v})" for k, v in p["stage"]["not_placed"].items()))
    return "\n".join(out)
