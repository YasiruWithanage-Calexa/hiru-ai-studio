"""adam_director hooks (plan/2026-11-04b §5.2).

New for Adam. Three treatments in one call, so the model sees all three and makes them differ; `adam_distinct` (code)
checks that they do. The answer is cleaned in code: one treatment per stance, in the order restrained, intimate,
heightened; a section that names a beat the analysis does not have loses that beat; a plant of an object that fits
neither the script nor the place is dropped (the director may not add an object). There is no fallback: with no model
the job fails clearly and the production's classic planner is the way out (plan §5.5).
"""
from __future__ import annotations

from contracts.adam.plan import SceneScript, compact
from contracts.adam.wire import STANCES, TreatmentsWire, TreatmentW
from hiru_ai.agents.adam.adam_director.schema import Input, Output


def user_message(inp: Input) -> str:
    near = "\n".join(r for r in (f"The scene before: {inp.before}" if inp.before else "",
                                 f"The scene after: {inp.after}" if inp.after else "") if r)
    return ((f"<devices>\n{inp.devices}\n</devices>\n\n" if inp.devices else "")
            + (f"<neighbours>\n{near}\n</neighbours>\n\n" if near else "")
            + f"<script>\n{inp.scene.listing()}\n</script>\n\n"
            + f"<analysis>\n{compact(inp.analysis)}\n</analysis>")


def memory_scope(inp: Input) -> dict[str, object]:
    """What this call is about, so the production memory is narrowed to it (plan/2026-11-05d M6)."""
    return {"place": inp.scene.place.name, "people": list(inp.scene.cast), "episode": inp.episode}


def clean(scene: SceneScript, beats: int, out: TreatmentsWire) -> tuple[TreatmentsWire, list[str]]:
    """-> (the answer cleaned, what was dropped or changed)."""
    notes: list[str] = []
    first: dict[str, TreatmentW] = {}
    for each in out.treatments:
        if each.stance in first:
            notes.append(f"a second {each.stance} treatment ({each.name!r}) was dropped")
        else:
            first[each.stance] = each
    kept: list[TreatmentW] = []
    for stance in STANCES:
        found = first.get(stance)
        if found is None:
            continue
        t = found
        sections = []
        for s in t.sections:
            beats_ok = [b for b in s.beats if 0 <= b < beats]
            if len(beats_ok) != len(s.beats):
                notes.append(f"{t.stance}: a section named beat {sorted(set(s.beats) - set(beats_ok))}, "
                             "which the analysis does not have")
            sections.append(s.model_copy(update={"beats": beats_ok}))
        plant = t.plant
        if plant is not None and not scene.fits(plant.object):
            notes.append(f"{t.stance}: the plant {plant.object!r} is neither in the script nor in the place")
            plant = None
        kept.append(t.model_copy(update={"sections": sections, "plant": plant}))
    return TreatmentsWire(treatments=kept), notes


def finish(inp: Input, out: Output) -> Output:
    return Output(treatments=clean(inp.scene, len(inp.analysis.beats), out)[0].treatments)
