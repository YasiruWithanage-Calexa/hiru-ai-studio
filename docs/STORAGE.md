# Stored files and egress (plan/2026-11-21)

Supabase bills **cached egress**: every byte its Storage sends out. A stored file in a write-once bucket (`frames`,
`references`, `takes`; a path there names one file forever) should cross the internet **once per machine**.

## Who keeps a copy

| Who | Where | Settings |
|---|---|---|
| API `/files` | `FILES__CACHE_DIR` (empty = `%LOCALAPPDATA%/hiru-ai/files`, `~/.cache/hiru-ai/files`) | `FILES__CACHE_MAX_GB` (default 5; 0 = off) |
| `frame_render`, `video_render` (and anything built on `hiru_ai` ports) | **the same folder**, same names (`hiru_ai/core/file_store.py`) | the same two settings. With 0 GB: a 300 MB in-memory copy per process |
| `infra/assemble` `/cut` | `FILES__CACHE_DIR/assemble`, else the temp folder | `ASSEMBLE__CACHE_MAX_MB` (default 512) |

`documents` overwrite, so they are never kept. A picture or take a worker stores is kept as it is written, so the frame
just painted (the next shot's same-setup reference, the take's first frame) is never downloaded.

Each render job ends with one log line, the proof and the regression signal:

```
storage: 2 from Supabase (4.4 MB), 14 from disk job=…
```

## Takes are read once, and only in part

* `video_render` calls assemble `/inspect` once after it stores a take: the take's length (`takes.duration_s`) and its
  still (`takes.poster_path`, **schema v24**: until `Database/upgrade_v23_to_v24.sql` is applied the still is skipped
  and only the length is saved). A view never probes.
* An upload in the API makes the same single `/inspect` call.
* assemble reads with Range over its own 300 s signed URL: the index for a probe, a moment for a poster, the last second
  for a last frame. ffmpeg asks for open-ended ranges and hangs up when it has enough, so a request still costs what was
  already in flight (measured on localhost, 10 MB take: probe 0.6-1.4 MB, poster ~2.8 MB, last frame 2.3-2.7 MB).
  Today's takes average 0.7 MB, so for them this saves little; the win is that no view probes any more.

## Deploying (the person's, nothing here is deployed)

1. **Cloud Run `/tmp` is memory.** A cache on Cloud Run uses the instance's RAM. Keep `FILES__CACHE_MAX_GB` for the API
   at 0.5-1 within its memory size. The functions (1 GiB) are safest at `FILES__CACHE_MAX_GB=0`: they then keep the
   300 MB in-memory copy (Q1: does 300 MB fit beside a frame job's own memory?).
2. A fresh instance starts empty (cold start, scale-out). `min-instances` is a separate cost decision.
3. **Deploy assemble before the API**: the API now calls `/inspect`; an older assemble answers 404 and an uploaded take
   is kept without its length or still.
4. **`hiru-video-render` bundles `hiru_ai` and calls assemble.** `deploy-functions.yml` gives it (and only it,
   `"assemble": true`) `ASSEMBLE__URL` from the GitHub variable `ASSEMBLE_URL` (terraform output `github_variables`)
   and `ASSEMBLE__SECRET` from the `<prefix>-assemble-secret` secret, which the functions account can already read.
   Terraform grants the functions account `run.invoker` on the assemble service. The function sends an ID token from
   the metadata server. **Open: the network path.** assemble's ingress is internal-only and neither the API nor the
   functions have VPC egress, so in the cloud both calls may be refused until one is chosen (a VPC connector / Direct
   VPC egress, or assemble's ingress opened to all with the ID token and secret still required). Without a path every
   take is still made, only without its length and still.
   Locally: `.env` holds `ASSEMBLE__URL=http://localhost:8220` and a random `ASSEMBLE__SECRET`;
   `scripts/start-functions.ps1` starts assemble on 8220 (`-Only hiru-assemble` restarts it alone).
5. **The Supabase dashboard's Storage previews cost egress** like any download. Look at pictures through the product.

## Checking it worked

1. The `storage:` line of each render job: a re-render of a painted scene shows near zero from Supabase.
2. The API with `DEBUG_TRAFFIC=true`: no "fetched from Supabase more than 2 times in an hour" warnings.
3. Supabase usage → Cached Egress per day ≈ the size of the new pictures and takes made that day.
4. Logs Explorer (edge_logs, `/storage/v1/object/%` grouped by path and user agent): no path repeated within a day.
