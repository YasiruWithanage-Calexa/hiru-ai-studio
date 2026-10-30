"""frame_render: claim → paint → store → record, references in order, refusals, reference sheets."""
from __future__ import annotations

from types import SimpleNamespace
from uuid import uuid4

from frame_render.app.handler import painter
from frame_render.engine import image, pipeline
from frame_render.runtime.config import Config

from contracts.jobs import DispatchPayload, JobKind
from contracts.producer import Pins
from tests.services.fakes import FakeJobs
from tests.services.frame_render.conftest import FakePainter, FakeStore
from tests.services.production_fixture import KAMALA, PID


def payload(**state) -> DispatchPayload:
    return DispatchPayload(job_id=uuid4(), kind=JobKind.FRAME_RENDER, actor_user_id=uuid4(), production_id=PID,
                           pipeline=[JobKind.FRAME_RENDER], state=state)


def shots(store: FakeStore) -> list[dict]:
    return sorted(store.shot_rows.values(), key=lambda s: s["number"])


def test_frames_are_painted_stored_and_pinned():
    store = FakeStore()
    s1, s2 = shots(store)[0], shots(store)[1]
    ids = [store.add_frame(s1["id"]), store.add_frame(s1["id"]), store.add_frame(s2["id"])]
    paint, jobs = FakePainter(), FakeJobs()
    result = pipeline.run(payload(frame_ids=ids), store, jobs, paint)
    assert result == {"done": 3, "failed": 0, "refused": 0, "skipped": 0} and jobs.status == "done"
    f = store.frame_rows[ids[0]]
    assert f["status"] == "done" and f["storage_path"] == f"{PID}/{s1['id']}/{ids[0]}.png"
    assert store.uploads[("frames", f["storage_path"])] == b"\x89PNG fake"
    assert Pins.model_validate(f["pins"]).shot_version == s1["version"]
    # S01's action names Kamala: her sheet first, then the house plate, named by position.
    call = next(c for c in paint.calls if "Kamala" in c["prompt"] and len(c["references"]) == 2)
    assert call["references"] == ["the character sheet for Kamala", "the location plate for Kamala's house"]
    assert "image 1 is the character sheet for Kamala; image 2 is the location plate" in call["prompt"]
    assert f["reference_ids"][0] == KAMALA
    assert "Wide shot, eye level, 28mm lens at f/4" in call["prompt"] and "16:9 framing" in call["prompt"]
    assert store.audits[0]["action"] == "frames.render"


def test_a_redelivery_paints_nothing_twice():
    store = FakeStore()
    fid = store.add_frame(shots(store)[0]["id"])
    paint = FakePainter()
    pipeline.run(payload(frame_ids=[fid]), store, FakeJobs(), paint)
    result = pipeline.run(payload(frame_ids=[fid]), store, FakeJobs(), paint)
    assert result["skipped"] == 1 and len(paint.calls) == 1


def test_a_persons_camera_reaches_the_frame_and_an_unreadable_sheet_is_not_named():
    store = FakeStore(orientation="vertical")
    s1 = shots(store)[0]
    s1["camera_overrides"] = {"framing": "Close-up", "lens": "85mm"}
    store.unreadable.add("p/kamala.png")
    paint = FakePainter()
    pipeline.run(payload(frame_ids=[store.add_frame(s1["id"])]), store, FakeJobs(), paint)
    prompt = paint.calls[0]["prompt"]
    assert "Close-up" in prompt and "85mm" in prompt and "Compose it as a close-up" in prompt
    assert paint.calls[0]["references"] == ["the location plate for Kamala's house"]
    assert "image 1 is the location plate" in prompt and "character sheet" not in prompt
    assert "9:16 vertical framing" in prompt


def test_refusals_failures_and_missing_designs_are_reported_not_raised():
    store = FakeStore()
    s1 = shots(store)[0]
    refused = store.add_frame(s1["id"])
    pipeline.run(payload(frame_ids=[refused]), store, FakeJobs(), FakePainter(refuse=True))
    assert store.frame_rows[refused]["status"] == "refused" and "declined" in store.frame_rows[refused]["error"]

    failed = store.add_frame(s1["id"])
    jobs = FakeJobs()
    pipeline.run(payload(frame_ids=[failed]), store, jobs, FakePainter(fail=True))
    assert store.frame_rows[failed]["status"] == "failed"
    assert "internal" not in store.frame_rows[failed]["error"], "provider text never reaches a person"
    assert jobs.status == "done"

    bare = FakeStore(design=False)
    fid = bare.add_frame(shots(bare)[0]["id"])
    pipeline.run(payload(frame_ids=[fid]), bare, FakeJobs(), FakePainter())
    assert bare.frame_rows[fid]["error"] == pipeline.NO_DESIGN

    off = FakeStore()
    fid = off.add_frame(shots(off)[0]["id"])
    pipeline.run(payload(frame_ids=[fid]), off, FakeJobs(), None)
    assert off.frame_rows[fid]["error"] == pipeline.NOT_CONFIGURED


def test_a_regenerated_sheet_uses_the_current_layout_and_is_wide_in_a_vertical_production():
    store = FakeStore(orientation="vertical")
    store.canon_rows[0]["current"]["reference_prompt"] = "Show the same person three times: front and profile."
    paint = FakePainter()
    pipeline.run(payload(reference_entity_id=KAMALA), store, FakeJobs(), paint)
    call = paint.calls[0]
    assert call["aspect"] == "16:9" and "five panels" in call["prompt"]
    assert "three times" not in call["prompt"], "the version's stored prompt predates the new layout"


def test_a_reference_sheet_for_the_current_card():
    store = FakeStore()
    paint, jobs = FakePainter(), FakeJobs()
    result = pipeline.run(payload(reference_entity_id=KAMALA), store, jobs, paint)
    assert result["status"] == "done" and jobs.status == "done"
    assert paint.calls[0]["references"] == [] and "Character reference sheet" in paint.calls[0]["prompt"]
    _, assets = store.asset_writes[0]
    assert assets[0]["path"].startswith(f"{PID}/{KAMALA}/") and assets[1] == {"path": "p/kamala.png"}
    assert ("references", assets[0]["path"]) in store.uploads


def test_the_openai_painter_uses_edit_with_references_and_records_usage():
    sent: dict = {}

    def respond(**kw):
        sent.update(kw)
        return SimpleNamespace(data=[SimpleNamespace(b64_json="iVBORw==")],
                               usage=SimpleNamespace(input_tokens=7, output_tokens=9))

    client = SimpleNamespace(images=SimpleNamespace(edit=respond, generate=respond))
    config = Config("u", "k", "sk", "gpt-image-2", "high", "", "")
    usage: list[dict] = []
    store = SimpleNamespace(record_usage=usage.append)
    paint = painter(config, payload(), store, client)  # type: ignore[arg-type]
    assert paint is not None
    picture = paint("p", "9:16", [image.Reference("a", b"x"), image.Reference("b", b"y")])
    assert sent["size"] == "1024x1536" and [f[0] for f in sent["image"]] == ["reference-1.png", "reference-2.png"]
    assert picture.data.startswith(b"\x89PNG") and usage[0]["output_tokens"] == 9

    class Blocked(Exception):
        code = "moderation_blocked"

    def refuse(**kw):
        raise Blocked("blocked")

    client.images.generate = refuse
    try:
        paint("p", "16:9", [])
        raise AssertionError("expected a refusal")
    except image.RefusedError:
        pass
    assert painter(Config("u", "k", "", "m", "high", "", ""), payload(), store) is None  # type: ignore[arg-type]


def test_a_persons_cast_edits_choose_which_sheets_are_attached_and_the_pins():
    store = FakeStore()
    prop = {"id": str(uuid4()), "kind": "prop", "code": "P01", "name": "Brass pan", "aliases": [], "locked": False,
            "current": {"version": 1, "id": str(uuid4()), "card": {}, "wardrobe_anchor": "", "voice_pin": "",
                        "reference_assets": [{"path": "p/pan.png"}]}}
    store.canon_rows = [*store.canon_rows, prop]
    s1 = shots(store)[0]
    s1["person_edits"] = {"cast": {"add": [prop["id"]], "remove": [KAMALA]}}
    paint = FakePainter()
    pipeline.run(payload(frame_ids=[store.add_frame(s1["id"])]), store, FakeJobs(), paint)
    # no Kamala (taken out), the house plate, then the pan a person added, named by what it is
    assert paint.calls[0]["references"] == ["the location plate for Kamala's house",
                                            "the reference sheet for Brass pan"]
    pins = store.frame_rows[next(iter(store.frame_rows))]["pins"]["canon"]
    assert prop["id"] in pins and KAMALA not in pins


def add_look(store: FakeStore, **fields) -> str:
    lid = str(uuid4())
    store.look_rows[lid] = {"id": lid, "entity_id": KAMALA, "production_id": str(PID), "name": "Heiress",
                            "ranges": [{"from": 36, "to": 60}], "outfit": "maroon silk saree",
                            "hair": "smooth bun", "makeup": "", "accessories": "gold earrings, a navy cap",
                            "status": "ready", "sheet_assets": [{"path": "old.png"}], **fields}
    return lid


def test_a_look_sheet_is_painted_from_the_base_sheet_and_goes_back_to_draft():
    store = FakeStore(orientation="vertical")
    lid = add_look(store)
    paint, jobs = FakePainter(), FakeJobs()
    result = pipeline.run(payload(look_id=lid), store, jobs, paint)
    assert result == {"status": "done", "look_id": lid} and jobs.status == "done"
    call = paint.calls[0]
    assert call["aspect"] == "16:9", "a look sheet is wide, even in a vertical production"
    assert call["references"] == ["the base character sheet for Kamala"]
    assert call["pictures"] == [b"sheet:p/kamala.png"], "the base sheet is the only picture sent"
    assert "Outfit: maroon silk saree" in call["prompt"] and "gold earrings, a navy cap" in call["prompt"]
    _, assets = store.look_writes[0]
    assert assets[0]["path"].startswith(f"{PID}/{KAMALA}/looks/{lid}-") and assets[1] == {"path": "old.png"}
    assert assets[0]["kind"] == "look" and ("references", assets[0]["path"]) in store.uploads
    assert store.look_rows[lid]["status"] == "draft", "a new sheet is not the one a person approved"
    assert store.audits[0]["action"] == "canon.look_sheet_made"


def test_a_look_sheet_without_a_base_sheet_or_a_look_is_reported_not_painted():
    store = FakeStore()
    paint = FakePainter()
    missing = pipeline.run(payload(look_id=str(uuid4())), store, FakeJobs(), paint)
    assert missing["status"] == "failed" and "no longer exists" in missing["error"]
    no_base = add_look(store, entity_id=store.canon_rows[1]["id"])  # Nimal has no sheet
    result = pipeline.run(payload(look_id=no_base), store, FakeJobs(), paint)
    assert result["status"] == "failed" and "base sheet" in result["error"] and not paint.calls
    ok = add_look(store)
    store.unreadable.add("p/kamala.png")
    unreadable = pipeline.run(payload(look_id=ok), store, FakeJobs(), paint)
    assert unreadable == {"status": "failed", "error": pipeline.FAILED} and not store.look_writes


def test_a_refused_look_sheet_leaves_the_old_one():
    store = FakeStore()
    lid = add_look(store)
    result = pipeline.run(payload(look_id=lid), store, FakeJobs(), FakePainter(refuse=True))
    assert result["status"] == "refused" and not store.look_writes
    assert store.look_rows[lid]["sheet_assets"] == [{"path": "old.png"}] and store.look_rows[lid]["status"] == "ready"


# ── frames wear the look the scene uses ────────────────────────────────────────────────────


def paint_s01(store: FakeStore) -> tuple[dict, dict]:
    """→ (the painter's call for S01, the frame row)."""
    paint = FakePainter()
    fid = store.add_frame(shots(store)[0]["id"])
    pipeline.run(payload(frame_ids=[fid]), store, FakeJobs(), paint)
    return paint.calls[0], store.frame_rows[fid]


def test_the_scenes_pick_dresses_kamala_in_her_look_sheet_not_the_base_sheet():
    store = FakeStore()
    lid = add_look(store)  # Ep 36-60: not this episode, but the scene picked it
    store.scene_look_rows = [{"entity_id": KAMALA, "look_id": lid}]
    call, frame = paint_s01(store)
    assert call["references"] == ["the look sheet for Kamala", "the location plate for Kamala's house"]
    assert call["pictures"][0] == b"sheet:old.png", "the look sheet is sent, not the base sheet"
    prompt = call["prompt"]
    assert "image 1 is the look sheet for Kamala" in prompt and "A look sheet shows what that person wears" in prompt
    assert "as in their look sheet: outfit maroon silk saree; hair smooth bun; accessories gold earrings" in prompt
    assert "faded blue cotton saree" not in prompt, "the card's wardrobe gives way to the look"
    assert "plain reference outfit" not in prompt
    assert frame["reference_ids"][0] == KAMALA
    assert Pins.model_validate(frame["pins"]).looks[KAMALA].id == lid


def test_without_a_pick_the_narrowest_ready_look_of_the_episode_applies():
    store = FakeStore()
    store.episode = 44
    add_look(store)  # Heiress, Ep 36-60
    hospital = add_look(store, name="Hospital", ranges=[{"from": 44, "to": 44}], outfit="a hospital gown",
                        sheet_assets=[{"path": "hospital.png"}])
    add_look(store, name="Draft", ranges=[{"from": 44, "to": 44}], status="draft", sheet_assets=[{"path": "d.png"}])
    call, frame = paint_s01(store)
    assert call["pictures"][0] == b"sheet:hospital.png" and "outfit a hospital gown" in call["prompt"]
    assert Pins.model_validate(frame["pins"]).looks[KAMALA].id == hospital


def test_no_look_keeps_the_base_sheet_and_the_cards_wardrobe():
    store = FakeStore()
    store.episode = 5  # outside Heiress (36-60)
    add_look(store)
    picked_draft = add_look(store, name="Old", status="draft")
    store.scene_look_rows = [{"entity_id": KAMALA, "look_id": picked_draft}]  # went back to draft: no effect
    call, frame = paint_s01(store)
    assert call["references"][0] == "the character sheet for Kamala"
    assert "wearing a faded blue cotton saree" in call["prompt"] and "plain reference outfit" in call["prompt"]
    assert Pins.model_validate(frame["pins"]).looks == {}


def test_an_unreadable_look_sheet_falls_back_to_the_base_sheet_with_the_looks_wardrobe():
    store = FakeStore()
    store.scene_look_rows = [{"entity_id": KAMALA, "look_id": add_look(store)}]
    store.unreadable.add("old.png")
    call, _ = paint_s01(store)
    assert call["references"][0] == "the character sheet for Kamala"
    assert call["pictures"][0] == b"sheet:p/kamala.png" and "outfit maroon silk saree" in call["prompt"]
