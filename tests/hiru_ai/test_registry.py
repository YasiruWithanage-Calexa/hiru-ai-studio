"""Manifests, the registry and `validate`: the rules that let parts be added and removed safely."""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

import pytest

from hiru_ai.cli import scaffold
from hiru_ai.cli.main import main
from hiru_ai.core import manifest as mf
from hiru_ai.core.errors import ManifestError, UnknownComponent
from hiru_ai.core.registry import Registry, default


@pytest.fixture
def root(tmp_path: Path) -> Path:
    return tmp_path / "hiru_ai"


def make(root: Path, kind: str, ident: str, **edit: str) -> None:
    """Scaffold a part, then edit its manifest text: edit={'old': 'new'}."""
    scaffold.create(kind, ident, root)
    if edit:
        path = root / mf.LAYERS[kind] / ident / "component.yaml"
        text = path.read_text(encoding="utf-8")
        for old, new in edit.items():
            assert old in text, f"{old!r} not in the manifest"
            text = text.replace(old, new)
        path.write_text(text, encoding="utf-8")


def problems(root: Path, **kw: Any) -> list[str]:
    return [str(p) for p in Registry(root).discover().validate(**kw)]


def clean(root: Path) -> None:
    assert problems(root) == []


# ── manifests ────────────────────────────────────────────────────────────────────────────────


def test_a_manifest_names_the_file_and_the_field_that_is_wrong():
    with pytest.raises(ManifestError, match=r"agents/x/component.yaml.*model"):
        mf.parse({"id": "xy", "kind": "agent", "summary": "does a thing", "input": "a:B", "output": "a:C"},
                 "agents/x/component.yaml")


def test_an_unknown_kind_or_key_is_refused():
    with pytest.raises(ManifestError, match="unknown kind"):
        mf.parse({"kind": "robot", "id": "xy"})
    with pytest.raises(ManifestError, match="Extra inputs"):
        mf.parse({"id": "xy", "kind": "step", "summary": "does a thing", "colour": "red"})


@pytest.mark.parametrize("ident", ["X", "1abc", "has-dash", "a", "has space"])
def test_ids_are_lower_snake(ident: str):
    with pytest.raises(ManifestError):
        mf.parse({"id": ident, "kind": "step", "summary": "does a thing"})


def test_a_panels_members_are_references():
    m = mf.parse({"id": "board", "kind": "panel", "summary": "the board", "pattern": "board",
                  "members": [{"agent": "editor", "owns": ["split"]}], "settle": "step:board_settle",
                  "review": ["agent:advisor"]})
    assert m.refs() == [("agent", "editor"), ("step", "board_settle"), ("agent", "advisor")]
    with pytest.raises(ManifestError, match="bad reference"):
        mf.parse({"id": "board", "kind": "panel", "summary": "the board", "pattern": "board", "settle": "board_settle"})


# ── the real package ─────────────────────────────────────────────────────────────────────────


def test_the_packages_own_parts_are_valid():
    """Every part that ships passes `hiru-ai validate` (none do yet in Phase 1; each phase adds some)."""
    reg = default()
    assert [str(p) for p in reg.validate() if p.level == "error"] == []


# ── discovery and lookup ─────────────────────────────────────────────────────────────────────


def test_a_scaffolded_part_is_found_by_id_and_validates(root: Path):
    make(root, "agent", "translator")
    clean(root)
    reg = Registry(root).discover()
    assert reg.get("agent", "translator").manifest.model == "medium" and reg.ids("agent") == ["translator"]


def test_a_missing_part_is_an_error_naming_it(root: Path):
    with pytest.raises(UnknownComponent, match="no active agent 'ghost'"):
        Registry(root).discover().get("agent", "ghost")


def test_a_disabled_part_is_not_served_unless_asked(root: Path):
    make(root, "agent", "advisor", **{"status: experimental": "status: disabled"})
    reg = Registry(root).discover()
    with pytest.raises(UnknownComponent):
        reg.get("agent", "advisor")
    assert reg.get("agent", "advisor", include_disabled=True).manifest.status == "disabled"
    assert reg.ids("agent") == [] and reg.ids("agent", include_disabled=True) == ["advisor"]


def test_the_folder_name_must_be_the_id_and_the_kind_must_match_the_layer(root: Path):
    make(root, "agent", "writer")
    (root / "agents" / "writer").rename(root / "agents" / "other")
    assert any("must equal the folder name" in p for p in problems(root))


def test_a_part_whose_code_is_not_imported_until_asked_for(root: Path):
    make(root, "tool", "weather")
    (root / "tools" / "weather" / "tool.py").write_text("raise RuntimeError('imported too early')\n", encoding="utf-8")
    reg = Registry(root).discover()
    assert reg.get("tool", "weather")  # discovery and lookup did not import it
    with pytest.raises(RuntimeError, match="too early"):
        reg.module("tool", "weather", "tool")
    sys.modules.pop("hiru_ai.tools.weather.tool", None)


# ── validate ─────────────────────────────────────────────────────────────────────────────────


def test_an_agent_naming_a_missing_tool_is_reported(root: Path):
    make(root, "agent", "writer", **{"tools: []": "tools: [weather]"})
    assert any("names tool 'weather', which does not exist" in p for p in problems(root))


def test_removing_a_tool_fails_validate_until_no_agent_lists_it(root: Path):
    make(root, "tool", "weather")
    make(root, "agent", "writer", **{"tools: []": "tools: [weather]"})
    clean(root)
    reg = Registry(root).discover()
    assert reg.refs_to("tool", "weather") == [("agent", "writer")]
    import shutil

    shutil.rmtree(root / "tools" / "weather")
    sys.modules.pop("hiru_ai.tools.weather.tool", None)
    assert problems(root) == ["error: agent writer: names tool 'weather', which does not exist"]


def test_an_active_part_may_not_name_a_disabled_one_but_a_disabled_part_may(root: Path):
    make(root, "tool", "weather", **{"status: experimental": "status: disabled"})
    make(root, "agent", "writer", **{"tools: []": "tools: [weather]"})
    assert any("which is disabled" in p for p in problems(root))
    path = root / "agents" / "writer" / "component.yaml"
    text = path.read_text(encoding="utf-8").replace("status: experimental", "status: disabled")
    path.write_text(text, encoding="utf-8")
    clean(root)


def test_an_unknown_model_tier_and_unknown_middleware_are_reported(root: Path):
    make(root, "agent", "writer",
         **{"model: medium": "model: smart", "[usage, untrusted_text": "[telepathy, usage, untrusted_text"})
    found = problems(root)
    assert any("model tier 'smart' is not in models.yaml" in p for p in found)
    assert any("unknown middleware telepathy" in p for p in found)


def test_react_only_middleware_and_knowledge_need_a_tool_loop(root: Path):
    make(root, "agent", "writer", **{"[usage, untrusted_text": "[hitl, usage, untrusted_text"})
    assert any("hitl apply to react agents" in p for p in problems(root))
    make(root, "knowledge_base", "craft")
    make(root, "agent", "reader", **{"knowledge: []": "knowledge: [craft]", "shape: structured": "shape: react"})
    assert any("not the search_kb tool" in p for p in problems(root))
    make(root, "agent", "oneshot", **{"knowledge: []": "knowledge: [craft]"})
    assert any("agent oneshot" in p and "cannot search" in p for p in problems(root))


def test_only_approved_parts_may_write_dialogue(root: Path):
    make(root, "agent", "writer", **{"writes_dialogue: false": "writes_dialogue: true"})
    assert any("writes_dialogue is limited to the approved parts" in p for p in problems(root))
    make(root, "agent", "translator", **{"writes_dialogue: false": "writes_dialogue: true"})
    assert not any("agent translator" in p for p in problems(root))


def test_an_agent_needs_a_prompt_and_eval_cases(root: Path):
    make(root, "agent", "writer")
    (root / "agents" / "writer" / "prompts" / "system.md").write_text("  \n", encoding="utf-8")
    (root / "agents" / "writer" / "evals" / "cases.yaml").write_text("[]\n", encoding="utf-8")
    found = problems(root)
    assert any("prompt 'system'" in p and "missing or empty" in p for p in found)
    assert any("has no eval cases" in p for p in found)


def test_input_and_output_must_be_pydantic_models(root: Path):
    make(root, "agent", "writer")
    (root / "agents" / "writer" / "schema.py").write_text("Input = dict\nclass Output: ...\n", encoding="utf-8")
    sys.modules.pop("hiru_ai.agents.writer.schema", None)
    found = problems(root)
    assert any("input 'schema:Input' is not a pydantic model" in p for p in found)
    assert any("output 'schema:Output' is not a pydantic model" in p for p in found)
    sys.modules.pop("hiru_ai.agents.writer.schema", None)


def test_an_import_error_in_a_part_is_a_problem_not_a_crash(root: Path):
    make(root, "agent", "writer")
    (root / "agents" / "writer" / "schema.py").write_text("import not_a_real_module_zzz\n", encoding="utf-8")
    sys.modules.pop("hiru_ai.agents.writer.schema", None)
    assert any("cannot resolve 'schema:Input'" in p for p in problems(root))
    assert problems(root, imports=False) == []  # --no-import skips running part code


def panel(root: Path, ident: str, body: str) -> None:
    make(root, "panel", ident)
    (root / "panels" / ident / "component.yaml").write_text(
        f"id: {ident}\nkind: panel\nsummary: a panel\npattern: board\nmembers: []\n{body}", encoding="utf-8")


def test_a_system_over_panels_over_agents_is_a_tree_not_a_cycle(root: Path):
    make(root, "agent", "gamma")
    panel(root, "beta", "review: ['agent:gamma']\n")
    make(root, "system", "alpha", **{"panels: []": "panels: [beta]", "agents: []": "agents: [gamma]"})
    assert not any("cycle" in p for p in problems(root))


def test_panels_that_review_each_other_are_a_cycle(root: Path):
    panel(root, "one", "review: ['panel:two']\n")
    panel(root, "two", "review: ['panel:one']\n")
    found = [p for p in problems(root) if "cycle" in p]
    assert found and "panel one -> panel two -> panel one" in found[0]


def test_a_malformed_manifest_is_reported_with_its_path_and_does_not_hide_the_others(root: Path):
    make(root, "tool", "good")
    make(root, "tool", "broken")
    (root / "tools" / "broken" / "component.yaml").write_text("id: broken\nkind: tool\n", encoding="utf-8")
    found = problems(root)
    assert any("broken" in p and "summary" in p for p in found)
    assert Registry(root).discover().get("tool", "good")


# ── the CLI ──────────────────────────────────────────────────────────────────────────────────


def test_new_validate_list_work_together_on_any_root(root: Path, capsys: pytest.CaptureFixture[str]):
    assert main(["--root", str(root), "new", "agent", "lighting"]) == 0
    assert main(["--root", str(root), "new", "tool", "weather_lookup"]) == 0
    assert main(["--root", str(root), "validate"]) == 0
    capsys.readouterr()
    assert main(["--root", str(root), "list"]) == 0
    out = capsys.readouterr().out
    assert "lighting" in out and "weather_lookup" in out
    assert main(["--root", str(root), "list", "tool"]) == 0
    assert "lighting" not in capsys.readouterr().out


def test_new_refuses_a_taken_or_malformed_id(root: Path):
    assert main(["--root", str(root), "new", "step", "settle"]) == 0
    assert main(["--root", str(root), "new", "step", "settle"]) == 2
    assert main(["--root", str(root), "new", "step", "Bad-Id"]) == 2


def test_validate_exits_one_on_errors_and_zero_on_warnings(root: Path):
    make(root, "agent", "writer", **{"tools: []": "tools: [ghost]"})
    assert main(["--root", str(root), "validate"]) == 1
    other = root.parent / "second"
    make(other, "panel", "empty")
    assert main(["--root", str(other), "validate"]) == 0  # a panel with no members is a warning
