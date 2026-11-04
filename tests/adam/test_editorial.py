"""Phase 9 (plan/2026-11-04b §5.6): the final cut trims a take to the part its card keeps and lays sound across cuts.

Real ffmpeg (skipped where it is not installed): a 2 s reaction cut from a 4 s take, and a pre-lap, are checked in the
length of the picture and in the sound itself (a tone that must arrive a second before its picture)."""
from __future__ import annotations

import importlib.util
import math
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from contracts.adam.editorial import plan_cuts
from contracts.adam.plan import ShotCard

ROOT = Path(__file__).resolve().parents[2]
needs_ffmpeg = pytest.mark.skipif(not (shutil.which("ffmpeg") and shutil.which("ffprobe")), reason="needs ffmpeg")
RATE = 8000
LOUD = 50  # a tone that is there is at least this many times stronger than one that is not


def load_app() -> Any:
    spec = importlib.util.spec_from_file_location("assemble_app_cut", ROOT / "infra" / "assemble" / "app.py")
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules["assemble_app_cut"] = module
    spec.loader.exec_module(module)
    return module


def take(tmp: Path, name: str, colour: str, hz: int | None, seconds: int = 4) -> bytes:
    out = tmp / f"{name}.mp4"
    args = ["ffmpeg", "-nostdin", "-y", "-f", "lavfi", "-i", f"color=c={colour}:s=64x36:d={seconds}:r=25"]
    if hz:
        args += ["-f", "lavfi", "-i", f"sine=frequency={hz}:duration={seconds}:sample_rate=48000"]
    subprocess.run([*args, "-pix_fmt", "yuv420p", "-shortest", str(out)], check=True, capture_output=True)  # noqa: S603
    return out.read_bytes()


def pcm(data: bytes) -> list[float]:
    raw = subprocess.run(["ffmpeg", "-nostdin", "-i", "pipe:0", "-vn", "-ac", "1", "-ar", str(RATE),  # noqa: S603, S607
                          "-f", "s16le", "-"], input=data, capture_output=True, check=True).stdout
    return [int.from_bytes(raw[i:i + 2], "little", signed=True) / 32768 for i in range(0, len(raw) - 1, 2)]


def power(samples: list[float], hz: int, start: float, end: float) -> float:
    """Goertzel: how much of `hz` is in the window."""
    window = samples[int(start * RATE): int(end * RATE)]
    k = 2 * math.cos(2 * math.pi * hz / RATE)
    s1 = s2 = 0.0
    for x in window:
        s1, s2 = x + k * s1 - s2, s1
    return (s1 * s1 + s2 * s2 - k * s1 * s2) / max(1, len(window)) ** 2


def run_cut(monkeypatch: pytest.MonkeyPatch, clips: list[dict[str, Any]],
            takes: dict[str, bytes]) -> tuple[dict[str, Any], bytes]:
    app = load_app()
    store = {("takes", f"p/{k}.mp4"): v for k, v in takes.items()}
    monkeypatch.setattr(app, "_download", lambda bucket, path: store[(bucket, path)])
    monkeypatch.setattr(app, "_upload", lambda bucket, path, data, ct: store.__setitem__((bucket, path), data))
    monkeypatch.setenv("ASSEMBLE__SECRET", "dev")
    body = {"clips": [{"path": f"p/{c['take']}.mp4", **{k: v for k, v in c.items() if k != "take"}} for c in clips],
            "out_path": "p/cut.mp4"}
    result = TestClient(app.app).post("/cut", json=body, headers={"X-Assemble-Secret": "dev"}).json()
    return dict(result), store.get(("takes", "p/cut.mp4"), b"")


@needs_ffmpeg
def test_a_two_second_reaction_is_cut_from_a_four_second_take(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    takes = {"a": take(tmp_path, "a", "red", 440), "b": take(tmp_path, "b", "blue", 880)}
    clips = [{"take": "a", "in_s": 0, "use_s": 4}, {"take": "b", "in_s": 0, "use_s": 2}]
    result, cut = run_cut(monkeypatch, clips, takes)
    assert result["error"] == "" and abs(result["duration_s"] - 6.0) < 0.15  # 4 s whole, then 2 s of a 4 s take
    samples = pcm(cut)
    assert power(samples, 880, 4.2, 5.8) > LOUD * power(samples, 880, 0.5, 3.5) + 1e-9


@needs_ffmpeg
def test_a_pre_lap_arrives_a_second_before_its_picture(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    takes = {"a": take(tmp_path, "a", "red", 440), "b": take(tmp_path, "b", "blue", 880)}
    cards = [ShotCard.model_validate({"number": 1, "moments": ["m1"], "size": "CU", "take_s": 4, "use_s": 2.0}),
             ShotCard.model_validate({"number": 2, "moments": ["m2"], "size": "CU", "take_s": 4, "use_s": 2.0,
                                      "in_s": 1.0, "sound": {"pre_lap": "the ring"}})]
    clips = plan_cuts(cards, editorial=True)
    assert [(c.start_s, c.lead_s) for c in clips] == [(0.0, 0.0), (2.0, 1.0)]
    result, cut = run_cut(monkeypatch, [{"take": "ab"[i], "in_s": c.in_s, "use_s": c.use_s, "lead_s": c.lead_s,
                                         "tail_s": c.tail_s} for i, c in enumerate(clips)], takes)
    assert result["error"] == "" and abs(result["duration_s"] - 4.0) < 0.15
    samples = pcm(cut)
    quiet = power(samples, 880, 0.2, 0.8)  # before the pre-lap: only the first take's tone
    early = power(samples, 880, 1.2, 1.8)  # under the end of the first picture: the second take's sound has arrived
    assert early > LOUD * quiet + 1e-9
    assert power(samples, 440, 0.2, 0.8) > LOUD * power(samples, 440, 2.5, 3.5) + 1e-9  # and the first has ended


@needs_ffmpeg
def test_a_take_with_no_sound_is_silent_in_the_cut_and_the_rest_still_plays(tmp_path: Path,
                                                                           monkeypatch: pytest.MonkeyPatch):
    takes = {"a": take(tmp_path, "a", "red", None), "b": take(tmp_path, "b", "blue", 880)}
    clips = [{"take": "a", "in_s": 0, "use_s": 2}, {"take": "b", "in_s": 0, "use_s": 2}]
    result, cut = run_cut(monkeypatch, clips, takes)
    assert result["error"] == "" and abs(result["duration_s"] - 4.0) < 0.15
    samples = pcm(cut)
    assert power(samples, 880, 2.3, 3.7) > LOUD * power(samples, 880, 0.2, 1.8) + 1e-9


@needs_ffmpeg
def test_a_kept_part_longer_than_the_take_is_refused_not_invented(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    result, cut = run_cut(monkeypatch, [{"take": "a", "in_s": 3, "use_s": 2}], {"a": take(tmp_path, "a", "red", 440)})
    assert "shorter" in result["error"] and cut == b""


def test_the_cut_needs_the_shared_secret_and_clips(monkeypatch: pytest.MonkeyPatch):
    client = TestClient(load_app().app)
    monkeypatch.setenv("ASSEMBLE__SECRET", "dev")
    assert client.post("/cut", json={"clips": []}).status_code == 401
    assert client.post("/cut", json={"clips": []}, headers={"X-Assemble-Secret": "dev"}).status_code == 400
