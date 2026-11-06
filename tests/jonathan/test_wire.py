"""The wire shape (plan/2026-11-06b §4.1): the cinematic lab's plan, what moves shots about (renumbering, removing,
the sequences' spans) and the JSON schema the author and the reviser are held to."""
from __future__ import annotations

from contracts.jonathan.stored import Removed, StoredPlan
from contracts.jonathan.wire import FRAMING, JonathanWire, card_size
from hiru_ai.agents.jonathan.jonathan_author import agent
from hiru_ai.agents.jonathan.jonathan_revise import agent as reviser
from hiru_ai.steps.serialize.schema import get_schema
from tests.jonathan import gold


def test_the_plan_is_written_treatment_first_then_sequences_then_shots():
    assert list(JonathanWire.model_fields) == ["treatment", "sequences", "shots", "added", "staging", "end_state"]
    shot_fields = list(gold.phone_call().shots[0].model_dump())
    assert shot_fields[:5] == ["n", "sequence", "blocks", "lines", "over"]
    assert {"angle", "lens", "use_s"} <= set(shot_fields)


def test_renumbering_keeps_list_order_when_the_models_numbers_repeat():
    plan = gold.phone_call()
    shots = [s.model_copy(update={"n": 1}) for s in plan.shots]
    out = JonathanWire.model_validate({**plan.model_dump(), "shots": [s.model_dump() for s in shots]}).renumbered()
    assert [s.n for s in out.shots] == list(range(1, 16))


def test_removing_a_shot_moves_its_additions_and_writes_the_sequences_spans_again():
    plan = gold.phone_call()
    out = plan.without({3})
    assert len(out.shots) == 14 and [a.shot for a in out.added] == [8, 12]
    spans = {q.id: (q.shots.first, q.shots.last) for q in out.sequences}
    assert spans == {"A": (1, 2), "B": (3, 10), "C": (11, 14)}


def test_the_treatment_is_every_word_a_free_text_check_reads():
    plan = gold.phone_call()
    text = " ".join(plan.treatment_text())
    assert plan.treatment.logline in text and "Ease" in text and "warm and open" in text
    assert plan.notes == "\n".join(plan.treatment_text())


def test_a_size_of_jonathans_own_is_read_as_its_nearest_by_the_shared_parts():
    shots = {s.size: s for s in gold.phone_call().shots}
    assert shots["EWS"].framing == "WIDE" and shots["ECU"].framing == "CU" and shots["MCU"].framing == "MCU"
    assert set(FRAMING.values()) <= {"WIDE", "MS", "MCU", "CU", "TWO", "OTS", "INSERT"}
    assert card_size("EWS") == "WS" and card_size("ECU") == "CU"


def test_the_authors_schema_is_one_flat_strict_tree_with_the_clip_schema_in_place_of_the_free_ir():
    schema = agent.output_schema()
    text = str(schema)
    assert "$ref" not in text and "$defs" not in text and schema["title"] == "jonathan_plan"
    assert list(schema["properties"])[:3] == ["treatment", "sequences", "shots"]
    shot_props = schema["properties"]["shots"]["items"]["properties"]
    clip = get_schema().required_structure
    assert list(shot_props["ir"]["properties"]) == list(clip) and shot_props["ir"]["additionalProperties"] is False
    assert shot_props["take_s"]["enum"] == [4, 6, 8] and {"EWS", "ECU", "POV"} <= set(shot_props["size"]["enum"])
    assert shot_props["ir"]["required"] == list(clip)  # strict mode: every property is required
    assert reviser.output_schema() == schema  # the reviser answers the whole plan, not a patch


def test_a_stored_plan_round_trips_through_the_json_the_scene_keeps():
    stored = StoredPlan(plan=gold.phone_call(), end_state=gold.phone_call().end_state,
                        removed=[Removed(kind="reaction", after_block=9, what="x")],
                        measures=[{"key": "opens", "label": "Opens", "status": "met", "detail": "S01 EWS"}])
    loaded = StoredPlan.load(stored.data())
    assert loaded == stored and StoredPlan.load({}) is None and StoredPlan.load({"planner": "adam"}) is None
    assert StoredPlan.load({"planner": "jonathan", "plan": "garbage"}) is None
