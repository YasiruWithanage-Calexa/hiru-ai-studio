"""Screen 3d: the Production panel — designs, a person's camera, first frames, the prompt lock,
and staleness when the shot or a canon card changes upstream."""
from __future__ import annotations

import asyncio
from uuid import UUID, uuid4

import pytest

from api.services.production import NOT_APPROVED, scene_states
from api.workers import task_manager
from tests.api.conftest import World
from tests.api.test_scenes import seed_scene, url

RECOMMENDED = {"framing": "Medium shot", "angle": "Eye level", "lens": "35mm", "aperture": "f/2.8",
               "movement": "Dolly in", "speed": "Slow", "axis": "Side A · left to right",
               "lighting": "Dawn, soft ambient"}


@pytest.fixture
def fired(monkeypatch: pytest.MonkeyPatch) -> list[dict]:
    calls: list[dict] = []
    monkeypatch.setattr(task_manager, "_fire_local",
                        lambda u, payload: calls.append({"url": u, **payload.model_dump(mode="json")}))
    return calls


def approved_scene(world: World) -> dict:
    s = seed_scene(world)
    s["scene"]["status"] = "approved"
    return s


def states(world: World, s: dict):  # type: ignore[no-untyped-def]
    r = world.repos

    async def go():  # type: ignore[no-untyped-def]
        shots = await r.shots.list(world.production, UUID(s["scene"]["id"]))
        ids = [str(x["id"]) for x in shots]
        return scene_states(s["scene"], shots, await r.lines.list(UUID(s["scene"]["id"])),
                            await r.canon.list(world.production), await r.frames.list_for_shots(ids),
                            await r.prompts.latest_for_shots(ids))
    return asyncio.run(go())


def design(world: World, s: dict) -> None:
    """What shot_producer writes: the IR and a design pinned to the shot as it is now."""
    for st in states(world, s):
        world.repos.shots.rows[st.id].update(  # type: ignore[attr-defined]
            ir={"setting": "the kitchen", "first_frame": {"composition": "Kamala at the stove"}, "beats": [{}]},
            design={"recommended": RECOMMENDED, "rationale": "A slow push builds it.", "planner": "model",
                    "pins": st.pins.model_dump(), "designed_at": "2026-10-24T00:00:00+00:00"})


def finish_frames(world: World, s: dict, frame_ids: list[str]) -> None:
    """What frame_render writes: done, stored, pinned to the shot as it is now."""
    pins = {st.id: st.pins.model_dump() for st in states(world, s)}
    for fid in frame_ids:
        row = world.repos.frames.rows[fid]  # type: ignore[attr-defined]
        row.update(status="done", storage_path=f"p/{row['shot_id']}/{fid}.png", pins=pins[row["shot_id"]])


def shot_url(world: World, s: dict, n: int, tail: str = "") -> str:
    return url(world, f"/shots/{s['shots'][n]['id']}{tail}")


# ── reading ────────────────────────────────────────────────────────────────────────────────


def test_the_panel_before_anything_is_made(world: World):
    s = seed_scene(world)
    r = world.client.get(url(world, f"/scenes/{s['scene']['id']}/production"), headers=world.headers(world.reviewer))
    assert r.status_code == 200, r.text
    v = r.json()
    assert not v["approved"] and v["aspect_ratio"] == "16:9" and len(v["shots"]) == 4
    shot = v["shots"][1]
    assert shot["code"] == "S02" and shot["design"]["state"] == "missing"
    assert shot["camera"]["recommended"]["framing"] == "Medium shot", "the director's size, before any design"
    assert shot["camera"]["recommended"]["lighting"] == "Dawn, soft ambient"
    assert shot["prompt_lock"] == {"locked": True, "reason": NOT_APPROVED}
    assert shot["lines"][0]["speaker"] == "Nimal" and shot["frames"] == [] and shot["prompt"] is None
    assert v["shots"][0]["checks"][0] == {"label": "Establishes axis · Side A", "tone": "pass", "code": "axis",
                                          "waived": False}
    assert {"label": "Axis matches S01", "tone": "pass", "code": "axis", "waived": False} in v["shots"][1]["checks"]
    assert world.client.get(f"/v1/productions/{world.other_production}/shots/{s['shots'][0]['id']}",
                            headers=world.headers(world.admin)).status_code == 404
    assert world.client.get(shot_url(world, s, 0), headers=world.headers(world.outsider)).status_code == 404


def test_production_work_needs_an_approved_scene_and_the_right_role(world: World, fired: list[dict]):
    s = seed_scene(world)
    sid = s["scene"]["id"]
    crew = world.headers(world.crew)
    assert world.client.post(url(world, f"/scenes/{sid}/design"), json={}, headers=crew).status_code == 409
    assert world.client.post(shot_url(world, s, 0, "/frames"), json={}, headers=crew).json()["detail"] == NOT_APPROVED
    s["scene"]["status"] = "approved"
    for who in (world.writer, world.reviewer):
        h = world.headers(who)
        assert world.client.post(url(world, f"/scenes/{sid}/design"), json={}, headers=h).status_code == 403
        assert world.client.post(shot_url(world, s, 0, "/frames"), json={}, headers=h).status_code == 403
        assert world.client.patch(shot_url(world, s, 0, "/camera"), json={"lens": "85mm"}, headers=h).status_code == 403
    r = world.client.post(url(world, f"/scenes/{sid}/design"), json={"force": True}, headers=crew)
    assert r.status_code == 202, r.text
    assert fired[0]["kind"] == "shot_produce" and fired[0]["url"].endswith(":8207/")
    assert fired[0]["state"] == {"mode": "design", "scene_ids": [sid], "force": True}


# ── frames ─────────────────────────────────────────────────────────────────────────────────


def test_frames_chain_a_design_when_one_is_missing(world: World, fired: list[dict]):
    s = approved_scene(world)
    r = world.client.post(shot_url(world, s, 1, "/frames"), json={"count": 2}, headers=world.headers(world.crew))
    assert r.status_code == 202, r.text
    body = r.json()
    assert len(body["frame_ids"]) == 2
    sent = fired[0]
    assert sent["kind"] == "shot_produce" and sent["pipeline"] == ["shot_produce", "frame_render"]
    assert sent["state"] == {"frame_ids": body["frame_ids"], "mode": "design", "shot_ids": [s["shots"][1]["id"]]}
    rows = world.repos.frames.rows  # type: ignore[attr-defined]
    assert all(rows[f]["status"] == "queued" and rows[f]["job_id"] == body["job_id"] for f in body["frame_ids"])
    view = world.client.get(shot_url(world, s, 1), headers=world.headers(world.reviewer)).json()
    assert [f["label"] for f in view["frames"]] == ["First frame 1", "First frame 2"]
    assert all(f["url"] is None and f["status"] == "queued" for f in view["frames"])

    design(world, s)
    r = world.client.post(shot_url(world, s, 1, "/frames"), json={}, headers=world.headers(world.crew))
    assert fired[1]["kind"] == "frame_render" and fired[1]["pipeline"] == ["frame_render"], "designed: frames only"
    assert fired[1]["url"].endswith(":8208/")


def test_scene_frames_skip_shots_that_have_one_and_carried_shots(world: World, fired: list[dict]):
    s = approved_scene(world)
    design(world, s)
    world.repos.shots.rows[s["shots"][2]["id"]].update(camera_link="continuous",  # type: ignore[attr-defined]
                                                       frame_strategy="carry_last_frame")
    r = world.client.post(shot_url(world, s, 2, "/frames"), json={}, headers=world.headers(world.crew))
    assert r.status_code == 409 and "S02's take" in r.json()["detail"]
    first = world.client.post(shot_url(world, s, 0, "/frames"), json={}, headers=world.headers(world.crew)).json()
    finish_frames(world, s, first["frame_ids"])
    world.client.post(url(world, f"/frames/{first['frame_ids'][0]}/accept"), headers=world.headers(world.crew))
    r = world.client.post(url(world, f"/scenes/{s['scene']['id']}/frames"), json={}, headers=world.headers(world.crew))
    assert r.status_code == 202
    shots = {world.repos.frames.rows[f]["shot_id"] for f in r.json()["frame_ids"]}  # type: ignore[attr-defined]
    assert shots == {s["shots"][1]["id"], s["shots"][3]["id"]}


def test_accepting_a_frame_unlocks_the_prompt(world: World, fired: list[dict]):
    s = approved_scene(world)
    design(world, s)
    crew = world.headers(world.crew)
    ids = world.client.post(shot_url(world, s, 1, "/frames"), json={"count": 2}, headers=crew).json()["frame_ids"]
    assert world.client.post(url(world, f"/frames/{ids[0]}/accept"), headers=crew).status_code == 409, "not finished"
    assert world.client.post(shot_url(world, s, 1, "/prompt"), headers=crew).json()["detail"] == \
        "Accept a first frame to unlock the prompt."
    finish_frames(world, s, ids)
    v = world.client.post(url(world, f"/frames/{ids[0]}/accept"), headers=crew).json()
    assert v["accepted_frame_id"] == ids[0] and v["status"] == "frame" and not v["prompt_lock"]["locked"]
    assert v["frames"][0]["url"].startswith("http://localhost:8000/files/"), "a ticket, never a storage URL"
    v = world.client.post(url(world, f"/frames/{ids[1]}/accept"), headers=crew).json()
    assert v["accepted_frame_id"] == ids[1] and [f["accepted"] for f in v["frames"]] == [False, True], "picking is free"

    r = world.client.post(shot_url(world, s, 1, "/prompt"), headers=crew)
    assert r.status_code == 202
    assert fired[-1]["state"] == {"mode": "prompt", "shot_ids": [s["shots"][1]["id"]]}
    assert world.client.post(shot_url(world, s, 1, "/prompt"), headers=world.headers(world.writer)).status_code == 403

    v = world.client.post(url(world, f"/frames/{ids[1]}/reject"), json={"reason": "wrong saree"}, headers=crew).json()
    assert v["accepted_frame_id"] is None and v["status"] == "draft" and v["prompt_lock"]["locked"]
    assert v["frames"][1]["rejected_reason"] == "wrong saree"


def _accept_one(world: World, s: dict, n: int) -> str:
    crew = world.headers(world.crew)
    fid = world.client.post(shot_url(world, s, n, "/frames"), json={}, headers=crew).json()["frame_ids"][0]
    finish_frames(world, s, [fid])
    assert world.client.post(url(world, f"/frames/{fid}/accept"), headers=crew).status_code == 200
    return fid


def _store_prompt(world: World, s: dict, n: int, fid: str | None) -> None:
    st = next(x for x in states(world, s) if x.id == s["shots"][n]["id"])
    world.repos.prompts.add(production_id=str(world.production), shot_id=st.id, version=1,  # type: ignore[attr-defined]
                            sections=[{"id": "camera", "title": "Camera", "segments": [{"text": "Dolly in."}]},
                                      {"id": "action", "title": "Action",
                                       "segments": [{"text": "He says, \""}, {"sinhala": "අම්මේ"}, {"text": "\""}]}],
                            prose="CAMERA\nDolly in.", model="Veo 3.1 · 4 s · 16:9",
                            checks=[{"label": "One visible speaker", "tone": "pass"}], frame_id=fid,
                            pins=st.pins.model_dump(), camera=st.camera.model_dump())


def test_a_shot_edit_flags_frames_and_prompt_out_of_date(world: World, fired: list[dict]):
    s = approved_scene(world)
    design(world, s)
    fid = _accept_one(world, s, 1)
    _store_prompt(world, s, 1, fid)
    v = world.client.get(shot_url(world, s, 1), headers=world.headers(world.reviewer)).json()
    assert v["prompt"]["version"] == 1 and not v["prompt"]["stale"] and v["design"]["state"] == "current"
    assert v["prompt"]["sections"][1]["segments"][1] == {"sinhala": "අම්මේ"}
    latest = world.client.get(shot_url(world, s, 1, "/prompt"), headers=world.headers(world.reviewer)).json()
    assert latest["version"] == 1

    # The director unapproves, makes S02 six seconds, approves again: nothing is redone.
    world.repos.shots.rows[s["shots"][1]["id"]]["version"] += 1  # type: ignore[attr-defined]
    v = world.client.get(shot_url(world, s, 1), headers=world.headers(world.reviewer)).json()
    assert v["design"]["state"] == "stale" and v["frames"][0]["stale"]
    assert v["prompt"]["stale"] and "The shot changed" in v["prompt"]["stale_reasons"][0]
    assert v["prompt_lock"]["locked"] and "no longer matches" in v["prompt_lock"]["reason"]
    assert world.client.post(url(world, f"/frames/{fid}/accept"), headers=world.headers(world.crew)).status_code == 409


def test_a_new_canon_card_flags_the_shots_it_is_in(world: World, fired: list[dict]):
    s = approved_scene(world)
    kamala = s["kamala"]["id"]
    asyncio.run(world.repos.canon.add_version(UUID(kamala), {"entity_id": kamala, "version": 1, "card": {}}))
    design(world, s)
    _accept_one(world, s, 3)  # Kamala speaks in S04
    _accept_one(world, s, 1)  # Nimal alone in S02
    asyncio.run(world.repos.canon.add_version(UUID(kamala), {"entity_id": kamala, "version": 2, "card": {}}))
    v = world.client.get(url(world, f"/scenes/{s['scene']['id']}/production"), headers=world.headers(world.crew)).json()
    s04, s02 = v["shots"][3], v["shots"][1]
    assert s04["frames"][0]["stale_reasons"] == ["C01 Kamala has a new card (v2; this used v1)."]
    assert s04["design"]["state"] == "stale" and s04["prompt_lock"]["locked"]
    assert not s02["frames"][0]["stale"] and not s02["prompt_lock"]["locked"]
    assert "C01 v2" in s04["canon_refs"]


def test_a_persons_camera_and_back(world: World, fired: list[dict]):
    s = approved_scene(world)
    design(world, s)
    fid = _accept_one(world, s, 1)
    _store_prompt(world, s, 1, fid)
    crew = world.headers(world.crew)
    r = world.client.patch(shot_url(world, s, 1, "/camera"), json={"lens": "85mm", "axis": "Side B · right to left"},
                           headers=crew)
    assert r.status_code == 200, r.text
    v = r.json()
    assert v["camera"]["current"]["lens"] == "85mm" and v["camera"]["recommended"]["lens"] == "35mm"
    assert sorted(v["camera"]["changed"]) == ["axis", "lens"]
    assert v["camera"]["storyboard_note"] == "85mm · slow dolly in"
    assert "85mm lens" in v["frame_prompt"]
    assert v["prompt"]["stale_reasons"] == ["The camera settings changed."]
    assert any(c["label"].startswith("Crosses the axis") for c in v["checks"])
    assert world.client.patch(shot_url(world, s, 1, "/camera"), json={"lens": "300mm"}, headers=crew).status_code == 422
    v = world.client.patch(shot_url(world, s, 1, "/camera"), json={"lens": None, "axis": "Side A · left to right"},
                           headers=crew).json()
    assert v["camera"]["changed"] == [] and not v["prompt"]["stale"]


def test_scene_prompts_take_every_unlocked_shot(world: World, fired: list[dict]):
    s = approved_scene(world)
    design(world, s)
    crew = world.headers(world.crew)
    assert world.client.post(url(world, f"/scenes/{s['scene']['id']}/prompts"), headers=crew).status_code == 409
    _accept_one(world, s, 0)
    _accept_one(world, s, 3)
    r = world.client.post(url(world, f"/scenes/{s['scene']['id']}/prompts"), headers=crew)
    assert r.status_code == 202
    assert fired[-1]["state"]["shot_ids"] == [s["shots"][0]["id"], s["shots"][3]["id"]]


def test_reference_sheets_are_asked_for_by_canon_editors(world: World, fired: list[dict]):
    s = seed_scene(world)
    kamala = s["kamala"]["id"]
    path = f"/v1/productions/{world.production}/canon/{kamala}/reference-sheet"
    assert world.client.post(path, headers=world.headers(world.director)).status_code == 409, "no card yet"
    asyncio.run(world.repos.canon.add_version(UUID(kamala), {"entity_id": kamala, "version": 1, "card": {}}))
    assert world.client.post(path, headers=world.headers(world.crew)).status_code == 403
    r = world.client.post(path, headers=world.headers(world.director))
    assert r.status_code == 202 and fired[-1]["state"] == {"reference_entity_id": kamala}
    world.repos.canon.version_rows[world.repos.canon.rows[kamala]["current_version_id"]]["reference_assets"] = [  # type: ignore[attr-defined]
        {"path": f"{world.production}/{kamala}/sheet.png"}]
    entity = world.client.get(f"/v1/productions/{world.production}/canon/{kamala}",
                              headers=world.headers(world.reviewer)).json()
    assert entity["reference_sheet_url"].startswith("http://localhost:8000/files/")
    assert "sheet.png" not in entity["reference_sheet_url"]
    assert world.client.post(f"/v1/productions/{world.production}/canon/{uuid4()}/reference-sheet",
                             headers=world.headers(world.director)).status_code == 404


def test_a_person_uploads_their_own_frame(world: World, fired: list[dict]):
    s = approved_scene(world)
    design(world, s)
    crew = world.headers(world.crew)
    png = b"\x89PNG\r\n\x1a\n" + b"\0" * 64
    r = world.client.post(shot_url(world, s, 1, "/frames/upload"), files={"file": ("mine.png", png, "image/png")},
                          headers=crew)
    assert r.status_code == 201, r.text
    frame = r.json()["frames"][0]
    assert frame["status"] == "done" and frame["url"].startswith("http://localhost:8000/files/") and not frame["stale"]
    assert ("frames", f"{world.production}/{s['shots'][1]['id']}/{frame['id']}.png") in world.repos.storage.objects  # type: ignore[attr-defined]
    v = world.client.post(url(world, f"/frames/{frame['id']}/accept"), headers=crew).json()
    assert not v["prompt_lock"]["locked"], "an uploaded frame unlocks the prompt like a painted one"
    gif = {"file": ("x.png", b"GIF89a....", "image/png")}
    r = world.client.post(shot_url(world, s, 1, "/frames/upload"), files=gif, headers=crew)
    assert r.status_code == 422, "the content decides, not the name"
    assert world.client.post(shot_url(world, s, 1, "/frames/upload"), files={"file": ("x.png", png, "image/png")},
                             headers=world.headers(world.writer)).status_code == 403


# ── what a person set on a shot (the director chat writes `person_edits`) ───────────────────


def marks(world: World, s: dict, n: int, **edits) -> None:
    world.repos.shots.rows[s["shots"][n]["id"]]["person_edits"] = edits  # type: ignore[attr-defined]


def panel(world: World, s: dict) -> list[dict]:
    r = world.client.get(url(world, f"/scenes/{s['scene']['id']}/production"), headers=world.headers(world.reviewer))
    assert r.status_code == 200, r.text
    return r.json()["shots"]


def test_canon_chips_follow_what_a_person_added_or_took_out(world: World):
    s = seed_scene(world)
    house = str(s["house"]["id"])
    nimal = next(c["id"] for c in world.repos.canon.rows.values() if c["code"] == "C02")  # type: ignore[attr-defined]
    base = panel(world, s)
    assert base[1]["canon_refs"][0].startswith("C02") and any(ref.startswith("L01") for ref in base[1]["canon_refs"])
    marks(world, s, 1, cast={"add": [], "remove": [house, str(nimal)]})
    taken = panel(world, s)[1]
    assert taken["canon_refs"] == [] and panel(world, s)[0]["canon_refs"] == base[0]["canon_refs"]  # only that shot
    kamala = str(s["kamala"]["id"])
    marks(world, s, 0, cast={"add": [kamala], "remove": []})
    added = panel(world, s)[0]["canon_refs"]
    assert any(ref.startswith("C01") for ref in added) and any(ref.startswith("L01") for ref in added)
    names = [c.name for c in states(world, s)[0].cast]
    assert "Kamala" in names  # a person added Kamala, so her wardrobe check applies to the shot


def test_a_shot_made_before_a_chip_changed_is_out_of_date(world: World):
    s = approved_scene(world)
    design(world, s)
    assert panel(world, s)[1]["design"]["state"] == "current"
    marks(world, s, 1, cast={"add": [], "remove": [str(s["house"]["id"])]})
    shot = panel(world, s)[1]
    assert shot["design"]["state"] == "stale"
    assert "Different people or place in the shot." in shot["design"]["stale_reasons"]


def test_an_ignored_advisory_stays_in_the_list_marked_and_a_pass_cannot_be_ignored(world: World):
    s = seed_scene(world)
    wide = world.repos.shots.rows[s["shots"][1]["id"]]  # type: ignore[attr-defined]
    wide.update(framing="WIDE", sound_mode="dialogue")
    hard = next(c for c in panel(world, s)[1]["checks"] if c["code"] == "speaker_size")
    assert hard["tone"] == "advisory" and hard["waived"] is False
    marks(world, s, 1, waived_checks=["speaker_size", "axis"])
    shown = {c["code"]: c for c in panel(world, s)[1]["checks"] if c["code"] in ("speaker_size", "axis")}
    assert shown["speaker_size"]["waived"] is True and shown["speaker_size"]["label"] == hard["label"]
    assert shown["axis"]["tone"] == "pass" and shown["axis"]["waived"] is False  # nothing to ignore
    assert panel(world, s)[0]["checks"][0]["waived"] is False  # only that shot


def test_the_dop_note_replaces_the_dps_reason_and_clearing_it_brings_it_back(world: World):
    s = approved_scene(world)
    design(world, s)
    v = panel(world, s)[1]["design"]
    assert v["rationale"] == "A slow push builds it." and v["note_by_person"] is False
    marks(world, s, 1, dop_note="Hold on the pan; keep the light warm.")
    v = panel(world, s)[1]["design"]
    assert v["rationale"] == "Hold on the pan; keep the light warm." and v["note_by_person"] is True
    assert v["state"] == "current"  # a note is not a change to what the shot is made against
    marks(world, s, 1)
    assert panel(world, s)[1]["design"]["rationale"] == "A slow push builds it."


def test_a_note_shows_even_before_any_design(world: World):
    s = seed_scene(world)
    marks(world, s, 0, dop_note="Open on the radio.")
    first = panel(world, s)[0]
    assert first["design"]["state"] == "missing" and first["design"]["rationale"] == "Open on the radio."
    assert first["design"]["note_by_person"] is True


def test_damaged_person_edits_read_as_none(world: World):
    s = seed_scene(world)
    world.repos.shots.rows[s["shots"][0]["id"]]["person_edits"] = {"cast": "nonsense", "dop_note": 5}  # type: ignore[attr-defined]
    assert panel(world, s)[0]["design"]["note_by_person"] is False
