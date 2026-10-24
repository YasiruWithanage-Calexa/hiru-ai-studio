"""Screen 2d by hand: the scene view and timeline, shot edits, re-split, approval, the script."""
from __future__ import annotations

from uuid import uuid4

import pytest

from api.workers import task_manager
from contracts import sceneplan
from contracts.screenplay import parse_document
from contracts.shotplan import ProposedShot, fit
from tests.api.conftest import World
from tests.services.doc_ingest.conftest import CORPUS


def seed_scene(world: World, n: int = 0, *, settings: dict | None = None) -> dict:
    """Episode 1 of the fixture with scene `n` parsed, one shot per block, fitted by the kernel."""
    r = world.repos
    pid = str(world.production)
    if settings is not None:
        r.productions.rows[pid]["settings"] = settings  # type: ignore[attr-defined]
    kamala = r.canon.add(production_id=pid, kind="character", code="C01", name="Kamala", aliases=["Amma"],  # type: ignore[attr-defined]
                         core=True, locked=False)
    nimal = r.canon.add(production_id=pid, kind="character", code="C02", name="Nimal", aliases=[], core=True,  # type: ignore[attr-defined]
                        locked=False)
    house = r.canon.add(production_id=pid, kind="location", code="L01", name="Kamala's house", aliases=[],  # type: ignore[attr-defined]
                        core=False, locked=True)
    ep = r.episodes.add(production_id=pid, number=1, title="The Return", synopsis="", status="ready")  # type: ignore[attr-defined]
    doc = parse_document((CORPUS / "harbour-lights-ep01-script.fountain").read_text(encoding="utf-8"))
    scene = r.scenes.add(production_id=pid, episode_id=ep["id"], number=1, heading=doc.scenes[n].heading.raw,  # type: ignore[attr-defined]
                         title="", note="", time_of_day="DAWN", location_id=house["id"], envelope_s=60,
                         status="split", script=[], script_version=1, fit_report={"planner": "rules"})
    blocks, lines = [], []
    for b in doc.scenes[n].blocks:
        if b.kind == "dialogue":
            line = {"id": str(uuid4()), "production_id": pid, "scene_id": scene["id"], "ord": len(lines),
                    "speaker": b.speaker.title(), "text": b.text, "delivery": b.delivery,
                    "character_id": {"NIMAL": nimal["id"], "KAMALA": kamala["id"]}.get(b.speaker)}
            lines.append(line)
            blocks.append({"kind": "dialogue", "text": "", "line_id": line["id"]})
        else:
            blocks.append({"kind": b.kind, "text": b.text, "line_id": None})
    scene["script"] = blocks
    items = sceneplan.items_for(blocks, lines)
    proposal = [ProposedShot(i, i + 1, "MS") for i in range(len(items))]
    shots, line_rows, _ = sceneplan.rows_after_fit(scene, [{"start": p.start} for p in proposal],
                                                   fit(items, proposal, envelope_s=60), lines)
    for s in shots:
        r.shots.rows[s["id"]] = {**s, "created_at": "2026-10-23T00:00:00+00:00"}  # type: ignore[attr-defined]
    for ln in line_rows:
        r.lines.rows[ln["id"]] = ln  # type: ignore[attr-defined]
    r.scenes.add(production_id=pid, episode_id=ep["id"], number=2, heading="EXT. HARBOUR", title="",  # type: ignore[attr-defined]
                 envelope_s=60, status="draft", script=[], script_version=1)
    return {"scene": scene, "shots": shots, "lines": line_rows, "episode": ep, "kamala": kamala, "house": house}


def url(world: World, path: str) -> str:
    return f"/v1/productions/{world.production}{path}"


def test_scene_view_carries_script_shots_lines_and_timeline(world: World):
    s = seed_scene(world)
    r = world.client.get(url(world, f"/scenes/{s['scene']['id']}"), headers=world.headers(world.reviewer))
    assert r.status_code == 200, r.text
    v = r.json()
    assert [x["code"] for x in v["shots"]] == ["S01", "S02", "S03", "S04"]
    assert [x["id"] for x in v["shots"]] == [x["id"] for x in s["shots"]]
    assert [(x["start_s"], x["end_s"]) for x in v["shots"]] == [(0, 6), (6, 10), (10, 14), (14, 18)]
    assert v["timeline"] == {"total_s": 18, "envelope_s": 60, "over_envelope_s": 0, "issues": []}
    assert [b["kind"] for b in v["script"]] == ["action", "dialogue", "action", "dialogue"]
    assert v["script"][1]["speaker"] == "Nimal" and v["script"][1]["shot_id"] == v["shots"][1]["id"]
    line = v["lines"][1]
    assert line["speaker"] == "Kamala" and line["shot_id"] == v["shots"][3]["id"]
    assert 14 < line["start_s"] < line["end_s"] <= 18 and line["overrun_s"] == 0
    assert v["shots"][3]["speaker"] == "Kamala" and v["shots"][3]["sound_mode"] == "dialogue"
    assert {c["code"] for c in v["canon"]} == {"C01", "C02", "L01"}
    assert v["board"][0]["seat"] == "lead" and v["board"][0]["persona"]["name"] == "Classic Teledrama"
    assert v["episode"]["number"] == 1 and v["previous_scene_id"] is None and v["next_scene_id"]
    assert v["planner"] == "rules"


def test_scene_view_is_scoped(world: World):
    s = seed_scene(world)
    assert world.client.get(f"/v1/productions/{world.other_production}/scenes/{s['scene']['id']}",
                            headers=world.headers(world.admin)).status_code == 404
    assert world.client.get(url(world, f"/scenes/{s['scene']['id']}"),
                            headers=world.headers(world.outsider)).status_code == 404
    assert world.client.get(url(world, f"/scenes/{uuid4()}"), headers=world.headers(world.admin)).status_code == 404


def test_a_person_sets_a_length_and_the_scene_is_retimed_around_it(world: World):
    s = seed_scene(world)
    shot2 = s["shots"][1]["id"]
    r = world.client.patch(url(world, f"/shots/{shot2}"), json={"duration_s": 8}, headers=world.headers(world.director))
    assert r.status_code == 200, r.text
    v = r.json()
    assert v["shots"][1]["duration_s"] == 8 and v["shots"][1]["duration_locked"]
    assert [x["start_s"] for x in v["shots"]] == [0, 6, 14, 18] and v["timeline"]["total_s"] == 22
    stored = world.repos.shots.rows  # type: ignore[attr-defined]
    assert stored[shot2]["version"] == 2 and stored[s["shots"][0]["id"]]["version"] == 1
    assert stored[s["shots"][2]["id"]]["start_s"] == 14
    assert world.repos.scenes.rows[s["scene"]["id"]]["fit_report"]["planner"] == "person"  # type: ignore[attr-defined]
    assert world.repos.audit.entries[-1]["action"] == "shot.update"  # type: ignore[attr-defined]
    # released back to the planner
    v = world.client.patch(url(world, f"/shots/{shot2}"), json={"duration_s": None},
                           headers=world.headers(world.director)).json()
    assert v["shots"][1]["duration_s"] == 4 and not v["shots"][1]["duration_locked"]


def test_a_locked_length_too_short_for_its_line_is_reported_not_trimmed(world: World):
    s = seed_scene(world, 3)  # the front yard: Kamala's trembling line
    long_shot = next(x for x in s["shots"] if x["words"] and x["duration_s"] > 4)
    v = world.client.patch(url(world, f"/shots/{long_shot['id']}"), json={"duration_s": 4},
                           headers=world.headers(world.producer)).json()
    shot = next(x for x in v["shots"] if x["id"] == long_shot["id"])
    assert shot["duration_s"] == 4
    assert any(i["code"] == "line_overrun" and i["shot_id"] == long_shot["id"] for i in v["timeline"]["issues"])
    assert any(ln["overrun_s"] > 0 for ln in v["lines"])
    texts = {ln["id"]: ln["text"] for ln in s["lines"]}
    assert all(texts[ln["id"]] == ln["text"] for ln in v["lines"])  # the words are untouched


def test_shot_edits_are_checked(world: World):
    s = seed_scene(world)
    first, spoken = s["shots"][0]["id"], s["shots"][1]["id"]
    h = world.headers(world.director)
    assert world.client.patch(url(world, f"/shots/{first}"), json={"duration_s": 10}, headers=h).status_code == 422
    assert world.client.patch(url(world, f"/shots/{first}"), json={"camera_link": "continuous"},
                              headers=h).status_code == 422
    r = world.client.patch(url(world, f"/shots/{spoken}"), json={"sound_mode": "silent"}, headers=h)
    assert r.status_code == 422 and "spoken lines" in r.json()["detail"]
    r = world.client.patch(url(world, f"/shots/{first}"), json={"sound_mode": "dialogue"}, headers=h)
    assert r.status_code == 422 and "invent speech" in r.json()["detail"]
    ok = world.client.patch(url(world, f"/shots/{first}"), json={"sound_mode": "silent", "framing": "WIDE",
                                                                 "title": "Dawn kitchen"}, headers=h)
    assert ok.status_code == 200 and ok.json()["shots"][0]["sound_mode"] == "silent"
    assert ok.json()["shots"][0]["framing"] == "WIDE" and ok.json()["shots"][0]["title"] == "Dawn kitchen"
    assert world.client.patch(url(world, f"/shots/{uuid4()}"), json={"duration_s": 4}, headers=h).status_code == 404


def test_fixed_length_productions_only_take_their_length(world: World):
    s = seed_scene(world, settings={"fixed_shot_seconds": 8})
    r = world.client.patch(url(world, f"/shots/{s['shots'][1]['id']}"), json={"duration_s": 6},
                           headers=world.headers(world.director))
    assert r.status_code == 422 and "8 second" in r.json()["detail"]


def test_who_may_edit_shots(world: World):
    s = seed_scene(world)
    shot = s["shots"][1]["id"]
    for user in (world.writer, world.crew, world.reviewer):
        assert world.client.patch(url(world, f"/shots/{shot}"), json={"duration_s": 8},
                                  headers=world.headers(user)).status_code == 403
    assert world.client.patch(url(world, f"/shots/{shot}"), json={"duration_s": 8},
                              headers=world.headers(world.admin)).status_code == 200


def test_approve_locks_the_scene_and_unapprove_releases_it(world: World):
    s = seed_scene(world)
    sid = s["scene"]["id"]
    h_writer = world.headers(world.writer)
    assert world.client.post(url(world, f"/scenes/{sid}/approve"), headers=h_writer).status_code == 403
    v = world.client.post(url(world, f"/scenes/{sid}/approve"), headers=world.headers(world.director)).json()
    assert v["status"] == "approved" and v["locked_at"]
    h = world.headers(world.director)
    assert world.client.patch(url(world, f"/shots/{s['shots'][1]['id']}"), json={"duration_s": 8},
                              headers=h).status_code == 409
    assert world.client.put(url(world, f"/scenes/{sid}/script"), json={"blocks": [], "script_version": 1},
                            headers=h).status_code == 409
    assert world.client.post(url(world, f"/scenes/{sid}/resplit"), headers=h).status_code == 409
    v = world.client.post(url(world, f"/scenes/{sid}/unapprove"), headers=h).json()
    assert v["status"] == "split" and v["locked_at"] is None
    draft = next(x for x in world.repos.scenes.rows.values() if x["status"] == "draft")  # type: ignore[attr-defined]
    assert world.client.post(url(world, f"/scenes/{draft['id']}/approve"), headers=h).status_code == 409  # no shots


def test_approving_every_scene_approves_the_episode(world: World):
    s = seed_scene(world)
    for row in world.repos.scenes.rows.values():  # type: ignore[attr-defined]
        if row["id"] != s["scene"]["id"]:
            row["status"] = "approved"
    world.client.post(url(world, f"/scenes/{s['scene']['id']}/approve"), headers=world.headers(world.producer))
    assert world.repos.episodes.rows[s["episode"]["id"]]["status"] == "approved"  # type: ignore[attr-defined]


@pytest.fixture
def fired(monkeypatch: pytest.MonkeyPatch) -> list[dict]:
    calls: list[dict] = []
    monkeypatch.setattr(task_manager, "_fire_local",
                        lambda u, payload: calls.append({"url": u, **payload.model_dump(mode="json")}))
    return calls


def test_resplit_sends_one_scene_to_script_split(world: World, fired: list[dict]):
    s = seed_scene(world)
    r = world.client.post(url(world, f"/scenes/{s['scene']['id']}/resplit"), headers=world.headers(world.director))
    assert r.status_code == 202, r.text
    assert fired[0]["kind"] == "script_split" and fired[0]["state"] == {"scene_ids": [s["scene"]["id"]]}
    assert fired[0]["url"].endswith(":8203/")
    assert world.client.post(url(world, f"/scenes/{s['scene']['id']}/resplit"),
                             headers=world.headers(world.writer)).status_code == 403


# ── the script ─────────────────────────────────────────────────────────────────────────────


def edit_body(view: dict) -> dict:
    blocks = []
    for b in view["script"]:
        if b["kind"] == "dialogue":
            line = next(ln for ln in view["lines"] if ln["id"] == b["line_id"])
            blocks.append({"kind": "dialogue", "speaker": line["speaker"], "delivery": line["delivery"],
                           "text": line["text"], "line_id": line["id"]})
        else:
            blocks.append({"kind": b["kind"], "text": b["text"]})
    return {"blocks": blocks, "script_version": view["script_version"]}


def test_a_writer_edits_a_line_and_its_shot_follows(world: World):
    s = seed_scene(world)
    sid = s["scene"]["id"]
    view = world.client.get(url(world, f"/scenes/{sid}"), headers=world.headers(world.writer)).json()
    body = edit_body(view)
    body["blocks"][3]["text"] = "කෑම කන්න වාඩි වෙන්න, පුතේ.‍"  # ZWJ kept, outer space trimmed
    r = world.client.put(url(world, f"/scenes/{sid}/script"), json=body, headers=world.headers(world.writer))
    assert r.status_code == 200, r.text
    v = r.json()
    assert v["script_version"] == 2
    assert [x["id"] for x in v["shots"]] == [x["id"] for x in s["shots"]]  # the shot list is kept
    line = next(ln for ln in v["lines"] if ln["speaker"] == "Kamala")
    assert line["text"].endswith("පුතේ.‍") and line["id"] == s["lines"][1]["id"]
    assert line["shot_id"] == s["shots"][3]["id"] and line["character_id"] == s["kamala"]["id"]
    # the same edit again is stale
    assert world.client.put(url(world, f"/scenes/{sid}/script"), json=body,
                            headers=world.headers(world.writer)).status_code == 409


def test_new_lines_join_the_shot_before_and_deleted_ones_go(world: World):
    s = seed_scene(world)
    sid = s["scene"]["id"]
    view = world.client.get(url(world, f"/scenes/{sid}"), headers=world.headers(world.writer)).json()
    body = edit_body(view)
    nimal_line = body["blocks"][1]
    body["blocks"] = [body["blocks"][0],
                      {"kind": "dialogue", "speaker": "Amma", "text": "කවුද ඒ?", "delivery": ""},
                      nimal_line, body["blocks"][3]]  # the action between the lines is deleted
    v = world.client.put(url(world, f"/scenes/{sid}/script"), json=body, headers=world.headers(world.writer)).json()
    assert [b["kind"] for b in v["script"]] == ["action", "dialogue", "dialogue", "dialogue"]
    assert [x["id"] for x in v["shots"]] == [s["shots"][0]["id"], s["shots"][1]["id"], s["shots"][3]["id"]]
    assert s["shots"][2]["id"] not in world.repos.shots.rows  # type: ignore[attr-defined]
    new = next(ln for ln in v["lines"] if ln["speaker"] == "Amma")
    assert new["shot_id"] == s["shots"][0]["id"]  # joins the shot before it
    assert new["character_id"] == s["kamala"]["id"]  # matched by alias
    assert [ln["ord"] for ln in v["lines"]] == [0, 1, 2]
    assert v["shots"][0]["sound_mode"] == "dialogue"  # it carries a line now


def test_script_edits_are_checked(world: World):
    s = seed_scene(world)
    sid = s["scene"]["id"]
    h = world.headers(world.writer)
    bad = {"blocks": [{"kind": "dialogue", "speaker": "X", "text": "a", "line_id": str(uuid4())}], "script_version": 1}
    assert world.client.put(url(world, f"/scenes/{sid}/script"), json=bad, headers=h).status_code == 422
    no_speaker = {"blocks": [{"kind": "dialogue", "speaker": "", "text": "a"}], "script_version": 1}
    assert world.client.put(url(world, f"/scenes/{sid}/script"), json=no_speaker, headers=h).status_code == 422
    assert world.client.put(url(world, f"/scenes/{sid}/script"), json={"blocks": [], "script_version": 1},
                            headers=world.headers(world.crew)).status_code == 403


def test_clearing_the_script_drops_the_shot_list(world: World):
    s = seed_scene(world)
    sid = s["scene"]["id"]
    v = world.client.put(url(world, f"/scenes/{sid}/script"), json={"blocks": [], "script_version": 1},
                         headers=world.headers(world.writer)).json()
    assert v["status"] == "draft" and v["shots"] == [] and v["lines"] == []
