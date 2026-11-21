# hiru-assemble

ffmpeg on Cloud Run: the last frame of an accepted take becomes the first frame of the shot that
carries on from it, and every uploaded take is probed for its duration. No model, no charge.

| Route | What it does |
|---|---|
| `POST /last-frame` | `{bucket, path, out_bucket, out_path}` → the take's true last frame as a PNG |
| `POST /probe` | `{bucket, path}` → `{duration_s, width, height, has_audio}` |
| `POST /poster` | `{bucket, path, out_path}` → a 640 px WebP still beside the take |
| `POST /inspect` | `{bucket, path, out_path}` → the probe and the still in one call (`poster_path`); `video_render` calls it once per stored take (plan/2026-11-21 D8) |
| `POST /cut` | takes → one cut, each trimmed to the part its card keeps |
| `GET /health` | Whether ffmpeg is on the PATH |

**Only the bytes ffmpeg needs** (plan/2026-11-21 D7): for a probe, a poster, a last frame and `/inspect` it mints its
own 300 s signed URL and ffmpeg reads it with Range requests (the index, a moment at the start, the last second). If
signing fails it downloads the whole file as before. `/cut` needs whole files: it keeps each take it read on the
instance's disk (`FILES__CACHE_DIR/assemble`, else the temp folder; `ASSEMBLE__CACHE_MAX_MB`, default 512), so a re-cut
downloads nothing. On Cloud Run that folder is memory: keep the cap well under the service's memory.

Auth is one shared secret in `X-Assemble-Secret` (`ASSEMBLE__SECRET`); with none set it refuses
every request. It reads and writes the same Supabase project as the API
(`SUPABASE__URL`, `SUPABASE__SERVICE_ROLE_KEY`).

## Run it locally

Needs `ffmpeg` and `ffprobe` on the PATH. Its pins are the API's, so it runs in the API's venv:

```bash
cd infra/assemble
ASSEMBLE__SECRET=dev ../../.venv/Scripts/python -m uvicorn app:app --port 8220
```

and in `.env` (read by the API and `hiru-video-render`): `ASSEMBLE__URL=http://localhost:8220`,
`ASSEMBLE__SECRET=dev`. `scripts/start-functions.ps1` starts it on 8220 with the `.env` secret
(`-Only hiru-assemble` to restart it alone).
Without them the API still accepts takes; it says the carried frame could not be made and the
person can upload that frame by hand.
