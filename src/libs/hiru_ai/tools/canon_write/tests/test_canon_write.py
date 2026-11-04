from __future__ import annotations

from typing import Any
from uuid import UUID, uuid4

from hiru_ai.core import parts
from hiru_ai.core.context import RunContext
from hiru_ai.core.fakes import ports_from
from hiru_ai.tools.canon_write import tool

PID = uuid4()
INDEX = "C01 Kamala (Amma): the mother, mid 40s, wears a faded blue saree\nL01 Harbour: the breakwater at dawn\n"


def candidates() -> list[dict[str, Any]]:
    docs = [{"filename": "i.md", "role": "canon_index", "text": INDEX}]
    out = parts.step("canon_rules", "step").run({"documents": docs})
    return list(out["candidates"])


def ctx(entities: list[dict[str, Any]] | None = None) -> RunContext:
    return RunContext(production_id=PID, actor_user_id=UUID(int=7), ports=ports_from({"canon": entities or []}))


def test_candidates_become_entities_with_a_first_version():
    c = ctx()
    out = tool.run(tool.Args(candidates=candidates()), c)
    assert (out.created, out.versioned, out.updated) == (2, 0, 0)
    assert sorted(e["code"] for e in c.ports.canon.entity_rows) == ["C01", "L01"]  # type: ignore[union-attr]
    assert {v["version"] for v in c.ports.canon.versions} == {1}  # type: ignore[union-attr]
    assert {v["created_by"] for v in c.ports.canon.versions} == {str(UUID(int=7))}  # type: ignore[union-attr]


def test_running_it_twice_changes_nothing_the_second_time():
    c = ctx()
    tool.run(tool.Args(candidates=candidates()), c)
    again = tool.run(tool.Args(candidates=candidates()), c)
    assert (again.created, again.versioned, again.updated, again.unchanged) == (0, 0, 0, 2)
    assert len(c.ports.canon.entity_rows) == 2  # type: ignore[union-attr]


def test_a_locked_entity_is_reported_and_left_alone():
    c = ctx()
    tool.run(tool.Args(candidates=candidates()), c)
    for row in c.ports.canon.entity_rows:  # type: ignore[union-attr]
        row["locked"] = True
    changed = candidates()
    changed[0]["card"] = {**changed[0]["card"], "appearance": "something new the documents now say"}
    out = tool.run(tool.Args(candidates=changed), c)
    assert sorted(out.locked) == ["C01", "L01"] and out.versioned == 0
