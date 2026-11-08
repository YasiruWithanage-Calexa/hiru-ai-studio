"""hiru-assemble: ffmpeg on Cloud Run. No model, no charge.

    POST /last-frame   the last frame of a take → the frames bucket (opens a shot that carries on)
    POST /probe        a take's duration, size and whether it has audio
    POST /poster       a take's first frame as a 640 px WebP beside it (a card shows it before any video loads)
    POST /cut          takes → one cut: each trimmed to the part its card keeps, its sound laid across the cuts
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


class PosterRequest(BaseModel):
    bucket: str = "takes"
    path: str = ""
    out_path: str = ""


class ProbeRequest(BaseModel):
    bucket: str = "takes"
    path: str = ""


class ProbeResult(BaseModel):
    duration_s: float = 0.0
    width: int = 0
    height: int = 0
    has_audio: bool = False
    error: str = ""


class Clip(BaseModel):
    """One take in a cut (contracts.adam.editorial.Clip): the part kept, and how its sound reaches across the cuts."""

    bucket: str = "takes"
    path: str = ""
    in_s: float = 0.0  # where the kept part starts in the take
    use_s: float = 0.0  # how long it plays
    lead_s: float = 0.0  # its sound starts this much before its picture (a J cut); needs lead_s <= in_s
    tail_s: float = 0.0  # its sound runs this much past its picture (an L cut)


class CutRequest(BaseModel):
    clips: list[Clip]
    out_bucket: str = "takes"
    out_path: str = ""


class CutResult(BaseModel):
    path: str = ""
    duration_s: float = 0.0
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


def cut_command(sources: list[Path], clips: list[Clip], has_audio: list[bool], out: Path) -> list[str]:
    """The ffmpeg call for a cut. Pictures are trimmed and joined end to end; each clip's sound is trimmed to the part
    kept plus its lead and tail, delayed to where it starts on the timeline (its picture's start minus its lead), and
    mixed with the others at full level. A take with no sound adds none: the cut is silent there."""
    args = ["ffmpeg", "-nostdin", "-y"]
    for src in sources:
        args += ["-i", str(src)]
    parts: list[str] = []
    audio: list[str] = []
    at = 0.0
    for i, clip in enumerate(clips):
        end = clip.in_s + clip.use_s
        parts.append(f"[{i}:v]trim=start={clip.in_s}:end={end},setpts=PTS-STARTPTS,fps=25,format=yuv420p[v{i}]")
        if has_audio[i]:
            lead = min(clip.lead_s, clip.in_s, at)  # nothing can arrive before the cut begins
            delay = round((at - lead) * 1000)
            parts.append(f"[{i}:a]atrim=start={clip.in_s - lead}:end={end + clip.tail_s},asetpts=PTS-STARTPTS,"
                         f"aresample=48000,aformat=channel_layouts=mono,adelay={delay}:all=1[a{i}]")
            audio.append(f"[a{i}]")
        at += clip.use_s
    joined = "".join(f"[v{i}]" for i in range(len(clips)))
    parts.append(f"{joined}concat=n={len(clips)}:v=1:a=0[v]")
    maps = ["-map", "[v]"]
    if audio:
        parts.append(f"{''.join(audio)}amix=inputs={len(audio)}:normalize=0:duration=longest,atrim=end={at}[a]")
        maps += ["-map", "[a]", "-c:a", "aac"]
    return [*args, "-filter_complex", ";".join(parts), *maps, "-c:v", "libx264", "-pix_fmt", "yuv420p", str(out)]


@app.post("/cut", response_model=CutResult)
def cut(body: CutRequest, x_assemble_secret: str | None = Header(default=None)) -> CutResult:
    """One scene's cut (plan/2026-11-04b Phase 9). Each clip keeps `use_s` from `in_s`; a pre-lap or a carry reaches
    into its neighbour's picture. A lead the take cannot give (no footage before `in_s`) is dropped, never invented."""
    _authorize(x_assemble_secret)
    if not body.clips or not body.out_path or any(not c.path or c.use_s <= 0 for c in body.clips):
        raise HTTPException(status_code=400, detail="clips (with a path and a length) and out_path are required")
    with tempfile.TemporaryDirectory() as tmp:
        sources, has_audio = [], []
        for i, clip in enumerate(body.clips):
            src = Path(tmp) / f"in{i}"
            try:
                src.write_bytes(_download(clip.bucket, clip.path))
            except httpx.HTTPError as exc:
                _logger.warning("download failed: %s", exc)
                return CutResult(error="could not read a take")
            info = probe_file(src)
            if info.error or clip.in_s + clip.use_s > info.duration_s + 0.1:
                return CutResult(error=f"take {i + 1} is shorter than the part the card keeps")
            sources.append(src)
            has_audio.append(info.has_audio)
        out = Path(tmp) / "cut.mp4"
        try:
            _run(cut_command(sources, body.clips, has_audio, out), timeout=600)
        except Exception as exc:
            _logger.warning("cut failed: %s", exc)
            return CutResult(error="could not make the cut")
        done = probe_file(out)
        try:
            _upload(body.out_bucket, body.out_path, out.read_bytes(), "video/mp4")
        except httpx.HTTPError as exc:
            _logger.warning("upload failed: %s", exc)
            return CutResult(error="could not store the cut")
    return CutResult(path=body.out_path, duration_s=done.duration_s)


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


@app.post("/poster", response_model=LastFrameResult)
def poster(body: PosterRequest, x_assemble_secret: str | None = Header(default=None)) -> LastFrameResult:
    """A still from the start of a take, 640 px wide, WebP: stored beside the take so its card needs no video."""
    _authorize(x_assemble_secret)
    if not body.path or not body.out_path:
        raise HTTPException(status_code=400, detail="path and out_path are required")
    with tempfile.TemporaryDirectory() as tmp:
        src = Path(tmp) / "in"
        dst = Path(tmp) / "out.webp"
        try:
            src.write_bytes(_download(body.bucket, body.path))
        except httpx.HTTPError as exc:
            _logger.warning("download failed: %s", exc)
            return LastFrameResult(error="could not read the take")
        try:
            # 0.1 s in, not 0: the very first frame of a generated clip is often a black fade-in.
            _run(["ffmpeg", "-nostdin", "-y", "-ss", "0.1", "-i", str(src), "-frames:v", "1",
                  "-vf", "scale='min(640,iw)':-2", "-c:v", "libwebp", "-quality", "75", str(dst)])
        except Exception as exc:
            _logger.warning("poster failed: %s", exc)
            return LastFrameResult(error="could not make a still of the take")
        try:
            _upload(body.bucket, body.out_path, dst.read_bytes(), "image/webp")
        except httpx.HTTPError as exc:
            _logger.warning("upload failed: %s", exc)
            return LastFrameResult(error="could not store the still")
    return LastFrameResult(path=body.out_path)


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
