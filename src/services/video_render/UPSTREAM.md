# video_render — fork record

Forked from PromptMotion `src/services/video_render/` at commit **a027aec** (PromptMotion's head on 2026-11-06), as
PLAN.md §2.1 and plan/2026-11-06c §6 describe. PromptMotion itself is not changed. `scripts/upstream_diff.py video_render`
lists what changed upstream since that commit in the files below.

| Hiru file | Upstream file | What was kept |
|---|---|---|
| `engine/omni.py` | `video_render/engine/omni.py` | The Interactions API request (`POST /v1beta/interactions`), images sent as ONE ordered list exactly as the adapter listed them (never sorted or de-duplicated: `<IMAGE_REF_n>` counts by position), submit / wait / download split, the inline-or-file result, refusal vs failure, `usage_tokens` |
| `engine/veo.py` | `video_render/engine/veo.py` | `predictLongRunning` → poll → download, each picture in the slot its `slot` names (`image`, `lastFrame`, `referenceImages`), refusals from the operation error and the RAI filter, download retried hard |
| `engine/transport.py` | `engine/transport.py` | `post_json` with rate-limit backoff and NO retry on a timeout (a request we stopped waiting for may still finish and bill) |
| `engine/fake.py` | `engine/fake.py` | A provider that calls nobody (`VIDEO__FAKE_PROVIDER=true`) |
| `engine/render.py` | `engine/take.py` | claim → generate → store → record; the row is the lock; resume of a submitted provider job by compare-and-swap on the provider id; a refusal is a result; no exception reaches the caller |
| `runtime/rest.py`, `runtime/store.py` | `runtime/storage.py` | Private buckets read and written with the service role; pictures travel inline as base64, never as a link; the path of a stored video is derived from the render, so a retry overwrites |
| `runtime/jobs.py`, `app/handler.py` | `app/handler.py` | One job per press, its renders in parallel, the job closed once by the invocation that ran them; answer 200 for a result, 500 only for a transient network error |

## Intentional divergences

1. **Two engines, not fourteen.** `minimax.py`, `seedance.py`, `image.py`, `content.py` and the image engines are not
   carried: Hiru renders video with Omni Flash and Veo 3.1 only (plan/2026-11-06c §2). A new engine is a capability row in
   `contracts/video_gen.py`, an adapter, and one entry in `render.PROVIDERS`.
2. **Hiru rows, no billing.** PromptMotion's `generation_runs` / `generation_takes`, credits, holds (`hold_key`,
   `capture_credits`), `token_tracker.py` and Redis events are gone. A render is a `video_renders` row; success inserts a
   `takes` row (`origin = 'generated'`); progress goes to `job_events`; usage is one `token_usage` row. The UI shows no costs.
3. **The request is `contracts.video_gen.RenderSpec`**, built by the API from the person's list and settings and checked
   here again (`validate_render`, the request hash, the picture paths). It carries each picture's BINDING and the seed.
4. **Slots, not roles.** A part's `slot` is `first_frame` / `last_frame` / `reference` (PromptMotion's `role`).
5. **Seed, negative prompt and options.** Veo sends `seed`, `negativePrompt` and `personGeneration` when the request carries
   them (the Phase 0 probe settles what our key accepts). Omni's `seed` stays off until the probe proves it on the
   `/interactions` endpoint.
6. **Veo is resumable** (`RESUMABLE = True`, `on_submitted`, `resume_id`): the operation name is written to
   `video_renders.provider_id` the moment submit returns, and a re-delivered task polls it instead of submitting again.
   PromptMotion's Veo module is not resumable.
7. **Google key.** `GOOGLE__API_KEY` (PromptMotion: `GEMINI__API_KEY`), read only by this function (plan §2.1).
   `VIDEO__MODELS` overrides an engine's default model id without a code change, but never a model a person chose.
8. **Usage.** Veo reports seconds, not tokens: `VIDEO__TOKENS_PER_SECOND` (a JSON map per engine) turns them into the
   hidden token equivalent so the one usage percentage stays (plan D3). Unset = Veo counts nothing yet.
9. **No ffmpeg.** The stored take has `duration_s = null`; the API probes it when the take is first read (Phase 4).
10. **Print → logging.** Provider text goes to the log only; a person reads the sentences in `render.py` and the
    providers' `_refusal_text`, which name no cost.
