"""Phase 7: the developer's commands (graph, catalog, studio, remove) and the per-environment overlays."""
from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest
import yaml

from hiru_ai.cli import main, tools
from hiru_ai.core import models
from hiru_ai.core.errors import HiruAIError
from hiru_ai.core.registry import PACKAGE_ROOT, Registry, default

REPO = Path(__file__).resolve().parents[2]


def test_the_catalog_in_the_repo_is_current():
    """CI check: `hiru-ai catalog` after any manifest change."""
    assert (REPO / tools.CATALOG).read_text(encoding="utf-8") == tools.catalog(default()), "run `hiru-ai catalog`"


def test_the_catalog_names_every_part_and_who_uses_it():
    reg = default()
    text = tools.catalog(reg)
    assert all(f"`{ident}`" in text for (_, ident) in reg.components)
    assert "| `advisor` | active | director | medium | - | panel:director_board, system:director_chat |" in text


def test_a_system_and_a_panel_draw_themselves():
    reg = default()
    assert "__start__" in tools.draw(reg, "director_chat") and "__start__" in tools.draw(reg, "shot_review")
    with pytest.raises(HiruAIError):
        tools.draw(reg, "nothing")


def test_studio_lists_every_graph_with_a_factory():
    config = json.loads(tools.studio(default()))
    assert config["graphs"]["director_chat"].endswith("systems/director_chat/graph.py:blank")
    assert "plan_review" in config["graphs"] and config["dependencies"] == ["."]
    assert (REPO / "langgraph.json").read_text(encoding="utf-8") == tools.studio(default())


@pytest.fixture
def copy_of_the_package(tmp_path: Path) -> Registry:
    root = tmp_path / "hiru_ai"
    shutil.copytree(PACKAGE_ROOT, root, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    return Registry(root).discover()


def test_removing_a_part_lists_every_reference_and_changes_nothing_without_yes(copy_of_the_package: Registry):
    reg = copy_of_the_package
    lines = tools.remove(reg, "agent", "advisor", yes=False)
    assert any("panel:director_board" in line for line in lines)
    assert any("system:director_chat" in line for line in lines)
    assert reg.components[("agent", "advisor")].folder.is_dir()


def test_removing_a_part_drops_its_references_and_its_folder(copy_of_the_package: Registry):
    reg = copy_of_the_package
    tools.remove(reg, "agent", "advisor", yes=True)
    after = Registry(reg.root).discover()
    assert ("agent", "advisor") not in after.components
    assert after.refs_to("agent", "advisor") == []
    board = yaml.safe_load((reg.root / "panels" / "director_board" / "component.yaml").read_text(encoding="utf-8"))
    assert "agent:advisor" not in board.get("review", [])
    assert [p for p in after.validate(imports=False) if p.level == "error" and "advisor" in str(p)] == []


def test_a_part_a_role_needs_cannot_be_removed_until_another_takes_the_role(copy_of_the_package: Registry):
    with pytest.raises(HiruAIError, match="cannot work without"):
        tools.remove(copy_of_the_package, "agent", "scene_planner", yes=True)
    with pytest.raises(HiruAIError):
        tools.remove(copy_of_the_package, "agent", "nothing", yes=False)


def test_a_critic_removed_from_the_panel_leaves_a_manifest_that_still_validates(copy_of_the_package: Registry):
    reg = copy_of_the_package
    tools.remove(reg, "agent", "emotion_critic", yes=True)
    after = Registry(reg.root).discover()
    panel = after.components[("panel", "plan_review")].manifest
    assert [m.agent for m in panel.members] == ["coverage_critic", "editor_critic"]  # type: ignore[union-attr]
    assert [p for p in after.validate(imports=False) if p.level == "error" and "plan_review" in str(p)] == []


def test_the_disable_overlay_switches_a_part_off_and_a_typo_is_reported(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("HIRU_AI__DISABLE", "agent:advisor, tool:nope")
    reg = Registry().discover()
    assert reg.components[("agent", "advisor")].manifest.status == "disabled"
    assert any("tool:nope" in str(p) for p in reg.errors)
    monkeypatch.delenv("HIRU_AI__DISABLE")
    assert Registry().discover().components[("agent", "advisor")].manifest.status == "active"


def test_an_environment_models_file_is_laid_over_the_tiers(tmp_path: Path):
    base = tmp_path / "models.yaml"
    shutil.copy(models.MODELS_YAML, base)
    (tmp_path / "models.staging.yaml").write_text("tiers:\n  high: { fallbacks: [medium] }\n", encoding="utf-8")
    plain = models.load_models(base, "")
    staged = models.load_models(base, "staging")
    assert plain.tiers["high"].fallbacks == [] and staged.tiers["high"].fallbacks == ["medium"]
    assert staged.tiers["high"].model == plain.tiers["high"].model  # only what the overlay names changes


def test_the_commands_run_from_the_command_line(tmp_path: Path, capsys: pytest.CaptureFixture[str]):
    out = tmp_path / "c.md"
    assert main(["catalog", "--out", str(out)]) == 0
    assert main(["catalog", "--check", "--out", str(out)]) == 0
    out.write_text("old", encoding="utf-8")
    assert main(["catalog", "--check", "--out", str(out)]) == 1
    capsys.readouterr()
    assert main(["graph", "plan_review"]) == 0
    assert "__start__" in capsys.readouterr().out
    assert main(["remove", "agent", "advisor"]) == 0
    assert "nothing changed" in capsys.readouterr().out


def test_a_member_written_over_two_lines_goes_whole(copy_of_the_package: Registry):
    reg = copy_of_the_package
    tools.remove(reg, "agent", "cinematographer", yes=True)
    after = Registry(reg.root).discover()
    panel = after.components[("panel", "director_board")].manifest
    assert [m.label for m in panel.members] == ["timing", "sound", "continuity"]  # type: ignore[union-attr]


def test_a_new_craft_is_one_folder_and_one_member_line(copy_of_the_package: Registry):
    """The recipe: `hiru-ai new agent lighting`, a prompt, one `members:` line on the board; nothing else is edited."""
    from hiru_ai.cli import scaffold

    reg = copy_of_the_package
    scaffold.create("agent", "lighting", reg.root)
    path = reg.root / "panels" / "director_board" / "component.yaml"
    line = "  - { agent: lighting, name: lighting, owns: [set], wins: [set.lighting] }\n"
    text = path.read_text(encoding="utf-8")
    path.write_text(text.replace("settle: step:board_settle", line + "settle: step:board_settle"), encoding="utf-8")
    after = Registry(reg.root).discover()
    members = after.components[("panel", "director_board")].manifest.members  # type: ignore[union-attr]
    assert "lighting" in [m.label for m in members]
    assert [p for p in after.validate(imports=False) if p.level == "error" and "director_board" in str(p)] == []


def test_every_agents_eval_cases_pass_when_scripted(capsys: pytest.CaptureFixture[str]):
    assert main(["eval"]) == 0
    assert "cases pass" in capsys.readouterr().out


def test_a_failing_case_is_named_and_fails_the_command(tmp_path: Path, capsys: pytest.CaptureFixture[str]):
    from hiru_ai.cli import evals

    reg = default()
    results = evals.run_agent(reg, "advisor")
    assert results and all(r.passed for r in results)
    assert evals.contained({"agrees": False}, {"agrees": True, "view": ""}) is False
    # an alternate prompt file is the other side of an A/B: it is read, sent and recorded
    alt = tmp_path / "alt.md"
    alt.write_text("You advise the lead. Be brief.", encoding="utf-8")
    assert all(r.passed for r in evals.run_agent(reg, "advisor", prompt=alt))
    assert "FAIL" in evals.report([evals.Result("advisor", "x", False, "got {}")])
