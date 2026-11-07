"""Phase 0 of plan/2026-11-06c: map what Omni Flash and Veo 3.1 accept on OUR key, before anything rests on a guess.

    python scripts/video_probe.py                      # free: invalid requests; a 400 names the field
    python scripts/video_probe.py --engine veo_3_1     # one engine
    python scripts/video_probe.py --generate --yes     # PAID: one take per engine, then the same request and seed twice

Needs GOOGLE__API_KEY (the environment or .env). It writes `plan/2026-11-06c/probe/<engine>.json` (every answer,
verbatim) and prints a table of what to set in `contracts/video_gen.py` (`EngineCapability.seed`,
`max_takes_per_call`, `negative_prompt`, `options`, `refs_with_first_frame`, the real reference cap, durations,
aspects, resolutions).

THE FREE PROBES CANNOT BILL. Every probe carries one anchor field that is invalid on purpose (an aspect ratio of
"0:0"), so the provider answers 400 whatever else is in the request. If a probe is ever answered 2xx the script stops
at once and says so: a 2xx may have started a generation. How to read a probe: the 400 names the FIRST thing it
dislikes. A probe that adds field X to a request already invalid in the anchor tells you X is unknown when the error
names X, and that X is accepted (as a name) when the error names only the anchor.

The paid mode is a person's (CLAUDE.md "Smoke scripts write test data / spend money: ask first"). It uses a 4 s, 720p,
no-picture request. Whether a seed repeats a take is measured by running the same request and seed twice and comparing
the bytes' SHA-256 and sizes; "honoured" needs identical bytes, "accepted" is a seed the API takes but does not
repeat. Cost appears in this script's output and in IMPLEMENTED.md only, never in the interface."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import time
from pathlib import Path
from typing import Any

import httpx

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src" / "libs"))
sys.path.insert(0, str(ROOT / "src" / "services" / "video_render"))

from contracts.video_gen import (  # noqa: E402
    ENGINE_CAPABILITIES,
    RenderSpec,
    VideoOverrides,
    VideoSettings,
    build_request,
    resolve,
    spec_for,
)

OUT = ROOT / "plan" / "2026-11-06c" / "probe"
BASE = "https://generativelanguage.googleapis.com"
ANCHOR = "0:0"  # invalid for every engine: a probe carrying it cannot be a valid generation


class Billable(Exception):
    """A probe was answered 2xx: stop, a generation may have started."""


def load_key() -> str:
    key = os.environ.get("GOOGLE__API_KEY", "")
    env = ROOT / ".env"
    if not key and env.exists():
        for line in env.read_text(encoding="utf-8").splitlines():
            if line.startswith("GOOGLE__API_KEY="):
                key = line.split("=", 1)[1].strip().strip('"')
    return key


def post(client: httpx.Client, url: str, body: dict[str, Any]) -> tuple[int, str]:
    resp = client.post(url, json=body, timeout=60.0)
    return resp.status_code, resp.text[:1500]


# ── Omni: POST /v1beta/interactions ───────────────────────────────────────────────────────────────────────────

def omni_body(**patch: Any) -> dict[str, Any]:
    body: dict[str, Any] = {
        "model": ENGINE_CAPABILITIES["omni_flash"].model, "input": [{"type": "text", "text": "probe"}],
        "background": False, "store": False,
        "generation_config": {"video_config": {"task": "text_to_video"}},
        "response_format": {"type": "video", "aspect_ratio": ANCHOR, "resolution": "720p", "duration": "4s",
                            "delivery": "uri"},
    }
    for path, value in patch.items():  # "generation_config.seed" style paths
        node = body
        *parents, leaf = path.split(".")
        for p in parents:
            node = node.setdefault(p, {})
        node[leaf] = value
    return body


OMNI_PROBES: dict[str, dict[str, Any]] = {
    "baseline (anchor only)": {},
    "seed in generation_config": {"generation_config.seed": 1},
    "seed in response_format": {"response_format.seed": 1},
    "seed at top level": {"seed": 1},
    "candidate_count": {"generation_config.candidate_count": 2},
    "negative prompt": {"generation_config.negative_prompt": "blur"},
    "person_generation": {"generation_config.video_config.person_generation": "allow_adult"},
    "generate_audio": {"generation_config.video_config.generate_audio": True},
    "duration 3s": {"response_format.duration": "3s"},
    "duration 10s": {"response_format.duration": "10s"},
    "duration 11s": {"response_format.duration": "11s"},
    "resolution 360p": {"response_format.resolution": "360p"},
    "resolution 1080p": {"response_format.resolution": "1080p"},
    "resolution 4k": {"response_format.resolution": "4k"},
    "resolution 480p": {"response_format.resolution": "480p"},
    "11 images": {"input": [{"type": "image", "mime_type": "image/png", "data": "iVBORw0KGgo="}] * 11
                  + [{"type": "text", "text": "probe"}]},
    "10 images": {"input": [{"type": "image", "mime_type": "image/png", "data": "iVBORw0KGgo="}] * 10
                  + [{"type": "text", "text": "probe"}]},
    "frames first, then text": {"input": [{"type": "image", "mime_type": "image/png", "data": "iVBORw0KGgo="},
                                          {"type": "text", "text": "<FIRST_FRAME> is the opening frame."}],
                                "generation_config.video_config.task": "image_to_video"},
    "references with a start frame": {"input": [{"type": "image", "mime_type": "image/png", "data": "iVBORw0KGgo="}] * 2
                                      + [{"type": "text", "text": "<IMAGE_REF_0> <FIRST_FRAME>"}],
                                      "generation_config.video_config.task": "reference_to_video"},
}


def probe_omni(client: httpx.Client, key: str) -> dict[str, Any]:
    url = f"{BASE}/v1beta/interactions?key={key}"
    return run_probes(client, url, OMNI_PROBES, omni_body)


# ── Veo: POST models/{model}:predictLongRunning ───────────────────────────────────────────────────────────────

IMG = {"inlineData": {"mimeType": "image/png", "data": "iVBORw0KGgo="}}


def veo_body(**patch: Any) -> dict[str, Any]:
    body: dict[str, Any] = {"instances": [{"prompt": "probe"}],
                            "parameters": {"aspectRatio": ANCHOR, "resolution": "720p", "durationSeconds": 4}}
    for path, value in patch.items():
        node: Any = body
        *parents, leaf = path.split(".")
        for p in parents:
            node = node[int(p)] if p.isdigit() else node.setdefault(p, {})
        node[leaf] = value
    return body


VEO_PROBES: dict[str, dict[str, Any]] = {
    "baseline (anchor only)": {},
    "seed": {"parameters.seed": 1},
    "seed above 32 bits": {"parameters.seed": 2**33},
    "sampleCount 2": {"parameters.sampleCount": 2},
    "numberOfVideos 2": {"parameters.numberOfVideos": 2},
    "negativePrompt": {"parameters.negativePrompt": "blur"},
    "personGeneration allow_adult": {"parameters.personGeneration": "allow_adult"},
    "personGeneration allow_all": {"parameters.personGeneration": "allow_all"},
    "generateAudio": {"parameters.generateAudio": True},
    "enhancePrompt": {"parameters.enhancePrompt": True},
    "durationSeconds 5": {"parameters.durationSeconds": 5},
    "durationSeconds 10": {"parameters.durationSeconds": 10},
    "resolution 1080p": {"parameters.resolution": "1080p"},
    "resolution 4k": {"parameters.resolution": "4k"},
    "image (start frame)": {"instances.0.image": IMG},
    "image + lastFrame": {"instances.0.image": IMG, "instances.0.lastFrame": IMG},
    "3 referenceImages": {"instances.0.referenceImages": [{"image": IMG, "referenceType": "asset"}] * 3},
    "4 referenceImages": {"instances.0.referenceImages": [{"image": IMG, "referenceType": "asset"}] * 4},
    "referenceImages + image": {"instances.0.image": IMG,
                                "instances.0.referenceImages": [{"image": IMG, "referenceType": "asset"}]},
}


def probe_veo(client: httpx.Client, key: str, engine: str) -> dict[str, Any]:
    url = f"{BASE}/v1beta/models/{ENGINE_CAPABILITIES[engine].model}:predictLongRunning?key={key}"
    return run_probes(client, url, VEO_PROBES, veo_body)


def run_probes(client: httpx.Client, url: str, probes: dict[str, dict[str, Any]], build: Any) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for name, patch in probes.items():
        status, text = post(client, url, build(**patch))
        if status < 400:
            raise Billable(f"probe {name!r} was answered {status}; a generation may have started. Check your usage.")
        out[name] = {"status": status, "answer": text}
        print(f"  {status}  {name:36s} {first_line(text)}")
        time.sleep(0.4)
    return out


def first_line(text: str) -> str:
    try:
        message = json.loads(text)["error"]["message"]
    except (ValueError, KeyError, TypeError):
        message = text
    return " ".join(str(message).split())[:150]


# ── the paid part ────────────────────────────────────────────────────────────────────────────────────────────

def generate_twice(engine: str, key: str) -> dict[str, Any]:
    """One real take, then the same request and seed twice. Returns what was measured."""
    from video_render.engine import omni, veo

    provider = veo if engine.startswith("veo") else omni
    settings = resolve(VideoSettings(engine=engine), None, VideoOverrides(resolution="720p", duration_s=4),
                       production_aspect="16:9", shot_seconds=4)

    def take(seed: int | None) -> dict[str, Any]:
        prose = "A single clay cup on a wooden table, soft morning light, nobody speaks."
        spec: RenderSpec = spec_for(settings, prose=prose, references=[], seed=seed)
        built = build_request(spec)
        t0 = time.monotonic()
        got = provider.generate(built, {}, api_key=key, base_url=BASE, deadline=time.monotonic() + 900,
                                poll_interval=5.0, download_attempts=5)
        data: bytes = got["data"]
        return {"seed": seed, "bytes": len(data), "sha256": hashlib.sha256(data).hexdigest(),
                "seconds": round(time.monotonic() - t0, 1),
                "usage": {k: got.get(k) for k in ("prompt_tokens", "completion_tokens", "provider_seconds")}}

    seed = 1234
    first, second = take(seed), take(seed)
    return {"first": first, "second": second,
            "identical_bytes": first["sha256"] == second["sha256"],
            "same_size": first["bytes"] == second["bytes"],
            "reading": ("honoured" if first["sha256"] == second["sha256"]
                        else "accepted (taken but not repeated)" if first["bytes"] > 0 else "unknown")}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--engine", choices=sorted(ENGINE_CAPABILITIES), help="probe one engine (default: all)")
    ap.add_argument("--generate", action="store_true", help="PAID: real takes, the same seed twice")
    ap.add_argument("--yes", action="store_true", help="required with --generate")
    args = ap.parse_args()

    key = load_key()
    if not key:
        print("Set GOOGLE__API_KEY (environment or .env).")
        return 2
    if args.generate and not args.yes:
        print("--generate calls the real models (two takes per engine) and costs money. Add --yes to go ahead.")
        return 2
    engines = [args.engine] if args.engine else sorted(ENGINE_CAPABILITIES)
    OUT.mkdir(parents=True, exist_ok=True)
    with httpx.Client() as client:
        for engine in engines:
            print(f"\n== {engine} ({ENGINE_CAPABILITIES[engine].model}) ==")
            try:
                result: dict[str, Any] = {"engine": engine, "model": ENGINE_CAPABILITIES[engine].model,
                                          "probes": probe_omni(client, key) if engine == "omni_flash"
                                          else probe_veo(client, key, engine)}
            except Billable as exc:
                print(f"STOP: {exc}")
                return 1
            if args.generate:
                print("  paid: one take twice with seed 1234 ...")
                result["generate"] = generate_twice(engine, key)
                print(f"  -> {result['generate']['reading']}")
            (OUT / f"{engine}.json").write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"\nAnswers saved under {OUT}. Read them, then set the capability rows in contracts/video_gen.py and "
          "write the findings (and, for --generate, the cost from your usage page) in plan/2026-11-06c/IMPLEMENTED.md.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
