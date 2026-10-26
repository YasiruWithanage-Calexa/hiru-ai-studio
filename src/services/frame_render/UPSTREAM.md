# frame_render — fork record

Forked from PromptMotion `src/services/video_render/` at commit **1d748dc** (2026-10-19), as
PLAN.md §2.1 describes. `scripts/upstream_diff.py frame_render` lists what changed upstream since
that commit in the files below.

| Hiru file | Upstream file | What was kept |
|---|---|---|
| `engine/pipeline.py` | `video_render/engine/take.py`, `video_render/app/handler.py` | claim → generate → store → record per picture; the API inserts the row `queued` and the worker CLAIMS it with a conditional update, so a re-delivery never pays twice; storage path derived from the row id (a retry overwrites); one run's pictures in parallel, the run's job closed once |
| `engine/image.py` | `video_render/engine/image.py`, `video_render/engine/transport.py` | One synchronous call per picture, picture returned inline; references sent in the order the prompt numbers them; a refusal is a reported result, never retried; provider text never reaches a person |
| `runtime/rest.py`, `runtime/store.py` | `video_render/runtime/storage.py` | Private buckets read and written with the service role; references inlined, never handed over as links; no signed URL is ever stored |

## Intentional divergences

1. **Provider replaced.** Gemini "Nano Banana" is replaced by OpenAI's image model (the `image`
   tier, `OPENAI__MODEL_IMAGE`, default `gpt-image-2`, quality `medium`): `images.generate`
   without references, `images.edit` with them. The video providers (`veo`, `omni`, `seedance`,
   `minimax`) and the content-list helpers are not carried: Hiru does not render video in the
   app (PLAN.md Q1).
2. **What is rendered.** First frames for shots (`first_frames` rows) and canon reference sheets
   (`canon_versions.reference_assets`), not video takes. The frame prompt is composed here from
   the shot's IR and the camera as it stands now (`contracts.producer.frame_prompt`), so a
   person's camera change reaches the next frame without a new design.
3. **Reference sheets as ingredients.** The sheets of the characters in the shot and the plate of
   its location are attached (at most four, in that order) and named in the prompt by position.
   A sheet that cannot be read is left out and not named.
4. **Pins.** Every frame records what it was made against (`contracts.producer.Pins`), so the API
   can say when a frame no longer matches its shot or a canon card.
5. **No credits, holds or billing.** Usage goes to `token_usage` only (the UI shows a monthly
   percentage). No resume of provider tasks: an image call is one request with nothing to poll.
6. **Progress** goes to `job_events` (Supabase Realtime), not Redis; the job is closed by the one
   invocation that ran the pictures, so there is no last-take race.
