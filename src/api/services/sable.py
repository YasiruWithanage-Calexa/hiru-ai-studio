"""Sable's server side that is not a route (plan/2026-11-08 §4.6, §4.7): the proxy to the `sable_chat` function, what a
stored message shows (never its `meta`), where a handoff card goes, and how a card a person accepts is carried out.

Like Zora the function is internal: locally a functions-framework port; on Cloud Run the API calls it with a
Google-signed ID token. Frames are forwarded byte for byte; a failure becomes one `error` frame with a sentence for
the person.

Sable never imports Zora. The one thing it reads of Zora's is `zora.routes_here(scene)` (read-only, rule 10): whether a
scene's edits go to Zora or to the classic chat, so the handoff card opens the right composer.
"""
from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator, Callable
from typing import Any
from uuid import UUID

import httpx

from api.config import get_settings
from api.repositories import Repos, Row
from api.services import zora as scene_chats  # read-only: `routes_here` (rule 10)
from api.services.director import _id_token, sse
from api.workers import task_manager
from contracts import sceneplan
from contracts import stagemap as sm
from contracts.sable.events import UNAVAILABLE, Mention, MentionOption, Ref, SableMessage

_logger = logging.getLogger(__name__)
CARD_KINDS = ("sable_change", "sable_state", "sable_memory")
SableStreamer = Callable[[dict[str, Any]], AsyncIterator[bytes]]


async def _headers(url: str) -> dict[str, str]:
    headers = {"Content-Type": "application/json"}
    if not get_settings().local_functions:
        headers["Authorization"] = f"Bearer {await asyncio.to_thread(_id_token, url)}"
    return headers


async def stream_turn(payload: dict[str, Any]) -> AsyncIterator[bytes]:
    spec = task_manager.SABLE_CHAT
    url = task_manager.function_url(spec, get_settings())
    started = False
    try:
        headers = await _headers(url)
        timeout = httpx.Timeout(float(spec.deadline_s), connect=10.0)
        async with httpx.AsyncClient(timeout=timeout) as client, client.stream(
                "POST", url, json=payload, headers=headers) as resp:
            if resp.status_code != 200:
                _logger.warning("sable function answered %s thread=%s", resp.status_code, payload.get("thread_id"))
                yield sse("error", {"message": UNAVAILABLE})
                return
            async for chunk in resp.aiter_raw():
                started = True
                yield chunk
    except Exception:
        _logger.exception("sable stream failed thread=%s", payload.get("thread_id"))
        yield (b"\n\n" if started else b"") + sse("error", {"message": UNAVAILABLE})


def get_streamer() -> SableStreamer:
    """A dependency, so tests can stand in for the function."""
    return stream_turn


def title_of(message: str) -> str:
    """A new thread is titled from its first message: its first line, cut at a word, at most 60 characters."""
    first = (message.strip().splitlines() or [""])[0].strip()
    if len(first) <= 60:
        return first or "New chat"
    cut = first[:60].rsplit(" ", 1)[0]
    return f"{cut or first[:60]}…"


async def handoff_target(repos: Repos, production_id: Any, scene_id: Any, cache: dict[str, str]) -> str:
    """"zora" when the scene's edits go to Zora (`zora.routes_here`), "classic" otherwise; "" for a scene that
    is gone."""
    key = str(scene_id)
    if key not in cache:
        scene = await repos.scenes.get(production_id, scene_id)
        cache[key] = "" if scene is None else ("zora" if scene_chats.routes_here(scene) else "classic")
    return cache[key]


async def view(repos: Repos, production_id: Any, row: Row, cache: dict[str, str] | None = None) -> SableMessage:
    """A stored message as the panel reads it: never `meta` (rule 1); each handoff card says where it opens."""
    cache = {} if cache is None else cache
    blocks = []
    for block in row.get("blocks") or []:
        if isinstance(block, dict) and block.get("kind") == "handoff" and block.get("scene_id"):
            block = {**block, "target": await handoff_target(repos, production_id, block["scene_id"], cache)}
        blocks.append(block)
    shown = {k: v for k, v in row.items() if k != "meta"}
    return SableMessage.model_validate({**shown, "blocks": blocks})


def card_at(row: Row, index: int) -> Row | None:
    """The card a person acts on, by its place in the message's blocks; None when there is no such card."""
    blocks = row.get("blocks") or []
    if not (0 <= index < len(blocks)):
        return None
    block = blocks[index]
    return block if isinstance(block, dict) and block.get("kind") in CARD_KINDS else None


def with_status(row: Row, index: int, status: str, note: str = "") -> list[Row]:
    blocks = [dict(b) for b in row.get("blocks") or []]
    blocks[index] = {**blocks[index], "status": status, "note": note}
    return blocks


# ── cards that change the scene's state or a shot's note (plan/2026-11-09b) ───────────────────────────────────────────

OUT_OF_DATE = "Shots already made from the old version are marked out of date; nothing is regenerated by itself."


def shot_words(codes: list[str]) -> str:
    if not codes:
        return " " + OUT_OF_DATE
    return f" {', '.join(codes)} {'is' if len(codes) == 1 else 'are'} out of date now. {OUT_OF_DATE}"


async def mark_out_of_date(repos: Repos, shots: list[Row]) -> None:
    """A shot's version moves, so everything made from it (prompt, frames, video) reads as made from the old one
    (`contracts.producer.stale_reasons`). A note on a shot or a change of state moves neither the script nor the shot's
    length, so nothing else would say so (phase 6)."""
    for shot in shots:
        await repos.shots.update(UUID(str(shot["id"])), {"version": int(shot.get("version") or 1) + 1})


async def note_shots(repos: Repos, production_id: UUID, scene_id: UUID, ops: list[Row]) -> list[Row]:
    """The shots of a scene a DoP note was set on, by the ids the stored operations carry."""
    ids = {str(o.get("shot_id")) for o in ops if o.get("op") == "dop_note.set" and o.get("shot_id")}
    return [s for s in await repos.shots.list(production_id, scene_id) if str(s["id"]) in ids]


class StateRefusedHere(Exception):
    """The state card cannot be carried out now: the message says why, in a sentence for the person."""


async def apply_state_card(repos: Repos, production_id: UUID, scene: Row, card: Row) -> tuple[list[str], list[str]]:
    """Merge a `sable_state` card's marks into the scene's map as a person's own (`by: "person"`, so the next plan keeps
    it) and mark the shots whose state changed out of date. -> (what changed, the shots touched). No model.
    Raises `StateRefusedHere`."""
    scene_id = UUID(str(scene["id"]))
    version = int(scene.get("script_version") or 1)
    if int(card.get("script_version") or version) != version:
        raise StateRefusedHere("The script changed since I proposed this. Ask me again.")
    lines, shots, canon = await asyncio.gather(repos.lines.list(scene_id), repos.shots.list(production_id, scene_id),
                                               repos.canon.list(production_id))
    cast = [str(c["name"]) for c in canon if c["kind"] == "character"]
    items = sceneplan.scene_items(scene, lines)
    before = sm.SceneStaging.of(scene)
    try:
        marks = [sm.StateMark.model_validate(m) for m in card.get("marks") or []]
        after = sm.apply_state(before, items, marks, cast, version=version)
    except sm.StateRefused as exc:
        raise StateRefusedHere(str(exc)) from exc
    except ValueError as exc:
        raise StateRefusedHere("That change is not one I can apply any more.") from exc
    ordered = sorted(shots, key=lambda s: int(s.get("number") or 0))
    where = sm.changed_blocks(before, after, items, [(int(s["block_start"]), int(s["block_end"])) for s in ordered])
    await repos.scenes.update(scene_id, {"staging": after.model_dump(mode="json")})
    await mark_out_of_date(repos, [ordered[n] for n in where])
    return [str(c) for c in card.get("changes") or []], [f"S{n + 1:02d}" for n in where]


# ── @ references (plan/2026-11-09b phase 4) ───────────────────────────────────────────────────────────────────────────

PER_GROUP = 12  # rows of one kind in the picker
PICKER_MAX = 40
KIND_OF_CANON = {"character": "person", "prop": "prop", "location": "place"}


class UnknownRef(LookupError):
    """A pointed-at thing that is not in this production."""


async def _scene_labels(repos: Repos, production_id: UUID) -> tuple[list[Row], dict[str, str]]:
    scenes, episodes = await asyncio.gather(repos.scenes.list(production_id), repos.episodes.list(production_id))
    numbers = {str(e["id"]): e["number"] for e in episodes}
    labels = {str(s["id"]): (f"E{numbers[str(s['episode_id'])]}S{s['number']}" if str(s.get("episode_id")) in numbers
                             else f"S{s['number']}") for s in scenes}
    return scenes, labels


def _block_detail(item: Any) -> str:
    """A block named for the picker and the agent: its kind and, for an action, its first words. A spoken line is only
    named by who speaks, so no dialogue is copied anywhere but where a tool returns it."""
    if item.kind == "dialogue":
        return f"{item.speaker or 'someone'} speaks"
    return f"{item.kind}: {' '.join(str(item.text).split())[:60]}"


def _open(outside: bool) -> str:
    return "not open: read only" if outside else "open"


async def resolve_refs(repos: Repos, production_id: UUID, open_scene: UUID | None, refs: list[Ref]) -> list[Mention]:
    """The refs the browser sent, read again from this production's own data. Raises `UnknownRef` for one that is not
    here. A shot, block or scene other than the open one is kept for reading and marked `outside`."""
    if not refs:
        return []
    scenes, labels = await _scene_labels(repos, production_id)
    by_id = {str(s["id"]): s for s in scenes}
    canon = {str(c["id"]): c for c in await repos.canon.list(production_id)}
    out: list[Mention] = []
    for ref in refs:
        if ref.kind == "scene":
            if ref.id not in by_id:
                raise UnknownRef(ref.label or ref.id)
            outside, label = ref.id != str(open_scene), labels[ref.id]
            out.append(Mention(kind="scene", id=ref.id, label=label, scene=label, outside=outside,
                               text=f"{label} = the scene ({_open(outside)})"))
        elif ref.kind == "shot":
            try:
                shot = await repos.shots.get(production_id, UUID(ref.id))
            except ValueError as exc:
                raise UnknownRef(ref.label or ref.id) from exc
            if shot is None or str(shot["scene_id"]) not in by_id:
                raise UnknownRef(ref.label or ref.id)
            sid = str(shot["scene_id"])
            outside, label = sid != str(open_scene), f"S{int(shot['number']):02d}"
            out.append(Mention(kind="shot", id=ref.id, label=label, scene=labels[sid], outside=outside,
                               text=f"{label} = shot {label} of {labels[sid]} ({_open(outside)})"))
        elif ref.kind in ("person", "prop", "place"):
            entity = canon.get(ref.id)
            if entity is None or KIND_OF_CANON.get(str(entity["kind"])) != ref.kind:
                raise UnknownRef(ref.label or ref.id)
            out.append(Mention(kind=ref.kind, id=ref.id, label=str(entity["name"]),
                               text=f"{entity['name']} = {ref.kind} {entity['code']} in the canon"))
        else:  # a block of a scene
            sid = str(ref.scene_id or open_scene or "")
            if sid not in by_id or not ref.id.isdigit():
                raise UnknownRef(ref.label or ref.id)
            items = sceneplan.scene_items(by_id[sid], await repos.lines.list(UUID(sid)))
            at = int(ref.id)
            if at >= len(items):
                raise UnknownRef(ref.label or ref.id)
            outside = sid != str(open_scene)
            out.append(Mention(kind="block", id=ref.id, label=f"b{at}", scene=labels[sid], outside=outside,
                               text=f"b{at} = block {at} of {labels[sid]} ({_block_detail(items[at])}; "
                                    f"{_open(outside)})"))
    return out


async def mention_options(repos: Repos, production_id: UUID, open_scene: UUID | None, q: str) -> list[MentionOption]:
    """The @ picker's rows: the open scene's shots and blocks first, then the canon (people, places, props), then the
    other scenes. Names only, no model. `q` matches a label or detail, case-insensitively."""
    needle = " ".join(q.lower().split())
    scenes, labels = await _scene_labels(repos, production_id)
    out: list[MentionOption] = []

    def keep(label: str, detail: str = "") -> bool:
        return not needle or needle in label.lower() or needle in detail.lower()

    if open_scene is not None and str(open_scene) in labels:
        scene = next(s for s in scenes if str(s["id"]) == str(open_scene))
        here = labels[str(open_scene)]
        shots = sorted(await repos.shots.list(production_id, open_scene), key=lambda s: int(s["number"]))
        out += [MentionOption(kind="shot", id=str(s["id"]), label=f"S{int(s['number']):02d}",
                              detail=str(s.get("title") or ""), scene_id=open_scene, scene=here)
                for s in shots if keep(f"S{int(s['number']):02d}", str(s.get("title") or ""))][:PER_GROUP]
        items = sceneplan.scene_items(scene, await repos.lines.list(open_scene))
        out += [MentionOption(kind="block", id=str(n), label=f"b{n}", detail=_block_detail(i), scene_id=open_scene,
                              scene=here)
                for n, i in enumerate(items) if keep(f"b{n}", _block_detail(i))][:PER_GROUP]
    for entity in sorted(await repos.canon.list(production_id), key=lambda c: str(c["name"]).lower()):
        kind = KIND_OF_CANON.get(str(entity["kind"]))
        if kind and keep(str(entity["name"]), str(entity.get("code") or "")):
            out.append(MentionOption(kind=kind, id=str(entity["id"]), label=str(entity["name"]),  # type: ignore[arg-type]
                                     detail=str(entity.get("code") or "")))
    for s in sorted(scenes, key=lambda s: labels[str(s["id"])]):
        if str(s["id"]) != str(open_scene) and keep(labels[str(s["id"])], str(s.get("title") or "")):
            out.append(MentionOption(kind="scene", id=str(s["id"]), label=labels[str(s["id"])],
                                     detail=str(s.get("title") or ""), scene_id=UUID(str(s["id"])),
                                     scene=labels[str(s["id"])]))
    return out[:PICKER_MAX]
