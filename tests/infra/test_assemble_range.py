"""plan/2026-11-21 phase 3: assemble reads only the bytes ffmpeg needs (Range over its own signed URL), never the whole
take, for a probe, a poster, a last frame and `/inspect`. A local HTTP server with Range support stands in for Supabase
Storage and counts the bytes it SENDS, which is what egress bills: ffmpeg asks for open-ended ranges (`bytes=N-`) and
hangs up when it has enough, so what the socket buffers already hold counts too (on localhost ~0.5-1.5 MB a request).
Bounds are fractions of a 20 MB take; measured numbers are in plan/2026-11-21/IMPLEMENTED.md. `/cut` keeps a disk copy:
a take is downloaded once per instance."""
from __future__ import annotations

import re
import shutil
import subprocess
import threading
from collections.abc import Iterator
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from tests.infra.test_assemble import load_app

pytestmark = pytest.mark.skipif(not (shutil.which("ffmpeg") and shutil.which("ffprobe")), reason="needs ffmpeg")
SECRET = {"X-Assemble-Secret": "dev"}


class Served:
    def __init__(self, data: bytes) -> None:
        self.data = data
        self.bytes = 0
        self.lock = threading.Lock()

    def reset(self) -> None:
        with self.lock:
            self.bytes = 0


def _handler(served: Served) -> type[BaseHTTPRequestHandler]:
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args: Any) -> None:
            pass

        def _range(self) -> tuple[int, int]:
            size = len(served.data)
            m = re.match(r"bytes=(\d*)-(\d*)", self.headers.get("Range") or "")
            if not m:
                return 0, size - 1
            start, end = m.group(1), m.group(2)
            if not start:  # a suffix: the last n bytes
                return max(0, size - int(end)), size - 1
            return int(start), min(int(end), size - 1) if end else size - 1

        def do_HEAD(self) -> None:
            self.send_response(200)
            self.send_header("Content-Length", str(len(served.data)))
            self.send_header("Accept-Ranges", "bytes")
            self.end_headers()

        def do_GET(self) -> None:
            start, end = self._range()
            ranged = "Range" in self.headers
            self.send_response(206 if ranged else 200)
            self.send_header("Content-Type", "video/mp4")
            self.send_header("Accept-Ranges", "bytes")
            self.send_header("Content-Length", str(end - start + 1))
            if ranged:
                self.send_header("Content-Range", f"bytes {start}-{end}/{len(served.data)}")
            self.end_headers()
            at = start
            try:
                while at <= end:
                    chunk = served.data[at: min(at + 16 * 1024, end + 1)]
                    self.wfile.write(chunk)
                    with served.lock:
                        served.bytes += len(chunk)
                    at += len(chunk)
            except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
                pass  # ffmpeg had what it needed and hung up

    return Handler


@pytest.fixture(scope="module")
def big_take(tmp_path_factory: pytest.TempPathFactory) -> bytes:
    """About 20 MB of hard-to-compress video with sound, a keyframe each second, its index at the end."""
    out = tmp_path_factory.mktemp("take") / "take.mp4"
    subprocess.run(["ffmpeg", "-nostdin", "-y", "-f", "lavfi", "-i", "testsrc2=s=640x360:r=25:d=16",  # noqa: S603, S607
                    "-f", "lavfi", "-i", "sine=frequency=440:duration=16", "-vf", "noise=alls=60:allf=t",
                    "-c:v", "libx264", "-b:v", "10M", "-maxrate", "10M", "-bufsize", "2M", "-g", "25",
                    "-pix_fmt", "yuv420p",
                    "-c:a", "aac", "-shortest", str(out)], check=True, capture_output=True)
    data = out.read_bytes()
    assert len(data) > 16 * 1024**2, len(data)
    return data


@pytest.fixture
def world(monkeypatch: pytest.MonkeyPatch, big_take: bytes) -> Iterator[tuple[Any, Served, dict]]:
    served = Served(big_take)
    server = ThreadingHTTPServer(("127.0.0.1", 0), _handler(served))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    app = load_app()
    stored: dict[tuple[str, str], bytes] = {}
    downloads: list[tuple[str, str]] = []
    url = f"http://127.0.0.1:{server.server_address[1]}/take.mp4"
    monkeypatch.setattr(app, "_signed_url", lambda bucket, path: url)

    def download(bucket: str, path: str) -> bytes:
        downloads.append((bucket, path))
        return big_take

    monkeypatch.setattr(app, "_download", download)
    monkeypatch.setattr(app, "_upload", lambda bucket, path, data, ct: stored.__setitem__((bucket, path), data))
    monkeypatch.setenv("ASSEMBLE__SECRET", "dev")
    try:
        yield app, served, {"stored": stored, "downloads": downloads}
    finally:
        server.shutdown()


def test_a_probe_reads_the_header_not_the_take(world: tuple[Any, Served, dict]):
    app, served, seen = world
    probe = TestClient(app.app).post("/probe", json={"path": "p/t.mp4"}, headers=SECRET).json()
    assert abs(probe["duration_s"] - 16.0) < 0.2 and probe["has_audio"] and not probe["error"]
    assert served.bytes < len(served.data) * 0.15, f"{served.bytes} of {len(served.data)} bytes"
    assert not seen["downloads"]


def test_inspect_probes_and_stores_the_still_in_one_call_reading_a_fraction(world: tuple[Any, Served, dict]):
    app, served, seen = world
    got = TestClient(app.app).post("/inspect", json={"path": "p/t.mp4", "out_path": "p/t.poster.webp"},
                                   headers=SECRET).json()
    assert got["poster_path"] == "p/t.poster.webp" and abs(got["duration_s"] - 16.0) < 0.2 and not got["error"]
    assert seen["stored"][("takes", "p/t.poster.webp")][:4] == b"RIFF"
    assert served.bytes < len(served.data) * 0.4, f"{served.bytes} of {len(served.data)} bytes"
    assert not seen["downloads"]


def test_the_last_frame_reads_the_end_not_the_take(world: tuple[Any, Served, dict]):
    app, served, seen = world
    r = TestClient(app.app).post("/last-frame", json={"path": "p/t.mp4", "out_path": "p/next/last.png"},
                                 headers=SECRET).json()
    assert r == {"path": "p/next/last.png", "error": ""}
    assert seen["stored"][("frames", "p/next/last.png")].startswith(b"\x89PNG")
    assert served.bytes < len(served.data) * 0.3, f"{served.bytes} of {len(served.data)} bytes"


def test_signing_that_fails_falls_back_to_the_whole_file(world: tuple[Any, Served, dict],
                                                         monkeypatch: pytest.MonkeyPatch):
    import httpx

    app, _served, seen = world

    def refuse(bucket: str, path: str) -> str:
        raise httpx.ConnectError("no storage")

    monkeypatch.setattr(app, "_signed_url", refuse)
    probe = TestClient(app.app).post("/probe", json={"path": "p/t.mp4"}, headers=SECRET).json()
    assert abs(probe["duration_s"] - 16.0) < 0.2 and seen["downloads"] == [("takes", "p/t.mp4")]


def test_a_cut_downloads_each_take_once_per_instance(world: tuple[Any, Served, dict]):
    app, _served, seen = world
    client = TestClient(app.app)
    body = {"clips": [{"path": "p/t.mp4", "in_s": 0, "use_s": 1}], "out_path": "p/cut.mp4"}
    for _ in range(2):
        r = client.post("/cut", json=body, headers=SECRET).json()
        assert r["path"] == "p/cut.mp4" and not r["error"], r
    assert seen["downloads"] == [("takes", "p/t.mp4")], "the second cut reads the take from this instance's disk"


def test_the_signed_url_is_minted_by_assemble_for_five_minutes(monkeypatch: pytest.MonkeyPatch):
    import httpx

    app = load_app()
    sent: dict[str, Any] = {}

    def post(url: str, json: dict, headers: dict, timeout: float) -> httpx.Response:
        sent.update(url=url, json=json)
        return httpx.Response(200, json={"signedURL": "/object/sign/takes/p/t.mp4?token=abc"},
                              request=httpx.Request("POST", url))

    monkeypatch.setenv("SUPABASE__URL", "http://sb.local")
    monkeypatch.setattr(app.httpx, "post", post)
    assert app._signed_url("takes", "p/t.mp4") == "http://sb.local/storage/v1/object/sign/takes/p/t.mp4?token=abc"
    assert sent == {"url": "http://sb.local/storage/v1/object/sign/takes/p/t.mp4", "json": {"expiresIn": 300}}
    assert Path(app.__file__).name == "app.py"
