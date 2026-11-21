"""hiru-assemble: ffmpeg on Cloud Run. No model, no charge.

    POST /last-frame   the last frame of a take → the frames bucket (opens a shot that carries on)
    POST /probe        a take's duration, size and whether it has audio
    POST /poster       a take's first frame as a 640 px WebP beside it (a card shows it before any video loads)
    POST /inspect      /probe and /poster in one call (plan/2026-11-21 D7: video_render calls it once per stored take)
    POST /cut          takes → one cut: each trimmed to the part its card keeps, its sound laid across the cuts
    GET  /health       whether ffmpeg is on the PATH

Forked from PromptMotion `infra/assemble/app.py` (1d748dc; see UPSTREAM.md). A Cloud Run
SERVICE, not a function: it needs ffmpeg in the image. Self-contained: it talks to Supabase
Storage over HTTP with the service role and to ffmpeg, and imports nothing from this repo.

WHAT IS LOAD-BEARING (kept from upstream):

  * KEEP DECODING AND KEEP THE LAST FRAME (`-sseof -1 -update 1`, NO `-frames:v 1`). With
    `-frames:v 1` "the last frame" is the first frame after the seek, a second early, and every
    carried shot starts a second back in the previous take's action.
  * PATHS, NEVER SIGNED URLS ON THE WIRE. Callers send paths; it reads and writes the private buckets itself. To read
    only the bytes ffmpeg needs (plan/2026-11-21 D7) it mints its OWN 300 s signed URL and hands that to ffprobe/ffmpeg,
    which read with Range: the header for a probe, a moment for a poster, the last second for a last frame. The URL
    never leaves this process. `/cut` needs whole files, so it keeps a small disk copy of each take it read.
  * ONE SHARED SECRET (`X-Assemble-Secret`) is the whole auth story; the API is the only caller.
    With no secret configured it REFUSES every request rather than running open.
"""
from __future__ import annotations

import hashlib
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


class InspectResult(BaseModel):
    duration_s: float = 0.0
    width: int = 0
    height: int = 0
    has_audio: bool = False
    poster_path: str = ""
    error: str = ""


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


SIGNED_URL_S = 300  # long enough for one ffmpeg call; a URL that leaks dies in five minutes


def _signed_url(bucket: str, path: str) -> str:
    """A short-lived signed URL for one object, which ffmpeg reads with Range requests. Raises when it cannot sign."""
    url, headers = _storage()
    r = httpx.post(f"{url}/sign/{bucket}/{path}", json={"expiresIn": SIGNED_URL_S}, headers=headers, timeout=30.0)
    r.raise_for_status()
    answer = r.json()
    signed = str(answer.get("signedURL") or answer.get("signedUrl") or "")
    if not signed:
        raise httpx.HTTPError("no signed URL in the answer")
    if signed.startswith("http"):
        return signed
    return f"{url.removesuffix('/object')}{signed if signed.startswith('/') else '/' + signed}"


def _input(bucket: str, path: str, tmp: Path) -> str:
    """What ffmpeg reads: the signed URL (only the bytes it needs cross the internet), or, when signing fails, the whole
    file downloaded into `tmp` as before. Raises httpx.HTTPError when neither works."""
    try:
        return _signed_url(bucket, path)
    except (httpx.HTTPError, ValueError) as exc:
        _logger.warning("signing failed (%s); downloading the whole file", exc)
    src = tmp / "in"
    src.write_bytes(_download(bucket, path))
    return str(src)


# /cut's disk copy (D7): a cut needs whole files; a take re-cut after a card's trim changes is read from this disk.
_CACHE_SUFFIX = ".take"


def _cache_dir() -> Path:
    base = os.environ.get("FILES__CACHE_DIR", "").strip()
    return Path(base) / "assemble" if base else Path(tempfile.gettempdir()) / "hiru-assemble"


def _cache_cap() -> int:
    try:
        return int(float(os.environ.get("ASSEMBLE__CACHE_MAX_MB", "512")) * 1024**2)
    except ValueError:
        return 512 * 1024**2


def _cached_take(bucket: str, path: str) -> Path:
    """The whole take on this instance's disk, downloaded on first use. Takes are written once (a path names one file
    forever), which is what makes a copy keyed by path correct."""
    folder = _cache_dir()
    file = folder / (hashlib.sha256(f"{bucket}/{path}".encode()).hexdigest() + _CACHE_SUFFIX)
    if file.is_file():
        os.utime(file)  # least recently used goes first
        return file
    folder.mkdir(parents=True, exist_ok=True)
    data = _download(bucket, path)
    part = file.with_name(f"{file.name}.{os.getpid()}.part")
    part.write_bytes(data)
    os.replace(part, file)
    _trim_cache(folder, _cache_cap(), keep=file)
    return file


def _trim_cache(folder: Path, cap: int, keep: Path) -> None:
    entries: list[tuple[float, int, Path]] = []
    for item in folder.glob(f"*{_CACHE_SUFFIX}"):
        try:
            stat = item.stat()
        except OSError:
            continue
        entries.append((stat.st_mtime, stat.st_size, item))
    total = sum(size for _m, size, _i in entries)
    for _mtime, size, item in sorted(entries):
        if total <= cap:
            break
        if item == keep:
            continue
        try:
            item.unlink()
            total -= size
        except OSError:
            continue


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


def probe_file(path: Path | str) -> ProbeResult:
    """ffprobe on a file or a URL (over a URL it reads the header with Range requests, never the whole take)."""
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
            try:
                src = _cached_take(clip.bucket, clip.path)
            except (httpx.HTTPError, OSError) as exc:
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
        try:
            src = _input(body.bucket, body.path, Path(tmp))
        except httpx.HTTPError:
            return ProbeResult(error="could not read the take")
        return probe_file(src)


def _poster(bucket: str, src: str, out_path: str, tmp: Path) -> LastFrameResult:
    dst = tmp / "out.webp"
    try:
        # 0.1 s in, not 0: the very first frame of a generated clip is often a black fade-in. `-ss` before `-i` seeks in
        # the input, so over a URL only the bytes around that point are read.
        _run(["ffmpeg", "-nostdin", "-y", "-ss", "0.1", "-i", src, "-frames:v", "1",
              "-vf", "scale='min(640,iw)':-2", "-c:v", "libwebp", "-quality", "75", str(dst)])
    except Exception as exc:
        _logger.warning("poster failed: %s", exc)
        return LastFrameResult(error="could not make a still of the take")
    try:
        _upload(bucket, out_path, dst.read_bytes(), "image/webp")
    except httpx.HTTPError as exc:
        _logger.warning("upload failed: %s", exc)
        return LastFrameResult(error="could not store the still")
    return LastFrameResult(path=out_path)


@app.post("/poster", response_model=LastFrameResult)
def poster(body: PosterRequest, x_assemble_secret: str | None = Header(default=None)) -> LastFrameResult:
    """A still from the start of a take, 640 px wide, WebP: stored beside the take so its card needs no video."""
    _authorize(x_assemble_secret)
    if not body.path or not body.out_path:
        raise HTTPException(status_code=400, detail="path and out_path are required")
    with tempfile.TemporaryDirectory() as tmp:
        try:
            src = _input(body.bucket, body.path, Path(tmp))
        except httpx.HTTPError as exc:
            _logger.warning("download failed: %s", exc)
            return LastFrameResult(error="could not read the take")
        return _poster(body.bucket, src, body.out_path, Path(tmp))


@app.post("/inspect", response_model=InspectResult)
def inspect(body: PosterRequest, x_assemble_secret: str | None = Header(default=None)) -> InspectResult:
    """plan/2026-11-21 D7/D8: the probe and the poster of one stored take in ONE call over ONE signed URL, so a take
    costs its header and a moment of video, once, when it is stored. `out_path` empty = probe only."""
    _authorize(x_assemble_secret)
    if not body.path:
        raise HTTPException(status_code=400, detail="path is required")
    with tempfile.TemporaryDirectory() as tmp:
        try:
            src = _input(body.bucket, body.path, Path(tmp))
        except httpx.HTTPError:
            return InspectResult(error="could not read the take")
        info = probe_file(src)
        result = InspectResult(**info.model_dump())
        if body.out_path and not info.error:
            still = _poster(body.bucket, src, body.out_path, Path(tmp))
            result.poster_path = still.path
            result.error = still.error
        return result


@app.post("/last-frame", response_model=LastFrameResult)
def last_frame(body: LastFrameRequest,
               x_assemble_secret: str | None = Header(default=None)) -> LastFrameResult:
    """The final frame of a take as a PNG in the frames bucket (the next shot's first frame)."""
    _authorize(x_assemble_secret)
    if not body.path or not body.out_path:
        raise HTTPException(status_code=400, detail="path and out_path are required")
    with tempfile.TemporaryDirectory() as tmp:
        dst = Path(tmp) / "out.png"
        try:
            src = _input(body.bucket, body.path, Path(tmp))
        except httpx.HTTPError as exc:
            _logger.warning("download failed: %s", exc)
            return LastFrameResult(error="could not read the take")
        try:
            # Over a URL `-sseof -1` reads only the last second (and the index); `-update 1` keeps the TRUE last frame.
            _run(["ffmpeg", "-nostdin", "-y", "-sseof", "-1", "-i", src, "-update", "1", str(dst)])
        except Exception as exc:
            _logger.warning("last-frame failed: %s", exc)
            return LastFrameResult(error="could not read the last frame of the take")
        try:
            _upload(body.out_bucket, body.out_path, dst.read_bytes(), "image/png")
        except httpx.HTTPError as exc:
            _logger.warning("upload failed: %s", exc)
            return LastFrameResult(error="could not store the frame")
    return LastFrameResult(path=body.out_path)
