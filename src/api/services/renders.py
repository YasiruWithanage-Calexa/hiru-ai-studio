"""Making a take in Hiru: what WOULD be sent (the plan), the checks on it, and the rows that send it
(plan/2026-11-06c §7).

`build_plan` and `start` share one resolution, so what the panel previews is what is sent. Nothing here edits the prose
or a person's list: checks report, a person decides. A browser never holds a storage path: it names a picture by
(kind, id) and this module resolves it from what the shot may use (`Pictures`).
"""
from __future__ import annotations

import logging
import secrets
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Literal
from uuid import UUID, uuid4

from fastapi import HTTPException, status
from pydantic import BaseModel, Field

from api.config import Settings
from api.repositories import Repos, Row
from api.routers.production import Loaded
from api.services import media_links
from api.services.production import ShotState
from api.workers import task_manager
from contracts.canon import look_sheet_path
from contracts.jobs import JobKind
from contracts.producer import Check, shot_canon_ids
from contracts.production import ProductionSettings
from contracts.veo import FrameStrategy
from contracts.video_gen import (
    DEFAULT_ENGINE,
    ENGINE_CAPABILITIES,
    DefaultReferences,
    EngineCapability,
    RefBinding,
    RefKind,
    RefSource,
    RenderFacts,
    RenderSpec,
    ResolvedSettings,
    SeedChoice,
    SheetCandidate,
    ShotVideoState,
    Slot,
    VideoOverrides,
    asset_id,
    check_render,
    default_references,
    describe_spec,
    draw_seeds,
    request_hash,
    resolve,
    seed_note,
    spec_for,
    tags_of,
    validate_render,
    wire_order,
)

_logger = logging.getLogger(__name__)
UNAVAILABLE = "Video generation is not set up on this server. Uploading a take from Flow still works."
STALE_ERROR = "The video took too long and was stopped. Try again."
ALLOWED_BUCKETS = ("frames", "references", "takes")


# ── what the browser sees ──────────────────────────────────────────────────────────────────────────────────────


class RefIn(BaseModel):
    """A picture the browser names: never a path."""

    slot: Slot
    kind: RefKind
    id: UUID
    binds_to: UUID | None = None
    label: str = Field(max_length=120)


class RefOut(BaseModel):
    slot: Slot
    kind: RefKind
    id: UUID
    binds_to: UUID | None
    label: str
    origin: Literal["code", "person"]
    tag: str  # `<IMAGE_REF_0>`, `image 2`, "start frame": the name the request gives it
    url: str | None  # /files/{ticket}
    thumb_url: str | None = None  # the small WebP beside it, for tiles
    version: int | None


class CatalogItem(BaseModel):
    kind: RefKind
    id: UUID
    binds_to: UUID | None
    label: str
    url: str | None
    thumb_url: str | None = None
    version: int | None


class EngineView(BaseModel):
    key: str
    label: str
    model: str
    durations: list[int]
    aspects: list[str]
    resolutions: list[str]
    max_refs: int
    first_frame: bool
    last_frame: bool
    refs_with_first_frame: bool
    seed: str
    seed_note: str
    negative_prompt: bool
    options: dict[str, dict[str, Any]]
    verified: bool
    notes: str


class RequestView(BaseModel):
    prompt: str  # the prose with its citation block: exactly what is sent
    references: list[RefOut]
    config: dict[str, Any]


class PlanView(BaseModel):
    shot_id: UUID
    available: bool
    unavailable_reason: str
    engines: list[EngineView]
    settings: ResolvedSettings
    references: list[RefOut]
    references_origin: Literal["hiru", "person"]
    hiru_references: list[RefOut]  # what "Reset to Hiru's choice" brings back
    left_out: list[str]
    catalog: list[CatalogItem]
    request: RequestView
    checks: list[Check]  # blocking first
    ready: bool
    request_hash: str
    seed_note: str


class RenderView(BaseModel):
    id: UUID
    shot_id: UUID
    status: str
    engine: str
    engine_label: str
    settings_text: str  # "Omni Flash · 720p · 16:9 · 8 s · 3 pictures · seed 1234"
    seed: int | None
    take_id: UUID | None
    error: str | None
    refusal: str | None
    created_at: str
    request: RequestView | None = None


class RenderStarted(BaseModel):
    job_id: UUID
    renders: list[RenderView]
    seeds: str  # "seeds 1234, 1235" or "" when the engine takes none


def engine_view(cap: EngineCapability) -> EngineView:
    return EngineView(
        key=cap.key, label=cap.label, model=cap.model, durations=list(cap.durations), aspects=list(cap.aspects),
        resolutions=list(cap.resolutions), max_refs=cap.max_refs, first_frame=cap.first_frame,
        last_frame=cap.last_frame, refs_with_first_frame=cap.refs_with_first_frame, seed=cap.seed,
        seed_note=seed_note(cap.key), negative_prompt=cap.negative_prompt,
        options={k: v.model_dump(mode="json") for k, v in cap.options.items()}, verified=cap.verified, notes=cap.notes)


# ── pictures: the catalog a shot may use ───────────────────────────────────────────────────────────────────────


def _path_of(asset: Any) -> str:
    return str((asset.get("path") if isinstance(asset, dict) else asset) or "")


def canon_sources(row: Row) -> list[RefSource]:
    """Every sheet of an entity's CURRENT card, newest first (alternates are other pictures of the same card)."""
    current = row.get("current") or {}
    version_id = current.get("id") or row["id"]
    out = []
    for asset in current.get("reference_assets") or []:
        path = _path_of(asset)
        if path:
            out.append(RefSource(kind="canon_sheet", id=asset_id(version_id, path), path=path, bucket="references",
                                 version=current.get("version")))
    return out


def look_sources(look: Mapping[str, Any]) -> list[RefSource]:
    out = []
    for asset in look.get("sheet_assets") or []:
        path = _path_of(asset)
        if path:
            out.append(RefSource(kind="look_sheet", id=asset_id(look["id"], path), path=path, bucket="references"))
    return out


def _look_first(look: Mapping[str, Any]) -> RefSource | None:
    path = look_sheet_path(look)
    return next((s for s in look_sources(look) if s.path == path), None)


@dataclass
class Pictures:
    """Everything this shot may use, by (kind, id): the single place a browser's choice becomes a storage path."""

    by_key: dict[tuple[str, UUID], RefSource] = field(default_factory=dict)
    binds: dict[tuple[str, UUID], UUID | None] = field(default_factory=dict)
    labels: dict[tuple[str, UUID], str] = field(default_factory=dict)

    def add(self, src: RefSource, label: str, binds_to: UUID | None) -> None:
        key = (src.kind, src.id)
        self.by_key.setdefault(key, src)
        self.binds.setdefault(key, binds_to)
        self.labels.setdefault(key, label)


_WORDS = {"character": "the character sheet for", "location": "the location plate for",
          "prop": "the reference sheet for"}


async def gather(repos: Repos, ld: Loaded, st: ShotState, state: ShotVideoState) -> tuple[Pictures, RefSource | None]:
    """The pictures the shot may use, and the previous take's last frame when this shot carries on from it."""
    pics = Pictures()
    for row in ld.canon:
        for src in canon_sources(row):
            pics.add(src, f"{_WORDS.get(str(row['kind']), 'the sheet for')} {row['name']}", UUID(str(row["id"])))
    for look in await repos.looks.list_for_production(UUID(str(ld.production["id"]))):
        owner = next((r for r in ld.canon if str(r["id"]) == str(look["entity_id"])), None)
        for src in look_sources(look):
            pics.add(src, f"the look sheet for {owner['name'] if owner else 'this person'}",
                     UUID(str(look["entity_id"])))
    for frame in st.frames:
        if frame.get("storage_path") and frame.get("status") == "done":
            src = RefSource(kind="accepted_frame", id=UUID(str(frame["id"])), path=str(frame["storage_path"]),
                            bucket="frames")
            pics.add(src, "the opening frame" if frame.get("accepted_at") else "a first frame of this shot", None)
    carried: RefSource | None = None
    previous = next((s for s in ld.states if int(s.row["number"]) == int(st.row["number"]) - 1), None)
    if previous is not None:
        for take in await repos.takes.list_for_shots([previous.id]):
            if take.get("last_frame_path") and take["status"] == "accepted":
                carried = RefSource(kind="take_last_frame", id=UUID(str(take["id"])), path=str(take["last_frame_path"]),
                                    bucket="frames")
                pics.add(carried, f"the last frame of {previous.code}", None)
    for up in state.uploads:
        pics.add(up, "a picture you added", None)
    return pics, carried


def _candidates(ld: Loaded, st: ShotState) -> list[SheetCandidate]:
    """The frame rule's entities in its order, each with the sheet it would attach."""
    by_id = {str(r["id"]): r for r in ld.canon}
    out: list[SheetCandidate] = []
    for cid in shot_canon_ids(ld.scene, st.staged.on_screen, st.edits):
        row = by_id.get(cid)
        if row is None:
            continue
        sheets = canon_sources(row)
        look = ld.looks.get(cid) if row["kind"] == "character" else None
        look_sheet = _look_first(look) if look is not None else None
        out.append(SheetCandidate(entity_id=UUID(cid), kind=row["kind"], name=str(row["name"]), seen=True,
                                  sheet=sheets[0] if sheets else None, look_sheet=look_sheet))
    return out


# ── the plan ───────────────────────────────────────────────────────────────────────────────────────────────────


@dataclass
class Plan:
    state: ShotVideoState
    resolved: ResolvedSettings
    cap: EngineCapability
    default: DefaultReferences
    references: list[RefBinding]
    origin: Literal["hiru", "person"]
    spec: RenderSpec  # no seed: drawn when sent
    checks: list[Check]
    hash: str
    pictures: Pictures

    @property
    def ready(self) -> bool:
        return not any(c.tone == "fail" for c in self.checks)


def shot_state(st: ShotState) -> ShotVideoState:
    try:
        return ShotVideoState.model_validate(st.row.get("video_settings") or {})
    except ValueError:
        _logger.warning("shot %s has video settings that do not parse; using Hiru's choice", st.id)
        return ShotVideoState()


def _sorted(checks: list[Check]) -> list[Check]:
    rank = {"fail": 0, "advisory": 1, "pass": 2}
    return sorted(checks, key=lambda c: rank[c.tone])


async def build_plan(repos: Repos, settings: Settings, ld: Loaded, st: ShotState, *, run: VideoOverrides | None = None,
                     references: list[RefBinding] | None = None, state: ShotVideoState | None = None,
                     handoff: list[Check] | None = None, draft: bool = False) -> Plan:
    """What would be sent for this shot now. `references`: a list to use instead of the shot's own. `draft`: the quick
    look (`DRAFT_ENGINE` at `DRAFT_RESOLUTION`) instead of the production's take."""
    state = state or shot_state(st)
    prod = ProductionSettings.model_validate(ld.production.get("settings") or {}).video
    resolved = resolve(prod, state.settings, run, production_aspect=ld.aspect, shot_seconds=int(st.row["duration_s"]),
                       draft=draft)
    problems: list[Check] = []
    if resolved.engine not in ENGINE_CAPABILITIES:
        problems.append(Check(label=f"{resolved.engine} is not a video model Hiru can use. Choose another.",
                              tone="fail"))
        resolved = resolved.model_copy(update={"engine": DEFAULT_ENGINE})
    cap = ENGINE_CAPABILITIES[resolved.engine]

    pictures, carried = await gather(repos, ld, st, state)
    accepted = (RefSource(kind="accepted_frame", id=UUID(str(st.accepted["id"])), path=str(st.accepted["storage_path"]),
                          bucket="frames") if st.accepted and st.accepted.get("storage_path") else None)
    strategy = FrameStrategy(st.row.get("frame_strategy") or "generate")
    default = default_references(cap=cap, strategy=strategy, accepted_frame=accepted, carried_frame=carried,
                                 candidates=_candidates(ld, st))
    mine = references if references is not None else state.references
    chosen = mine if mine is not None else default.bindings

    prompt = st.prompt or {}
    spec = spec_for(resolved, prose=str(prompt.get("prose") or ""), references=chosen,
                    prompt_id=UUID(str(prompt["id"])) if prompt.get("id") else None,
                    prompt_version=int(prompt["version"]) if prompt.get("version") else None,
                    frame_id=UUID(str(st.accepted["id"])) if st.accepted else None, pins=st.pins)

    checks = [*problems, *validate_render(spec, seed_choice=resolved.seed, takes=resolved.takes)]
    if not settings.video_available:
        checks.append(Check(label=UNAVAILABLE, tone="fail"))
    checks += [c for c in (handoff or []) if c.tone != "pass"]
    if st.prompt_reasons:
        checks.append(Check(label=f"The prompt is out of date: {'; '.join(st.prompt_reasons)}", tone="advisory"))
    versions = {UUID(str(r["id"])): int(r["current"]["version"]) for r in ld.canon if r.get("current")}
    names = {UUID(str(r["id"])): str(r["name"]) for r in ld.canon}
    facts = RenderFacts(seen={UUID(c.id): c.name for c in st.seen}, names=names, current_versions=versions,
                        frame_stale=st.frame_reasons.get(str(st.accepted["id"]), []) if st.accepted else [])
    checks += check_render(spec, facts)
    return Plan(state=state, resolved=resolved, cap=cap, default=default, references=list(chosen),
                origin="person" if mine is not None else "hiru", spec=spec, checks=_sorted(checks),
                hash=request_hash(spec, with_seed=False), pictures=pictures)


def _thumb(bucket: str, path: str | None) -> str | None:
    """The small copy of a PICTURE (only frames and references have one)."""
    return media_links.thumb_url(bucket, path) if path and bucket in ("frames", "references") else None


def ref_out(spec: RenderSpec, bindings: list[RefBinding] | None = None) -> list[RefOut]:
    """The pictures as the browser sees them, in WIRE order with the tag each goes by."""
    ordered = wire_order(bindings if bindings is not None else spec.references)
    tags = tags_of(spec.model_copy(update={"references": ordered}))
    return [RefOut(slot=b.slot, kind=b.source.kind, id=b.source.id, binds_to=b.binds_to, label=b.label,
                   origin=b.origin, tag=tag,
                   url=media_links.url(b.source.bucket, b.source.path) if b.source.path else None,
                   thumb_url=_thumb(b.source.bucket, b.source.path),
                   version=b.source.version) for b, tag in zip(ordered, tags, strict=True)]


def plan_view(shot_id: UUID, plan: Plan, settings: Settings) -> PlanView:
    from contracts.video_gen import build_request

    built = build_request(plan.spec)
    spec_default = plan.spec.model_copy(update={"references": plan.default.bindings})
    catalog = [CatalogItem(kind=src.kind, id=src.id, binds_to=plan.pictures.binds.get(key),
                           label=plan.pictures.labels[key], version=src.version,
                           url=media_links.url(src.bucket, src.path), thumb_url=_thumb(src.bucket, src.path))
               for key, src in plan.pictures.by_key.items()]
    return PlanView(
        shot_id=shot_id, available=settings.video_available,
        unavailable_reason="" if settings.video_available else UNAVAILABLE,
        engines=[engine_view(c) for c in ENGINE_CAPABILITIES.values()], settings=plan.resolved,
        references=ref_out(plan.spec), references_origin=plan.origin,
        hiru_references=ref_out(spec_default), left_out=plan.default.left_out, catalog=catalog,
        request=RequestView(prompt=built["prompt"], references=ref_out(plan.spec), config=built["config"]),
        checks=plan.checks, ready=plan.ready, request_hash=plan.hash, seed_note=seed_note(plan.resolved.engine))


# ── resolving what the browser names ───────────────────────────────────────────────────────────────────────────


def resolve_refs(items: list[RefIn], pictures: Pictures) -> list[RefBinding]:
    """A person's list from (kind, id) names. A picture the shot may not use is a 422, never a guess."""
    out: list[RefBinding] = []
    for item in items:
        src = pictures.by_key.get((item.kind, item.id))
        if src is None:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT,
                                "One of those pictures is not available for this shot. Reload and choose again.")
        out.append(RefBinding(slot=item.slot, source=src.model_copy(update={"sha256": ""}), binds_to=item.binds_to,
                              label=item.label, origin="person"))
    return out


# ── starting renders ───────────────────────────────────────────────────────────────────────────────────────────


def render_view(row: Row, *, with_request: bool = False) -> RenderView:
    try:
        spec: RenderSpec | None = RenderSpec.model_validate(row.get("spec") or {})
    except ValueError:
        spec = None
    cap = ENGINE_CAPABILITIES.get(str(row["engine"]))
    request = None
    if with_request and spec is not None:
        from contracts.video_gen import build_request

        built = build_request(spec)
        request = RequestView(prompt=built["prompt"], references=ref_out(spec), config=built["config"])
    return RenderView(id=row["id"], shot_id=row["shot_id"], status=str(row["status"]), engine=str(row["engine"]),
                      engine_label=cap.label if cap else str(row["engine"]),
                      settings_text=describe_spec(spec) if spec else str(row["engine"]), seed=row.get("seed"),
                      take_id=row.get("take_id"), error=row.get("error"), refusal=row.get("refusal"),
                      created_at=str(row["created_at"]), request=request)


async def expire_stale(repos: Repos, settings: Settings, rows: list[Row]) -> list[Row]:
    """A render still queued or running long after the function's own deadline will never finish: say so."""
    now = datetime.now(UTC)
    stale: list[str] = []
    for r in rows:
        if r["status"] in ("queued", "running"):
            try:
                age = (now - datetime.fromisoformat(str(r.get("updated_at") or r["created_at"]))).total_seconds()
            except ValueError:
                continue
            if age > settings.video.stale_after_s:
                stale.append(str(r["id"]))
    if stale:
        await repos.renders.update_many(stale, {"status": "failed", "error": STALE_ERROR})
        for r in rows:
            if str(r["id"]) in stale:
                r.update(status="failed", error=STALE_ERROR)
    return rows


async def start(repos: Repos, settings: Settings, *, production_id: UUID, shot_id: UUID, actor: UUID,
                specs: list[RenderSpec], seeds_text: str) -> RenderStarted:
    """Insert one `queued` row per take, then one job. The cap on running renders is enforced here, before any spend."""
    cap = settings.video.max_running_per_production
    if await repos.renders.count_active(production_id) + len(specs) > cap:
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS,
                            "Videos are already being made for this production. Wait for one to finish.")
    rows: list[Row] = [
        {"id": str(uuid4()), "production_id": str(production_id), "shot_id": str(shot_id), "status": "queued",
         "engine": s.engine, "model": s.model, "spec": s.model_dump(mode="json"), "request_hash": request_hash(s),
         "seed": s.seed, "prompt_id": str(s.prompt_id) if s.prompt_id else None, "created_by": str(actor)}
        for s in specs]
    await repos.renders.create_many(rows)
    ids = [str(r["id"]) for r in rows]
    try:
        job_id = await task_manager.dispatch(JobKind.VIDEO_RENDER, repos, actor_user_id=actor,
                                             production_id=production_id,
                                             request={"shot_id": str(shot_id), "renders": len(ids)},
                                             state={"render_ids": ids})
    except RuntimeError:
        await repos.renders.update_many(ids, {"status": "failed", "error": "The job could not be started."})
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE,
                            "The video could not be started. Try again.") from None
    await repos.renders.update_many(ids, {"job_id": str(job_id)})
    for r in rows:
        r["job_id"] = str(job_id)
        r.setdefault("created_at", datetime.now(UTC).isoformat())
    return RenderStarted(job_id=job_id, renders=[render_view(r) for r in rows], seeds=seeds_text)


def specs_for(plan: Plan, seeds: list[int]) -> list[RenderSpec]:
    """One spec per take, each with its own seed (None for an engine that takes none)."""
    if plan.cap.seed == "none":
        return [plan.spec.model_copy(update={"seed": None}) for _ in seeds]
    return [plan.spec.model_copy(update={"seed": s}) for s in seeds]


def seeds_for(plan: Plan, choice: SeedChoice, takes: int, *, take_seed: int | None = None) -> list[int]:
    if plan.cap.seed == "none":
        return [0] * takes  # nothing is drawn or sent; the length is the number of takes
    try:
        return draw_seeds(choice, takes, take_seed=take_seed, draw=secrets.randbelow)
    except ValueError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)) from None
