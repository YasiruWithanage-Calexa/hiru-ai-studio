"""Screen 4: handoff checks, takes (upload, accept, reject), the carried last frame, the bundle,
and the usage budget."""
from __future__ import annotations

import io
import json
import zipfile
from uuid import UUID

import pytest

from api.services.assemble import Inspection, Probe, get_assembler
from api.workers import task_manager
from tests.api.conftest import World
from tests.api.test_production import (
    _accept_one,
    _store_prompt,
    design,
    open_scene,
    shot_url,
    url,
)

MP4 = b"\0\0\0\x18ftypisom" + b"\0" * 64


class FakeAssembler:
    def __init__(self, world: World, duration: float = 4.0, frame_ok: bool = True) -> None:
        self.world, self.duration, self.frame_ok = world, duration, frame_ok
        self.calls: list[tuple[str, ...]] = []

    async def probe(self, bucket: str, path: str) -> Probe | None:
        self.calls.append(("probe", bucket, path))
        return Probe(duration_s=self.duration, width=1920, height=1080, has_audio=True)

    async def poster(self, bucket: str, path: str, out_path: str) -> str:
        return out_path

    async def inspect(self, bucket: str, path: str, out_path: str) -> Inspection | None:
        self.calls.append(("inspect", bucket, path, out_path))
        return Inspection(duration_s=self.duration, width=1920, height=1080, has_audio=True, poster_path=out_path)

    async def last_frame(self, bucket: str, path: str, out_bucket: str, out_path: str) -> str:
        self.calls.append(("last_frame", bucket, path, out_bucket, out_path))
        if not self.frame_ok:
            return ""
        self.world.repos.storage.objects[(out_bucket, out_path)] = b"\x89PNG last"  # type: ignore[attr-defined]
        return out_path


@pytest.fixture
def fired(monkeypatch: pytest.MonkeyPatch) -> list[dict]:
    calls: list[dict] = []
    monkeypatch.setattr(task_manager, "_fire_local",
                        lambda u, payload: calls.append({"url": u, **payload.model_dump(mode="json")}))
    return calls


@pytest.fixture
def assembler(world: World) -> FakeAssembler:
    fake = FakeAssembler(world)
    world.client.app.dependency_overrides[get_assembler] = lambda: fake  # type: ignore[attr-defined]
    return fake


def _ready_shot(world: World, n: int = 1) -> tuple[dict, str]:
    s = open_scene(world)
    design(world, s)
    fid = _accept_one(world, s, n)
    world.repos.storage.objects[("frames", world.repos.frames.rows[fid]["storage_path"])] = b"\x89PNG"  # type: ignore[attr-defined]
    _store_prompt(world, s, n, fid)
    return s, fid


def test_the_handoff_view_runs_the_checks_on_every_read(world: World, fired: list[dict]):
    s, fid = _ready_shot(world)
    v = world.client.get(shot_url(world, s, 1, "/handoff"), headers=world.headers(world.reviewer)).json()
    assert v["code"] == "S02" and v["prompt"]["version"] == 1 and v["opening_frame"]["id"] == fid
    got = {c["label"]: c["tone"] for c in v["checks"]}
    # The stored test prompt has a made-up Sinhala word, no aspect and no voice pin: all reported.
    assert got["A line differs from the approved script"] == "fail"
    assert not v["ready"] and v["takes"] == [] and v["next_carries"] is False
    world.repos.productions.rows[str(world.production)]["settings"] = {"banned_terms": ["Dolly"]}  # type: ignore[attr-defined]
    v = world.client.get(shot_url(world, s, 1, "/handoff"), headers=world.headers(world.reviewer)).json()
    assert {"label": "Names to remove: Dolly", "tone": "fail"} in v["checks"], "a production's own list"


def test_takes_upload_accept_and_reject(world: World, fired: list[dict], assembler: FakeAssembler):
    s, _ = _ready_shot(world)
    crew = world.headers(world.crew)
    files = {"file": ("take.mp4", MP4, "video/mp4")}
    assert world.client.post(shot_url(world, s, 1, "/takes"), files=files,
                             headers=world.headers(world.writer)).status_code == 403
    assert world.client.post(shot_url(world, s, 1, "/takes"), files={"file": ("x.mp4", b"GIF89a..", "video/mp4")},
                             headers=crew).status_code == 422
    assembler.duration = 7.2
    v = world.client.post(shot_url(world, s, 1, "/takes"), files=files, headers=crew).json()
    take = v["takes"][0]
    assert take["label"] == "Take 1" and take["status"] == "uploaded" and take["prompt_version"] == 1
    assert take["url"].startswith("http://localhost:8000/files/") and take["duration_note"] == "7.2 s; the shot is 4 s"
    second = world.client.post(shot_url(world, s, 1, "/takes"), files=files, headers=crew).json()["takes"][1]
    v = world.client.post(url(world, f"/takes/{take['id']}/accept"), headers=crew).json()
    assert v["accepted_take_id"] == take["id"]
    v = world.client.post(url(world, f"/takes/{second['id']}/accept"), headers=crew).json()
    assert [t["status"] for t in v["takes"]] == ["uploaded", "accepted"], "one accepted take per shot"
    v = world.client.post(url(world, f"/takes/{second['id']}/reject"), json={"reason": "lips drift"},
                          headers=crew).json()
    assert v["accepted_take_id"] is None and v["takes"][1]["reason"] == "lips drift"
    assert ("last_frame",) not in [c[:1] for c in assembler.calls], "S03 does not carry on from S02"


def test_a_rejected_take_keeps_the_picked_reasons_for_tuning_the_action_budget(world: World, fired: list[dict],
                                                                             assembler: FakeAssembler):
    """plan/2026-11-18c phase 8: the reasons a person picks lead the take's reason and are kept in the audit log."""
    s, _ = _ready_shot(world)
    crew = world.headers(world.crew)
    take = world.client.post(shot_url(world, s, 1, "/takes"), files={"file": ("take.mp4", MP4, "video/mp4")},
                             headers=crew).json()["takes"][0]
    v = world.client.post(url(world, f"/takes/{take['id']}/reject"),
                          json={"codes": ["too_many_actions", "object_vanished"], "reason": "the phone"},
                          headers=crew).json()
    assert v["takes"][0]["reason"] == "Too many actions; Object vanished · the phone"
    assert world.client.post(url(world, f"/takes/{take['id']}/reject"), json={"codes": ["bad_lighting"]},
                             headers=crew).status_code == 422


def test_accepting_a_take_opens_the_carried_shot_on_its_last_frame(world: World, fired: list[dict],
                                                                   assembler: FakeAssembler):
    s, _ = _ready_shot(world)
    s03 = s["shots"][2]["id"]
    world.repos.shots.rows[s03].update(camera_link="continuous", frame_strategy="carry_last_frame")  # type: ignore[attr-defined]
    crew = world.headers(world.crew)
    v = world.client.post(shot_url(world, s, 1, "/takes"), files={"file": ("t.mp4", MP4, "video/mp4")},
                          headers=crew).json()
    assert v["next_carries"]
    world.client.post(url(world, f"/takes/{v['takes'][0]['id']}/accept"), headers=crew)
    out = next(c for c in assembler.calls if c[0] == "last_frame")
    assert out[1:4] == ("takes", world.repos.takes.rows[v["takes"][0]["id"]]["storage_path"], "frames")  # type: ignore[attr-defined]
    nxt = world.client.get(url(world, f"/shots/{s03}/handoff"), headers=crew).json()
    assert nxt["carried_from"] == "S02" and nxt["opening_frame"]["accepted"]
    assert nxt["opening_frame"]["url"].startswith("http://localhost:8000/files/")
    frame = world.repos.frames.rows[nxt["opening_frame"]["id"]]  # type: ignore[attr-defined]
    assert frame["prompt"] == "The last frame of S02's accepted take." and frame["accepted_by"] == str(world.crew)

    assembler.frame_ok = False  # ffmpeg missing: the take is still accepted; the frame is not made
    v2 = world.client.post(shot_url(world, s, 1, "/takes"), files={"file": ("t.mp4", MP4, "video/mp4")},
                           headers=crew).json()
    r = world.client.post(url(world, f"/takes/{v2['takes'][1]['id']}/accept"), headers=crew)
    assert r.status_code == 200 and r.json()["accepted_take_id"] == v2["takes"][1]["id"]


def test_the_scene_bundle(world: World, fired: list[dict]):
    s, _ = _ready_shot(world)
    r = world.client.get(url(world, f"/scenes/{s['scene']['id']}/bundle"), headers=world.headers(world.crew))
    assert r.status_code == 200 and r.headers["content-type"] == "application/zip"
    assert "scene-01-handoff.zip" in r.headers["content-disposition"]
    z = zipfile.ZipFile(io.BytesIO(r.content))
    names = set(z.namelist())
    assert {"README.txt", "shots.json", "S02/prompt.txt", "S02/first_frame.png"} <= names
    assert "S01/prompt.txt" not in names
    readme = z.read("README.txt").decode()
    assert "S01  6 s" in readme and "NO PROMPT YET" in readme and "CHECKS FAIL" in readme
    manifest = json.loads(z.read("shots.json"))
    assert manifest[1]["prompt_version"] == 1 and manifest[1]["first_frame"] is True
    assert world.client.get(url(world, f"/scenes/{s['scene']['id']}/bundle"),
                            headers=world.headers(world.reviewer)).status_code == 403


def _prop(world: World, code: str, name: str, card: dict, sheets: list[str]) -> str:
    canon = world.repos.canon  # type: ignore[attr-defined]
    row = canon.add(production_id=str(world.production), kind="prop", code=code, name=name, aliases=[], core=False,
                    locked=False)
    version = {"id": f"v-{code}", "entity_id": str(row["id"]), "version": 2, "card": card,
               "reference_assets": [{"path": p} for p in sheets]}
    canon.version_rows[version["id"]] = version
    canon.rows[str(row["id"])]["current_version_id"] = version["id"]
    return str(row["id"])


def test_the_scene_bundle_carries_every_canon_card_of_the_production(world: World, fired: list[dict]):
    s, _ = _ready_shot(world)
    _prop(world, "P01", "Steel lunchbox", {"details": "Dented, two tiers."},
          ["p/lunch/sheet-a.png", "p/lunch/sheet-b.webp", "p/lunch/gone.png"])
    pan = _prop(world, "P02", "Brass pan", {"details": "Old and polished."}, ["p/pan/sheet.png"])
    _prop(world, "P03", "Umbrella", {}, [])  # in no shot and no sheet: still exported, with its card
    storage = world.repos.storage.objects  # type: ignore[attr-defined]
    storage[("references", "p/lunch/sheet-a.png")] = b"\x89PNG a"
    storage[("references", "p/lunch/sheet-b.webp")] = b"RIFF b"
    storage[("references", "p/pan/sheet.png")] = b"\x89PNG pan"
    canon = world.repos.canon  # type: ignore[attr-defined]
    person = next(r for r in canon.rows.values() if r["kind"] == "character")
    version = canon.version_rows.setdefault(f"v-{person['code']}", {"id": f"v-{person['code']}",
                                                                   "entity_id": person["id"], "version": 1})
    canon.rows[person["id"]]["current_version_id"] = version["id"]
    version["reference_assets"] = [{"path": "p/person/base.png"}, {"path": "p/person/face.png", "kind": "face"}]
    storage[("references", "p/person/base.png")] = b"base"
    storage[("references", "p/person/face.png")] = b"face"
    world.repos.looks.add(production_id=str(world.production), entity_id=person["id"], name="Office day",  # type: ignore[attr-defined]
                          outfit="Navy blazer", sheet_assets=[{"path": "p/person/look.png"}])
    storage[("references", "p/person/look.png")] = b"look"
    prompt = next(p for p in world.repos.prompts.rows.values() if p["shot_id"] == s["shots"][1]["id"])  # type: ignore[attr-defined]
    prompt["prose"] = "CAMERA\nDolly in. She opens the steel lunchbox."  # named in S02's prompt
    world.repos.shots.rows[s["shots"][2]["id"]]["person_edits"] = {"cast": {"add": [pan], "remove": []}}  # type: ignore[attr-defined]

    r = world.client.get(url(world, f"/scenes/{s['scene']['id']}/bundle"), headers=world.headers(world.crew))
    assert r.status_code == 200
    z = zipfile.ZipFile(io.BytesIO(r.content))
    names = set(z.namelist())
    who = f"canon/characters/{person['code']}-"
    assert {"canon.json", "canon/props/P01-steel-lunchbox/card.txt", "canon/props/P01-steel-lunchbox/sheet.png",
            "canon/props/P01-steel-lunchbox/sheet-2.webp", "canon/props/P02-brass-pan/sheet.png",
            "canon/props/P03-umbrella/card.txt", "S02/canon.txt", "S03/canon.txt"} <= names
    assert {n.rsplit("/", 1)[-1] for n in names if n.startswith(who)} == {"card.txt", "sheet.png", "face.png",
                                                                          "look-office-day.png"}
    assert any(n.startswith("canon/locations/") for n in names), "the scene's place too"
    assert z.read("canon/props/P01-steel-lunchbox/sheet.png") == b"\x89PNG a"
    card = z.read("canon/props/P01-steel-lunchbox/card.txt").decode()
    assert "Steel lunchbox  (card v2)" in card and "In this scene's shots: S02" in card
    assert "Details: Dented, two tiers." in card
    assert "In this scene's shots: none" in z.read("canon/props/P03-umbrella/card.txt").decode()
    person_card = z.read(next(n for n in names if n.startswith(who) and n.endswith("card.txt"))).decode()
    assert "Office day" in person_card and "Outfit: Navy blazer" in person_card
    assert "canon/props/P02-brass-pan/" in z.read("S03/canon.txt").decode()
    listed = {p["code"]: p for p in json.loads(z.read("canon.json"))}
    assert {"P01", "P02", "P03", person["code"]} <= set(listed)
    assert listed["P01"]["files_missing"] == 1 and listed["P02"]["shots"] == ["S03"] and listed["P03"]["shots"] == []
    manifest = json.loads(z.read("shots.json"))
    assert "P01" in manifest[1]["canon"] and "P02" in manifest[2]["canon"] and "P01" not in manifest[0]["canon"]
    assert "P01" in z.read("README.txt").decode()


def test_the_usage_budget_is_admin_set_and_members_see_a_percentage(world: World):
    world.repos.usage.rows.append({"input_tokens": 400_000, "output_tokens": 100_000})  # type: ignore[attr-defined]
    assert world.client.get("/v1/usage", headers=world.headers(world.crew)).json() == {"percent": 10}
    assert world.client.get("/v1/usage/budget", headers=world.headers(world.producer)).status_code == 403
    r = world.client.put("/v1/usage/budget", json={"budget_tokens": 1_000_000}, headers=world.headers(world.admin))
    assert r.status_code == 200 and r.json()["source"] == "budget"
    assert world.client.get("/v1/usage", headers=world.headers(world.crew)).json() == {"percent": 50}
    assert UUID(str(world.admin))


def test_a_take_shows_a_still_only_when_its_row_says_it_exists() -> None:
    """plan/2026-11-13b phase 9: no link to a file that was never made."""
    from api.routers.handoff import _take_view

    base = {"id": "00000000-0000-0000-0000-000000000001", "status": "uploaded", "storage_path": "p/s/t.mp4",
            "created_at": "2026-11-13T00:00:00Z"}
    assert _take_view(base, 1, 8).poster_url == ""
    assert _take_view({**base, "poster_path": "p/s/t.poster.webp"}, 1, 8).poster_url != ""
