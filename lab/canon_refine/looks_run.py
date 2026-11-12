"""Looks lab (2026-11-12): one call decides story time, the looks (one outfit each) and who wears which look in every
scene, with the scene's condition. Code checks; at most one repair call for `fix` findings. Nothing is written to the
database. Same meter, cap and cache as run.py.

    python lab/canon_refine/looks_run.py ekama dry
    python lab/canon_refine/looks_run.py you7 dry
    python lab/canon_refine/looks_run.py <ekama|you7> live --yes      # PAID: only with the person's yes
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
sys.path[:0] = [str(HERE)]

import looks_checks  # noqa: E402
import looks_inputs  # noqa: E402
from contracts import safe_depiction  # noqa: E402
from looks_schema import LooksAnswer, json_schema  # noqa: E402
from run import LAB_CAP_USD, MAX_OUTPUT, RUNS, call, spent, tokens_of, worst_case  # noqa: E402

DATASETS = {
    "ekama": "breakdown (timeline and presence known) + run2's refined cards",
    "you7": "You and I 7 from today's tables (no breakdown: the model reads story time)",
}


def load(name: str) -> tuple[dict[str, Any], dict[str, Any]]:
    if name == "ekama":
        export = json.loads((HERE / "ekama" / "export.json").read_text(encoding="utf-8"))
        refined = json.loads((RUNS / "run2" / "final.json").read_text(encoding="utf-8"))
        return looks_inputs.from_breakdown(export, refined)
    export = json.loads((HERE / "you_and_i_7" / "export.json").read_text(encoding="utf-8"))
    return looks_inputs.from_tables(export)


def repair_message(user: str, answer: LooksAnswer, fixes: list[looks_checks.Finding]) -> str:
    return (f"{user}\n\nYOUR EARLIER ANSWER\n{answer.model_dump_json(indent=1)}\n\nTHE CHECKS SAID\n"
            + "\n".join(f"- {f.message}" for f in fixes)
            + "\n\nAnswer again in full, fixing exactly what the checks say and keeping everything else the same.")


def report(data: dict[str, Any], a: LooksAnswer, found: list[looks_checks.Finding], title: str) -> str:
    people = {p["id"]: p["name"] for p in data["people"]}
    looks = {lk.id: lk for lk in a.looks}
    heads = {s["id"]: s["heading"] for s in data["scenes"]}
    wear = {sw.scene: {w.person: w for w in sw.on_screen} for sw in a.scenes}
    order = sorted(a.story, key=lambda s: (s.story_day, ["dawn", "morning", "day", "evening", "night"].index(s.part_of_day)))
    cols = list(people)
    out = [f"# Looks · {title}", "",
           f"Findings: **{sum(f.level == 'fix' for f in found)} to fix**, {sum(f.level == 'review' for f in found)} to review", ""]
    out += [f"- `{f.level}` {f.message}" for f in found] or ["- none"]
    out += ["", "## Who wears what, in STORY order", "",
            "| scene | day | time | continues | " + " | ".join(people[c] for c in cols) + " |",
            "|---|---|---|---|" + "---|" * len(cols)]
    for s in order:
        cells = []
        for c in cols:
            w = wear.get(s.scene, {}).get(c)
            if w is None:
                cells.append("")
            else:
                name = looks[w.look].name if w.look in looks else f"?{w.look}"
                cells.append(f"**{name}**{f' + _{w.condition}_' if w.condition else ''}")
        out.append(f"| {s.scene} {heads.get(s.scene, '')} | {s.story_day} | {s.part_of_day} | {s.continuous_with or '—'} | "
                   + " | ".join(cells) + " |")
    out += ["", "## Story time, as the agent read it", ""]
    out += [f"- **{s.scene}** day {s.story_day}, {s.part_of_day}{f', continues {s.continuous_with}' if s.continuous_with else ''}: {s.why}"
            for s in order]
    out += ["", "## Looks", ""]
    for lk in a.looks:
        worn = [s for s, w in wear.items() if any(x.look == lk.id for x in w.values())]
        out += [f"### {lk.id} · {people.get(lk.person, lk.person)} · {lk.name}", "",
                f"- outfit: {lk.outfit}", f"- hair: {lk.hair}", f"- makeup: {lk.makeup}", f"- accessories: {lk.accessories}",
                f"- worn in: {', '.join(sorted(worn)) or 'none'}", f"- why: _{lk.why}_", ""]
    out += ["## Each choice, scene by scene", ""]
    for sw in a.scenes:
        for w in sw.on_screen:
            out.append(f"- {sw.scene} · {people.get(w.person, w.person)} → {w.look}: {w.why}")
    return "\n".join(out) + "\n"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("dataset", choices=list(DATASETS))
    ap.add_argument("mode", choices=["dry", "live"])
    ap.add_argument("--run", default="looks1")
    ap.add_argument("--yes", action="store_true")
    a = ap.parse_args()

    data, truth = load(a.dataset)
    system = (HERE / "looks_system.md").read_text(encoding="utf-8").strip() + "\n\n" + safe_depiction.PROMPT_LINE
    user = looks_inputs.message(data)
    scene_ids = [s["id"] for s in data["scenes"]]
    out = RUNS / f"{a.run}_{a.dataset}"
    out.mkdir(parents=True, exist_ok=True)
    (out / "request_system.md").write_text(system, encoding="utf-8")
    (out / "request_user.txt").write_text(user, encoding="utf-8")
    print(f"{a.dataset}: {DATASETS[a.dataset]}; {len(scene_ids)} scenes, {len(data['people'])} people; "
          f"~{tokens_of(system) + tokens_of(user)} input tokens; worst case ${worst_case(system, user):.4f} per call "
          f"(max {MAX_OUTPUT} out); lab spent ${spent():.4f} of ${LAB_CAP_USD:.2f}")
    if a.mode == "dry":
        print(f"dry run: request saved to {out}; nothing was sent")
        return
    if not a.yes:
        raise SystemExit("A live run is paid: add --yes only after the person said yes.")

    schema = json_schema()
    answer = LooksAnswer.model_validate_json(call(out.name, "looks", system, user, schema, "looks"))
    (out / "answer.json").write_text(answer.model_dump_json(indent=1), encoding="utf-8")
    found = looks_checks.check(answer, scene_ids, truth)
    fixes = [f for f in found if f.level == "fix"]
    print(f"  checks: {len(fixes)} to fix, {len(found) - len(fixes)} to review")
    for f in found:
        print(f"    - {f.level}: {f.message}")
    if fixes:
        answer = LooksAnswer.model_validate_json(
            call(out.name, "looks repair", system, repair_message(user, answer, fixes), schema, "looks"))
        (out / "repair.json").write_text(answer.model_dump_json(indent=1), encoding="utf-8")
        found = looks_checks.check(answer, scene_ids, truth)
        print(f"  after repair: {sum(f.level == 'fix' for f in found)} to fix, {sum(f.level == 'review' for f in found)} to review")
    out.mkdir(parents=True, exist_ok=True)
    (out / "final.json").write_text(answer.model_dump_json(indent=1), encoding="utf-8")
    (out / "report.md").write_text(report(data, answer, found, a.dataset), encoding="utf-8")
    print(f"report: {out / 'report.md'}; lab spent ${spent():.4f} of ${LAB_CAP_USD:.2f}")


if __name__ == "__main__":
    main()
