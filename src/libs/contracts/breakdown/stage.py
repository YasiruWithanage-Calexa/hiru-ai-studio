"""Step 6, the stager (plan/2026-11-11 §4.6): the existing stager's prompt and output shape (`breakdown_stager`), run
ONCE per
scene before planning on the scene's blocks from the breakdown memory, not on the raw script.

It owns positions, facing, hands, posture and condition per block. Marks are written only where something changes (D2);
code
expands "the last mark holds" per block. Where it disagrees with the episode call (who holds a thing at the end) that is
a
finding: neither side overwrites the other."""

from __future__ import annotations

from typing import Any

from contracts.breakdown.packet import Names, _pretty
from contracts.breakdown.schema import Breakdown, Finding, Scene

FIELDS = ("zone", "facing", "frame_side", "holding", "posture", "left_hand", "right_hand", "condition", "wearing")


def people_names(bd: Breakdown, sc: Scene) -> dict[str, str]:
    """name as shown to the stager -> person id, for the people of this scene."""
    n = Names(bd)
    return {n.by_id[p["person"]]: p["person"] for p in (sc.brief or {}).get("people", [])}


def user_message(bd: Breakdown, sc: Scene) -> str:
    n = Names(bd)
    brief = sc.brief or {}
    place = bd.entity(brief.get("place", ""))
    place_text = ""
    if place:
        facts = " ".join(
            str(v.value)
            for k, v in place.card.items()
            if k != "summary" and v.lines and sc.heading_line <= v.lines[0] <= sc.last
        )
        place_text = f"{n.by_id[place.id]} ({place.place_kind}). {facts}".strip()
    people = "\n".join(
        f"- {n.by_id[p['person']]}: {p['presence']}"
        + (" (NOT in the place: heard only)" if p["presence"] not in ("on_screen", "body") else "")
        for p in brief.get("people", [])
    )
    rows = []
    for i, b in enumerate(sc.blocks):
        who = f" {n.by_id.get(b['speaker'], b['speaker'])}, {b['presence']}" if b["speaker"] else ""
        rows.append(f"[{i}] {b['kind']}{who}: {b['text']}")
    return (
        f"<place>\n{place_text}\n</place>\n\n<people>\n{people}\n</people>\n\n"
        f"Blocks 0 to {len(sc.blocks) - 1}:\n<script>\n" + "\n".join(rows) + "\n</script>"
    )


def apply(bd: Breakdown, sc: Scene, out: Any) -> list[Finding]:
    """Keep only valid entries (an invalid one is dropped, not repaired), store the map on the scene, return its
    findings.
    `out` is the stager's answer (`zones`, `marks`, `props`: the `breakdown_stager` agent's Output, read by
    attribute)."""
    names = people_names(bd, sc)
    nb = len(sc.blocks)
    zones = [z for z in out.zones if z and z != "off"]
    found: list[Finding] = []
    marks = []
    for m in out.marks:
        if m.who not in names or not 0 <= m.block < nb or (m.zone not in zones and m.zone != "off"):
            found.append(
                Finding(
                    code="stage",
                    scene=sc.id,
                    message=f"stager entry dropped: {m.who!r} at block {m.block} zone {m.zone!r}",
                )
            )
            continue
        marks.append({"person": names[m.who], "block": m.block, **{f: getattr(m, f) for f in FIELDS}})
    props = [p.model_dump() for p in out.props if 0 <= p.block < nb]
    sc.stage = {"zones": zones, "marks": marks, "props": props}
    found += _against_episode(bd, sc)
    return found


def states(sc: Scene) -> dict[str, list[dict[str, str]]]:
    """Per person, the state at every block: the last mark holds, an empty field keeps what it was (code expands,
    D2)."""
    out: dict[str, list[dict[str, str]]] = {}
    marks = (sc.stage or {}).get("marks", [])
    for pid in {m["person"] for m in marks}:
        cur = dict.fromkeys(FIELDS, "")
        rows = []
        mine = sorted((m for m in marks if m["person"] == pid), key=lambda m: m["block"])
        for i in range(len(sc.blocks)):
            for m in (x for x in mine if x["block"] == i):
                for f in FIELDS:
                    if m[f] or f == "zone":
                        cur[f] = m[f]
                if m["condition"] == "well":
                    cur["condition"] = ""
            rows.append(dict(cur))
        out[pid] = rows
    return out


def _against_episode(bd: Breakdown, sc: Scene) -> list[Finding]:
    """Report only: the episode call says who holds a thing at the scene's end; the stager's last hands must not
    contradict it."""
    found: list[Finding] = []
    st = states(sc)
    n = Names(bd)
    for t in (sc.brief or {}).get("things", []):
        holder = t["holder_end"]
        if t["role"] not in ("hero", "used") or holder not in st or not st[holder]:
            continue
        last = st[holder][-1]
        held = " ".join((last["holding"], last["left_hand"], last["right_hand"])).lower()
        word = n.by_id[t["thing"]].lower().split()[-1]
        if held.strip() and word not in held:
            found.append(
                Finding(
                    code="stage",
                    scene=sc.id,
                    message=(
                        f"episode call: {n.by_id[holder]} ends the scene with {n.by_id[t['thing']]}; the stager's "
                        "last state has "
                        f"{n.by_id[holder]} holding {held.strip()!r}"
                    ),
                )
            )
    return found


def packet_part(bd: Breakdown, sc: Scene) -> dict[str, Any]:
    """What the packet adds: the zones, each person's in and out state, and where a block changes someone's state."""
    stage = sc.stage
    if not stage:
        return {}
    n = Names(bd)
    st = states(sc)
    by_block: dict[int, list[dict[str, Any]]] = {}
    for m in stage["marks"]:
        by_block.setdefault(m["block"], []).append(
            {"person": _pretty(n.by_id[m["person"]]), **{f: m[f] for f in FIELDS if m[f]}}
        )
    first = {pid: min(m["block"] for m in stage["marks"] if m["person"] == pid) for pid in st}
    not_placed = {_pretty(n.by_id[pid]): f"no position before block {b}" for pid, b in first.items() if b > 0}
    on_screen = {p["person"] for p in (sc.brief or {}).get("people", []) if p["presence"] in ("on_screen", "body")}
    not_placed |= {_pretty(n.by_id[pid]): "never placed" for pid in on_screen if pid not in st}
    return {
        "zones": stage["zones"],
        "not_placed": not_placed,
        "people": {
            p: {"in": {k: v for k, v in rows[0].items() if v}, "out": {k: v for k, v in rows[-1].items() if v}}
            for p, rows in st.items()
        },
        "changes_at": {sc.blocks[i]["id"]: v for i, v in sorted(by_block.items())},
        "props": stage["props"],
    }
