from __future__ import annotations

import sys
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "src" / "services" / "canon_extract"))

from canon_extract.engine import model, pipeline, rules, write  # noqa: E402
from langgraph.checkpoint.memory import InMemorySaver  # noqa: E402

from contracts.build import BUILD_PIPELINE  # noqa: E402
from contracts.canon import CanonKind  # noqa: E402
from contracts.jobs import DispatchPayload, JobKind  # noqa: E402
from tests.services.doc_ingest.conftest import CORPUS  # noqa: E402
from tests.services.fakes import FakeJobs, FakeLLM  # noqa: E402

PID = uuid4()
DOCS = [
    ("harbour-lights-canon-index.md", "canon_index"),
    ("harbour-lights-bible.md", "bible"),
    ("harbour-lights-ep01-script.fountain", "script"),
]


def documents() -> list[dict[str, str]]:
    return [{"id": str(uuid4()), "filename": f, "role": r, "text": (CORPUS / f).read_text(encoding="utf-8")}
            for f, r in DOCS]


class FakeStore:
    def __init__(self, docs: list[dict[str, str]] | None = None) -> None:
        self.docs = docs if docs is not None else documents()
        self.entity_rows: dict[str, dict[str, Any]] = {}
        self.version_rows: dict[str, dict[str, Any]] = {}

    def production(self, production_id: UUID) -> dict[str, Any] | None:
        return {"id": str(production_id), "orientation": "horizontal", "settings": {}}

    def documents(self, production_id: UUID) -> list[dict[str, Any]]:
        return [{"id": d["id"], "filename": d["filename"], "confirmed_role": d["role"], "detected_role": None,
                 "text_path": f"p/{d['id']}/extracted.txt" if d.get("text") else None} for d in self.docs]

    def text(self, path: str) -> str:
        return next(d["text"] for d in self.docs if d["id"] in path)

    def entities(self, production_id: UUID) -> list[dict[str, Any]]:
        return [{**e, "current": self.version_rows.get(e.get("current_version_id"))} for e in self.entity_rows.values()]

    def create_entity(self, entity: dict[str, Any], version: dict[str, Any]) -> None:
        self.entity_rows[entity["id"]] = {**entity, "locked": False, "current_version_id": version["id"]}
        self.version_rows[version["id"]] = version

    def add_version(self, entity_id: str, version: dict[str, Any], fields: dict[str, Any]) -> None:
        self.version_rows[version["id"]] = version
        self.entity_rows[entity_id].update({**fields, "current_version_id": version["id"]})

    def update_entity(self, entity_id: str, fields: dict[str, Any]) -> None:
        self.entity_rows[entity_id].update(fields)

    def by_code(self, code: str) -> dict[str, Any]:
        e = next(e for e in self.entity_rows.values() if e["code"] == code)
        return {**e, "current": self.version_rows[e["current_version_id"]]}


def payload(build: bool = False) -> DispatchPayload:
    hops = list(BUILD_PIPELINE) if build else [JobKind.CANON_EXTRACT]
    return DispatchPayload(job_id=uuid4(), kind=JobKind.CANON_EXTRACT, actor_user_id=uuid4(), production_id=PID,
                           pipeline=hops, state={"build": build})


def run(store: FakeStore, llm: FakeLLM | None = None, build: bool = False, jobs: FakeJobs | None = None):
    jobs = jobs or FakeJobs()
    result = pipeline.run(payload(build), store, jobs, llm or FakeLLM(enabled=False), InMemorySaver())
    return result, jobs


def test_rules_build_the_fixture_canon_with_the_index_codes():
    store = FakeStore()
    result, jobs = run(store)
    assert result["created"] == 11 and jobs.status == "done"
    kamala = store.by_code("C01")
    assert kamala["name"] == "Kamala" and "කමලා" in kamala["aliases"] and kamala["core"]
    v = kamala["current"]
    assert v["voice_pin"] == "low, clipped female voice (52), a Sri Lankan (southern) accent"
    assert v["wardrobe_anchor"].startswith("Faded blue cotton saree")
    assert "Outfit in every panel:" in v["reference_prompt"] and v["source"] == "extract"
    harbour = store.by_code("L02")
    assert "Kalugala Harbour" in harbour["aliases"]  # the heading joined the index entry
    assert {e["code"] for e in store.entity_rows.values()} >= {"P01", "P04", "L03", "C04"}
    assert any("4 core characters" in c for e in jobs.events for c in e.get("chips", []))
    assert ("canon", "done") in jobs.stages() and ("read", "done") in jobs.stages()


def test_rerun_is_idempotent():
    store = FakeStore()
    run(store)
    result, _ = run(store)
    assert result["created"] == 0 and result["versioned"] == 0 and result["unchanged"] == 11


def test_locked_entities_are_never_changed():
    store = FakeStore()
    run(store)
    kamala = store.by_code("C01")
    store.entity_rows[kamala["id"]]["locked"] = True
    store.docs[0]["text"] = store.docs[0]["text"].replace("Voice: low, clipped", "Voice: high, bright")
    result, jobs = run(store)
    assert "C01" in result["locked"]
    assert store.by_code("C01")["current"]["version"] == 1
    assert any("C01" in t for t in jobs.texts("agent_step"))


def test_a_changed_card_is_a_new_version_but_a_person_s_wording_is_kept():
    store = FakeStore()
    run(store)
    nimal = store.by_code("C02")
    # a person wrote version 2 with their own voice description
    v2 = {**nimal["current"], "id": str(uuid4()), "version": 2, "source": "user",
          "card": {**nimal["current"]["card"], "voice": "warm, unhurried"}, "card_hash": "user"}
    store.version_rows[v2["id"]] = v2
    store.entity_rows[nimal["id"]]["current_version_id"] = v2["id"]
    run(store)
    current = store.by_code("C02")["current"]
    assert current["version"] == 3 and current["card"]["voice"] == "warm, unhurried"


def test_canon_can_be_skipped_by_the_build_settings():
    store = FakeStore()
    store.production = lambda pid: {"id": str(pid), "orientation": "horizontal",  # type: ignore[method-assign]
                                    "settings": {"build": {"canon": False}}}
    result, jobs = run(store, build=True)
    assert result == {"skipped": "canon not requested"} and store.entity_rows == {}
    assert jobs.advanced and jobs.advanced[0]["state"]["build"] is True


def test_a_build_hop_hands_over_to_the_next_function():
    store = FakeStore()
    _, jobs = run(store, build=True)
    assert jobs.status == "running"  # not finished: the structure build comes next
    assert jobs.advanced[0]["cursor"] == 0 and jobs.advanced[0]["state"]["previous"]["created"] == 11


def test_documents_without_stored_text_are_reported():
    docs = documents()
    docs[1]["text"] = ""
    store = FakeStore(docs)
    _, jobs = run(store)
    assert any("re-ingest" in w for w in jobs.texts("warning"))


def test_model_cards_fill_in_and_dedupe_merges_a_script_nickname():
    docs = documents()
    docs[2]["text"] = docs[2]["text"].replace("KAMALA\n", "AMMA\n")  # the script calls her "Amma"
    store = FakeStore(docs)

    def extract(system: str, user: str) -> dict[str, Any]:
        assert '<document name="harbour-lights-bible.md" role="bible">' in user
        assert "Amma (" in user  # the scripts' speakers are listed for the model
        card = dict.fromkeys(model.CARD_FIELDS, "")
        return {"entities": [
            {"kind": "character", "name": "Sunil", "code": "C03", "aliases": [], "core": True,
             "card": {**card, "appearance": "wiry, sun-darkened", "voice": "model paraphrase"}},
            {"kind": "prop", "name": "Lantern", "code": "", "aliases": [], "core": False,
             "card": {**card, "details": "kerosene lantern"}}]}

    def dedupe(system: str, user: str) -> dict[str, Any]:
        return {"groups": [{"kind": "character", "keep": "Kamala", "same_as_keep": ["Amma"]}]}

    llm = FakeLLM({"canon": extract, "canon_dupes": dedupe})
    run(store, llm)
    sunil = store.by_code("C03")["current"]["card"]
    assert sunil["appearance"] == "wiry, sun-darkened"
    assert sunil["voice"] == "quiet, hesitant"  # the index's own words beat the model's paraphrase
    assert store.by_code("P05")["name"] == "Lantern"
    kamala = store.by_code("C01")
    assert "Amma" in kamala["aliases"]
    assert not [e for e in store.entity_rows.values() if e["name"] == "Amma"]
    assert [c["tier"] for c in llm.calls] == ["high", "medium"]


def test_model_failure_keeps_the_rules_canon():
    store = FakeStore()
    result, _ = run(store, FakeLLM({}))
    assert result["created"] == 11


def test_critic_names_core_characters_missing_pins():
    cands = rules.merge(rules.from_index("- C09 Ravi — a fisherman, 40.", "idx"))
    assert write.critic(cands) == ["C09: no wardrobe anchor or voice in the documents yet."]


def test_a_heading_place_that_only_partly_matches_is_left_for_the_build_to_ask():
    cands = rules.merge(rules.from_index("- L02 Kalugala harbour breakwater — concrete, lighthouse.", "idx"),
                        [rules.candidate(CanonKind.LOCATION, n) for n in ("Kalugala Beach", "Temple")])
    kept = [c["name"] for c in rules.drop_uncertain_places(cands)]
    assert kept == ["Kalugala harbour breakwater", "Temple"]


def test_index_line_variants():
    found = rules.from_index("* **L07** Temple steps: stone steps, frangipani trees.\n- P10 Ledger - a debt book", "x")
    assert [(c["code"], c["name"]) for c in found] == [("L07", "Temple steps"), ("P10", "Ledger")]
