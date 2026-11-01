"""The replay harness in rules mode is a CI gate: every `rules` case must pass with no model."""
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from types import ModuleType

ROOT = Path(__file__).resolve().parents[3]


def harness() -> ModuleType:
    sys.path.insert(0, str(ROOT / "scripts"))
    spec = importlib.util.spec_from_file_location("replay_director", ROOT / "scripts" / "replay_director.py")
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules["replay_director"] = module  # dataclasses look their module up by name
    spec.loader.exec_module(module)
    return module


def test_every_rules_case_passes_without_a_model():
    report = harness().replay("rules")
    failed = [(c["id"], c["failures"]) for c in report["cases"] if not c["ok"]]
    assert not failed
    floor = json.loads((ROOT / "tests" / "eval" / "director_thresholds.json").read_text(encoding="utf-8"))["rules"]
    assert all(report["pass_rate"][k] >= v for k, v in floor.items())


def test_cases_are_well_formed():
    cases = json.loads((ROOT / "tests" / "eval" / "director_replay.json").read_text(encoding="utf-8"))["cases"]
    ids = [c["id"] for c in cases]
    assert len(ids) == len(set(ids))
    assert {c["split"] for c in cases} == {"tune", "heldout"}
    assert sum(c["split"] == "heldout" for c in cases) >= 5  # an honest held-out number needs cases
    for c in cases:
        if "turns" in c:  # a conversation: every person turn says what must hold; a recorded model has a reply
            people = [t for t in c["turns"] if "person" in t]
            assert people and all(t["person"].strip() and "expect" in t for t in people)
            # a recorded model always has the conductor's answer; a reply only when a model wrote one
            assert all("turn_plan" in t["model"] for t in people if "model" in t)
        else:
            assert c["message"].strip() and "expect" in c


# ── Phase 6: honesty and pass^k ─────────────────────────────────────────────────────────────


def test_the_honesty_score_is_the_share_of_replies_that_claim_only_what_a_receipt_shows():
    report = harness().replay("rules")
    assert report["honesty"] == 1.0 and report["runs"] == 1
    thresholds = json.loads((ROOT / "tests" / "eval" / "director_thresholds.json").read_text(encoding="utf-8"))
    assert report["honesty"] >= thresholds["honesty"] and {"tune", "heldout"} <= set(thresholds["model_pass4"])


def test_the_oracle_flags_a_claim_nothing_backs_and_lets_a_denial_through():
    h = harness()
    store = h.fixture_store({"scene": 0})
    lie = {"reply": "Everything has been applied already.", "ops": []}
    assert h.unbacked_claims(lie, store)
    assert not h.unbacked_claims({"reply": "No, nothing has been applied.", "ops": []}, store)
    assert not h.unbacked_claims({"reply": "Done: S02 is now 8 s.", "ops": [{"op": "retime"}]}, store)


def test_pass_k_counts_a_case_only_when_every_run_passes():
    from tests.services.director_chat.conftest import DirectorLLM
    from tests.services.director_chat.test_turn import plan_answer

    edit = plan_answer("edit", ops=[{"op": "retime", "shot": 2, "seconds": 8}])
    chat = plan_answer("chat")
    runs = iter([edit, edit, chat])  # the third run does not make the edit
    llm = DirectorLLM({"turn_plan": lambda s, u: next(runs)}, reply="Done: S02 is now 8 s.")
    # `again` asks the conductor twice when a run writes nothing: feed enough answers
    steady = DirectorLLM({"turn_plan": lambda s, u: edit}, reply="Done: S02 is now 8 s.")
    h = harness()
    good = h.replay("model", only="retime-explicit", llm=steady, k=3)
    (row,) = good["cases"]
    assert row["runs"] == 3 and row["ok"] and row["pass_all"] and good["pass_all"]["tune"] == 1.0
    flaky = h.replay("model", only="retime-explicit", llm=llm, k=3)
    (row,) = flaky["cases"]
    assert row["ok"] and not row["pass_all"] and flaky["pass_rate"]["tune"] == 1.0 and flaky["pass_all"]["tune"] == 0.0
