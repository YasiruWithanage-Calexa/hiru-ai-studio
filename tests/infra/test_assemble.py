"""infra/assemble with real ffmpeg (skipped where it is not installed): the TRUE last frame,
the probe, and the shared-secret rule. Storage is stood in for."""
from __future__ import annotations

import importlib.util
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[2]
pytestmark = pytest.mark.skipif(not (shutil.which("ffmpeg") and shutil.which("ffprobe")), reason="needs ffmpeg")


def load_app():  # type: ignore[no-untyped-def]
    spec = importlib.util.spec_from_file_location("assemble_app", ROOT / "infra" / "assemble" / "app.py")
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules["assemble_app"] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def clip(tmp_path: Path) -> bytes:
    """2 s at 25 fps: frames numbered by a red→blue fade, so the last frame is mostly blue."""
    out = tmp_path / "clip.mp4"
    subprocess.run(["ffmpeg", "-nostdin", "-y", "-f", "lavfi", "-i", "color=c=red:s=64x36:d=2:r=25",  # noqa: S603, S607
                    "-vf", "fade=out:st=1:d=1:color=blue", "-pix_fmt", "yuv420p", str(out)],
                   check=True, capture_output=True)
    return out.read_bytes()


def test_last_frame_and_probe(monkeypatch: pytest.MonkeyPatch, clip: bytes):
    app = load_app()
    store: dict[tuple[str, str], bytes] = {("takes", "p/t.mp4"): clip}
    monkeypatch.setattr(app, "_download", lambda bucket, path: store[(bucket, path)])
    monkeypatch.setattr(app, "_upload", lambda bucket, path, data, ct: store.__setitem__((bucket, path), data))
    client = TestClient(app.app)

    monkeypatch.delenv("ASSEMBLE__SECRET", raising=False)
    assert client.post("/probe", json={"path": "p/t.mp4"}).status_code == 503, "no secret: refuses everything"
    monkeypatch.setenv("ASSEMBLE__SECRET", "dev")
    assert client.post("/probe", json={"path": "p/t.mp4"}, headers={"X-Assemble-Secret": "x"}).status_code == 401

    probe = client.post("/probe", json={"path": "p/t.mp4"}, headers={"X-Assemble-Secret": "dev"}).json()
    assert probe["width"] == 64 and abs(probe["duration_s"] - 2.0) < 0.1 and not probe["error"]

    r = client.post("/last-frame", json={"path": "p/t.mp4", "out_path": "p/next/last.png"},
                    headers={"X-Assemble-Secret": "dev"}).json()
    assert r == {"path": "p/next/last.png", "error": ""}
    png = store[("frames", "p/next/last.png")]
    assert png.startswith(b"\x89PNG")
    # The true last frame is the end of the fade (blue), not one a second early (red).
    raw = subprocess.run(["ffmpeg", "-nostdin", "-i", "pipe:0", "-f", "rawvideo", "-pix_fmt", "rgb24", "-"],  # noqa: S607
                         input=png, capture_output=True, check=True).stdout
    r_, g_, b_ = raw[0], raw[1], raw[2]
    assert b_ > r_, (r_, g_, b_)
