"""What a take did, measured (no model): camera motion (lab/camera_moves' phase correlation on the top 40 % of the
frame), scene cuts (a frame-to-frame jump far above the take's own motion), and when speech starts and ends (audio
energy over the ambience floor). numpy + ffmpeg only.

    python lab/timecodes/measure.py <take.mp4> [...]
"""
from __future__ import annotations

import json
import subprocess
import sys

import numpy as np

W, H, FPS = 320, 180, 8


def frames(path: str) -> np.ndarray:
    raw = subprocess.run(["ffmpeg", "-loglevel", "error", "-i", path, "-vf", f"fps={FPS},scale={W}:{H},format=gray",
                          "-f", "rawvideo", "-"], capture_output=True, check=True).stdout
    return np.frombuffer(raw, np.uint8).reshape(-1, H, W).astype(float)


def shift(a: np.ndarray, b: np.ndarray) -> tuple[int, int]:
    a, b = a[: int(H * .4)], b[: int(H * .4)]
    win = np.outer(np.hanning(a.shape[0]), np.hanning(a.shape[1]))
    fa, fb = np.fft.fft2(a * win), np.fft.fft2(b * win)
    r = np.fft.ifft2(fa * fb.conj() / (np.abs(fa * fb.conj()) + 1e-9)).real
    y, x = np.unravel_index(r.argmax(), r.shape)
    y = y - r.shape[0] if y > r.shape[0] // 2 else y
    x = x - r.shape[1] if x > r.shape[1] // 2 else x
    return int(x), int(y)


def cuts(f: np.ndarray) -> list[float]:
    """Times (s) of frame-to-frame jumps 6x over the take's median change and over 18 grey levels: a scene cut."""
    d = np.array([np.abs(f[i + 1] - f[i]).mean() for i in range(len(f) - 1)])
    floor = float(np.median(d)) or 1.0
    return [round((i + 1) / FPS, 2) for i, v in enumerate(d) if v > 6 * floor and v > 18]


def speech(path: str, hop: float = 0.05) -> dict:
    """First and last moment the audio rises well over its quiet floor (rain/room), and the loud spans."""
    raw = subprocess.run(["ffmpeg", "-loglevel", "error", "-i", path, "-ac", "1", "-ar", "16000", "-f", "s16le", "-"],
                         capture_output=True, check=True).stdout
    a = np.frombuffer(raw, np.int16).astype(float)
    if not len(a):
        return {"audio": False}
    n = int(16000 * hop)
    rms = np.array([np.sqrt(np.mean(a[i:i + n] ** 2)) for i in range(0, len(a) - n, n)])
    smooth = np.convolve(rms, np.ones(3) / 3, mode="same")
    floor = float(np.percentile(smooth, 20)) or 1.0
    loud = smooth > max(3.0 * floor, floor + 400)
    spans, start = [], None
    for i, v in enumerate(list(loud) + [False]):
        if v and start is None:
            start = i
        elif not v and start is not None:
            if (i - start) * hop >= 0.25:
                spans.append([round(start * hop, 2), round(i * hop, 2)])
            start = None
    return {"audio": True, "first_s": spans[0][0] if spans else None, "last_s": spans[-1][1] if spans else None,
            "spans": spans, "length_s": round(len(a) / 16000, 2)}


def measure(path: str) -> dict:
    f = frames(path)
    s = np.array([shift(f[i], f[i + 1]) for i in range(len(f) - 1)])
    xy = np.cumsum(s, axis=0)
    return {"take": path, "frames": len(f), "path_px": int(np.abs(s).sum()), "net_x": int(xy[-1][0]),
            "net_y": int(xy[-1][1]), "cuts_s": cuts(f), "speech": speech(path)}


if __name__ == "__main__":
    for p in sys.argv[1:]:
        print(json.dumps(measure(p), ensure_ascii=False))
