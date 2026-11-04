"""Naming is the legacy architect's, unchanged."""
from __future__ import annotations

import copy

from structure_build.engine import architect as legacy

from hiru_ai.steps.episode_names import logic, step

EPISODE = {"number": 1, "title": "The Return", "synopsis": "",
           "scenes": [{"number": 1, "title": "Scene 1", "heading": {"raw": "INT. KITCHEN - DAY"},
                       "blocks": [{"kind": "action", "speaker": "", "text": "Nimal comes home."},
                                  {"kind": "dialogue", "speaker": "KAMALA", "text": "Come."}]}]}
ANSWER = {"synopsis": "  Nimal comes   home. ", "scenes": [{"number": 1, "title": " Nimal comes home "}]}


def test_the_episode_is_named_exactly_as_the_legacy_architect_named_it():
    old = copy.deepcopy(EPISODE)
    legacy.name_all(lambda system, user: ANSWER, [old], lambda ep: None)
    got = step.run({"episode": EPISODE, **ANSWER})["episode"]
    assert got == old and got["synopsis"] == "Nimal comes home." and got["scenes"][0]["title"] == "Nimal comes home"


def test_an_outlines_synopsis_is_kept_and_the_input_is_the_agents_listing():
    ep = copy.deepcopy(EPISODE)
    ep["synopsis"] = "From the outline."
    assert step.run({"episode": ep, **ANSWER})["episode"]["synopsis"] == "From the outline."
    assert logic.input_for(EPISODE)["scenes"][0]["heading"] == "INT. KITCHEN - DAY"
