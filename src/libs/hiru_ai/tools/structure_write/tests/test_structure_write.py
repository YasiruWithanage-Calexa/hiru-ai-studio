from __future__ import annotations

from typing import Any
from uuid import UUID, uuid4

import pytest
from pydantic import ValidationError

from hiru_ai.core.context import RunContext
from hiru_ai.core.fakes import ports_from
from hiru_ai.tools.structure_write import tool

PID = uuid4()


def structure(title: str = "The Meeting") -> dict[str, Any]:
    return {"episodes": [{"number": 1, "title": title, "synopsis": "A woman and a boat.", "doc_ids": [], "scenes": [
        {"number": 1, "title": "Kitchen", "heading": {"raw": "INT. KITCHEN - DAWN", "time_of_day": "DAWN"},
         "location": {"new": "Kitchen"}, "blocks": [
             {"kind": "action", "text": "Kamala stirs the tea."},
             {"kind": "dialogue", "speaker": "KAMALA", "character": {"new": "Kamala"}, "text": "Come and eat.",
              "delivery": ""}]}]}]}


def ctx(**fixtures: Any) -> RunContext:
    return RunContext(production_id=PID, actor_user_id=UUID(int=3), ports=ports_from(fixtures))


def test_a_structure_becomes_episodes_scenes_lines_and_draft_canon():
    c = ctx()
    out = tool.run(tool.Args(structure=structure(), envelope_s=30), c)
    assert (out.episodes, out.scenes, out.entities) == (1, 1, 2)  # the kitchen and Kamala are new canon
    assert out.new_characters == ["Kamala"]
    s = c.ports.structure
    assert [r["heading"] for r in s.scene_rows] == ["INT. KITCHEN - DAWN"]  # type: ignore[union-attr]
    assert [r["text"] for r in s.line_rows] == ["Come and eat."]  # type: ignore[union-attr]
    assert s.scene_rows[0]["envelope_s"] == 30  # type: ignore[union-attr]


def test_a_rebuild_keeps_ids_and_adds_no_second_copy_of_canon():
    c = ctx()
    first = tool.run(tool.Args(structure=structure(), envelope_s=30), c)
    again = tool.run(tool.Args(structure=structure("Renamed"), envelope_s=30), c)
    assert again.entities == 0 and again.scene_ids == first.scene_ids
    assert len(c.ports.structure.episode_rows) == 1  # type: ignore[union-attr]
    assert c.ports.structure.episode_rows[0]["title"] == "Renamed"  # type: ignore[union-attr]


def test_an_approved_scene_is_never_rewritten():
    c = ctx()
    first = tool.run(tool.Args(structure=structure(), envelope_s=30), c)
    c.ports.structure.scene_rows[0]["status"] = "approved"  # type: ignore[union-attr]
    changed = structure()
    changed["episodes"][0]["scenes"][0]["blocks"][0]["text"] = "Something else entirely."
    out = tool.run(tool.Args(structure=changed, envelope_s=30), c)
    assert out.kept_approved == 1 and out.scenes == 0 and first.scenes == 1
    assert c.ports.structure.line_rows[0]["text"] == "Come and eat."  # type: ignore[union-attr]


def test_a_scene_too_short_for_veo_is_refused_before_anything_is_written():
    with pytest.raises(ValidationError):
        tool.Args(structure=structure(), envelope_s=2)
