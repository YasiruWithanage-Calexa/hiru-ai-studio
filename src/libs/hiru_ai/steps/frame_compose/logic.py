"""The code half of `frame_render/engine/pipeline.py` and `inspect.py`: no store, no model, no network.

The legacy `FrameJob` read the scene, its lines, the canon and the looks as it needed them. Here they are handed in
(a `World`), so the same answers come from rows alone. The system downloads the sheets, paints and records.
"""
from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

from contracts import sceneplan
from contracts.canon import (
    SHEET_ASPECT,
    CanonCard,
    CanonKind,
    LookFields,
    look_sheet_path,
    look_sheet_prompt,
    look_wardrobe,
    looks_in_force,
    reference_sheet_aspect,
    reference_sheet_prompt,
)
from contracts.holding import Hands, hands_for, references_for
from contracts.producer import (
    CameraSettings,
    CastMember,
    PersonEdits,
    default_camera,
    frame_prompt,
    identity_line,
    pins_for,
    shot_canon_ids,
    shot_items,
)
from contracts.staging import ShotIntent, Staging, shot_cast, source_phrase, staging, unseen_sentence
from contracts.veo import ASPECT_RATIO, Orientation

Row = dict[str, Any]
# plan/2026-11-09 (D4, Raphael first): the first frame is the clip's opening, so it shows the state the clip opens in
OPENS_LINE = "In this frame, as the clip opens: {state}."


def opens_line(shot: Row) -> str:
    """The state a Raphael shot opens in (its intent's `opens`, from the scene's state ledger), for the still, so the
    still and the video agree. "" for every other planner and for a shot with no ledger."""
    if str(shot.get("planner") or "") != "raphael":
        return ""
    intent = ShotIntent.of(shot)
    state = " ".join((intent.opens if intent else "").split()).rstrip(" .;,")
    return OPENS_LINE.format(state=state) if state else ""
# The people seen, the place, a second place (the stall) and what they hold; the image model takes up to 16
MAX_REFERENCES = 6
ASPECT_OF_SHEET = SHEET_ASPECT


def cast_member(row: Row) -> CastMember:
    current = row.get("current") or {}
    card = current.get("card") or {}
    return CastMember(id=str(row["id"]), code=str(row["code"]), name=str(row["name"]), kind=str(row["kind"]),
                      version=current.get("version"), wardrobe_anchor=str(current.get("wardrobe_anchor") or ""),
                      voice_pin=str(current.get("voice_pin") or ""), appearance=str(card.get("appearance") or ""),
                      gender=str(card.get("gender") or ""))


def sheet_path(row: Row) -> str:
    assets = (row.get("current") or {}).get("reference_assets") or []
    first = assets[0] if assets else None
    return str(first.get("path") if isinstance(first, dict) else first or "")


def production_aspect(production: Row) -> str:
    return ASPECT_RATIO[Orientation(production.get("orientation") or "horizontal")]


def looks_for_scene(all_looks: list[Row], scene_picks: list[Row], episode: int | None) -> dict[str, Mapping[str, Any]]:
    """character id → the look the scene uses (`contracts.canon.looks_in_force`)."""
    if not all_looks:
        return {}
    return dict(looks_in_force(all_looks, scene_picks, episode))


@dataclass
class World:
    """Everything one scene's frames are made from."""

    production: Row
    canon: list[Row]
    scene: Row
    lines: list[Row]
    looks: dict[str, Mapping[str, Any]] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.aspect = production_aspect(self.production)
        self.by_id = {str(c["id"]): c for c in self.canon}
        self.members = {str(c["id"]): cast_member(c) for c in self.canon}

    @classmethod
    def of(cls, payload: Mapping[str, Any]) -> World:
        return cls(production=payload["production"], canon=payload["canon"], scene=payload["scene"],
                   lines=payload.get("lines") or [], looks=payload.get("looks") or {})

    def _own(self, shot: Row) -> tuple[list[Any], list[str], Staging]:
        items = sceneplan.scene_items(self.scene, self.lines)
        own = shot_items(items, int(shot["block_start"]), int(shot["block_end"]))
        characters = [c for c in self.canon if c["kind"] == "character"]
        cast_ids = shot_cast(own, characters, shot)
        return own, cast_ids, staging(own, characters, shot, cast_ids=cast_ids)

    def staged(self, shot: Row) -> Staging:
        return self._own(shot)[2]

    def reference_choices(self, shot: Row) -> list[Row]:
        """For each person the camera SEES, then the place: `{id, choices: [{label, path}]}`, in the order they are
        attached, at most four. A person wearing a look is offered the look sheet first and the base sheet next; the
        system takes the first that can be read, and leaves one with none out. Someone only heard is never attached:
        their sheet would put their face in the frame."""
        staged = self._own(shot)[2]
        edits = PersonEdits.of(shot)
        seen = {c: self.members[c].name for c in staged.on_screen if c in self.members}
        planned = references_for(self.scene, shot, self.canon, shot_canon_ids(self.scene, staged.on_screen, edits),
                                 seen, removed=edits.cast.remove, has_sheet=lambda r: bool(sheet_path(r)))
        out: list[Row] = []
        for cid, note in planned:
            row = self.by_id.get(cid)
            if not row or len(out) >= MAX_REFERENCES:
                continue
            what = {"location": "the location plate for", "prop": "the reference sheet for"}.get(
                row["kind"], "the character sheet for")
            choices = [{"label": f"{what} {row['name']}" + (f" ({note})" if note else ""), "path": sheet_path(row)}]
            look = self.looks.get(cid) if row["kind"] == "character" else None
            if look is not None:
                choices.insert(0, {"label": f"the look sheet for {row['name']}", "path": look_sheet_path(look)})
            out.append({"id": cid, "choices": [c for c in choices if c["path"]]})
        return out

    def cast(self, shot: Row, cast_ids: list[str]) -> list[CastMember]:
        """The people in the shot, each dressed in the look the scene uses, if any."""
        return [self.members[c].model_copy(update={"look": look_wardrobe(self.looks[c])}) if c in self.looks
                else self.members[c] for c in cast_ids if c in self.members]

    def compose(self, shot: Row, labels: list[str]) -> tuple[str, Row]:
        """→ (the frame prompt naming exactly `labels` as its attached images, the pins). The pins cover everyone in
        the shot, heard too (a voice's card is still part of the shot); the People line names only who is seen."""
        own, cast_ids, staged = self._own(shot)
        scene = self.scene
        pins = pins_for(shot_version=int(shot.get("version") or 1), scene=scene, items=own, cast_ids=cast_ids,
                        versions={k: m.version for k, m in self.members.items()}, edits=PersonEdits.of(shot),
                        looks=self.looks)
        default = default_camera(str(shot.get("framing") or "MS"), heading=str(scene.get("heading") or ""),
                                 time_of_day=str(scene.get("time_of_day") or ""))
        try:
            recommended = CameraSettings.model_validate((shot.get("design") or {}).get("recommended")
                                                        or default.model_dump())
        except ValueError:
            recommended = default
        camera = recommended.with_overrides(shot.get("camera_overrides") or {})
        prompt = frame_prompt(ir=shot.get("ir") or {}, camera=camera, aspect_ratio=self.aspect,
                              cast=self.cast(shot, staged.on_screen), references=labels,
                              recommended_framing=recommended.framing,
                              unseen=unseen_sentence(staged, {k: m.name for k, m in self.members.items()}),
                              hands=" ".join(p for p in (self.hands(shot).sentence, opens_line(shot)) if p))
        return prompt, pins.model_dump()

    def hands(self, shot: Row) -> Hands:
        """Who holds what as the shot opens (`contracts.holding`), for the people the camera sees."""
        staged = self._own(shot)[2]
        return hands_for(self.scene, shot, [self.members[c].name for c in staged.on_screen if c in self.members])

    def expected(self, shot: Row) -> Row:
        """What the vision check compares the picture with: `{seen, unseen, frame}`."""
        staged = self._own(shot)[2]
        raw = (shot.get("ir") or {}).get("first_frame")
        frame: Mapping[str, Any] = raw if isinstance(raw, Mapping) else {}
        listed = frame.get("subjects")
        subjects: list[Any] = listed if isinstance(listed, list) else []
        text = " ".join([str(frame.get("composition") or ""), *[str(x) for x in subjects]]).strip()
        return {"seen": [identity_line(m) for m in self.cast(shot, staged.on_screen)],
                "unseen": [f"{self.members[c].name} (heard {source_phrase(staged.voice_source)}, not in the place)"
                           for c in staged.heard_only if c in self.members],
                "frame": text, "hands": self.hands(shot).expect}

    def seen_names(self, shot: Row) -> dict[str, str]:
        staged = self.staged(shot)
        return {c: self.members[c].name for c in staged.on_screen if c in self.members}


def sheet_checks(seen_names: dict[str, str], attached: set[str]) -> list[Row]:
    """An on-screen person painted without their sheet: the face was invented."""
    return [{"label": f"No reference sheet · {name}", "tone": "advisory"}
            for cid, name in seen_names.items() if cid not in attached]


def vision_checks(answer: Row | None, expected: Row) -> list[Row]:
    """What the vision model saw, against what the shot expects, as advisory chips. No answer, no chips."""
    if answer is None:
        return []
    checks: list[Row] = []
    try:
        people = int(answer.get("main_people"))  # type: ignore[arg-type]  # a bad answer is caught below
    except (TypeError, ValueError):
        people = -1
    if expected["seen"] and people >= 0 and people != len(expected["seen"]):
        checks.append({"label": f"{people} people in frame, expected {len(expected['seen'])}", "tone": "advisory"})
    if expected["unseen"] and answer.get("unexpected_person"):
        checks.append({"label": "Shows someone who is only heard", "tone": "advisory"})
    if expected.get("hands") and answer.get("hands_match") is False:
        what = " ".join(str(answer.get("hands_problem") or "").split())[:120]
        checks.append({"label": f"Hands · {what or 'not holding what the shot says'}", "tone": "advisory"})
    if answer.get("matches") is False:
        problems = [" ".join(str(p).split())[:120] for p in answer.get("problems") or [] if str(p).strip()][:2]
        checks += [{"label": f"Differs · {p}", "tone": "advisory"} for p in problems] or [
            {"label": "Differs from the shot's first frame", "tone": "advisory"}]
    if not checks:
        checks.append({"label": "Frame matches the shot", "tone": "pass"})
    return checks


def reference_sheet(production: Row, row: Row) -> tuple[str, str]:
    """→ (prompt, aspect) of the sheet for an entity's CURRENT card. Built again from the card each time, not read from
    the version's stored `reference_prompt`, which was written when the version was made and would keep an older sheet
    layout alive."""
    kind = CanonKind(row["kind"])
    aspect = reference_sheet_aspect(kind, production_aspect(production))
    card = CanonCard.model_validate((row.get("current") or {}).get("card") or {})
    return reference_sheet_prompt(kind, str(row["name"]), card, aspect_ratio=aspect), aspect


def look_sheet(row: Row, look: Row) -> str:
    fields = LookFields.model_validate({k: look.get(k) or ([] if k == "ranges" else "")
                                       for k in ("name", "ranges", "outfit", "hair", "makeup", "accessories")})
    return look_sheet_prompt(str(row["name"]), fields)
