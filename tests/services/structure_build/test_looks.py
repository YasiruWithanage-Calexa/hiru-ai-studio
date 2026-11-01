"""The structure build drafts looks from the canon's wardrobes once the episodes are known."""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Any
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "src" / "services" / "structure_build"))

from langgraph.checkpoint.memory import InMemorySaver  # noqa: E402
from structure_build.engine import looks, pipeline  # noqa: E402

from tests.services.fakes import FakeJobs, FakeLLM  # noqa: E402
from tests.services.structure_build.test_prose import DRAMA, good_cut  # noqa: E402
from tests.services.structure_build.test_structure_build import FakeStore, build_payload, doc  # noqa: E402

KASUN = ("Simple plain T-shirts or casual shirts; Dark jeans; "
         "Later, as his business grows, clean smart-casual clothing")


def character(name: str, wardrobe: str = "", code: str = "C01") -> dict[str, Any]:
    card = {"wardrobe": wardrobe} if wardrobe else {"summary": "x"}
    return {"id": str(uuid4()), "kind": "character", "code": code, "name": name, "aliases": [],
            "current": {"card": card}}


class Store(FakeStore):
    def __init__(self, docs: list[dict[str, str]], canon_rows: list[dict[str, Any]]) -> None:
        super().__init__(docs)
        self.canon_rows = canon_rows

    def create_entity(self, entity: dict[str, Any], version: dict[str, Any]) -> None:
        self.canon_rows.append({**entity, "current": {"card": version["card"]}})


def build(store: Store, llm: FakeLLM) -> dict[str, Any]:
    jobs = FakeJobs(status="running", cursor=1)
    result = pipeline.run(build_payload(uuid4()), store, jobs, llm, InMemorySaver(), durable=False)
    store.jobs = jobs  # type: ignore[attr-defined]
    return result


def test_rules_draft_looks_for_characters_whose_card_has_a_wardrobe():
    kasun, nimal = character("Kasun", KASUN), character("Nimal", code="C02")
    store = Store([doc("pack.pdf", "bible", DRAMA)], [kasun, nimal])
    result = build(store, FakeLLM(enabled=False))
    assert result["looks"] == 2 == len(store.look_rows)
    assert {r["entity_id"] for r in store.look_rows} == {kasun["id"]}  # no wardrobe, no look
    assert [(r["name"], r["ranges"]) for r in store.look_rows] == [
        ("Everyday", [{"from": 1, "to": 2}]), ("Later", [{"from": 3, "to": 3}])]
    assert all(r["production_id"] and "status" not in r for r in store.look_rows)  # drafts
    [step] = [t for t in store.jobs.texts("agent_step") if t.startswith("Drafted")]  # type: ignore[attr-defined]
    assert "2 looks for 1 characters" in step


def test_a_character_that_already_has_looks_is_left_alone():
    kasun = character("Kasun", KASUN)
    store = Store([doc("pack.pdf", "bible", DRAMA)], [kasun])
    store.look_rows.append({"entity_id": kasun["id"], "name": "Mine"})
    result = build(store, FakeLLM(enabled=False))
    assert result["looks"] == 0 and [r["name"] for r in store.look_rows] == ["Mine"]


def test_a_second_build_does_not_double_the_looks():
    store = Store([doc("pack.pdf", "bible", DRAMA)], [character("Kasun", KASUN)])
    build(store, FakeLLM(enabled=False))
    first = list(store.look_rows)
    build(store, FakeLLM(enabled=False))
    assert store.look_rows == first


def proposal(system: str, user: str) -> dict[str, Any]:
    assert "Episodes: 3" in user and '<character name="Kasun">' in user and KASUN in user
    return {"looks": [
        {"character": "kasun", "name": "Street", "from": 1, "to": 2, "outfit": "plain T-shirt, dark jeans",
         "hair": "", "makeup": "", "accessories": "sandals"},
        {"character": "Kasun", "name": "Restaurant owner", "from": 3, "to": 3, "outfit": "smart-casual shirt",
         "hair": "", "makeup": "", "accessories": ""}]}


def test_the_model_proposes_the_looks_when_there_is_a_key():
    store = Store([doc("pack.pdf", "bible", DRAMA)], [character("Kasun", KASUN)])
    llm = FakeLLM({"prose_scenes": good_cut, "canon_looks": proposal}, enabled=True)
    build(store, llm)
    assert [r["name"] for r in store.look_rows] == ["Street", "Restaurant owner"]
    [call] = [c for c in llm.calls if c["schema"] == "canon_looks"]
    assert call["tier"] == "medium" and call["system"] == looks.SYSTEM  # the static part never changes


def test_a_model_that_fails_or_rambles_falls_back_to_the_rules():
    nonsense = lambda s, u: {"looks": [{"character": "Kasun", "name": "", "from": 9, "to": 1, "outfit": "",  # noqa: E731
                                         "hair": "", "makeup": "", "accessories": ""}]}
    for responders in ({"prose_scenes": good_cut}, {"prose_scenes": good_cut, "canon_looks": nonsense}):
        store = Store([doc("pack.pdf", "bible", DRAMA)], [character("Kasun", KASUN)])
        build(store, FakeLLM(responders, enabled=True))  # no responder for canon_looks → the call raises
        assert [r["name"] for r in store.look_rows] == ["Everyday", "Later"]


def test_a_failure_drafting_looks_never_fails_the_build():
    class Broken(Store):
        def create_looks(self, rows: list[dict[str, Any]]) -> None:
            raise RuntimeError("table missing")

    store = Broken([doc("pack.pdf", "bible", DRAMA)], [character("Kasun", KASUN)])
    result = build(store, FakeLLM(enabled=False))
    assert result["episodes"] == 3
    assert any("Looks could not be drafted" in t for t in store.jobs.texts("warning"))  # type: ignore[attr-defined]


def test_canon_that_is_not_part_of_the_build_gets_no_drafted_looks():
    class Off(Store):
        def production(self, production_id: Any) -> dict[str, Any] | None:
            return {"id": str(production_id), "orientation": "vertical",
                    "settings": {"default_scene_envelope_s": 45, "build": {"canon": False}}}

    store = Off([doc("pack.pdf", "bible", DRAMA)], [character("Kasun", KASUN)])
    build(store, FakeLLM(enabled=False))
    assert store.look_rows == []
