"""plan/2026-11-08c 1d: a media path names one file for ever, so a worker never overwrites it."""
from __future__ import annotations

import httpx
import pytest
from frame_render.runtime import thumbs
from frame_render.runtime.rest import Rest


def _rest(*replies: httpx.Response) -> tuple[Rest, list[httpx.Request]]:
    seen: list[httpx.Request] = []
    queue = list(replies)

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return queue.pop(0) if len(queue) > 1 else queue[0]

    return Rest("http://sb", "key", httpx.Client(transport=httpx.MockTransport(handler))), seen


@pytest.mark.parametrize("bucket", ["frames", "references", "takes"])
def test_media_is_never_upserted(bucket: str):
    rest, seen = _rest(httpx.Response(200))
    rest.upload(bucket, "p/x.png", b"x", "image/png")
    assert seen[0].headers["x-upsert"] == "false"


def test_other_buckets_still_overwrite():
    rest, seen = _rest(httpx.Response(200))
    rest.upload("documents", "p/x.txt", b"x", "text/plain")
    assert seen[0].headers["x-upsert"] == "true"


def test_a_second_write_to_a_media_path_fails():
    rest, seen = _rest(httpx.Response(400, json={"message": "The resource already exists"}))
    with pytest.raises(httpx.HTTPStatusError):
        rest.upload("frames", "p/x.png", b"x", "image/png")
    assert len(seen) == 1


def test_the_worker_thumbnail_is_a_webp_beside_the_picture():
    from io import BytesIO

    from PIL import Image

    out = BytesIO()
    Image.new("RGB", (1536, 1024), (10, 120, 10)).save(out, "PNG")
    small = thumbs.make(out.getvalue())
    assert small is not None and Image.open(BytesIO(small)).width == 640
    assert thumbs.thumb_path("p/f.png") == "p/f.png.thumb.webp"
    assert thumbs.wants_thumb("frames", "p/f.png", "image/png")
    assert not thumbs.wants_thumb("takes", "p/f.mp4", "video/mp4")
    assert not thumbs.wants_thumb("frames", "p/f.png.thumb.webp", "image/webp")
