# Storage egress: a stored file crosses the internet once (plan/2026-11-21)

Revision 1 (2026-11-21). Agreed with the person in chat on 2026-11-20/21. Building status: not started (no IMPLEMENTED.md).
Builds on plan/2026-11-08c ("Quiet by default": the API's disk cache 1b, write-once media paths 1d, thumbnails 1c).

Why: Supabase **cached egress** reached 3.31 GB of the free plan's 5 GB this period, ~430 MB a day, while everything
stored is about 1 GB. The browser is NOT the cause: the API's `/files` disk cache downloaded only 8–80 MB a day (8 MB
on 19 Nov, a ~620 MB day). The render WORKERS are: every frame downloads every face/look/place/prop sheet and the
same-setup frame again, in full, with nothing kept between frames or jobs. Egress peaks track `frame_render` jobs
(56 on 13 Nov, 36 on 19 Nov).

## 0. Rules for the chat that builds this

- **No paid call without the person's yes, each time** (model, image, video). Tests run with `OPENAI__API_KEY=` blank.
- **No schema change is applied by the builder.** Applying `upgrade_v23_to_v24.sql` is the person's (phase 5).
- **Write-once is the whole safety argument.** Only `frames`, `references`, `takes` are cached (`IMMUTABLE_BUCKETS`,
  `storage.py`); a path there names one file forever. `documents` overwrite (x-upsert) and are never cached.
- **Both trees have uncommitted work.** Read `git diff` of a file before you edit it. Never stash; use a worktree.
- **Only Shot Planner Raphael stays.** Ignore Adam/David/Jonathan/DaVinci test failures.
- **Every number in section 1 came from read-only queries** (2026-11-20). Re-measure in phase 0; do not trust them.

## 1. What was measured (2026-11-20, read-only)

| What | Value |
|---|---|
| Stored | frames PNG 599 files 755 MB (avg 1.26 MB); references PNG 79 files 171 MB (avg 2.2 MB); takes MP4 83 files 58 MB; thumbs 598 files 16 MB |
| API disk cache | 345 MB of a 5 GB cap, never evicted; 8–80 MB a day first-downloaded |
| Pictures without `.thumb.webp` | 57 frames (116 MB) + 23 references (49 MB), all 13–16 Nov |
| `takes.poster_path` | **column missing in the live DB**: `upgrade_v23_to_v24.sql` was never applied though v25–v28 were |
| Picture format | gpt-image output stored as PNG (`adapters/images.py`: no `output_format`) |

## 2. Causes, biggest first

| # | Cause | Where |
|---|---|---|
| C1 | Frame render downloads each reference for every frame; no reuse in a job or across jobs; a frame just painted is downloaded again when used as a reference | `systems/frame_render/graph.py` `_references` `_board_panel` `_draft_picture`, `board.py` `_pictures`, `faces.py`; `services/frame_render/.../runtime/store.py` |
| C2 | Video render downloads every reference in full per take | `services/video_render/.../engine/render.py:183`, `runtime/store.py` |
| C3 | Assemble downloads the WHOLE video for probe, poster, last frame and cut; upload calls probe and poster separately (two downloads) | `infra/assemble/app.py`, `api/routers/handoff.py:241-242` |
| C4 | `_probe_generated` probes on every VIEW while `duration_s` is empty; a failing probe repeats on every page load (deployed only; local has no `ASSEMBLE__URL`) | `api/routers/handoff.py:163` |
| C5 | Labs and scripts download from Supabase directly | `lab/storyboard/fetch.py`, `lab/portrait_board/fetch.py`, `lab/series_block/live_check.py`, `scripts/board_update_live.py` |
| C6 | 80 pictures have no thumbnail: their tiles load the full PNG (first view only, then the API cache) | storage |
| C7 | Pictures stored as 1–2 MB PNG where WebP would be ~5–10× smaller | `adapters/images.py`, frame/sheet path builders |
| C8 | Generated takes have no poster (column missing, worker makes none) | v24 not applied; `video_render` |
| C9 | A fresh API instance (Cloud Run cold start, another machine) starts with an empty cache; dashboard Storage previews | deployment, habit |

## 3. Decisions

| # | Decision | Why |
|---|---|---|
| D1 | **One cache folder for the API and the workers.** Move `root()`, `_file_for()`, `bucket_dir()` and `_trim()` UNCHANGED from `api/services/file_cache.py` into `libs/hiru_ai/core/file_store.py`; the API imports them | Same hash, same folder: files the API already holds are hits for the workers, and the reverse |
| D2 | **`CachedFiles`** wraps the `Files` port (`download`, `upload`): write-once buckets read disk first, else download once and keep; other buckets pass through. Per-key lock (frames paint in a thread pool: one download per sheet, not N). Atomic write (`.part` + `os.replace`), `.type` file beside it, LRU trim with the API's rule | The API's cache, made sync for workers |
| D3 | **Write-through on upload**: a picture or take a worker stores is also written to the cache, and forgets a remembered 404 for that path | A frame just painted is the next shot's same-setup reference and the video's first frame; it should never be downloaded |
| D4 | **No disk (`FILES__CACHE_MAX_GB=0`, e.g. Cloud Run where `/tmp` is memory)**: `CachedFiles` keeps a bounded in-memory LRU (300 MB) for the life of the process | At least once per sheet per job |
| D5 | Same settings as the API (`FILES__CACHE_DIR`, `FILES__CACHE_MAX_GB`); no new switch, no enable flag | One knob |
| D6 | **Counters**: `CachedFiles` counts hits, misses and bytes from Supabase; every worker job ends with ONE log line `storage: n from Supabase (x MB), m from disk` | Proof per job, and the regression signal |
| D7 | **Assemble reads with Range over a short-lived signed URL** (300 s) instead of downloading: `ffprobe` reads the header, poster `-ss 0.5`, last frame `-sseof -0.2`. New `/inspect` = probe + poster in one call. `/cut` still needs whole files: keeps a small disk cache on its own instance | Only the bytes ffmpeg needs |
| D8 | **Probe at write time, never at read time.** `video_render`, after storing a take, calls `/inspect` once and saves `duration_s` and `poster_path`; `_probe_generated` and the probe in the view are deleted. Until then a per-process failure memo (1 h) guards the view | A read must never cost a video download |
| D9 | **Thumbnail backfill** as a one-off script through `CachedFiles` (most sources are already on disk) | C6 |
| D10 | **Smaller pictures are a LAB first, not a build**: (a) gpt-image `output_format="webp"`, `output_compression=90`, path extension from the mime; (b) a `<path>.work.webp` (1024 px, q90) beside each reference, attached to `images.edit` and Omni instead of the PNG. Built only after the person reads the lab (face likeness, detail) | It changes what the models receive |

## 4. Phases

| # | What | Done when |
|---|---|---|
| 0 | Read-only: every `download(` caller in `libs`, `services`, `infra`, `lab`, `scripts`; every `Files` construction (`supabase_rest.py:814`, each service's `Rest`); which services run in the API process and which alone; re-measure section 1 | A list in IMPLEMENTED.md |
| 1 | `libs/hiru_ai/core/file_store.py`: moved helpers (D1), `CachedFiles` (D2–D6); the API's `file_cache` imports the helpers | Unit tests: hit, miss, write-through, per-key lock (two threads, one download), atomic write, LRU trim, pass-through for `documents`, in-memory fallback cap, a 404 not kept; API cache tests unchanged and green |
| 2 | Wiring: `supabase_rest.py:814` builds `CachedFiles(SupabaseFiles(rest), …)`; `frame_render` and `video_render` stores route `download*` and `upload` through it; job-end log line (D6) | System test: a scripted frame job over a scene of 5 shots that share 2 sheets downloads each sheet once; a second job downloads nothing; the just-painted frame used as same-setup reference is not downloaded |
| 3 | Assemble (D7): signed-URL Range reads for probe/poster/last-frame; `/inspect`; upload in `handoff.py` uses `/inspect` once | Tests with a local HTTP server that counts bytes served: probe < 1 MB of a 10 MB file; poster and last frame read a fraction |
| 4 | Probe at write time (D8): `video_render` calls `/inspect` after storing; `_probe_generated` removed from the view; interim failure memo if 3 lands later | Test: opening the handoff view N times makes zero assemble calls |
| 5 | **The person**: apply `Database/upgrade_v23_to_v24.sql` (`takes.poster_path`); then the worker's poster write (D8) goes live | Column present; a new generated take has a still on its card |
| 6 | Thumbnail backfill script (D9) `scripts/backfill_thumbs.py`, dry run by default (lists, counts MB), `--apply` writes | Dry run lists the 80; the person runs `--apply` |
| 7 | Labs and scripts (C5) read through `CachedFiles` | `grep '/storage/v1/object'` finds only the adapters and assemble |
| 8 | Deployment note in `docs/`: Cloud Run `FILES__CACHE_MAX_GB` within memory (0.5–1), dashboard previews cost egress | Doc reviewed by the person |
| 9 | **Lab, paid, the person's yes and a hard budget** (D10): one scene, PNG vs WebP references and output; frames compared side by side; Omni accepts WebP or JPEG? | Person's read; a build plan only if it passes |

Interface: no change needed. `<Media>` already uses `thumbSrc`, one URL per file, `preload="none"` with poster.

## 5. How we know it worked

1. Each worker job's `storage:` line: on a re-render of a painted scene, Supabase downloads near zero.
2. The API with `DEBUG_TRAFFIC=true`: no "fetched from Supabase more than 2 times in an hour" warnings.
3. Supabase usage → Cached Egress per day ≈ the size of the new pictures and takes made that day (was 2–4×).
4. Supabase Logs Explorer (edge_logs, `/storage/v1/object/%` grouped by path and user agent): no path repeated within
   a day.

## 6. Not in this plan

- Supabase image transformations (paid plan) or moving storage to another provider.
- Browser-side changes (already guarded by plan/2026-11-08c).
- Making Cloud Run instances stay warm (`min-instances`) — a cost the person decides separately.

## 7. Open for the person

- **Q1**: the in-memory fallback cap for workers without disk (300 MB proposed) — fits the Cloud Run memory size?
- **Q2**: apply `upgrade_v23_to_v24.sql` now (phase 5 waits for it)? Why it was skipped while v25–v28 landed is worth a
  look: other columns from v24 may be missing too.
- **Q3**: phase 9 lab budget (proposed $1, low/medium quality only).
- **Q4**: keep a `.work.webp` beside each PNG (D10b, more files), or switch the stored format to WebP outright (D10a,
  older PNGs stay)?
