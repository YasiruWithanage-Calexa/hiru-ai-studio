"""Screen 3d: the Production panel — designs, a person's camera, first frames, the prompt lock,
and staleness when the shot or a canon card changes upstream."""
from __future__ import annotations

import asyncio
from uuid import UUID, uuid4

import pytest

from api.services.production import LOCKED, scene_states
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


def open_scene(world: World) -> dict:
    """A scene that is not approved: designs, camera and frames are made now."""
    return seed_scene(world)


def locked_scene(world: World) -> dict:
    """An approved scene: the picture work is closed, video prompts and videos still run."""
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
    assert shot["prompt_lock"] == {"locked": True, "reason": "Accept a first frame to unlock the prompt."}
    assert shot["lines"][0]["speaker"] == "Nimal" and shot["frames"] == [] and shot["prompt"] is None
    assert v["shots"][0]["checks"][0] == {"label": "Establishes axis · Side A", "tone": "pass", "code": "axis",
                                          "waived": False}
    assert {"label": "Axis matches S01", "tone": "pass", "code": "axis", "waived": False} in v["shots"][1]["checks"]
    assert world.client.get(f"/v1/productions/{world.other_production}/shots/{s['shots'][0]['id']}",
                            headers=world.headers(world.admin)).status_code == 404
    assert world.client.get(shot_url(world, s, 0), headers=world.headers(world.outsider)).status_code == 404


def test_picture_work_needs_an_unlocked_scene_and_the_right_role(world: World, fired: list[dict]):
    s = open_scene(world)
    sid = s["scene"]["id"]
    crew = world.headers(world.crew)
    for who in (world.writer, world.reviewer):
        h = world.headers(who)
        assert world.client.post(url(world, f"/scenes/{sid}/design"), json={}, headers=h).status_code == 403
        assert world.client.post(shot_url(world, s, 0, "/frames"), json={}, headers=h).status_code == 403
        assert world.client.patch(shot_url(world, s, 0, "/camera"), json={"lens": "85mm"}, headers=h).status_code == 403
    r = world.client.post(url(world, f"/scenes/{sid}/design"), json={"force": True}, headers=crew)
    assert r.status_code == 202, r.text
    assert fired[0]["kind"] == "shot_produce" and fired[0]["url"].endswith(":8207/")
    assert fired[0]["state"] == {"mode": "design", "scene_ids": [sid], "force": True}


def test_a_locked_scene_closes_the_picture_work_but_not_the_video_prompt(world: World, fired: list[dict]):
    s = open_scene(world)
    sid = s["scene"]["id"]
    crew = world.headers(world.crew)
    design(world, s)
    _accept_one(world, s, 0)  # the picture work is done, then the scene is approved
    fired.clear()
    s["scene"]["status"] = "approved"
    for call in (
        world.client.post(url(world, f"/scenes/{sid}/design"), json={}, headers=crew),
        world.client.post(url(world, f"/scenes/{sid}/frames"), json={}, headers=crew),
        world.client.post(shot_url(world, s, 0, "/frames"), json={}, headers=crew),
        world.client.patch(shot_url(world, s, 0, "/camera"), json={"lens": "85mm"}, headers=crew),
        world.client.patch(url(world, f"/scenes/{sid}/coverage"), json={"axis": "x"}, headers=crew),
    ):
        assert call.status_code == 409 and call.json()["detail"] == LOCKED
    assert not fired, "nothing was started"
    r = world.client.post(shot_url(world, s, 0, "/prompt"), json={}, headers=crew)
    assert r.status_code == 202, r.text
    assert fired[-1]["kind"] == "shot_produce" and fired[-1]["state"]["mode"] == "prompt"
    r = world.client.post(url(world, f"/scenes/{sid}/prompts"), json={}, headers=crew)
    assert r.status_code == 202, r.text


# ── frames ─────────────────────────────────────────────────────────────────────────────────


def test_frames_chain_a_design_when_one_is_missing(world: World, fired: list[dict]):
    s = open_scene(world)
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
    s = open_scene(world)
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


def test_scene_drafts_skip_shots_that_have_a_current_draft_and_carried_shots(world: World, fired: list[dict]):
    s = open_scene(world)
    design(world, s)
    crew = world.headers(world.crew)
    world.repos.shots.rows[s["shots"][2]["id"]].update(camera_link="continuous",  # type: ignore[attr-defined]
                                                       frame_strategy="carry_last_frame")
    one = world.client.post(shot_url(world, s, 0, "/frames"), json={"stage": "draft"}, headers=crew).json()
    r = world.client.post(url(world, f"/scenes/{s['scene']['id']}/frames"), json={"stage": "draft"}, headers=crew)
    assert r.status_code == 202
    rows = world.repos.frames.rows  # type: ignore[attr-defined]
    assert {rows[f]["shot_id"] for f in r.json()["frame_ids"]} == {s["shots"][1]["id"], s["shots"][3]["id"]}
    assert {rows[f]["stage"] for f in r.json()["frame_ids"]} == {"draft"}
    assert one["frame_ids"][0] not in r.json()["frame_ids"], "a painting draft counts as having one"
    again = world.client.post(url(world, f"/scenes/{s['scene']['id']}/frames"), json={"stage": "draft"}, headers=crew)
    assert again.status_code == 409 and "draft" in again.json()["detail"]


def test_accepting_a_frame_unlocks_the_prompt(world: World, fired: list[dict]):
    s = open_scene(world)
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
    s = open_scene(world)
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
    s = open_scene(world)
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
    s = open_scene(world)
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
    assert "a long portrait lens" in v["frame_prompt"], "a person's lens reaches the frame, as its look"
    assert v["prompt"]["stale_reasons"] == ["The camera settings changed."]
    assert any(c["label"].startswith("Crosses the axis") for c in v["checks"])
    assert world.client.patch(shot_url(world, s, 1, "/camera"), json={"lens": "300mm"}, headers=crew).status_code == 422
    v = world.client.patch(shot_url(world, s, 1, "/camera"), json={"lens": None, "axis": "Side A · left to right"},
                           headers=crew).json()
    assert v["camera"]["changed"] == [] and not v["prompt"]["stale"]


def test_scene_prompts_take_every_unlocked_shot(world: World, fired: list[dict]):
    s = open_scene(world)
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
    s = open_scene(world)
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


def test_a_person_adds_and_removes_canon_for_one_shot(world: World):
    s = open_scene(world)
    design(world, s)
    house = str(s["house"]["id"])
    kamala = str(s["kamala"]["id"])
    director = world.headers(world.director)
    base = panel(world, s)
    # Taking the place out of shot 2 only: the answer is that shot, and shot 1 keeps it.
    r = world.client.delete(shot_url(world, s, 1, f"/canon/{house}"), headers=director)
    assert r.status_code == 200, r.text
    assert not any(ref.startswith("L01") for ref in r.json()["canon_refs"])
    assert panel(world, s)[0]["canon_refs"] == base[0]["canon_refs"]
    # The shot was designed before: its design now reads as out of date (approval is not undone).
    assert "Different people or place in the shot." in r.json()["design"]["stale_reasons"]
    # Putting it back stores nothing: the script already gives the shot its place.
    r = world.client.put(shot_url(world, s, 1, f"/canon/{house}"), headers=director)
    assert r.json()["canon_refs"] == base[1]["canon_refs"] and r.json()["design"]["state"] == "current"
    # Canon the script never uses goes into this shot only.
    r = world.client.put(shot_url(world, s, 0, f"/canon/{kamala}"), headers=director)
    assert any(ref.startswith("C01") for ref in r.json()["canon_refs"])
    assert not any(ref.startswith("C01") for ref in panel(world, s)[1]["canon_refs"])
    # A person who may generate but not change canon is refused; an unknown item is not found.
    assert world.client.put(shot_url(world, s, 0, f"/canon/{kamala}"), headers=world.headers(world.crew)).status_code == 403
    unknown = "00000000-0000-0000-0000-000000000000"
    assert world.client.put(shot_url(world, s, 0, f"/canon/{unknown}"), headers=director).status_code == 404


def test_a_shot_made_before_a_chip_changed_is_out_of_date(world: World):
    s = open_scene(world)
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
    s = open_scene(world)
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


# ── draft and final first frames ───────────────────────────────────────────────────────────


def test_a_draft_is_its_own_stage_and_never_unlocks_the_prompt(world: World, fired: list[dict]):
    s = open_scene(world)
    design(world, s)
    crew = world.headers(world.crew)
    r = world.client.post(shot_url(world, s, 1, "/frames"), json={"stage": "draft", "count": 2}, headers=crew)
    assert r.status_code == 202, r.text
    ids = r.json()["frame_ids"]
    rows = world.repos.frames.rows  # type: ignore[attr-defined]
    assert all(rows[f]["stage"] == "draft" and "draft_id" not in rows[f] for f in ids)
    assert fired[-1]["kind"] == "frame_render" and fired[-1]["state"] == {"frame_ids": ids}
    finish_frames(world, s, ids)

    v = world.client.get(shot_url(world, s, 1), headers=crew).json()
    assert v["frames"] == [] and [d["label"] for d in v["drafts"]] == ["Draft 1", "Draft 2"], "drafts are kept apart"
    assert all(d["stage"] == "draft" for d in v["drafts"])

    v = world.client.post(url(world, f"/frames/{ids[0]}/accept"), headers=crew).json()
    assert v["accepted_draft_id"] == ids[0] and v["accepted_frame_id"] is None
    assert v["status"] == "draft" and v["prompt_lock"]["locked"], "an accepted draft is not a first frame"
    v = world.client.post(url(world, f"/frames/{ids[1]}/accept"), headers=crew).json()
    assert v["accepted_draft_id"] == ids[1] and [d["accepted"] for d in v["drafts"]] == [False, True]
    v = world.client.post(url(world, f"/frames/{ids[1]}/reject"), json={}, headers=crew).json()
    assert v["accepted_draft_id"] is None and v["status"] == "draft"


def test_a_draft_and_a_final_are_accepted_independently(world: World, fired: list[dict]):
    s = open_scene(world)
    design(world, s)
    crew = world.headers(world.crew)
    (draft,) = world.client.post(shot_url(world, s, 1, "/frames"), json={"stage": "draft"},
                                 headers=crew).json()["frame_ids"]
    (final,) = world.client.post(shot_url(world, s, 1, "/frames"), json={}, headers=crew).json()["frame_ids"]
    finish_frames(world, s, [draft, final])
    world.client.post(url(world, f"/frames/{draft}/accept"), headers=crew)
    v = world.client.post(url(world, f"/frames/{final}/accept"), headers=crew).json()
    assert v["accepted_draft_id"] == draft and v["accepted_frame_id"] == final, "one accepted per stage"
    assert v["status"] == "frame" and not v["prompt_lock"]["locked"]
    assert [f["id"] for f in v["frames"]] == [final] and [d["id"] for d in v["drafts"]] == [draft]


def test_a_final_can_be_painted_from_the_accepted_draft_or_without_it(world: World, fired: list[dict]):
    s = open_scene(world)
    design(world, s)
    crew = world.headers(world.crew)
    rows = world.repos.frames.rows  # type: ignore[attr-defined]
    r = world.client.post(shot_url(world, s, 1, "/frames"), json={"from_draft": True}, headers=crew)
    assert r.status_code == 409 and "Accept a draft first" in r.json()["detail"]
    (draft,) = world.client.post(shot_url(world, s, 1, "/frames"), json={"stage": "draft"},
                                 headers=crew).json()["frame_ids"]
    finish_frames(world, s, [draft])
    r = world.client.post(shot_url(world, s, 1, "/frames"), json={"from_draft": True}, headers=crew)
    assert r.status_code == 409, "a draft that is not accepted is not the draft"
    world.client.post(url(world, f"/frames/{draft}/accept"), headers=crew)

    (with_draft,) = world.client.post(shot_url(world, s, 1, "/frames"), json={"from_draft": True},
                                      headers=crew).json()["frame_ids"]
    (without,) = world.client.post(shot_url(world, s, 1, "/frames"), json={"from_draft": False},
                                   headers=crew).json()["frame_ids"]
    assert rows[with_draft]["stage"] == "final" and rows[with_draft]["draft_id"] == draft
    assert rows[without]["stage"] == "final" and "draft_id" not in rows[without]
    v = world.client.get(shot_url(world, s, 1), headers=crew).json()
    assert [f["draft_id"] for f in v["frames"]] == [draft, None]


def test_a_draft_cannot_be_painted_from_a_draft_and_a_stale_draft_is_not_a_reference(world: World, fired: list[dict]):
    s = open_scene(world)
    design(world, s)
    crew = world.headers(world.crew)
    r = world.client.post(shot_url(world, s, 1, "/frames"), json={"stage": "draft", "from_draft": True}, headers=crew)
    assert r.status_code == 422
    (draft,) = world.client.post(shot_url(world, s, 1, "/frames"), json={"stage": "draft"},
                                 headers=crew).json()["frame_ids"]
    finish_frames(world, s, [draft])
    world.client.post(url(world, f"/frames/{draft}/accept"), headers=crew)
    world.repos.shots.rows[s["shots"][1]["id"]]["version"] += 1  # type: ignore[attr-defined]  # the shot moved on
    r = world.client.post(shot_url(world, s, 1, "/frames"), json={"from_draft": True}, headers=crew)
    assert r.status_code == 409 and "earlier version" in r.json()["detail"]


def test_scene_frames_are_finals_and_a_draft_does_not_count_as_having_a_frame(world: World, fired: list[dict]):
    s = open_scene(world)
    design(world, s)
    crew = world.headers(world.crew)
    (draft,) = world.client.post(shot_url(world, s, 0, "/frames"), json={"stage": "draft"},
                                 headers=crew).json()["frame_ids"]
    finish_frames(world, s, [draft])
    world.client.post(url(world, f"/frames/{draft}/accept"), headers=crew)
    r = world.client.post(url(world, f"/scenes/{s['scene']['id']}/frames"), json={}, headers=crew)
    assert r.status_code == 202
    rows = world.repos.frames.rows  # type: ignore[attr-defined]
    assert {rows[f]["stage"] for f in r.json()["frame_ids"]} == {"final"}
    assert s["shots"][0]["id"] in {rows[f]["shot_id"] for f in r.json()["frame_ids"]}, "S01 still needs a first frame"


# ── the first frame's brief (plan/2026-11-11b) ─────────────────────────────────────────────


def test_the_frame_prompt_names_the_productions_genre_from_its_memory(world: World):
    """plan/2026-11-12b: the genre row of production memory (a person's edit first) reaches the lead."""
    s = open_scene(world)
    design(world, s)
    reviewer = world.headers(world.reviewer)
    before = world.client.get(shot_url(world, s, 1), headers=reviewer).json()["frame_prompt"]
    assert before.startswith("Photorealistic still frame from a Sri Lankan television drama,")
    world.repos.direction.add_row({"production_id": str(world.production), "topic": "series",  # type: ignore[attr-defined]
                                   "says": "Genre: action, crime thriller; love as a thread.", "strength": "fact"})
    after = world.client.get(shot_url(world, s, 1), headers=reviewer).json()["frame_prompt"]
    assert after.startswith("Photorealistic still frame from a Sri Lankan action and crime thriller,")
    assert after.split(",", 1)[1] == before.split(",", 1)[1], "only the lead changed"


def test_the_shot_shows_the_frames_brief_its_pictures_and_what_is_missing(world: World):
    s = open_scene(world)
    design(world, s)
    v = world.client.get(shot_url(world, s, 1), headers=world.headers(world.reviewer)).json()
    keys = [b["key"] for b in v["frame_brief"]]
    assert keys[0] == "lead" and keys[-1] == "close" and "shot" in keys and "place" in keys
    assert " ".join(b["text"] for b in v["frame_brief"]) == v["frame_prompt"], "the sections ARE the prompt"
    named = [r["label"] for r in v["frame_references"] if not r["missing"]]
    assert all(f"image {n} is {label}" in v["frame_prompt"] for n, label in enumerate(named, start=1)), \
        "every picture the renderer will attach is named, in order"
    for r in v["frame_references"]:
        assert bool(r["job"]) != r["missing"]
    assert len(v["frame_missing"]) == sum(r["missing"] for r in v["frame_references"])
    assert v["setup_frame_off"] is False


def test_a_later_shot_of_a_setup_shows_the_first_ones_accepted_frame_and_a_person_can_turn_it_off(world: World):
    s = open_scene(world)
    design(world, s)
    first, later = (world.repos.shots.rows[s["shots"][n]["id"]] for n in (0, 1))  # type: ignore[attr-defined]
    first["slate"], later["slate"] = "1A-1", "1A-2"
    _accept_one(world, s, 0)
    crew = world.headers(world.crew)
    v = world.client.get(shot_url(world, s, 1), headers=crew).json()
    assert v["frame_references"][-1]["role"] == "setup" and v["frame_references"][-1]["name"] == "1A-1"
    assert "the accepted frame of shot 1A-1" in v["frame_prompt"]
    r = world.client.put(shot_url(world, s, 1, "/setup-frame"), json={"off": True}, headers=crew)
    assert r.status_code == 200, r.text
    v = r.json()
    assert v["setup_frame_off"] is True and all(x["role"] != "setup" for x in v["frame_references"])
    assert world.client.put(shot_url(world, s, 1, "/setup-frame"), json={"off": True},
                            headers=world.headers(world.reviewer)).status_code == 403
    v = world.client.put(shot_url(world, s, 1, "/setup-frame"), json={"off": False}, headers=crew).json()
    assert v["frame_references"][-1]["role"] == "setup"


def test_the_prompt_writer_is_asked_for_a_shots_first_frame(world: World, fired: list[dict]):
    s = open_scene(world)
    crew = world.headers(world.crew)
    assert world.client.post(shot_url(world, s, 1, "/frame-prompt"), headers=crew).status_code == 409, "no design"
    design(world, s)
    r = world.client.post(shot_url(world, s, 1, "/frame-prompt"), headers=crew)
    assert r.status_code == 202, r.text
    assert fired[-1]["state"] == {"mode": "frame_prompt", "shot_ids": [s["shots"][1]["id"]]}
    assert world.client.post(shot_url(world, s, 1, "/frame-prompt"),
                             headers=world.headers(world.reviewer)).status_code == 403
    v = world.client.get(shot_url(world, s, 1), headers=crew).json()
    assert v["frame_polished"] is False


def test_the_prompt_writer_is_asked_for_every_designed_shot_of_a_scene(world: World, fired: list[dict]):
    s = open_scene(world)
    crew = world.headers(world.crew)
    to = url(world, f"/scenes/{s['scene']['id']}/frame-prompts")
    assert world.client.post(to, json={}, headers=crew).status_code == 409, "no design"
    design(world, s)
    r = world.client.post(to, json={}, headers=crew)
    assert r.status_code == 202, r.text
    assert fired[-1]["state"] == {"mode": "frame_prompt", "shot_ids": [shot["id"] for shot in s["shots"]]}
    assert world.client.post(to, json={}, headers=world.headers(world.reviewer)).status_code == 403
