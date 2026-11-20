"""plan/2026-11-19: Raphael reads the production's take lengths (`SceneS.takes`)."""
from __future__ import annotations

from contracts import take_lengths as tl
from contracts.raphael.scene import BlockS, SceneS, scene_dump, shortest_take
from hiru_ai.agents.raphael import wire_schema


def _scene(takes: list[int] | None = None) -> SceneS:
    extra = {"takes": takes} if takes else {}
    return SceneS(blocks=[BlockS(index=0, kind="action", text="Kasun waits at the gate.")], **extra)


def test_raphael_reads_the_scenes_lengths_and_an_old_scene_hashes_as_before() -> None:
    old, new = _scene(), _scene(list(tl.take_lengths("any", 15)))
    assert old.legacy and old.longest == 8 and "takes" not in scene_dump(old)
    assert not new.legacy and new.longest == 15 and scene_dump(new)["takes"] == list(range(3, 16))
    assert shortest_take(8.5, new.takes) == 9 and shortest_take(8.5, old.takes) is None


def test_raphaels_tool_schema_names_only_the_runs_lengths() -> None:
    def take_enum(specs: list[dict]) -> list[int]:
        put = next(t for t in specs if t["function"]["name"] in ("put_clips", "put_extras"))["function"]
        return put["parameters"]["properties"]["clips"]["items"]["properties"]["take_s"]["enum"]

    assert take_enum(wire_schema.stage1_specs()) == [4, 6, 8]
    assert take_enum(wire_schema.stage1_specs((4, 6, 8, 10))) == [4, 6, 8, 10]
    assert take_enum(wire_schema.stage2_specs(tuple(range(3, 16)))) == list(range(3, 16))
