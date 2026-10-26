"""hiru-assemble: ffmpeg on Cloud Run. No model, no charge.

    POST /last-frame   the last frame of a take → the frames bucket (opens a shot that carries on)
    POST /probe        a take's duration, size and whether it has audio
    GET  /health       whether ffmpeg is on the PATH

Forked from PromptMotion `infra/assemble/app.py` (1d748dc; see UPSTREAM.md). A Cloud Run
SERVICE, not a function: it needs ffmpeg in the image. Self-contained: it talks to Supabase
Storage over HTTP with the service role and to ffmpeg, and imports nothing from this repo.

WHAT IS LOAD-BEARING (kept from upstream):

  * KEEP DECODING AND KEEP THE LAST FRAME (`-sseof -1 -update 1`, NO `-frames:v 1`). With
    `-frames:v 1` "the last frame" is the first frame after the seek, a second early, and every
    carried shot starts a second back in the previous take's action.
  * PATHS, NEVER SIGNED URLS. It reads and writes the private buckets itself.
  * ONE SHARED SECRET (`X-Assemble-Secret`) is the whole auth story; the API is the only caller.
    With no secret configured it REFUSES every request rather than running open.
"""
from __future__ import annotations

import logging
import os
import secrets
import shutil
import subprocess
import tempfile
from pathlib import Path

import httpx
from fastapi import FastAPI, Header, HTTPException
from pydantic import BaseModel

logging.basicConfig(level=logging.INFO)
_logger = logging.getLogger("assemble")

app = FastAPI(title="hiru-assemble")


class LastFrameRequest(BaseModel):
    bucket: str = "takes"
    path: str = ""
    out_bucket: str = "frames"
    out_path: str = ""


class LastFrameResult(BaseModel):
    path: str = ""
    error: str = ""


class ProbeRequest(BaseModel):
    bucket: str = "takes"
    path: str = ""


class ProbeResult(BaseModel):
    duration_s: float = 0.0
    width: int = 0
    height: int = 0
    has_audio: bool = False
    error: str = ""


def _storage() -> tuple[str, dict[str, str]]:
    base = os.environ.get("SUPABASE__URL", "http://127.0.0.1:54321").rstrip("/")
    key = os.environ.get("SUPABASE__SERVICE_ROLE_KEY", "")
    return f"{base}/storage/v1/object", {"apikey": key, "Authorization": f"Bearer {key}"}


def _download(bucket: str, path: str) -> bytes:
    url, headers = _storage()
    r = httpx.get(f"{url}/{bucket}/{path}", headers=headers, timeout=120.0)
    r.raise_for_status()
    return r.content


def _upload(bucket: str, path: str, data: bytes, content_type: str) -> None:
    url, headers = _storage()
    r = httpx.post(f"{url}/{bucket}/{path}", content=data, timeout=120.0,
                   headers={**headers, "Content-Type": content_type, "x-upsert": "true"})
    r.raise_for_status()


def _authorize(secret: str | None) -> None:
    expected = os.environ.get("ASSEMBLE__SECRET", "")
    if not expected:
        raise HTTPException(status_code=503, detail="not configured")
    if not secret or not secrets.compare_digest(secret, expected):
        raise HTTPException(status_code=401, detail="unauthorized")


def _run(args: list[str], timeout: int = 120) -> None:
    """One ffmpeg call. Raises with the tail of stderr, where ffmpeg explains itself."""
    proc = subprocess.run(args, capture_output=True, timeout=timeout, check=False)  # noqa: S603
    if proc.returncode != 0:
        tail = proc.stderr.decode("utf-8", "replace").strip().splitlines()[-6:]
        raise RuntimeError(" / ".join(tail) or f"{args[0]} exited {proc.returncode}")


def probe_file(path: Path) -> ProbeResult:
    out = subprocess.run(  # noqa: S603
        ["ffprobe", "-v", "error", "-show_entries", "stream=codec_type,width,height:format=duration",  # noqa: S607
         "-of", "default=noprint_wrappers=1", str(path)], capture_output=True, timeout=60, check=False)
    info = ProbeResult()
    for line in out.stdout.decode("utf-8", "replace").splitlines():
        key, _, value = line.partition("=")
        if key == "width" and value.strip().isdigit() and not info.width:
            info.width = int(value)
        elif key == "height" and value.strip().isdigit() and not info.height:
            info.height = int(value)
        elif key == "codec_type" and value.strip() == "audio":
            info.has_audio = True
        elif key == "duration":
            try:
                info.duration_s = float(value)
            except ValueError:
                pass
    if out.returncode != 0:
        info.error = "could not read the take"
    return info


@app.get("/health")
def health() -> dict[str, object]:
    return {"ok": bool(shutil.which("ffmpeg")), "ffmpeg": shutil.which("ffmpeg") or ""}


@app.post("/probe", response_model=ProbeResult)
def probe(body: ProbeRequest, x_assemble_secret: str | None = Header(default=None)) -> ProbeResult:
    _authorize(x_assemble_secret)
    if not body.path:
        raise HTTPException(status_code=400, detail="path is required")
    with tempfile.TemporaryDirectory() as tmp:
        src = Path(tmp) / "in"
        try:
            src.write_bytes(_download(body.bucket, body.path))
        except httpx.HTTPError:
            return ProbeResult(error="could not read the take")
        return probe_file(src)


@app.post("/last-frame", response_model=LastFrameResult)
def last_frame(body: LastFrameRequest,
               x_assemble_secret: str | None = Header(default=None)) -> LastFrameResult:
    """The final frame of a take as a PNG in the frames bucket (the next shot's first frame)."""
    _authorize(x_assemble_secret)
    if not body.path or not body.out_path:
        raise HTTPException(status_code=400, detail="path and out_path are required")
    with tempfile.TemporaryDirectory() as tmp:
        src = Path(tmp) / "in"
        dst = Path(tmp) / "out.png"
        try:
            src.write_bytes(_download(body.bucket, body.path))
        except httpx.HTTPError as exc:
            _logger.warning("download failed: %s", exc)
            return LastFrameResult(error="could not read the take")
        try:
            _run(["ffmpeg", "-nostdin", "-y", "-sseof", "-1", "-i", str(src), "-update", "1", str(dst)])
        except Exception as exc:
            _logger.warning("last-frame failed: %s", exc)
            return LastFrameResult(error="could not read the last frame of the take")
        try:
            _upload(body.out_bucket, body.out_path, dst.read_bytes(), "image/png")
        except httpx.HTTPError as exc:
            _logger.warning("upload failed: %s", exc)
            return LastFrameResult(error="could not store the frame")
    return LastFrameResult(path=body.out_path)
