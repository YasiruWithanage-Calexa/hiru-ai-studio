# Video generation in Hiru: what is built

Plan: [PLAN.md](PLAN.md). Plain words: [human-read.md](human-read.md). Written 2026-11-06.

**Phases 0 (the script), 1, 2, 3, 4 and 5 are built and tested offline. The live parts of Phase 0 and Phase 6 are not.**
Nothing is deployed. Nothing here has called Google. The interface has been type-checked, linted and tested, but **not opened in
a browser** against a running API: that is the first thing Phase 6 does.

## Status by phase

| Phase | State | Where |
|---|---|---|
| 0. Map the two APIs | **Script written, not run.** `scripts/video_probe.py` sends deliberately invalid requests (a 400 names the field and costs nothing; every probe carries an invalid anchor so a 2xx stops the script) and, with `--generate --yes`, makes one paid take per engine twice with the same seed. A person runs it with a `GOOGLE__API_KEY`, then fills the capability rows. | `scripts/video_probe.py`, writes `plan/2026-11-06c/probe/` |
| 1. Contracts | Built. 43 tests. | `contracts/video_gen.py`, `tests/contracts/test_video_gen.py` |
| 2. Storage | Built and **verified on the local stack**: migration, pgTAP (`015_video_renders`, 14 tests; all 199 pass), advisors clean, and a three-way dump of `public,storage` (migrations, `schema_v14.sql`, `schema_v13.sql` + `upgrade_v13_to_v14.sql`) has no difference in anything this plan adds (v14 and v13 + upgrade are identical; the upgrade also re-runs cleanly; after the merge of main, Jonathan's migration runs before this one and its column matches too; the only differences from the migrations are older: column order in `dialogue_lines` and `token_usage` and the comment on `token_usage.reasoning_tokens`). | `supabase/migrations/20261106162357_video_renders.sql`, `Database/schema_v14.sql`, `Database/upgrade_v13_to_v14.sql` |
| 3. The function | Built. 54 tests, fake provider and fake store. | `src/services/video_render/`, `tests/services/video_render/` |
| 4. API | Built. 33 tests. | `api/routers/renders.py`, `api/services/renders.py`, `api/routers/handoff.py`, `tests/api/test_renders.py` |
| 5. Interface | Built in `hiru-ai-studio-interface` (branch `main`, uncommitted): `features/handoff/` `render-types.ts`, `lib/map-render.ts`, `components/generate-panel.tsx`, `reference-tray.tsx`, `request-preview.tsx`, `takes-log.tsx` (generated takes, Make again, Vary, renders being made), the handoff page, and `lib/api/errors.ts` (a refusal that lists failed checks is shown in words). 24 new tests; the whole suite is 197 passing, lint and typecheck clean (one existing lint warning in `script-edit-form.tsx`). It reads the API, not mocks (the seam in this repo is now `features/*/api.ts` over the real API). | `hiru-ai-studio-interface/src/features/handoff/` |
| 6. Live on localhost | A person's. | |

## The decisions, as taken (each can be overturned)

| | Plan said | Taken | Why |
|---|---|---|---|
| D1 Google for video only | recommended yes | **Built as yes.** The key is read by `video_render` alone; the API reads it only to know whether Generate can be pressed. CLAUDE.md and PLAN.md §14 Q1 say so. | The person asked for Omni and Veo on 2026-11-06. |
| D2 Engines | Omni Flash, Veo 3.1, Veo 3.1 Fast; not Lite | As recommended. | Lite cannot take references. |
| D3 Usage % | a hidden per-second token equivalent | **The mechanism is built; the numbers are not.** `VIDEO__TOKENS_PER_SECOND` (JSON per engine) turns a Veo take's seconds into `token_usage.output_tokens`. Unset = Veo counts nothing yet. Omni reports tokens and counts them. | The right number needs the real cost per second, which only the first paid takes tell. **Open: set it after Phase 6.** |
| D4 Who may render | admin, producer, director | `Permission.RENDER_VIDEO` for those three. | |
| D5 Schema version | v12 if unapplied, else v13 | **A new v14 pair** (`schema_v14.sql` = v13 + this plan; `upgrade_v13_to_v14.sql`). v12 was already applied to the hosted project and v13 (Shot Planner Jonathan) came in while this was built, so neither was touched. | The person said so on 2026-11-06. |
| D6 Key | Gemini API key | `GOOGLE__API_KEY`, `GOOGLE__BASE_URL` overridable. | |
| D7 Seed default | random and recorded | As recommended. | |

## What differs from the plan

1. **A browser never holds a storage path.** The plan's `RefSource` carries `path`; it stays server-side. A browser names a
   picture by `(kind, id)` (`RefIn`) and the server resolves it from what the shot may use (`Pictures` in
   `api/services/renders.py`: the production's current card sheets, look sheets, the shot's own frames, the previous take's
   last frame, and the pictures a person uploaded for this shot). A picture's id is `asset_id(owner, path)`, a stable
   `uuid5`, so a card's alternate sheets ("another version of the same sheet") are separate, nameable pictures. This also means
   a person cannot make the function download an arbitrary object.
2. **No `uploads` bucket.** A person's own pictures go in the existing `references` bucket under
   `<production>/uploads/<shot>/<id>`, and are listed on the shot's `video_settings.uploads`. `RefSource.bucket` is
   `frames | references | takes`.
3. **Engines that take a start frame OR references.** PLAN §4.3 builds a default list of start frame plus sheets; Veo takes
   one or the other (`refs_with_first_frame` is False until Phase 0 proves otherwise), so the default for such an engine
   keeps the start frame (it was painted from those sheets) and lists the sheets under "left out", with the reason. The
   person can still swap the list; a list that mixes them is a blocking check.
4. **`seed` starts at `none` for Omni and `accepted` for Veo.** PromptMotion's table says Omni has no seed; its S0 saw `seed`
   accepted on the wrong endpoint. Omni's request therefore carries no seed until the probe settles it, and a fixed seed on
   Omni is a blocking check ("This model does not take a seed: every take is new. Choose Random."). Veo sends `seed` but the
   panel text says it is "not proven to repeat a take". `EngineCapability.verified` is False for all three.
5. **`RenderSpec.prompt_version` added** (the plan lists the prompt id only): the takes table records the version a take was
   made from, as uploads do.
6. **Make again** uses the stored spec as it was, not today's plan: the repeat is the old request. It re-checks the engine's
   rules and availability, clears the recorded picture hashes, and keeps the seed (`vary` draws a new one).
7. **Realtime:** `video_renders` is added to the `supabase_realtime` publication.
8. **A stale `queued`/`running` render** (older than `VIDEO__STALE_AFTER_S`, 45 minutes; the function's deadline is 30) is
   reported failed by the handoff view and `GET renders/{id}`. An Omni render has no resume (one synchronous call), so a task
   killed mid-call would otherwise stay `running` for ever.
9. **The take's length** is probed by the API when a generated take is first read (`duration_s` is null when the function
   stores it, which has no ffmpeg), then kept. The existing "7.5 s; the shot is 4 s" note works unchanged.
10. **Per-press overrides on the preview** are passed as an `overrides` JSON query parameter on `GET render-plan` so the
    preview shows what the press will send.

## The interface, as built (Screen 4)

A **Make a take in Hiru** panel between the checks and the takes log: model (Omni Flash, Veo 3.1, Veo 3.1 Fast, each "Not yet
verified" until Phase 6), size, length (only the engine's ladder), shape (the production's), takes per press, seed (Random,
Fixed with the per-take numbers shown, From a take; hidden with the reason on a model that takes none), the engine's own
options, and "Save for this shot" / "Use production default" per field with where each value came from. The reference tray
lists the pictures in the order they go with the tag the request gives each one (`<IMAGE_REF_0>`, `image 2`, "start frame");
a person can move up and down, remove, relabel, rebind to a person or place, add from the production's sheets, frames and
takes or upload their own, and "Reset to Hiru's choice"; the tags renumber after each save. "What will be sent" shows the
exact prompt with its citation block, the pictures in order and every setting; the checks sit under it, blocking ones first.
Generate sends the hash of the plan the person saw; the server refuses a different request, and the panel then shows the plan
as it is now. The takes log shows where each take came from, the settings in words, **Make again** and **Vary**, and the renders
being made, with their reason when one failed or was declined; the page looks again every 5 s while one is running.
Nothing on the screen names a cost, a price or a credit (tested).

Differences from PLAN §8: reorder is by ↑ / ↓ buttons, not drag (keyboard-first, no new dependency); **"Use these settings"**
on a take is not built (Make again repeats the exact request, which is the common case; the API would need to send the take's
settings as data); progress is by polling the page, not Realtime.

## Behaviour worth knowing

- `POST renders` re-resolves the whole request, refuses with the failing checks (422) if anything blocks, refuses a stale
  preview (409, when the panel sends back the `request_hash` it saw), caps running renders per production (429,
  `VIDEO__MAX_RUNNING_PER_PRODUCTION`, 4), inserts one `queued` row per take, then dispatches ONE job (`video_render`).
- The function claims each row (`queued → running`), re-validates the stored spec against its hash, downloads pictures
  (inline base64, never links), calls Omni or Veo, stores the video under a path derived from the render, inserts the take
  (`origin = 'generated'`, id derived from the render so a retry repairs a half-finished one), records the sha256 of every
  picture that went, and writes one `token_usage` row. Veo is resumable (`provider_id` is written the moment submit
  returns; a re-delivered task polls it, at most `VIDEO__MAX_RESUMES` times). A refusal is a result (`refused`), a failure
  is `failed`, both answer 200; only a transient network error answers 500.
- Without `GOOGLE__API_KEY` (and without `VIDEO__FAKE_PROVIDER=true`) the plan says "Video generation is not set up on this
  server. Uploading a take from Flow still works." as a blocking check. Upload is untouched.
- Nothing in any response names a cost, a price or a credit (tested).

## Tests run

`pytest` for the new code: `tests/contracts/test_video_gen.py` (43), `tests/services/video_render/` (54),
`tests/api/test_renders.py` (33), `tests/contracts/test_roles.py` (the `RENDER_VIDEO` row); in the interface
`map-render.test.ts` and `generate-panel.test.tsx` (24). `ruff` is clean on everything
touched except one line in `hiru_ai/core/settings.py` that was already over the limit. `mypy` is clean for `contracts`, `api`
and `video_render` (as CI runs it). `supabase test db`: 15 files, 199 tests, all pass. `supabase db advisors`: none.

**Already failing before this work, unchanged by it** (the same set fails at `HEAD`): the `-graph` cases of
`tests/parity` and `tests/adam/test_system.py` and friends (this machine's `.venv` has no `langchain`); six API tests that
assert a `http://localhost:8000/files/` URL (`test_handoff`, `test_looks`, `test_production`; the base URL comes from `.env`);
and `tests/adam/test_removal.py` / `test_score_mutations.py`. I did not touch them.

Not run: `import-linter` (not installed here; `video_render` is added to every list in `pyproject.toml`'s
`[tool.importlinter]`, and `tests/test_isolation.py` passes), the retrieval eval (no retrieval change).

## What waits for a person

1. **Phase 0 live:** `python scripts/video_probe.py` (free), read `plan/2026-11-06c/probe/*.json`, then set per engine in
   `contracts/video_gen.py`: `seed`, `max_takes_per_call`, `negative_prompt`, `options`, `refs_with_first_frame`, `max_refs`,
   `durations`, `aspects`, `resolutions`. Then `--generate --yes` (paid) to learn whether a seed repeats a take. Write the
   findings and the cost here.
2. **Apply the database change** (`Database/upgrade_v13_to_v14.sql`, once v13 is applied), and create
   `GOOGLE__API_KEY` for the function (and the API, which only checks it exists).
3. **D3:** set `VIDEO__TOKENS_PER_SECOND` once a Veo take's cost is known.
4. **Phase 6:** a real scene on localhost (Omni, a Veo comparison, reorder and rebind, make again, accept, carry the last
   frame). Only then set `verified=True` per engine. Deploy only when the person says so.

## Simplified at the person's request (2026-11-06, later the same day)

The person saw the Screen 4 panel and asked for much less: "just a Generate button; one video per clip; the model and size
chosen only when the production is created, never changed later; a Render draft at 360p." Asked and answered: a draft in a
Veo production is **Omni Flash at 360p** (Veo has no 360p); a take is **the shot's own length**; each press makes **one** take
and earlier takes stay listed.

Backend (`contracts/video_gen.py`, `api/routers/renders.py`, `api/routers/productions.py`):
- `MAX_TAKES_PER_PRESS = 1`. `VideoOverrides` no longer has `engine`, `model` or `resolution`: a shot or a press that names
  one is a 422. `resolve` takes them from the production alone (`LOCKED_VIDEO_FIELDS`).
- `VideoSettings` checks the engine and that the size is one of `final_resolutions(engine)` (720p / 1080p; 360p is for drafts).
- `resolve(..., draft=True)` gives `DRAFT_ENGINE` (`omni_flash`) at `DRAFT_RESOLUTION` (`360p`), sources `"draft"`; when the
  production is on another engine its negative prompt, options and model id are left behind. `RenderSpec.draft` is stored,
  is part of `request_hash`, and `describe_spec` begins "Draft · ". `GET render-plan?draft=true`; `POST renders {"draft": true}`;
  audit `video.draft`.
- `PATCH /productions/{id}`: settings sent without `video` keep the production's (they used to reset it to the default);
  a change to the engine, model or size is a 422 "cannot be changed".
- The reference list, seed and per-shot settings routes still exist in the API (Make again / Vary still use the seed), but
  the interface no longer offers them: the pictures and the seed are Hiru's choice.

Interface (`hiru-ai-studio-interface`):
- **Create production** (`new-production-form.tsx`): Video model (Omni Flash default, Veo 3.1, Veo 3.1 Fast) and size (720p,
  1080p), with "cannot be changed after the production is created". Sent as `settings.video`. Mirrors in
  `features/productions/video-model.ts`.
- **Production page → step 2 Video prompt** (`production-workspace.tsx`): under the prompt, a **Video** card
  (`features/handoff/components/generate-video-card.tsx`) with the production's model · size · the shot's length, and two
  buttons: **Render draft** and **Generate video**; the first blocking reason in words when it cannot go; a link to the takes.
- Screen 4 (Prompt & Handoff) no longer has the panel; `generate-panel`, `reference-tray`, `request-preview` and their test are
  deleted. The takes log (accept, Make again, Vary, upload) is unchanged.

Tests: `tests/api/test_renders.py` (35: the lock, drafts, one take a press, creation-time choice), `tests/contracts/test_video_gen.py`
(+3), the function tests unchanged in substance (helpers set the size past validation); the interface 188 (new
`generate-video-card.test.tsx`). ruff / mypy / eslint / tsc clean on everything touched. Not opened in a browser.

## The first live call (2026-11-06): Omni takes a start frame OR references

The first Render draft on the dev key reached Omni and came back `400 "Image-to-video does not support more than 2 images."`:
Hiru had sent the accepted frame plus three sheets, because the Omni row said `refs_with_first_frame=True` (PromptMotion's
unproven value). A request with a frame is image-to-video, which takes the frames only (start, and an end). The row is now
`False`, as Veo's is: Hiru's choice is the start frame alone (it was painted from those sheets) and the sheets are listed in
`left_out`; a list that mixes them is a blocking check; a sheets-only list (reference-to-video, up to 10) is still allowed.
The API tests now also force `GOOGLE__API_KEY` empty (a real key in `.env` made "not set up" untestable).
