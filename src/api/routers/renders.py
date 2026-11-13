"""Making a take in Hiru with Omni Flash or Veo (plan/2026-11-06c §7). The upload path in `handoff.py` is unchanged.

    GET   .../shots/{id}/render-plan          the exact request that would be sent, with every setting's source
    PUT   .../shots/{id}/video-settings       the shot's overrides and/or its own reference list (reset = Hiru's choice)
    POST  .../shots/{id}/references/uploads   a person's own picture for the shot's list (PNG / JPEG / WebP)
    POST  .../shots/{id}/renders              resolve → validate → draw seeds → one queued row per take → one job
    POST  .../renders/{id}/again              the same request and seed, or `vary` for a new seed
    GET   .../renders/{id}                    one render's status and the request it sent

`render-plan` and `renders` share `build_plan`, so what is previewed is what is sent; POST re-resolves and refuses
when the request has changed since the preview it was pressed on. Checks report; they never edit the prompt or
a person's list.
Nothing here shows a cost. Pictures reach the browser only through `/files/{ticket}`.
"""
from __future__ import annotations

from typing import Annotated
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile, status
from pydantic import BaseModel, Field, ValidationError

from api.config import Settings, get_settings
from api.deps.authz import ProductionAccess, require_permission
from api.deps.db import get_repos
from api.repositories import Repos, Row
from api.routers.handoff import handoff_checks
from api.routers.production import Loaded, load_shot
from api.services import media_links, media_thumbs
from api.services import renders as svc
from api.services.production import ShotState
from contracts.producer import Check
from contracts.roles import Permission
from contracts.video_gen import (
    ENGINE_CAPABILITIES,
    MAX_REFERENCE_BYTES,
    RefSource,
    RenderSpec,
    SeedChoice,
    ShotVideoState,
    VideoOverrides,
    draw_seeds,
    image_kind,
    label_problem,
    request_hash,
    seed_phrase,
    validate_render,
)

router = APIRouter(prefix="/v1/productions/{production_id}", tags=["renders"])
ReposDep = Annotated[Repos, Depends(get_repos)]
SettingsDep = Annotated[Settings, Depends(get_settings)]
CanView = Annotated[ProductionAccess, Depends(require_permission(Permission.VIEW))]
CanRender = Annotated[ProductionAccess, Depends(require_permission(Permission.RENDER_VIDEO))]


class SaveSettings(BaseModel):
    """Only the fields sent are changed. `settings: null` clears the shot's overrides; `references: null` goes back to
    Hiru's choice; `reset` does both."""

    settings: VideoOverrides | None = None
    references: list[svc.RefIn] | None = Field(default=None, max_length=14)
    reset: bool = False


class RenderRequest(BaseModel):
    draft: bool = False  # a quick look at 360p with Omni Flash instead of the production's take
    overrides: VideoOverrides | None = None  # one-off, for this press
    request_hash: str | None = None  # from the preview this press was made on; a different one is refused
    save_for_shot: bool = False  # also keep the overrides on the shot


class Again(BaseModel):
    vary: bool = False  # a new seed instead of the same one


def _blocked(plan: svc.Plan) -> HTTPException:
    failing = [c.model_dump() for c in plan.checks if c.tone == "fail"]
    return HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT,
                         {"message": "This request cannot be sent yet.", "checks": failing})


async def _plan(repos: Repos, access: ProductionAccess, settings: Settings, shot_id: UUID, *,
                run: VideoOverrides | None = None, draft: bool = False) -> tuple[svc.Plan, UUID]:
    ld, st = await load_shot(repos, access, shot_id)
    plan = await svc.build_plan(repos, settings, ld, st, run=run, handoff=handoff_checks(ld, st), draft=draft)
    return plan, UUID(st.id)


@router.get("/shots/{shot_id}/render-plan", response_model=svc.PlanView)
async def render_plan(production_id: UUID, shot_id: UUID, access: CanView, repos: ReposDep, settings: SettingsDep,
                      overrides: Annotated[str | None, Query(max_length=4000)] = None,
                      draft: bool = False) -> svc.PlanView:
    """`overrides`: the panel's unsaved changes as JSON (a `VideoOverrides`), so the preview shows them. `draft`: the
    plan for Render draft (360p, Omni Flash)."""
    run = None
    if overrides:
        try:
            run = VideoOverrides.model_validate_json(overrides)
        except ValidationError:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "Those settings could not be read.") from None
    plan, sid = await _plan(repos, access, settings, shot_id, run=run, draft=draft)
    return svc.plan_view(sid, plan, settings)


class PlanPair(BaseModel):
    take: svc.PlanView
    draft: svc.PlanView


@router.get("/shots/{shot_id}/render-plans", response_model=PlanPair)
async def render_plans(production_id: UUID, shot_id: UUID, access: CanView, repos: ReposDep,
                       settings: SettingsDep) -> PlanPair:
    """The take's plan and the draft's from ONE load of the shot (plan/2026-11-13b phase 5): the Generate card used to
    make two requests that each loaded the whole scene. Same builder as `render-plan`, so they cannot disagree."""
    ld, st = await load_shot(repos, access, shot_id)
    return await plans_for(repos, settings, ld, st)


async def plans_for(repos: Repos, settings: Settings, ld: Loaded, st: ShotState) -> PlanPair:
    """Both plans for a shot already loaded (also `GET .../shots/{id}/panel`, plan/2026-11-13d phase 4)."""
    handoff = handoff_checks(ld, st)
    take = await svc.build_plan(repos, settings, ld, st, handoff=handoff)
    draft = await svc.build_plan(repos, settings, ld, st, handoff=handoff, draft=True)
    return PlanPair(take=svc.plan_view(UUID(st.id), take, settings), draft=svc.plan_view(UUID(st.id), draft, settings))


@router.put("/shots/{shot_id}/video-settings", response_model=svc.PlanView)
async def save_video_settings(production_id: UUID, shot_id: UUID, body: SaveSettings, access: CanRender,
                              repos: ReposDep, settings: SettingsDep) -> svc.PlanView:
    ld, st = await load_shot(repos, access, shot_id)
    state = svc.shot_state(st)
    if body.reset:
        state = ShotVideoState(uploads=state.uploads)
    else:
        sent = body.model_fields_set
        if "settings" in sent:
            state.settings = body.settings or VideoOverrides()
        if "references" in sent:
            if body.references is None:
                state.references = None
            else:
                for item in body.references:  # refused at save, not only at send: the model would draw it as lettering
                    problem = label_problem(item.label)
                    if problem:
                        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, problem)
                pictures, _ = await svc.gather(repos, ld, st, state)
                state.references = svc.resolve_refs(body.references, pictures)
    plan = await svc.build_plan(repos, settings, ld, st, state=state, handoff=handoff_checks(ld, st))
    await repos.shots.update(UUID(st.id), {"video_settings": state.model_dump(mode="json")})
    await repos.audit.record(action="video.settings", entity="shot", entity_id=st.id, actor_user_id=access.user.id,
                             production_id=access.production_id,
                             diff={"reset": body.reset, "references": len(state.references or [])
                                   if state.references is not None else None})
    return svc.plan_view(UUID(st.id), plan, settings)


@router.post("/shots/{shot_id}/references/uploads", response_model=svc.CatalogItem,
             status_code=status.HTTP_201_CREATED)
async def upload_reference(production_id: UUID, shot_id: UUID, file: Annotated[UploadFile, File()], access: CanRender,
                           repos: ReposDep) -> svc.CatalogItem:
    """A person's own picture for this shot's list. Checked by content; stored in the private `references` bucket."""
    _, st = await load_shot(repos, access, shot_id)
    data = bytearray()
    while chunk := await file.read(1024 * 1024):
        data += chunk
        if len(data) > MAX_REFERENCE_BYTES:
            raise HTTPException(status.HTTP_413_CONTENT_TOO_LARGE,
                                f"A picture can be at most {MAX_REFERENCE_BYTES // (1024 * 1024)} MB.")
    kind = image_kind(bytes(data))
    if kind is None:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "Upload a PNG, JPEG or WebP picture.")
    ext, mime = kind
    picture_id = uuid4()
    path = f"{production_id}/uploads/{st.id}/{picture_id}.{ext}"
    await media_thumbs.store_with_thumb(repos, "references", path, bytes(data), mime)
    src = RefSource(kind="upload", id=picture_id, path=path, bucket="references")
    state = svc.shot_state(st)
    state.uploads.append(src)
    await repos.shots.update(UUID(st.id), {"video_settings": state.model_dump(mode="json")})
    await repos.audit.record(action="video.reference_upload", entity="shot", entity_id=st.id,
                             actor_user_id=access.user.id, production_id=access.production_id,
                             diff={"bytes": len(data)})
    return svc.CatalogItem(kind="upload", id=picture_id, binds_to=None, label="a picture you added", version=None,
                           url=media_links.url("references", path),
                           thumb_url=media_links.thumb_url("references", path))


async def _begin(repos: Repos, access: ProductionAccess, settings: Settings, plan: svc.Plan, shot_id: UUID,
                 seeds: list[int], *, actor_action: str, extra: dict | None = None) -> svc.RenderStarted:
    specs = svc.specs_for(plan, seeds)
    started = await svc.start(repos, settings, production_id=access.production_id, shot_id=shot_id,
                              actor=access.user.id, specs=specs,
                              seeds_text="" if plan.cap.seed == "none" else seed_phrase(seeds))
    await repos.audit.record(action=actor_action, entity="shot", entity_id=str(shot_id), actor_user_id=access.user.id,
                             production_id=access.production_id,
                             diff={"job_id": str(started.job_id), "engine": plan.resolved.engine, "takes": len(specs),
                                   "seeds": [s.seed for s in specs], **(extra or {})})
    return started


@router.post("/shots/{shot_id}/renders", response_model=svc.RenderStarted, status_code=status.HTTP_202_ACCEPTED)
async def start_renders(production_id: UUID, shot_id: UUID, body: RenderRequest, access: CanRender, repos: ReposDep,
                        settings: SettingsDep) -> svc.RenderStarted:
    plan, sid = await _plan(repos, access, settings, shot_id, run=body.overrides, draft=body.draft)
    if body.request_hash is not None and body.request_hash != plan.hash:
        raise HTTPException(status.HTTP_409_CONFLICT,
                            "The request changed since you looked at it. Review it and press Generate again.")
    if not plan.ready:
        raise _blocked(plan)
    take_seed = None
    if plan.resolved.seed.mode == "from_take":
        take_seed = await _seed_of_take(repos, access, plan.resolved.seed)
    seeds = svc.seeds_for(plan, plan.resolved.seed, plan.resolved.takes, take_seed=take_seed)
    if body.save_for_shot and body.overrides is not None:
        state = plan.state.model_copy(update={"settings": _merge(plan.state.settings, body.overrides)})
        await repos.shots.update(sid, {"video_settings": state.model_dump(mode="json")})
    action = "video.draft" if body.draft else "video.render"
    return await _begin(repos, access, settings, plan, sid, seeds, actor_action=action)


def _merge(base: VideoOverrides, over: VideoOverrides) -> VideoOverrides:
    """The shot's overrides with this press's fields on top (only fields the press set)."""
    data = base.model_dump()
    for name in over.model_fields_set:
        value = getattr(over, name)
        if name == "options":
            data["options"] = {**data["options"], **value}
        elif value is not None:
            data[name] = value if not isinstance(value, SeedChoice) else value.model_dump()
    return VideoOverrides.model_validate(data)


async def _seed_of_take(repos: Repos, access: ProductionAccess, choice: SeedChoice) -> int:
    if choice.take_id is None:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "Choose which take's seed to use.")
    take = await repos.takes.get(access.production_id, choice.take_id)
    render = None
    if take and take.get("render_id"):
        render = await repos.renders.get(access.production_id, UUID(str(take["render_id"])))
    if render is None or render.get("seed") is None:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "That take has no seed to reuse.")
    return int(render["seed"])


async def _render(repos: Repos, access: ProductionAccess, render_id: UUID) -> Row:
    row = await repos.renders.get(access.production_id, render_id)
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Render not found.")
    return row


@router.post("/renders/{render_id}/again", response_model=svc.RenderStarted, status_code=status.HTTP_202_ACCEPTED)
async def render_again(production_id: UUID, render_id: UUID, body: Again, access: CanRender, repos: ReposDep,
                       settings: SettingsDep) -> svc.RenderStarted:
    """The same request again (same pictures in the same order, same seed), or the same with a new seed (`vary`)."""
    row = await _render(repos, access, render_id)
    try:
        spec = RenderSpec.model_validate(row["spec"])
    except ValueError:
        raise HTTPException(status.HTTP_409_CONFLICT, "That request can no longer be read.") from None
    shot_id = UUID(str(row["shot_id"]))
    ld, st = await load_shot(repos, access, shot_id)
    spec = spec.model_copy(update={"references": [b.model_copy(update={"source": b.source.model_copy(
        update={"sha256": ""})}) for b in spec.references]})
    plan = await svc.build_plan(repos, settings, ld, st, handoff=handoff_checks(ld, st))
    # The repeat is the OLD request, not today's: the plan only supplies availability and the engine's rules.
    blocking = [c for c in validate_render(spec) if c.tone == "fail"]
    if not settings.video_available:
        blocking.append(Check(label=svc.UNAVAILABLE, tone="fail"))
    if blocking:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, {
            "message": "This request cannot be sent any more.", "checks": [c.model_dump() for c in blocking]})
    cap = plan.cap if plan.cap.key == spec.engine else ENGINE_CAPABILITIES[spec.engine]
    if cap.seed == "none":
        seeds = [0]
    elif body.vary:
        seeds = draw_seeds(SeedChoice(), 1)
    else:
        seeds = [int(row["seed"])] if row.get("seed") is not None else draw_seeds(SeedChoice(), 1)
    specs = [spec.model_copy(update={"seed": None if cap.seed == "none" else seeds[0]})]
    started = await svc.start(repos, settings, production_id=access.production_id, shot_id=shot_id,
                              actor=access.user.id, specs=specs,
                              seeds_text="" if cap.seed == "none" else seed_phrase(seeds))
    await repos.audit.record(action="video.vary" if body.vary else "video.again", entity="render",
                             entity_id=str(render_id), actor_user_id=access.user.id,
                             production_id=access.production_id,
                             diff={"job_id": str(started.job_id), "seed": specs[0].seed,
                                   "request_hash": request_hash(specs[0])})
    return started


@router.get("/renders/{render_id}", response_model=svc.RenderView)
async def get_render(production_id: UUID, render_id: UUID, access: CanView, repos: ReposDep,
                     settings: SettingsDep) -> svc.RenderView:
    row = await _render(repos, access, render_id)
    await svc.expire_stale(repos, settings, [row])
    return svc.render_view(row, with_request=True)
