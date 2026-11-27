"""`core/media.py` (plan/2026-11-27 §4): the same folder and path in Supabase Storage or in a Cloud Storage bucket,
with a read fallback while files are being moved. No network and no Google credentials."""
from __future__ import annotations

import httpx
import pytest

from hiru_ai.core import media

KEY = "service-key"
SINHALA = "p1/තිරය 01/a b.png"


def make(backend: str = "supabase", *, fallback: bool = False) -> media.Media:
    config = media.MediaConfig(backend=backend, bucket="bkt" if backend == "gcs" else "", read_fallback=fallback)
    return media.Media("http://sb/", KEY, config, token=lambda: "google-token")


def recorder(*answers: httpx.Response) -> tuple[httpx.Client, list[httpx.Request]]:
    seen: list[httpx.Request] = []
    queue = list(answers)

    def handle(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return queue.pop(0)

    return httpx.Client(transport=httpx.MockTransport(handle)), seen


def test_the_default_is_supabase_with_the_same_requests_as_before(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv("FILES__BACKEND", raising=False)
    m = media.Media("http://sb", KEY)
    [read] = m.reads("frames", "p/a.png")
    assert read.url == "http://sb/storage/v1/object/frames/p/a.png"
    assert read.headers == {"apikey": KEY, "Authorization": f"Bearer {KEY}"}
    write = m.write("frames", "p/a.png", "image/png", once=True)
    assert write.url == read.url and write.headers["x-upsert"] == "false"
    assert m.write("documents", "p/d.txt", "text/plain", once=False).headers["x-upsert"] == "true"


def test_a_setting_that_cannot_work_is_refused(monkeypatch: pytest.MonkeyPatch):
    for env in ({"FILES__BACKEND": "s3"}, {"FILES__BACKEND": "gcs", "FILES__GCS_BUCKET": ""}):
        for name, value in env.items():
            monkeypatch.setenv(name, value)
        with pytest.raises(ValueError, match="FILES__"):
            media.MediaConfig.from_env()


def test_the_environment_is_read(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("FILES__BACKEND", " GCS ")
    monkeypatch.setenv("FILES__GCS_BUCKET", "bkt")
    monkeypatch.setenv("FILES__READ_FALLBACK", "true")
    assert media.MediaConfig.from_env() == media.MediaConfig("gcs", "bkt", True)


def test_a_cloud_object_keeps_the_folder_and_path_as_one_escaped_name():
    m = make("gcs")
    [read] = m.reads("frames", SINHALA)
    sent = httpx.Request("GET", read.url)
    # one path segment after /o/: the slashes stay escaped on the wire, and nothing is escaped twice
    segment = sent.url.raw_path.decode().split("/o/")[1].split("?")[0]
    assert "/" not in segment and "%25" not in segment and segment.startswith("frames%2Fp1%2F")
    assert read.url.endswith("?alt=media") and read.headers == {"Authorization": "Bearer google-token"}


def test_a_write_once_upload_is_conditional_and_an_overwrite_is_not():
    m = make("gcs")
    once = m.write("takes", "p/t.mp4", "video/mp4", once=True)
    assert "uploadType=media&name=takes%2Fp%2Ft.mp4" in once.url and once.url.endswith("&ifGenerationMatch=0")
    assert once.headers == {"Authorization": "Bearer google-token", "Content-Type": "video/mp4"}
    assert "ifGenerationMatch" not in m.write("documents", "p/d.txt", "text/plain", once=False).url


def test_without_fallback_only_the_bucket_is_asked():
    client, seen = recorder(httpx.Response(404))
    assert media.get(client, make("gcs"), "frames", "p/a.png").status_code == 404
    assert [r.url.host for r in seen] == ["storage.googleapis.com"]


def test_with_fallback_a_file_the_bucket_lacks_is_read_from_supabase():
    client, seen = recorder(httpx.Response(404), httpx.Response(200, content=b"old"))
    assert media.get(client, make("gcs", fallback=True), "frames", "p/a.png").content == b"old"
    assert [r.url.host for r in seen] == ["storage.googleapis.com", "sb"]
    assert "google-token" not in seen[1].headers["authorization"]  # each place gets only its own credential
    assert "apikey" not in seen[0].headers


def test_only_a_404_moves_on_to_supabase():
    client, seen = recorder(httpx.Response(403))
    assert media.get(client, make("gcs", fallback=True), "frames", "p/a.png").status_code == 403
    assert len(seen) == 1


def test_a_removal_covers_every_place_a_read_looks():
    assert [r.url.split("/")[2] for r in make("gcs", fallback=True).removes("documents", "p/d")] == [
        "storage.googleapis.com", "sb"]
    assert len(make("gcs").removes("documents", "p/d")) == 1


def test_an_existing_file_is_recognised_on_both():
    assert media.already_exists(httpx.Response(412))
    assert media.already_exists(httpx.Response(409, text="The resource already exists"))
    assert media.already_exists(httpx.Response(400, text='{"error":"Duplicate"}'))
    assert not media.already_exists(httpx.Response(400, text="bad mime type"))


def test_a_request_never_prints_its_credential():
    assert KEY not in repr(make().reads("frames", "p/a.png"))


def test_the_token_is_kept_until_shortly_before_it_expires(monkeypatch: pytest.MonkeyPatch):
    asked: list[int] = []

    def fetch() -> tuple[str, float]:
        asked.append(1)
        return f"t{len(asked)}", 10_000.0

    monkeypatch.setattr(media, "_fetch_token", fetch)
    now = [0.0]
    monkeypatch.setattr(media.time, "time", lambda: now[0])
    token = media._Token()
    assert (token(), token()) == ("t1", "t1")
    now[0] = 10_000.0 - 299
    assert token() == "t2"


def test_missing_credentials_read_as_storage_unreachable(monkeypatch: pytest.MonkeyPatch):
    def fetch() -> tuple[str, float]:
        raise RuntimeError("no default credentials")

    monkeypatch.setattr(media, "_fetch_token", fetch)
    with pytest.raises(httpx.TransportError):
        media._Token()()
