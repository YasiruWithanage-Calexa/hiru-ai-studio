"""A provider that calls nobody. For tests and localhost only (`VIDEO__FAKE_PROVIDER=true`).

It lets the whole path - dispatch, claim, store, record, and the browser playing the take - run for free and
deterministically. It proves OUR code, not Google's: a real take on localhost is what notices a provider changing
under us. Nothing here costs money, so a person can press Generate as often as they like while testing.

Returns the same shape every real provider returns. The clip is `placeholder.mp4` next to this file: a real, playable
2 s H.264 test pattern at 256x144 (~12 KB), made once with `ffmpeg -f lavfi -i testsrc2=size=256x144:rate=12:duration=2
-c:v libx264 -crf 36 -pix_fmt yuv420p -movflags +faststart`.
Usage numbers are fixed so a test can assert them.
"""
from __future__ import annotations

from pathlib import Path

PLACEHOLDER_MP4 = (Path(__file__).with_name("placeholder.mp4")).read_bytes()


def generate(built: dict, ref_bytes: dict, **_ignored: object) -> dict:
    """Same return shape as `omni.generate` / `veo.generate`."""
    return {"data": PLACEHOLDER_MP4, "mime": "video/mp4", "provider_id": "fake-take",
            "prompt_tokens": 100, "completion_tokens": 1000,
            "provider_seconds": int(built["config"]["duration_seconds"])}
