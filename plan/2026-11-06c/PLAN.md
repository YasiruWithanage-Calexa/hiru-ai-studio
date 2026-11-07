# Video generation in Hiru: Omni Flash and Veo, with references, order and seed under our control: plan

Status: written 2026-11-06, **nothing built**. Plain-words version: [human-read.md](human-read.md).

This answers PLAN.md Q1 ("in-app video generation … ask again then"): the person asked on 2026-11-06. Today a shot ends at
Screen 4 (Prompt & handoff): the prose is copied to Flow, the clip is made there and brought back as an uploaded take
(`api/routers/handoff.py`). After this plan, the same screen can also **generate** the take in Hiru. The upload path stays
as it is.

**Goal:** a person generates a shot's take from Hiru with **Gemini Omni Flash (default)** or **Veo 3.1**. Everything that
reaches the model is decided by us and visible before it is sent: which images go, **what each one is bound to**, **the
order they go in**, **the seed**, and every model setting. Each take records exactly what was sent, so any take can be
made again or varied on purpose.

**PromptMotion is reference only.** Nothing in `d:\projects\Prompt Motion` is changed. What we take is forked, as the
fixed decisions say (PLAN.md §2.1), with an `UPSTREAM.md` naming the source path, the commit (`a027aec`, PromptMotion's
head on 2026-11-06) and every divergence.

## 1. What we found

| Finding | Evidence |
|---|---|
| Hiru already has everything around a take: one accepted take per shot, the last frame carried to the next shot, the length note, the bundle | `takes` table (`schema_v12.sql`), `api/routers/handoff.py`, `assemble` `/last-frame` |
| Hiru already picks reference images for frames: the sheets of the people the camera SEES, then the place; a look sheet before the base sheet; someone only heard is never attached | `frame_render/engine/pipeline.py` `FrameJob.references` |
| PromptMotion has a working video worker for both engines: claim → generate → store → record, resume on re-delivery, refusals as results | PM `src/services/video_render/video_render/engine/{omni,veo,take,transport,fake}.py` |
| Omni Flash is `gemini-omni-1.1-flash`, served ONLY by the Interactions API (`POST /v1beta/interactions`); images are one ordered list cited as `<IMAGE_REF_n>`; up to 10 references; start and end frame | PM `engine/omni.py`, `contracts/media.py` `ENGINE_CAPABILITIES["omni_flash"]` |
| Veo 3.1 is `predictLongRunning`: `image` (start), `lastFrame`, `referenceImages` (max 3, `asset`); 4/6/8 s; 1080p, references and an end frame need 8 s | PM `engine/veo.py`, capability rows `veo_3_1`, `_fast`, `_lite` |
| **Order matters and is easy to break**: Omni numbers references by their position in the request; sorting or de-duplicating them silently points every citation at the wrong picture | PM `omni.submit` docstring, `build_omni_input` |
| **An attached image the prompt never names drifts the frame**; a label that looks like an id is drawn as on-screen lettering | PM `build_omni_input` docstring, `docs/nova/README.md` §9b |
| **Seed is not settled.** PM's table says Omni has no seed, but its S0 probe found `seed` accepted (on `generateContent`, the wrong endpoint for Omni). Whether either engine honours a seed on the endpoint we use is untested | PM `plans/2026-09-23/s0-omni-reality-check.md` §5 |
| A 400 from these APIs names the unknown field and costs nothing, so the request schema can be mapped for free | same, §2 |

## 2. Decisions this plan takes (the person can overturn any)

1. **Google video models are allowed for video generation only.** CLAUDE.md says "LLMs are OpenAI only; ask before
   Gemini or any other Google model". The person asked for Omni Flash and Veo on 2026-11-06, so this is that ask
   answered, **for rendering a take and nothing else**. Every prompt, check and agent stays on OpenAI. The Google key is
   read only by the new `video_render` function. Recorded in PLAN.md §14 when Phase 1 lands.
2. **Default engine `omni_flash`.** Offered: `omni_flash`, `veo_3_1`, `veo_3_1_fast` (D2 asks about `veo_3_1_lite`).
3. **Code decides the default references; a person can change all of it**, and what they set is kept and never replaced
   by code (the same rule as a person's reading, plan/2026-11-01d).
4. **Every take carries a seed it was actually sent with** (when the engine takes one). "Random" means code draws the
   number and records it, so a random take can still be made again.
5. **Nothing is sent that the person cannot see first**: the API returns the exact request (prompt text with its
   citation block, images in order with their bindings, every setting) before Generate is pressed.
6. **Checks report, they never edit** (as `contracts.handoff.check_prompt` does today). The prose is never rewritten to
   fit the references; a missing name is a check, not an edit.
7. **No costs in the interface.** Usage stays one percentage (D3 says how video counts toward it).

## 3. In one picture

```
Screen 4 (handoff)                API                                   video_render function (port 8212)
──────────────────                ───                                   ─────────────────────────────────
Generate panel  ── GET  render-plan ──► resolve settings (production → shot → this run)
  engine, settings,                     default refs (frame + sheets) or the shot's saved refs
  reference tray (order,                build the bound prompt + checks  ──► returns the exact request
  bindings), seed                                                         
                ── POST renders ──────► validate again, draw seeds,
                                        insert video_renders rows (queued) + jobs row, dispatch ──► claim row (queued→running)
                                                                                                   download refs (private buckets)
                                                                                                   omni.py / veo.py (inline base64)
                                                                                                   upload mp4 → takes bucket
                                                                                                   insert takes row (origin=generated)
Takes log  ◄── realtime / poll ──────── video_renders.status, takes                                record usage, job events
  accept → existing flow (last frame → next shot)
```

## 4. Contracts: `contracts/video_gen.py` (pydantic + stdlib only)

Kept apart from `contracts/veo.py`, which is Veo **timing** and mirrors the frontend. PM's rule stands: a prompt engine
and a generation engine are different tables, never merged.

### 4.1 Engine capabilities

```python
class EngineCapability(BaseModel):
    key: str                      # "omni_flash" | "veo_3_1" | "veo_3_1_fast"
    model: str                    # default model id; VIDEO__MODELS overrides per engine without a code change
    api: Literal["interactions", "predict_long_running"]
    durations: tuple[int, ...]    # what we OFFER: Hiru's ladder ∩ the engine's (4/6/8; 10 s off, PLAN.md Q4)
    aspects: tuple[str, ...]
    resolutions: tuple[str, ...]
    max_refs: int                 # plain references, frames not counted
    first_frame: bool
    last_frame: bool
    refs_with_first_frame: bool   # may references and a start frame go together (probe, §8 Phase 0)
    full_length_for: tuple[str, ...]  # Veo: "1080p", "references", "last_frame" need 8 s
    seed: Literal["honoured", "accepted", "none"]   # set by Phase 0, never assumed
    max_takes_per_call: int       # candidateCount / sampleCount, 1 until probed
    negative_prompt: bool
    options: dict[str, OptionSpec]  # every other knob the engine takes (person_generation, audio, enhance …), typed
    verified: bool                # False until one real take on our key (Phase 6)
```

Starting values are PM's rows, corrected by Phase 0. An unverified engine can run (the person tests on localhost) but the
panel labels it "not yet verified".

### 4.2 Settings, in three layers

```python
class VideoSettings(BaseModel):          # every field optional at the shot and run layers
    engine: str = "omni_flash"
    model: str | None = None             # a specific model id, e.g. a newer Veo preview
    resolution: str = "720p"
    aspect_ratio: str | None = None      # None → the production's orientation
    duration_s: int | None = None        # None → the shot's length
    takes: int = Field(1, ge=1, le=4)    # takes per press of Generate
    seed: SeedChoice = SeedChoice()      # §4.4
    negative_prompt: str = ""            # engines that take one; otherwise refused by validate()
    options: dict[str, str | int | bool] = {}   # checked against EngineCapability.options
```

- `ProductionSettings.video: VideoSettings` (admin, `MANAGE_PRODUCTION`): the production default.
- `shots.video_settings` (jsonb): the shot's overrides **and its reference list once a person has touched it**.
- The run request: one-off overrides; "Save for this shot" writes them to the shot layer.

`resolve(production, shot, run) -> RenderSpec` merges them field by field and says where each value came from
(`"production" | "shot" | "run" | "code"`), so the panel can show "720p (production default)". Code never moves a person's
value; a value the chosen engine cannot take is a **blocking check** ("Veo 3.1 takes references only at 8 s; this shot is
6 s"), never silently snapped. The shot's length is never changed by a render: a different `duration_s` is allowed within
the engine's ladder and shows the existing take note ("6.0 s; the shot is 8 s").

### 4.3 References: binding and order

```python
class RefSource(BaseModel):
    kind: Literal["accepted_frame", "carried_frame", "canon_sheet", "look_sheet", "take_last_frame", "upload"]
    id: UUID                              # first_frames / canon_versions / canon_looks / takes / an uploaded file
    path: str                             # private bucket path; never a URL, never sent to a browser
    bucket: Literal["frames", "references", "takes", "uploads"]
    sha256: str                           # recorded at send time: proves which picture went

class RefBinding(BaseModel):
    slot: Literal["first_frame", "last_frame", "reference"]
    source: RefSource
    binds_to: UUID | None                 # the canon entity this picture IS (character, place, prop), or None
    label: str                            # plain words the prompt uses: "Nimal's face and clothes"
    origin: Literal["code", "person"]     # who put it here
```

- **Default list** (`default_references(shot, canon, looks, frames, takes)`), the frame rule reused:
  1. `first_frame`: the shot's accepted first frame, or the previous take's last frame when the shot carries on
     (`FrameStrategy.CARRY_LAST_FRAME`). None when there is neither.
  2. `reference`s, in this order: the people the camera **sees** (a look sheet before the base sheet), then the place,
     then props in the shot. Someone only heard is never attached. Cut to the engine's `max_refs`; what was cut is
     listed as "left out: …", never dropped silently.
  3. `last_frame`: none by default.
- **Order is the list order, and nothing re-sorts it.** For Omni the request is: references in the person's order
  (`<IMAGE_REF_0>` … `<IMAGE_REF_n-1>`), then the start frame, then the end frame. That is PM's fixed layout, and it is
  the reason the tags match positions. Phase 0 checks whether Omni also accepts frames first. If it does, `frames_first`
  becomes a setting; if not, the panel says why the frames sit last. For Veo the references fill `referenceImages` in
  the person's order and the frames fill `image` and `lastFrame`.
- **Binding is written into the prompt by code, from the same list that becomes the payload**:
  `Reference images:\n<IMAGE_REF_0> is Nimal's face and clothes.\n<FIRST_FRAME> is the literal opening frame.` (Omni) or
  `Reference images, in order: image 1 is …` (Veo). The prose itself is not touched. A test asserts
  **attached == cited**, in the same order, for every engine.
- **Labels are words.** `validate()` refuses a label containing a canon code (`C01`), a UUID, a path or a hash-shaped
  token, because the model draws those as on-screen lettering. Code labels come from names: "the character sheet for
  Nimal", as frames say today.
- **Checks on the bound request** (`check_render`, reporting only): a bound person not named in the prose ("image 2 is
  Kamala; the prompt never mentions her: the picture will drift the frame"); a person the camera sees with no reference;
  two references bound to the same entity; a start frame that is out of date against the shot's pins; a reference whose
  canon version is older than the current card.
- A person can add, remove, reorder, rebind, relabel, and swap a picture for another version of the same sheet. The shot
  keeps their list (`origin: person`). "Reset to Hiru's choice" brings back the code default. Code never edits a
  person's list. When the shot changes under it, the list shows as out of date through the pins, like frames and prompts.

### 4.4 Seed

```python
class SeedChoice(BaseModel):
    mode: Literal["random", "fixed", "from_take"] = "random"
    value: int | None = Field(None, ge=0, le=2**32 - 1)   # fixed
    take_id: UUID | None = None                           # from_take: that take's seed AND its whole spec
```

- `random`: the API draws `secrets.randbelow(2**32)` per take and stores it **before** dispatch, so a random take can be
  repeated.
- `fixed` with `takes > 1`: take *i* uses `value + i`, stated on the panel ("seeds 1234, 1235, 1236"). One seed for all
  would give near-identical takes.
- `from_take`: "Make this again" (same spec and seed) and "Vary" (same spec, new seed) on any generated take.
- An engine whose `seed` is `"none"` gets no seed field. The panel says "this model does not take a seed: every take is
  new". An engine whose seed is `"accepted"` but not proven to repeat a take says that too. We never claim repeatability
  we have not measured.

### 4.5 `RenderSpec` and adapters

`RenderSpec` is the resolved request: engine, model, prompt (prose + citation block), the ordered `RefBinding`s, every
setting, the seed, the prompt version, the frame id and the `Pins`. `build_omni_input(spec)` and `build_veo_input(spec)`
(ported from PM `contracts/media.py`) return the provider-shaped dict and call nothing, so the whole assembly is tested
with no network. `request_hash(spec)` is the identity of "the same request".

## 5. Storage (one structural change: `video_renders` + two columns)

```sql
create table public.video_renders (
  id             uuid primary key default gen_random_uuid(),
  production_id  uuid not null references public.productions (id) on delete cascade,
  shot_id        uuid not null references public.shots (id) on delete cascade,
  job_id         uuid references public.jobs (id) on delete set null,
  status         text not null default 'queued'
                   check (status in ('queued', 'running', 'done', 'failed', 'refused')),
  engine         text not null,
  model          text not null,
  spec           jsonb not null,        -- contracts.video_gen.RenderSpec, exactly as sent (no image bytes)
  request_hash   text not null,
  seed           bigint,                -- null only for an engine that takes none
  prompt_id      uuid references public.video_prompts (id) on delete set null,
  provider_id    text,                  -- Omni interaction id / Veo operation name: resume, later extend/edit
  take_id        uuid references public.takes (id) on delete set null,   -- the take it made
  error          text,                  -- written for people, never a provider's own text
  refusal        text,
  usage          jsonb not null default '{}'::jsonb,   -- tokens or seconds, latency, bytes; never shown
  created_by     uuid references public.profiles (id) on delete set null,
  created_at     timestamptz not null default now(),
  updated_at     timestamptz not null default now()
);
-- + indexes on shot_id, production_id, job_id, prompt_id, take_id, created_by; touch trigger;
--   RLS on, one read policy on can_view_production(); no write policies (as every table).
alter table public.takes add column origin text not null default 'upload' check (origin in ('upload', 'generated'));
alter table public.takes add column render_id uuid references public.video_renders (id) on delete set null;
alter table public.shots add column video_settings jsonb not null default '{}'::jsonb;
```

A render becomes a take only when it succeeds, so the `takes` invariants (a stored file, a mime, bytes) stay as they
are. A migration (`npx supabase migration new video_renders`), pgTAP rows in `supabase/tests/database/`, and the next
schema pair. That is v12 if it is still unapplied on the hosted project (folded in, per the rule), otherwise
`schema_v13.sql` + `upgrade_v12_to_v13.sql` (D5).

## 6. The function: `src/services/video_render/` (fork of PM `services/video_render`)

| File | From PM | Divergence (goes in `UPSTREAM.md`) |
|---|---|---|
| `engine/omni.py` | `engine/omni.py` | + seed and options fields as Phase 0 finds them; frame position setting if proven |
| `engine/veo.py` | `engine/veo.py` | + `seed`, `negativePrompt`, `sampleCount`, `personGeneration` as proven; resume (`on_submitted`) |
| `engine/transport.py`, `engine/fake.py` | same | none |
| `engine/take.py` → `engine/render.py` | `engine/take.py` | Hiru rows (`video_renders`, `takes`); no credits, no `generation_takes`; refs from Hiru buckets |
| `runtime/store.py`, `runtime/config.py` | `runtime/storage.py`, `config.py` | vendored Hiru store (as `frame_render`), `GOOGLE__API_KEY`, `VIDEO__*` |
| `app/handler.py` | `app/handler.py` | Hiru's job contract (`src/services/echo/` template) |
| not copied | `minimax.py`, `seedance.py`, `image.py`, `content.py`, `token_tracker.py` | other providers; PM billing |

The flow keeps PM's guarantees:
- **claim**: `update video_renders set status='running' where id=… and status='queued'`. A re-delivered task that finds no
  row to claim does nothing, so a re-delivery never pays for a second video.
- **resume**: the provider id is written the moment submit returns. A re-delivered task finds a `running` row with an id
  and polls it instead of submitting again (PM `resume_claim`, compare-and-swap on `provider_id`).
- **images travel inline as base64**, never as a link to our storage.
- **a refusal is a result** (`refused`, reason for the person, answered 200, never retried). A failed render is marked
  failed and answers 200. Only a retry that can help answers 500.
- **download retries hard**: by then the video is paid for.
- **absent-safe**: no `GOOGLE__API_KEY` means the API reports `video_generation: unavailable` and the Generate button
  says why. Upload keeps working. `VIDEO__FAKE_PROVIDER=true` runs the whole path with no network, in tests and on
  localhost.

Registered in `task_manager.FUNCTIONS` (`JobKind.VIDEO_RENDER`, `hiru-video-render`, port **8212**, deadline 1800 s, because
Veo takes minutes), in `deploy-functions.yml` and in `scripts/start-functions.ps1`. A per-production cap on running
renders (`VIDEO__MAX_RUNNING_PER_PRODUCTION`, default 4) is enforced by the API. Every render writes a `token_usage` row
(Omni reports tokens; Veo reports seconds in `usage`, see D3).

This is a render, not an agent: no model reasons here, so it has no `hiru_ai` part, like `frame_render`'s painter.

## 7. API (`api/routers/handoff.py` grows; a new `api/routers/renders.py` if it gets long)

| Route | What | Permission |
|---|---|---|
| `GET  .../shots/{id}/render-plan` | the resolved `RenderSpec` for this shot now, with each value's source, the default and current reference lists, the engine capabilities, checks, `ready` | `VIEW` |
| `PUT  .../shots/{id}/video-settings` | save the shot's overrides and/or reference list (`origin: person`); `{}` resets to Hiru's choice | `RENDER_VIDEO` |
| `POST .../shots/{id}/renders` | `{overrides?, takes?, seed?}` → resolves, validates, refuses on a blocking check (422 with the checks), draws seeds, inserts rows + job, dispatches | `RENDER_VIDEO` |
| `POST .../renders/{id}/again` | same spec and seed (`from_take`), or `{"vary": true}` for a new seed | `RENDER_VIDEO` |
| `GET  .../shots/{id}/handoff` | as today, plus the shot's renders (status, engine, seed, settings in words) and `origin` on each take | `VIEW` |
| `GET  .../renders/{id}` | one render's status and the request it sent (images as `/files/{ticket}`) | `VIEW` |
| `POST .../references/uploads` | a person's own reference picture (PNG/JPEG/WebP) for a shot's list | `RENDER_VIDEO` |

- A new `Permission.RENDER_VIDEO` in `contracts/roles.py`, because a render spends money and an upload does not (D4 says
  who gets it).
- Routers never query Supabase: `video_renders` gets a `RendersRepo` protocol, a Supabase repository and a fake in
  `tests/api/fakes.py`.
- Media reaches the browser only through `media_links.url()` → `/files/{ticket}`.
- `render-plan` and `renders` share one function, so what is previewed is what is sent. `POST` re-resolves and refuses
  when the request has changed since the preview it was pressed on (`request_hash` sent back by the panel).

## 8. Interface (`hiru-ai-studio-interface`, Screen 4)

A **Generate** panel next to the prompt in `features/handoff`:

- **Engine**: Omni Flash (default) / Veo 3.1 / Veo 3.1 Fast, with "not yet verified" until Phase 6. Changing it re-reads
  the plan, and options the engine cannot take disappear with the reason.
- **Settings**: resolution, aspect (the production's, shown), length (the shot's, other values from the engine's ladder
  only), takes per press, negative prompt and engine options where they exist. Each shows where its value came from and
  has "Save for this shot" and "Use production default".
- **Reference tray**: the slots `Start frame` / `End frame`, then the ordered references as cards (thumbnail, `IMAGE_REF_n`
  or "image n", what it is bound to, label). Drag to reorder (the tags renumber in front of the person), remove, add from
  the canon / looks / frames / takes / an upload, rebind, relabel. "Left out: …" lists what the engine's cap cut. "Reset to
  Hiru's choice".
- **Seed**: Random (shows the drawn seeds once sent) / Fixed (number) / From a take. The panel says when the engine does
  not take a seed or one is not proven.
- **"What will be sent"**: the exact prompt text with its citation block, the images in order, every setting. The
  checks sit beside it, blocking ones on top.
- **Takes log** (`takes-log.tsx`): generated takes next to uploaded ones, each with engine, seed and settings in words,
  plus **Make again**, **Vary** and **Use these settings**. Queued and running renders show live, and failed or refused
  ones show their reason. Accept is today's button and flow.
- **No credits, no costs, no prices** anywhere.

The interface follows its mock-data seam: the panel works against mocks first, then the API.

## 9. Phases

Each phase ends with `ruff`, `mypy`, `pytest -q`, `npx supabase test db`, advisors, and an update to `IMPLEMENTED.md`.

### Phase 0: map the two APIs (free) and one take each (the person's)
- `scripts/video_probe.py`: deliberately invalid requests (a 400 names the field and costs nothing) to settle, for
  **each engine on our key**: the seed field and its range, takes per call (`candidateCount` / `sampleCount`),
  negative prompt, person generation, audio, frames before references (Omni), references together with a start frame
  (Veo), the real reference cap, the accepted durations, aspects and resolutions.
- `--generate --yes` (the person runs it; it costs money): one Omni and one Veo take; then the **same request and seed
  twice** to measure whether a seed repeats a take. The findings set `EngineCapability.seed` (`honoured` / `accepted` /
  `none`) and the other fields. Written to `IMPLEMENTED.md` with the cost (cost appears there only).

### Phase 1: contracts (offline)
`contracts/video_gen.py`: capabilities, `VideoSettings`, `resolve`, `RefBinding`, `default_references`, `SeedChoice`,
`RenderSpec`, `validate`, `check_render`, the two adapters, `request_hash`. Tests: attached == cited and order kept for
both engines; tag numbering under reorder; label refusals; layer merge and sources; blocking vs advisory checks; seed
drawing, `value + i`, `from_take`; the engine caps (Veo 8 s rule, `max_refs` cut listed); the default list against the
frame rule (only heard → not attached, look sheet first).

### Phase 2: storage (local stack)
Migration, RLS read policy, pgTAP, the schema pair (D5), three-way dump comparison.

### Phase 3: the function (offline, fake provider)
Fork with `UPSTREAM.md`; claim / resume / refusal / failure / download-retry tests with fake HTTP; idempotency per
`job_id`; registered in the three places.

### Phase 4: API (offline)
Routes, `RENDER_VIDEO`, repos and fakes, preview == send, the running cap, absent-safe without a key, `origin` on takes,
404 for a production the caller cannot see.

### Phase 5: interface (mocks, then localhost)
The Generate panel, reference tray, seed, "what will be sent", and the takes log additions.

### Phase 6: live on localhost (the person's)
A real scene: Omni default, a Veo comparison, reorder and rebind references and see it follow, make-again with a seed,
accept, carry the last frame to the next shot. Set `verified=True` per engine only after this. **Nothing is deployed
until the person says so.**

## 10. What this plan does not do
- It changes nothing in PromptMotion and no shot planner, agent or prompt writer.
- It does not rewrite prose for Omni. If Omni needs differently shaped prose, that is a new prompt serializer in
  `shot_producer` (and its `hiru_ai` part), planned separately after Phase 6 shows the need.
- It does not do extend / edit / interpolate-from-take. `provider_id` is stored from day one so they can come later.
- It does not trim or retime: overruns are reported, as everywhere.
- It does not turn on 10 s shots (Q4).

## 11. Risks
| Risk | Answer |
|---|---|
| Seed does not repeat a take on one or both engines | Phase 0 measures it. The capability says so and the panel never promises it |
| Omni's real duration does not match the request | the existing length note on the take; reported, never trimmed |
| A re-delivered task pays twice | claim + resume (PM's, tested) |
| Reference order silently broken by a later change | the attached == cited, in-order test runs on both adapters; `omni.py` never sorts |
| Model ids move (previews renamed) | `VIDEO__MODELS` overrides without a code change; `model` is a setting |
| Veo spends money fast | `RENDER_VIDEO` permission, the running cap, takes ≤ 4 a press, the usage percentage |

## 12. Decisions for the person
- **D1. Google for video only**: confirm that Omni Flash and Veo may be used for rendering takes, and that no Google
  model writes prompts or text. *(Recommended: yes, as written in §2.)*
- **D2. Which engines to offer**: Omni Flash (default), Veo 3.1, Veo 3.1 Fast. Add Veo 3.1 Lite (cheaper, start frame
  only, no references)? *(Recommended: not at first; it cannot take references.)*
- **D3. How video counts toward the usage percentage**: Omni reports tokens, Veo reports seconds. Options: a hidden
  per-second token equivalent per engine in config, so the one % stays, or a second video budget so the top bar shows the
  larger of the two. *(Recommended: token equivalent; one number.)*
- **D4. Who may render**: `RENDER_VIDEO` for admin, producer and director only, or for everyone who has `GENERATE`
  today? *(Recommended: admin, producer, director.)*
- **D5. Schema version**: is v12 applied to the hosted project yet? If not, fold into v12; if it is, v13.
- **D6. Key**: Gemini API key (`GOOGLE__API_KEY`, what PM uses), or Vertex AI with a service account? *(Recommended: the
  Gemini API key for localhost and dev; Vertex later if quotas need it.)*
- **D7. Seed default**: random-and-recorded *(recommended)*, or fixed per shot so every first take of a shot starts from
  the same seed.

## 13. Sources
- PromptMotion (read only, commit `a027aec`): `src/services/video_render/**`, `src/libs/contracts/media.py`
  (`ENGINE_CAPABILITIES`, `build_omni_input`, `build_veo_input`, `TakeRequest`, `TakeResult`),
  `plans/2026-09-23/s0-omni-reality-check.md`, `plans/2026-09-23/video-engines-implemented.md`,
  `docs/engines/veo-3-1-prompting-guide.md`.
- Hiru: `api/routers/handoff.py`, `frame_render/engine/pipeline.py`, `contracts/veo.py`, `contracts/production.py`,
  `contracts/producer.py` (`Pins`), `Database/schema_v12.sql` (`takes`, `first_frames`, `video_prompts`, `canon_*`),
  `api/workers/task_manager.py`, plan/2026-10-23 PLAN.md Q1 and Q4.
