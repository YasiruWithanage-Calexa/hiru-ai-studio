# Storage egress: what is built (plan/2026-11-21)

Built offline 2026-11-22, uncommitted. No paid call, no live database read or write, nothing deployed. Phases 0 (code
part), 1, 2, 3, 4, 6, 7 (scripts), 8 are done; **5 and 9 are the person's**, and so is phase 0's re-measure (it needs the
live database). Interface: no change (as the plan said).

## Phase 0: who downloads a stored file

| Caller | Bucket(s) | Now |
|---|---|---|
| `hiru_ai` frame_render: `graph.py` `_references` / `_draft_picture` / board panel, `board.py` `_pictures`, `faces.py` | references, frames | through `ports.files` = `CachedFiles` (phase 2) |
| `hiru_ai` `tools/image_generate` | any | `ports.files` (cached for write-once buckets) |
| `hiru_ai` doc_ingest graph, `SupabaseDocs` text | documents | `ports.files`, passes through (documents overwrite) |
| legacy `frame_render` `Store.download_reference` / `download_frame` | references, frames | `Store.files = CachedFiles(rest)` (cloud deploy has no `AI_ENGINE`, so legacy still runs there) |
| legacy `video_render` `Store.download` (every reference per take) | references, frames | `Store.files = CachedFiles(rest)` |
| other services' vendored `Rest.download` (planners, doc_ingest, canon_extract …) | documents | unchanged: documents only, never cached |
| `infra/assemble` `/probe` `/poster` `/last-frame` | takes | Range over its own signed URL (phase 3) |
| `infra/assemble` `/cut` | takes | per-instance disk copy (phase 3) |
| API `/files` | all | its disk cache (plan/2026-11-08c), now the shared folder |
| API `handoff.py` upload: `/probe` then `/poster` (two whole downloads) | takes | one `/inspect` (phase 3) |
| API `handoff.py` view: `_probe_generated` on every view while `duration_s` is empty | takes | **deleted** (phase 4) |
| API `GET .../scenes/{id}/bundle` (`repos.storage.download`, every frame and sheet, every request) | frames, references | **not in the plan's list**: now read through the API's disk cache |
| `scripts/board_update_live.py`, `lab/series_block/live_check.py` | frames, references | `build_context` / `build_ports` → cached by phase 2 |
| `lab/storyboard/fetch.py`, `lab/portrait_board/fetch.py` | references | **left as they are** (see phase 7) |

Which run in the API process: none of the render systems. `frame_render` and `video_render` are their own functions;
`frame_render` runs `hiru_ai` (graph) locally via `start-functions.ps1` and legacy in the cloud unless `AI_ENGINE=graph`
is set there. Both paths are wired.

## Phase 1: `hiru_ai/core/file_store.py`

* `root`, `_file_for`, `bucket_dir`, `media_type` (was `_media_type`), `trim` moved unchanged from
  `api/services/file_cache.py`; the API's module binds the same functions (`file_cache.root is file_store.root`).
  `IMMUTABLE_BUCKETS` lives here now; `adapters/storage.py` re-exports it.
* `CachedFiles(inner, settings=None)`: D2-D6 as written. Settings come from `FILES__CACHE_DIR` / `FILES__CACHE_MAX_GB`
  (`CacheSettings.from_env`), the API's names. A disk that fails (full, read-only) costs a download next time, never the
  job. `__getattr__` reaches the wrapped adapter's own attributes (`files.rest`).
* `conftest.py` at the repo root gives every test its own cache folder, so no test reads another's bytes or the
  developer's real cache.
* Tests `tests/hiru_ai/test_file_store.py`: hit, miss, write-through, 8 threads → 1 download, atomic write, LRU trim,
  documents pass through, memory fallback + cap, 404 not kept, shared folder with the API, env names, ports wiring.

## Phase 2: wiring

* `supabase_rest._ports` builds `CachedFiles(SupabaseFiles(rest))` (every `build_ports` / `build_context`).
* `frame_render` (graph and legacy) and `video_render` end each job with `storage: n from Supabase (x MB), m from disk`.
* System tests (same file): five frames over two shots that share two sheets download each sheet once; a second job
  downloads nothing; a draft just painted is read for its final without a download (write-through).
* **Deviation**: `hiru-video-render` was not bundled with `hiru_ai`; it is now (`"ai": true` in
  `deploy-functions.yml`) so it imports `file_store` instead of a fourth vendored copy.

## Phase 3: assemble (D7)

* `_signed_url` mints a 300 s URL (`POST /storage/v1/object/sign/...`); `_input` hands it to ffmpeg, or downloads the
  whole file as before when signing fails. `/probe`, `/poster`, `/last-frame` use it; new `/inspect` = probe + poster
  over one URL. `/cut` keeps each take on the instance's disk (`FILES__CACHE_DIR/assemble` or temp,
  `ASSEMBLE__CACHE_MAX_MB` 512).
* **Kept, not changed**: the last frame stays `-sseof -1 -update 1` (the load-bearing upstream rule; the plan's
  `-sseof -0.2` would risk a frame without a keyframe before it). The poster stays at `-ss 0.1` (the existing note: the
  very first frame is often a black fade-in), not the plan's 0.5.
* API: `HttpAssembler.inspect`; `upload_take` makes one `/inspect` call instead of `/probe` + `/poster`.
* **Measured** (local server that counts bytes SENT, localhost, 10 MB take with a keyframe each second):

  | | index at end | faststart |
  |---|---|---|
  | probe | 1.0-1.4 MB | 0.6-0.7 MB |
  | poster | 2.4-3.6 MB | 2.7-3.3 MB |
  | last frame | 2.7 MB | 2.2-2.3 MB |

  **The plan's "probe < 1 MB of a 10 MB file" is not met on localhost.** ffmpeg asks for open-ended ranges (`bytes=N-`)
  and hangs up when it has enough, so whatever the sockets already hold is sent too (~0.5-1.5 MB per request here;
  `-probesize`/`-analyzeduration` and `-short_seek_size` did not change it). A take with ONE keyframe (x264's default
  GOP of 250 is longer than an 8 s clip) makes the last frame read the whole file, since decoding must start at frame 0.
  Over the internet the overshoot depends on the link; the real figure is for the live check. Stored takes average
  0.7 MB (section 1), so Range saves little on them today; the real win is phase 4.
  `tests/infra/test_assemble_range.py` holds the bounds as fractions of a 20 MB take (probe < 15 %, inspect < 40 %, last
  frame < 30 %), plus signing fallback, cut downloads once, and the signed URL's shape.

## Phase 4: probe at write time (D8)

* `video_render` (`runtime/assemble.py`) calls `/inspect` after the take, the render and the usage row are recorded,
  never raising; saves `duration_s` and `poster_path` with `Store.set_take`. A database without `takes.poster_path`
  (v24 not applied) answers 400: the length is saved alone and a warning logged. On an `https://` assemble URL it sends
  an ID token from the metadata server (no google-auth needed). New config: `ASSEMBLE__URL`, `ASSEMBLE__SECRET`.
* `_probe_generated` and the `assembler` argument of the view are removed (`handoff.view_of`, `get_handoff`,
  `shot_panel.get_panel`). No interim failure memo: phases 3 and 4 landed together.
* Test (`tests/api/test_renders.py`): opening the handoff and the panel 3 times each makes zero assemble calls; the length
  shows once video_render has saved it. `tests/services/video_render/test_inspect.py`: inspected once, saved; no URL or a
  failing service still gives a done take; v24 missing; ID token; store through the cache.
* Older generated takes already stored without a length keep none (no view probes them any more). `scripts/
  backfill_thumbs.py --posters` covers stills; a length backfill was not asked for.

## Phase 5: the person's — DONE 2026-11-22

The person applied `Database/upgrade_v23_to_v24.sql` (checked: v24 adds only `takes.poster_path` and `image/webp` in the
`takes` bucket; no v25-v28 file touches that bucket, so applying it after v28 is safe). Before that: Until then video_render saves lengths but not stills (logged), and the API's
upload sends `poster_path` only when there is a still (as before; on a database without v24 that insert fails, which
was already true before this plan).

## Phase 6: thumbnail backfill (D9)

`scripts/backfill_thumbs.py` already existed (plan/2026-11-08c). Now: the dry run (default) lists each missing picture
with its size (HEAD, no body) and the total MB; `--apply` reads sources through `CachedFiles` (files already in the
API's folder cost nothing), writes `<path>.thumb.webp`, and prints the storage line. `--posters` stops with a clear
message on a database without v24. **Not run** (it reads the live database): the person runs the dry run, then `--apply`.

## Phase 7: labs and scripts (C5)

`scripts/board_update_live.py` and `lab/series_block/live_check.py` read through `ports.files`, so phase 2 covers them.
**`lab/storyboard/fetch.py` and `lab/portrait_board/fetch.py` are NOT changed**: the standing rule is never to edit a lab.
The grep of phase 7 therefore finds the adapters, assemble, `scripts/_common.py` (upload only), the backfill script and
those two lab files. The person decides whether the labs may be touched.

## Phase 8: deployment note

`docs/STORAGE.md`: who keeps a copy, the job line, Cloud Run memory (`FILES__CACHE_MAX_GB` 0.5-1 for the API; 0 for the
functions = the 300 MB in-memory copy), deploy assemble before the API, video_render's new env and reachability of
assemble, dashboard previews cost egress, how to check. `.env.example` and `infra/assemble/README.md` / `UPSTREAM.md`
updated. To be reviewed by the person.

## Checks

`ruff check src tests scripts infra/assemble`: no new findings in touched files (the remaining E501s are older files).
`mypy` (whole + frame_render and video_render service runs): clean. `scripts/lint_imports.py`: one BROKEN contract, older
(`david_repair` → `david/wire_schema`), not from this work. `hiru-ai catalog --check`: current.
Full suite: 6096 passed, 68 failed, 28 skipped; all 68 fail on a clean HEAD worktree too (Adam/David/Jonathan/Raphael,
parity, removal tests and the two handoff port tests), none from this work. `tests/api/test_handoff.py::test_takes_upload_accept_and_reject` and
`::test_accepting_a_take_opens_the_carried_shot_on_its_last_frame` fail on a clean HEAD too (the local `.env` gives the
public URL port 8001 where the test expects 8000).

## Open for the person

Q1-Q4 of the plan, plus:
- Run the phase 0 re-measure and, after deploying, the four checks of `docs/STORAGE.md`.
- `ASSEMBLE__URL` / `ASSEMBLE__SECRET`: set up 2026-11-22 (local `.env` + start-functions.ps1 on 8220; deploy workflow
  `"assemble": true`, GitHub variable `ASSEMBLE_URL`, terraform invoker binding). Still open: the network path to the
  internal-only assemble from the API and the functions, `terraform apply`, and the `ASSEMBLE_URL` variable in GitHub.
- Whether the two lab `fetch.py` files may be changed to read through `CachedFiles`.
- A one-off length backfill for older generated takes (none planned).
