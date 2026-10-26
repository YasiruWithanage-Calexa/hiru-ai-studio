"""Screen 4: handoff checks, takes (upload, accept, reject), the carried last frame, the bundle,
and the usage budget."""
from __future__ import annotations

import io
import json
import zipfile
from uuid import UUID

import pytest

from api.services.assemble import Probe, get_assembler
from api.workers import task_manager
from tests.api.conftest import World
from tests.api.test_production import (
    _accept_one,
    _store_prompt,
    approved_scene,
    design,
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
    s = approved_scene(world)
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


def test_the_usage_budget_is_admin_set_and_members_see_a_percentage(world: World):
    world.repos.usage.rows.append({"input_tokens": 400_000, "output_tokens": 100_000})  # type: ignore[attr-defined]
    assert world.client.get("/v1/usage", headers=world.headers(world.crew)).json() == {"percent": 10}
    assert world.client.get("/v1/usage/budget", headers=world.headers(world.producer)).status_code == 403
    r = world.client.put("/v1/usage/budget", json={"budget_tokens": 1_000_000}, headers=world.headers(world.admin))
    assert r.status_code == 200 and r.json()["source"] == "budget"
    assert world.client.get("/v1/usage", headers=world.headers(world.crew)).json() == {"percent": 50}
    assert UUID(str(world.admin))
