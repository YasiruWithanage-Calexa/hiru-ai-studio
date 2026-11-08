from __future__ import annotations

from uuid import uuid4

import pytest

from api.services import media_links
from api.workers import task_manager
from tests.api.conftest import World


@pytest.fixture
def fired(monkeypatch: pytest.MonkeyPatch) -> list[dict]:
    calls: list[dict] = []
    monkeypatch.setattr(task_manager, "_fire_local",
                        lambda url, payload: calls.append({"url": url, **payload.model_dump(mode="json")}))
    return calls


def test_echo_dispatch_creates_job_then_fires(world: World, fired: list[dict]):
    r = world.client.post("/v1/jobs/echo", json={"message": "hello"}, headers=world.headers(world.admin))
    assert r.status_code == 202
    job_id = r.json()["job_id"]
    assert fired[0]["url"] == "http://localhost:8201/"
    assert fired[0]["job_id"] == job_id and fired[0]["state"] == {"message": "hello"}
    job = world.client.get(f"/v1/jobs/{job_id}", headers=world.headers(world.admin)).json()
    assert job["status"] == "pending" and job["kind"] == "echo"


def test_echo_is_admin_only(world: World, fired: list[dict]):
    r = world.client.post("/v1/jobs/echo", json={}, headers=world.headers(world.producer))
    assert r.status_code == 403
    assert fired == []


def test_failed_dispatch_marks_job_failed(world: World, monkeypatch: pytest.MonkeyPatch):
    def boom(url, payload):  # type: ignore[no-untyped-def]
        raise RuntimeError("queue down")

    monkeypatch.setattr(task_manager, "_fire_local", boom)
    with pytest.raises(RuntimeError):
        world.client.post("/v1/jobs/echo", json={}, headers=world.headers(world.admin))
    (job,) = world.repos.jobs.rows.values()  # type: ignore[attr-defined]
    assert job["status"] == "failed"


def test_job_visibility_follows_production(world: World):
    jobs = world.repos.jobs
    mine = str(uuid4())
    theirs = str(uuid4())
    jobs.rows[mine] = {"id": mine, "kind": "echo", "status": "done",  # type: ignore[attr-defined]
                       "production_id": str(world.production), "requested_by": str(world.admin),
                       "created_at": "2026-10-23T00:00:00Z", "updated_at": "2026-10-23T00:00:00Z"}
    jobs.rows[theirs] = {**jobs.rows[mine], "id": theirs,  # type: ignore[attr-defined]
                         "production_id": str(world.other_production)}
    jobs.event_rows += [{"job_id": mine, "seq": 1, "type": "status", "payload": {}},  # type: ignore[attr-defined]
                        {"job_id": mine, "seq": 2, "type": "progress", "payload": {"n": 1}}]
    h = world.headers(world.reviewer)
    assert world.client.get(f"/v1/jobs/{mine}", headers=h).status_code == 200
    assert world.client.get(f"/v1/jobs/{theirs}", headers=h).status_code == 404
    events = world.client.get(f"/v1/jobs/{mine}/events?after=1", headers=h).json()
    assert [e["seq"] for e in events] == [2]


def test_file_ticket_round_trip_and_opacity():
    t = media_links.ticket("frames", "prod/shot-1/frame-1.png")
    assert "frames" not in t and "shot-1" not in t  # encrypted, not just encoded
    assert media_links.open_ticket(t) == {"bucket": "frames", "path": "prod/shot-1/frame-1.png"}


def test_file_ticket_rejects_tampering_and_expiry():
    t = media_links.ticket("frames", "a.png")
    tampered = t[:-2] + ("AA" if not t.endswith("AA") else "BB")
    assert media_links.open_ticket(tampered) is None
    assert media_links.open_ticket(media_links.ticket("frames", "a.png", seconds=-1)) is None
    assert media_links.open_ticket("garbage") is None


def test_bad_file_ticket_is_404(world: World):
    assert world.client.get("/files/not-a-ticket").status_code == 404


# ── one URL per file per window (plan/2026-11-08c 1a) ──────────────────────────────────────


def test_the_same_file_in_the_same_window_is_the_same_url(monkeypatch: pytest.MonkeyPatch):
    import time

    base = 1_800_000_000 - 1_800_000_000 % 3600 + 600  # ten minutes into an hour
    monkeypatch.setattr(time, "time", lambda: base)
    first = media_links.ticket("frames", "a.png")
    monkeypatch.setattr(time, "time", lambda: base + 1500)
    assert media_links.ticket("frames", "a.png") == first  # 25 minutes later, still the same window
    assert media_links.ticket("frames", "b.png") != first  # another file: another ticket
    assert media_links.ticket("references", "a.png") != first
    assert media_links.url("frames", "a.png") == media_links.url("frames", "a.png")
    assert media_links.open_ticket(first) == {"bucket": "frames", "path": "a.png"}
    monkeypatch.setattr(time, "time", lambda: base + 3000)
    assert media_links.ticket("frames", "a.png") != first  # next window


def test_a_ticket_never_has_less_than_ten_minutes_left(monkeypatch: pytest.MonkeyPatch):
    import time

    hour = 1_800_000_000 - 1_800_000_000 % 3600
    monkeypatch.setattr(time, "time", lambda: hour + 3600 - 120)  # two minutes before the window ends
    t = media_links.ticket("frames", "a.png")
    assert media_links.seconds_left(t) >= 3600  # handed the NEXT window's end
    monkeypatch.setattr(time, "time", lambda: hour + 3600 - 700)
    assert 600 <= media_links.seconds_left(media_links.ticket("frames", "a.png")) <= 700


def test_tampering_with_a_deterministic_ticket_is_still_404(world: World):
    t = media_links.ticket("frames", "a.png")
    flipped = t[:-3] + ("AAA" if not t.endswith("AAA") else "BBB")
    assert world.client.get(f"/files/{flipped}").status_code == 404
    assert media_links.open_ticket(t[:20]) is None


def test_the_key_names_a_file_but_is_not_its_path():
    key = media_links.key("frames", "prod/shot/frame.png")
    assert key == media_links.key("frames", "prod/shot/frame.png")
    assert key != media_links.key("takes", "prod/shot/frame.png")
    assert "frame" not in key and len(key) == 20


# ── the disk cache (plan/2026-11-08c 1b) ───────────────────────────────────────────────────

PNG = b"\x89PNG\r\n\x1a\n" + bytes(range(256)) * 8  # 2 KB


def _path(bucket: str, path: str, **kw: str) -> str:
    return "/files/" + media_links.url(bucket, path, **kw).rsplit("/files/", 1)[1]


@pytest.fixture
def upstream(monkeypatch: pytest.MonkeyPatch, tmp_path):
    """A fake storage provider that counts every request that reaches it, and a clean cache folder."""
    import httpx

    from api.config import get_settings
    from api.services import file_cache

    monkeypatch.setenv("FILES__CACHE_DIR", str(tmp_path / "cache"))
    get_settings.cache_clear()
    seen: list[str] = []
    store: dict[str, bytes] = {"frames/p/a.png": PNG, "frames/p/clip.mp4": b"V" * 5000}
    real = httpx.AsyncClient

    def handler(request: httpx.Request) -> httpx.Response:
        name = request.url.path.split("/object/", 1)[1]
        seen.append(name)
        if name not in store:
            return httpx.Response(404, json={"message": "Object not found frames/secret/path"})
        kind = "video/mp4" if name.endswith(".mp4") else "image/png"
        return httpx.Response(200, content=store[name], headers={"content-type": kind})

    monkeypatch.setattr(file_cache.httpx, "AsyncClient",
                        lambda **kw: real(transport=httpx.MockTransport(handler), **kw))
    return type("Upstream", (), {"seen": seen, "store": store})


def test_the_second_request_for_a_file_never_reaches_storage(world: World, upstream):
    url = _path("frames", "p/a.png")
    first = world.client.get(url)
    second = world.client.get(url)
    assert first.status_code == second.status_code == 200
    assert first.content == second.content == PNG
    assert first.headers["content-type"] == "image/png"
    assert upstream.seen == ["frames/p/a.png"]  # downloaded once, served twice
    cc = second.headers["cache-control"]
    assert "private" in cc and "immutable" in cc and "max-age=" in cc
    assert 600 <= int(cc.split("max-age=")[1].split(",")[0]) <= 7200


def test_a_cached_video_answers_a_range_request_with_206(world: World, upstream):
    url = _path("frames", "p/clip.mp4")
    world.client.get(url)
    ranged = world.client.get(url, headers={"Range": "bytes=100-199"})
    assert ranged.status_code == 206 and ranged.content == b"V" * 100
    assert ranged.headers["content-range"] == "bytes 100-199/5000" and ranged.headers["accept-ranges"] == "bytes"
    assert upstream.seen == ["frames/p/clip.mp4"]


def test_a_missing_object_is_404_and_leaks_nothing(world: World, upstream):
    r = world.client.get(_path("frames", "p/none.png"))
    assert r.status_code == 404 and "secret" not in r.text and "frames" not in r.text


def test_many_first_requests_share_one_download(upstream):
    import asyncio

    from api.config import get_settings
    from api.services import file_cache

    cache = file_cache.get_cache(get_settings())

    async def many() -> list[file_cache.Cached]:
        return await asyncio.gather(*(cache.fetch("frames", "p/a.png") for _ in range(8)))

    got = asyncio.run(many())
    assert len({c.path for c in got}) == 1 and got[0].path.read_bytes() == PNG
    assert upstream.seen == ["frames/p/a.png"]


def test_removing_an_object_removes_its_disk_copy(upstream):
    import asyncio

    from api.config import get_settings
    from api.services import file_cache

    cache = file_cache.get_cache(get_settings())
    asyncio.run(cache.fetch("frames", "p/a.png"))
    assert cache.lookup("frames", "p/a.png") is not None
    file_cache.evict(get_settings(), "frames", "p/a.png")
    assert cache.lookup("frames", "p/a.png") is None


def test_the_cache_drops_the_least_recently_used_file_over_its_cap(monkeypatch: pytest.MonkeyPatch, upstream):
    import asyncio
    import os

    from api.config import get_settings
    from api.services import file_cache

    for n in range(3):
        upstream.store[f"frames/p/{n}.png"] = bytes([n]) * 4000
    monkeypatch.setenv("FILES__CACHE_MAX_GB", str(9000 / 1024**3))  # room for two 4 KB files
    get_settings.cache_clear()
    cache = file_cache.get_cache(get_settings())

    async def run() -> None:
        await cache.fetch("frames", "p/0.png")
        await cache.fetch("frames", "p/1.png")
        os.utime(cache.lookup("frames", "p/0.png").path, (1, 1))  # 0 is now the oldest
        await cache.fetch("frames", "p/2.png")

    asyncio.run(run())
    assert cache.lookup("frames", "p/0.png") is None
    assert cache.lookup("frames", "p/1.png") is not None and cache.lookup("frames", "p/2.png") is not None


def test_with_the_cache_off_every_request_streams_through(monkeypatch: pytest.MonkeyPatch, world: World, upstream):
    from api.config import get_settings

    monkeypatch.setenv("FILES__CACHE_MAX_GB", "0")
    get_settings.cache_clear()
    url = _path("frames", "p/a.png")
    assert world.client.get(url).content == PNG and world.client.get(url).content == PNG
    assert upstream.seen == ["frames/p/a.png"] * 2


def test_a_download_name_is_safe_in_a_header(world: World, upstream):
    r = world.client.get(_path("frames", "p/a.png", download="කතාව 1.png"))
    assert r.status_code == 200
    assert r.headers["content-disposition"].startswith("attachment; filename=")
    assert "filename*=UTF-8''" in r.headers["content-disposition"]
