"""frame_render, plan/2026-11-01: only the people the camera SEES are attached and named; a painted
frame carries checks (a missing sheet, a vision model's look at it)."""
from __future__ import annotations

import copy
from uuid import uuid4

from frame_render.app.handler import inspector
from frame_render.engine import inspect, pipeline
from frame_render.runtime.config import Config

from contracts.producer import Pins
from tests.services.fakes import FakeJobs
from tests.services.frame_render.conftest import RECOMMENDED, FakePainter, FakeStore
from tests.services.frame_render.test_frame_render import payload
from tests.services.production_fixture import ANUDI, FATHER, PHONE_CANON, phone_scene

IR = {"setting": "the stall", "lighting": "open shade",
      "beats": [{"time": "0-3s", "camera": "", "director_line": "", "action": "smiles"}],
      "first_frame": {"composition": "Anudi in a 3/4 single at the stall", "subjects": ["Anudi smiling"],
                      "setting": "the stall", "lighting": "open shade"}}


def phone_store(*, father_sheet: bool = True, anudi_sheet: bool = True) -> FakeStore:
    store = FakeStore()
    store.scene_row, store.line_rows, shots = phone_scene()
    for s in shots:
        s.update(ir=IR, design={"recommended": RECOMMENDED}, camera_overrides={})
    store.shot_rows = {s["id"]: s for s in shots}
    canon = copy.deepcopy(PHONE_CANON)
    sheets = {"C01": True, "C02": anudi_sheet, "C03": father_sheet, "L01": True}
    for c in canon:
        c["current"].update(id=str(uuid4()), reference_assets=[{"path": f"p/{c['code']}.png"}] if sheets[c["code"]]
                            else [])
    store.canon_rows = canon
    return store


def paint_call(store: FakeStore, look: inspect.Inspector | None = None) -> tuple[dict, dict]:
    shot = sorted(store.shot_rows.values(), key=lambda s: s["number"])[1]
    fid = store.add_frame(shot["id"])
    paint = FakePainter()
    pipeline.run(payload(frame_ids=[fid]), store, FakeJobs(), paint, look)
    return paint.calls[0], store.frame_rows[fid]


def test_the_caller_is_never_attached_or_named():
    call, frame = paint_call(phone_store())
    assert call["references"] == ["the character sheet for Anudi",
                                  "the location plate for Kasun's Food Three-Wheeler"]
    prompt = call["prompt"]
    assert "character sheet for Anudi's Father" not in prompt and "navy polo" not in prompt
    assert "People: Anudi: mid 20s" in prompt and "| Anudi's Father" not in prompt
    assert ("Anudi's Father is not in this place and not in the frame (heard through the phone held by Anudi, "
            "thin and compressed like a real call).") in prompt
    assert frame["reference_ids"] == [ANUDI, frame["reference_ids"][1]] and FATHER not in frame["reference_ids"]
    assert FATHER in Pins.model_validate(frame["pins"]).canon, "his card still pins the shot (his voice)"
    assert frame["checks"] == [], "no inspector, no sheet missing: nothing to say"


def test_a_person_can_still_put_him_in_the_shot():
    store = phone_store()
    shot = sorted(store.shot_rows.values(), key=lambda s: s["number"])[1]
    shot["person_edits"] = {"cast": {"add": [FATHER], "remove": []}}
    call, _ = paint_call(store)
    assert "the character sheet for Anudi's Father" in call["references"]


def test_an_on_screen_person_without_a_sheet_is_flagged():
    _, frame = paint_call(phone_store(anudi_sheet=False))
    assert {"label": "No reference sheet · Anudi", "tone": "advisory"} in frame["checks"]


def test_the_vision_check_compares_the_picture_with_the_shot():
    asked: list[str] = []

    def look(data: bytes, mime: str, system: str, user: str, schema: dict) -> dict:
        asked.append(user)
        return {"main_people": 2, "unexpected_person": True, "matches": False,
                "problems": ["an older man stands beside her"]}

    _, frame = paint_call(phone_store(), look)
    assert "MAIN PEOPLE WHO SHOULD BE VISIBLE:\n- Anudi" in asked[0]
    assert "PEOPLE WHO MUST NOT BE VISIBLE:\n- Anudi's Father (heard through the phone" in asked[0]
    assert "Anudi in a 3/4 single at the stall" in asked[0]
    assert frame["checks"] == [{"label": "2 people in frame, expected 1", "tone": "advisory"},
                               {"label": "Shows someone who is only heard", "tone": "advisory"},
                               {"label": "Differs · an older man stands beside her", "tone": "advisory"}]

    _, ok = paint_call(phone_store(), lambda *a: {"main_people": 1, "unexpected_person": False, "matches": True,
                                                  "problems": []})
    assert ok["checks"] == [{"label": "Frame matches the shot", "tone": "pass"}]

    def broken(*a):
        raise RuntimeError("vision down")

    _, quiet = paint_call(phone_store(), broken)
    assert quiet["status"] == "done" and quiet["checks"] == [], "a failed look never fails the frame"


def test_the_openai_inspector_sends_the_picture_and_records_usage():
    from types import SimpleNamespace

    sent: dict = {}

    def create(**kw):
        sent.update(kw)
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content='{"main_people": 1}'))],
                               usage=SimpleNamespace(prompt_tokens=50, completion_tokens=5))

    client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))
    usage: list[dict] = []
    store = SimpleNamespace(record_usage=usage.append)
    config = Config("u", "k", "sk", "gpt-image-2", "medium", "", "", vision_model="gpt-5-mini")
    look = inspector(config, payload(), store, client)  # type: ignore[arg-type]
    assert look is not None and look(b"png", "image/png", "sys", "user", {"type": "object"}) == {"main_people": 1}
    image_part = sent["messages"][1]["content"][1]
    assert image_part["image_url"]["url"].startswith("data:image/png;base64,")
    assert sent["response_format"]["json_schema"]["strict"] is True
    assert usage[0]["phase"] == "frame_render.vision" and usage[0]["input_tokens"] == 50
    off = Config("u", "k", "sk", "gpt-image-2", "medium", "", "", vision_model="")
    assert inspector(off, payload(), store, client) is None  # type: ignore[arg-type]


def test_a_database_without_the_checks_column_still_records_the_frame():
    import httpx
    from frame_render.runtime.store import Store

    class Rest:
        def __init__(self) -> None:
            self.patches: list[dict] = []

        def patch(self, table: str, params: dict, fields: dict) -> None:
            if "checks" in fields:
                request = httpx.Request("PATCH", "http://db/first_frames")
                raise httpx.HTTPStatusError("no column", request=request,
                                            response=httpx.Response(400, request=request))
            self.patches.append(fields)

    rest = Rest()
    Store(rest).finish_frame("f1", {"status": "done", "storage_path": "p.png", "checks": []})  # type: ignore[arg-type]
    assert rest.patches == [{"status": "done", "storage_path": "p.png"}]
