"""Jonathan is the cinematic lab, in the product (plan/2026-11-06b §4.1): the same request, the same judgement.

What the lab proved (lab/cinematic/RESULTS.md) holds in the product only if the model is asked the same thing and code
judges the answer the same way. These tests compare Jonathan with the lab's own code while the lab exists, and skip when
it is deleted:

    the prompt          the author's system prompt is the lab's (team prompt + worked example), to the letter
    the schema          the JSON schema the model is held to is the lab's (only the class titles differ)
    the message         the context pack for the lab's scenes is the lab's user message, to the letter
    the revise message  the reviser's message is the lab's `revise_message`, to the letter
    the judgement       every saved lab answer gets the lab's score (faults, craft gaps) from Jonathan's mend, checks
                        and measures; the one known difference is the end state's place name, which Jonathan's mend
                        writes from the staging (a fault the lab reported against itself)
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

import pytest

from contracts.jonathan import checks, measures, mend
from contracts.jonathan.plan import Problem
from contracts.jonathan.scene import SceneS
from contracts.jonathan.wire import JonathanWire
from hiru_ai.agents.jonathan.jonathan_author import agent as author
from hiru_ai.agents.jonathan.jonathan_revise import agent as reviser
from hiru_ai.agents.jonathan.jonathan_revise.schema import Input as ReviseInput
from hiru_ai.agents.jonathan.wire_schema import wire_schema
from hiru_ai.core.prompts import Prompt
from hiru_ai.steps.jonathan.jonathan_pack import logic as pack_logic

ROOT = Path(__file__).resolve().parents[2]
LAB = ROOT / "lab"
AGENTS = ROOT / "src" / "libs" / "hiru_ai" / "agents" / "jonathan"
if not (LAB / "cinematic" / "run.py").exists():
    pytest.skip("the cinematic lab is not here (it is deleted once Jonathan is the default)", allow_module_level=True)
if str(LAB) not in sys.path:
    sys.path.insert(0, str(LAB))

from cinematic import checks as lab_checks  # noqa: E402
from cinematic import mend as lab_mend  # noqa: E402
from cinematic import pack as lab_pack  # noqa: E402
from cinematic import run as lab_run  # noqa: E402
from cinematic import schema as lab_schema  # noqa: E402


def _untitled(node: Any) -> Any:
    if isinstance(node, dict):
        return {k: _untitled(v) for k, v in node.items() if k != "title"}
    if isinstance(node, list):
        return [_untitled(v) for v in node]
    return node


def _scene(reading: Any) -> SceneS:
    """The lab's scene as Jonathan is given it; the lab's length guide is the product's envelope."""
    scene = SceneS.model_validate(reading.scene.model_dump(mode="json"))
    return scene.model_copy(update={"envelope_s": reading.guide_s or None})


def _craft(reading: Any) -> measures.Craft:
    return measures.Craft(codes={str(p["name"]): str(p.get("code") or "") for p in reading.people},
                          story_objects=reading.story_objects, guide_s=reading.guide_s)


def _pack(reading: Any) -> str:
    """Jonathan's context pack for a lab scene, from the rows the graph would read."""
    raw = reading.raw
    production = {"style_note": str(raw.get("style") or ""),
                  "people": [{"name": p["name"], "code": p.get("code") or "", "look": p.get("look") or "",
                              "voice": p.get("voice") or "", "essence": p.get("essence") or ""}
                             for p in reading.people]}
    context = {"heading": raw.get("heading"), "episode_title": raw.get("episode_title"),
               "synopsis": " ".join(str(raw.get("synopsis") or "").split())}
    return str(pack_logic.pack({"scene": _scene(reading).model_dump(mode="json"), "production": production,
                                "context": context, "link": "", "start": None})["text"])


def _runs() -> list[Path]:
    found = []
    for folder in sorted(lab_run.RUNS.glob("*/")):
        if (folder / "request.json").exists() and (folder / "answer.json").exists():
            found.append(folder)
    return found


def test_the_authors_prompt_is_the_labs_to_the_letter_and_the_reviser_has_the_same():
    lab = lab_run.system_prompt()
    mine = Prompt.load(AGENTS / "jonathan_author" / "prompts" / "system.md").text
    assert mine.rstrip("\n") == lab
    assert Prompt.load(AGENTS / "jonathan_revise" / "prompts" / "system.md").text == mine


def test_the_schema_the_model_is_held_to_is_the_labs():
    assert _untitled(author.output_schema()) == _untitled(lab_schema.output_schema())
    assert _untitled(reviser.output_schema()) == _untitled(wire_schema(JonathanWire, "x"))


def test_the_context_pack_for_a_lab_scene_is_the_labs_user_message():
    """Episode 1, the scene the lab's best runs used. (The lab's second scene still carries the policy the lab dropped,
    "it may run longer", which wrote 94 s for a 60 s scene: Jonathan writes every scene's length as a budget, the
    wording that moved the result most, RESULTS.md "What moved the result" 1.)"""
    reading = lab_pack.load(lab_run.scene_path("episode1"))
    assert _pack(reading) == lab_pack.message(reading)


def test_every_scene_gets_the_budget_wording_from_its_envelope_and_a_scene_with_none_only_what_use_s_is():
    reading = lab_pack.load(lab_run.scene_path("second"))
    text = _pack(reading)
    assert "The length is the producer's budget (about 60 s): land within about 20% of it in `use_s`." in text
    assert "may run longer" not in text
    assert pack_logic.time_policy(None).startswith("A take may be longer than the edit keeps")


def test_the_revise_message_is_the_labs_to_the_letter():
    folder = next((f for f in reversed(_runs()) if (f / "checks.json").exists()
                   and json.loads((f / "request.json").read_text(encoding="utf-8"))["scene"] == "episode1"
                   and "measures" in json.loads((f / "checks.json").read_text(encoding="utf-8"))), None)
    if folder is None:
        pytest.skip("no checked Episode 1 run is saved")
    reading = lab_pack.load(lab_run.scene_path("episode1"))
    found = json.loads((folder / "checks.json").read_text(encoding="utf-8"))
    inp = ReviseInput(scene=_scene(reading), pack=_pack(reading),
                      draft=JonathanWire.model_validate_json((folder / "answer.json").read_text(encoding="utf-8")),
                      problems=[Problem.model_validate(p) for p in found.get("left") or [] if p.get("fix") != "report"],
                      gaps=[measures.Measure.model_validate(m) for m in found.get("measures") or []
                            if m.get("status") == "missed"])
    lab_message = lab_pack.message(reading) + lab_run.revise_message(folder.name)
    assert reviser.user_message(inp) == lab_message


def test_every_saved_lab_answer_gets_the_labs_score_from_jonathan():
    runs = _runs()
    if not runs:
        pytest.skip("no lab runs are saved (runs/ is local)")
    compared = 0
    for folder in runs:
        raw = (folder / "answer.json").read_text(encoding="utf-8")
        try:
            lab_plan = lab_schema.CinemaWire.model_validate_json(raw)
        except ValueError:
            continue
        reading = lab_pack.load(lab_run.scene_path(json.loads((folder / "request.json").read_text("utf-8"))["scene"]))
        lab_mended, _, _ = lab_mend.mend(reading.scene, lab_plan)
        lab_faults = {p.key for p in lab_checks.hard(reading.scene, lab_mended) if p.fix != "report"}
        lab_gaps = {m.key for m in lab_checks.measures(reading, lab_mended) if m.status == "missed"}
        scene = _scene(reading)
        mine, _, _ = mend.mend(scene, JonathanWire.model_validate_json(raw))
        my_faults = {p.key for p in checks.faults(checks.problems(scene, mine))}
        my_gaps = {m.key for m in measures.missed(measures.measures(scene, mine, _craft(reading)))}
        assert my_gaps == lab_gaps, folder.name
        # the end state's place is written from the staging by Jonathan's mend, and Jonathan checks who holds what
        # (the frames are painted from it; the lab never painted); nothing else may differ
        assert {k for k in lab_faults if not k.startswith("end_state:where:")} == {
            k for k in my_faults if not k.startswith("holding:")}, folder.name
        compared += 1
    assert compared
