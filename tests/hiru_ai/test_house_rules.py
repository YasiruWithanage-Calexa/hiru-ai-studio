"""plan/2026-11-12 §3.1: house rules, the studio's own rules, always given to the agents that subscribe.

What is held: a rule file is checked before anything runs; an agent gets exactly the rules of its topics, at the END of
its system prompt, the same bytes every call; an agent that subscribes to nothing is unchanged byte for byte; what a
call was given is recorded only when the call returns; a manifest cannot subscribe to a topic no rule has or forget the
middleware."""

from __future__ import annotations

from pathlib import Path

import pytest

from hiru_ai.core import agents, house_rules, middleware
from hiru_ai.core.context import RunContext
from hiru_ai.core.errors import ManifestError
from hiru_ai.core.middleware import house_rules as hr_mw
from hiru_ai.core.middleware.base import ModelCall
from hiru_ai.core.registry import default

GOOD = """id: H-07
topics: [objects, sound]
kind: default
why: A reason.
version: 1
---
Rule seven, in
two lines.
"""


def _write(folder: Path, name: str, text: str) -> Path:
    p = folder / name
    p.write_text(text, encoding="utf-8")
    return p


def test_a_rule_file_is_read_with_its_header(tmp_path: Path):
    r = house_rules.parse(_write(tmp_path, "seven.md", GOOD))
    assert (r.id, r.topics, r.kind, r.version, r.label) == ("H-07", ("objects", "sound"), "default", 1, "H-07 v1")
    assert r.text == "Rule seven, in two lines."  # one line in the block, whatever the file's wrapping
    assert house_rules.parse(_write(tmp_path, "crlf.md", GOOD.replace("\n", "\r\n"))).text == r.text


@pytest.mark.parametrize(
    "text, says",
    [
        (GOOD.replace("---\n", ""), "must end with a line '---'"),
        (GOOD.replace("kind: default", "kind: maybe"), "kind is one of"),
        (GOOD.replace("id: H-07", "id: rule7"), "is not like H-12"),
        (GOOD.replace("topics: [objects, sound]", "topics: [Objects]"), "lower-case words"),
        (GOOD.replace("version: 1", "version: 0"), "version is 1 or more"),
        (GOOD.replace("why: A reason.\n", ""), "exactly"),
        (GOOD.split("---")[0] + "---\n   \n", "no text"),
    ],
)
def test_a_bad_rule_file_is_refused_by_name(tmp_path: Path, text: str, says: str | None):
    path = _write(tmp_path, "bad.md", text)
    if says is None:
        house_rules.parse(path)
        return
    with pytest.raises(ManifestError, match=r"bad\.md") as exc:
        house_rules.parse(path)
    assert says in str(exc.value)


def test_two_files_with_one_id_are_refused_and_rules_are_sorted_by_id(tmp_path: Path):
    _write(tmp_path, "b.md", GOOD)
    _write(tmp_path, "a.md", GOOD.replace("H-07", "H-03").replace("[objects, sound]", "[camera]"))
    assert [r.id for r in house_rules.load(tmp_path)] == ["H-03", "H-07"]
    _write(tmp_path, "c.md", GOOD)
    with pytest.raises(ManifestError, match="H-07 is in both"):
        house_rules.load(tmp_path)


def test_an_agent_gets_exactly_the_rules_of_its_topics(tmp_path: Path):
    _write(tmp_path, "a.md", GOOD.replace("H-07", "H-03").replace("[objects, sound]", "[camera]"))
    _write(tmp_path, "b.md", GOOD)
    pool = house_rules.load(tmp_path)
    assert [r.id for r in house_rules.select(("sound",), pool)] == ["H-07"]
    assert [r.id for r in house_rules.select(("camera", "objects"), pool)] == ["H-03", "H-07"]
    assert [r.id for r in house_rules.select(("*",), pool)] == ["H-03", "H-07"]
    assert house_rules.select((), pool) == [] and house_rules.select(("lighting",), pool) == []


def test_the_deployed_rules_load_and_h12_is_one_of_them():
    labels = {r.id: r for r in house_rules.rules()}
    assert "H-12" in labels and {"objects", "sound"} <= set(labels["H-12"].topics)
    assert "close enough for the audience to read" in labels["H-12"].text


def _call(name: str) -> tuple[ModelCall, agents.Agent]:
    ag = agents.build(name)
    system = ag.prompt.system()
    return ModelCall(component=f"agent:{name}", phase="p", tier="t", system=system, user="the scene",
                     static=ag.prompt, house_topics=tuple(ag.manifest.house_rules)), ag


def _through(name: str, terminal=None) -> tuple[str, RunContext, dict]:
    call, ag = _call(name)
    ctx, seen = RunContext(), {}

    def end(c: ModelCall):
        seen["system"], seen["config"] = c.system, c.config
        return terminal(c) if terminal else "ok"

    middleware.run_chain(middleware.build(ag.manifest.middleware), call, ctx, end)
    return seen["system"], ctx, seen["config"]


@pytest.mark.parametrize("name", ["breakdown_episode", "breakdown_repair"])  # the planners: tests/raphael
def test_the_four_subscribers_get_h12_at_the_end_of_the_system_prompt_every_call(name: str):
    first, ctx, config = _through(name)
    again, _, _ = _through(name)
    own = agents.build(name).prompt.text
    assert first.startswith(own) and first.endswith(house_rules.block(house_rules.select(("objects",))))
    assert "- H-12 (default) Implied things." in first and first == again  # the cached prefix never moves
    assert hr_mw.used(ctx) == ["H-12 v2"] and config["metadata"]["house_rules"] == ["H-12 v2"]


def test_an_agent_that_subscribes_to_nothing_is_unchanged_byte_for_byte():
    call, ag = _call("breakdown_split")
    before = call.system
    system, ctx, _ = _through("breakdown_split")
    assert not ag.manifest.house_rules and system == before and hr_mw.used(ctx) == []


def test_a_call_that_fails_is_not_recorded_as_having_relied_on_a_rule():
    def boom(c: ModelCall):
        raise RuntimeError("the model failed")

    call, _ = _call("breakdown_episode")
    ctx = RunContext()
    with pytest.raises(RuntimeError):
        middleware.run_chain([hr_mw.HouseRules()], call, ctx, boom)
    assert hr_mw.used(ctx) == []


def test_a_manifest_cannot_subscribe_to_an_unknown_topic_or_forget_the_middleware():
    reg = default()
    m = agents.build("breakdown_episode").manifest
    unknown = reg._check_house_rules("x", m.model_copy(update={"house_rules": ["objcts"]}))
    assert len(unknown) == 1 and "objcts" in unknown[0].message
    no_mw = reg._check_house_rules("x", m.model_copy(update={"middleware": ["static_first", "usage"]}))
    assert len(no_mw) == 1 and "house_rules middleware" in no_mw[0].message
    assert reg._check_house_rules("x", m) == []
    assert reg._check_house_rules("x", m.model_copy(update={"house_rules": ["*"]})) == []
