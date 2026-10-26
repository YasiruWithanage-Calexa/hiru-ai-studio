# hiru-assemble

ffmpeg on Cloud Run: the last frame of an accepted take becomes the first frame of the shot that
carries on from it, and every uploaded take is probed for its duration. No model, no charge.

| Route | What it does |
|---|---|
| `POST /last-frame` | `{bucket, path, out_bucket, out_path}` → the take's true last frame as a PNG |
| `POST /probe` | `{bucket, path}` → `{duration_s, width, height, has_audio}` |
| `GET /health` | Whether ffmpeg is on the PATH |

Auth is one shared secret in `X-Assemble-Secret` (`ASSEMBLE__SECRET`); with none set it refuses
every request. It reads and writes the same Supabase project as the API
(`SUPABASE__URL`, `SUPABASE__SERVICE_ROLE_KEY`).

## Run it locally

Needs `ffmpeg` and `ffprobe` on the PATH. Its pins are the API's, so it runs in the API's venv:

```bash
cd infra/assemble
ASSEMBLE__SECRET=dev ../../.venv/Scripts/python -m uvicorn app:app --port 8209
```

and in the API's `.env`: `ASSEMBLE__URL=http://localhost:8209`, `ASSEMBLE__SECRET=dev`.
Without them the API still accepts takes; it says the carried frame could not be made and the
person can upload that frame by hand.
