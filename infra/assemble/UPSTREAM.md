# assemble — fork record

Forked from PromptMotion `infra/assemble/` at commit **1d748dc** (2026-10-19), as PLAN.md §2.1
describes.

| Hiru file | Upstream file | What was kept |
|---|---|---|
| `app.py` | `app.py` | `/last-frame` with `-sseof -1 -update 1` (the true last frame, not one a second early); paths, never signed URLs; one shared secret, refusing every request when none is set; ffmpeg's stderr tail as the error; `/health` |
| `Dockerfile` | `Dockerfile` | ffmpeg from Debian, one worker |

## Intentional divergences

1. **Only `/last-frame` and `/probe`.** `/join` (the final cut) and the colour looks are not
   carried yet (PLAN.md §2.1: "`/join` is kept for later"); `/probe` is new: the API records a
   take's duration and warns when it is not the shot's length.
2. **Storage over HTTP** (`httpx`, service role) instead of the supabase-py client, so the image
   carries no SDK. Buckets are Hiru's: `takes` in, `frames` out.
3. **PNG out**, not JPEG: the carried frame is the next shot's first frame, handed to Flow.
4. No `at_seconds` trim: Hiru takes are not trimmed before the join (there is no join yet).
5. **Signed URLs inside the service** (plan/2026-11-21 D7). Upstream reads whole files by path. Here callers still send
   paths, but for `/probe`, `/poster`, `/last-frame` and the new `/inspect` the service mints its own 300 s signed URL
   and hands it to ffmpeg, which reads with Range. The URL never leaves the process. `-sseof -1 -update 1` is kept.

6. **Cloud Storage** (plan/2026-11-27). With `FILES__BACKEND=gcs` it reads and writes the media bucket as its own
   service account and signs nothing (the whole take is read, inside the region). Its copy of the addresses is held
   equal to `hiru_ai/core/media.py` by `tests/infra/test_assemble_gcs.py`.
