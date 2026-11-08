"""Thumbnails (plan/2026-11-08c 1c): every picture is stored twice, and views carry both links."""
from __future__ import annotations

from io import BytesIO

import pytest
from PIL import Image

from api.services import media_links, media_thumbs
from api.workers import task_manager
from tests.api.conftest import World
from tests.api.test_production import approved_scene, design, shot_url


@pytest.fixture
def fired(monkeypatch: pytest.MonkeyPatch) -> list[dict]:
    calls: list[dict] = []
    monkeypatch.setattr(task_manager, "_fire_local",
                        lambda url, payload: calls.append({"url": url, **payload.model_dump(mode="json")}))
    return calls


def _png(width: int = 1536, height: int = 1024) -> bytes:
    out = BytesIO()
    Image.new("RGB", (width, height), (180, 40, 40)).save(out, "PNG")
    return out.getvalue()


def test_a_uploaded_frame_is_stored_with_a_small_copy_and_the_view_links_both(world: World, fired: list[dict]):
    s = approved_scene(world)
    design(world, s)
    big = _png()
    r = world.client.post(shot_url(world, s, 1, "/frames/upload"), files={"file": ("mine.png", big, "image/png")},
                          headers=world.headers(world.crew))
    assert r.status_code == 201, r.text
    frame = r.json()["frames"][0]
    path = f"{world.production}/{s['shots'][1]['id']}/{frame['id']}.png"
    objects = world.repos.storage.objects  # type: ignore[attr-defined]
    assert objects[("frames", path)] == big
    thumb = Image.open(BytesIO(objects[("frames", f"{path}.thumb.webp")]))
    assert thumb.format == "WEBP" and thumb.width == 640
    assert len(objects[("frames", f"{path}.thumb.webp")]) < len(big) / 4
    assert frame["thumb_url"].startswith("http://localhost:8000/files/") and frame["thumb_url"] != frame["url"]
    assert media_links.open_ticket(frame["thumb_url"].rsplit("/", 1)[1]) == {"bucket": "frames",
                                                                              "path": f"{path}.thumb.webp"}
    assert frame["file_key"] == media_links.key("frames", path) and path not in frame["file_key"]


def test_a_picture_that_is_not_one_pillow_can_read_is_still_stored(world: World):
    import asyncio

    broken = b"\x89PNG\r\n\x1a\nbroken"
    asyncio.run(media_thumbs.store_with_thumb(world.repos, "references", "p/x.png", broken, "image/png"))
    objects = world.repos.storage.objects  # type: ignore[attr-defined]
    assert ("references", "p/x.png") in objects and ("references", "p/x.png.thumb.webp") not in objects


def test_a_take_poster_sits_beside_the_take():
    assert media_thumbs.poster_path("p/s/t.mp4") == "p/s/t.poster.webp"
    assert media_thumbs.poster_path("p/s/t") == "p/s/t.poster.webp"
