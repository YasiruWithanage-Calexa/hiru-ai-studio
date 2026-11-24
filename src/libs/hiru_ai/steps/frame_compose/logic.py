"""The code half of `frame_render/engine/pipeline.py` and `inspect.py`: no store, no model, no network.

The legacy `FrameJob` read the scene, its lines, the canon and the looks as it needed them. Here they are handed in
(a `World`), so the same answers come from rows alone. The system downloads the sheets, paints and records.
"""
from __future__ import annotations

import struct
import zlib
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

from contracts import board as board_kit
from contracts import picture_pins, sceneplan, vehicles
from contracts.canon import (
    SHEET_ASPECT,
    CanonCard,
    CanonKind,
    LookFields,
    look_sheet_prompt,
    look_wardrobe,
    looks_in_force,
    reference_sheet_aspect,
    reference_sheet_prompt,
)
from contracts.frame_brief import (
    MAX_REFERENCES,
    FrameBrief,
    PlannedReference,
    SetupFrame,
    agent_camera,
    black_plate,
    expected_frame,
    frame_brief,
    missing_references,
    opens_line,
    plan_references,
    setup_frame,
)
from contracts.frame_brief import OPENS_LINE as OPENS_LINE
from contracts.frame_brief import sheet_path as sheet_path
from contracts.holding import Hands, hands_for
from contracts.producer import (
    CameraSettings,
    CastMember,
    PersonEdits,
    camera_changes,
    default_camera,
    identity_line,
    look_pins,
    pins_for,
    shot_canon_ids,
    shot_items,
    stale_reasons,
)
from contracts.staging import Staging, shot_cast, source_phrase, staging, unseen_sentence
from contracts.veo import ASPECT_RATIO, Orientation

Row = dict[str, Any]
ASPECT_OF_SHEET = SHEET_ASPECT
NO_SHOT_PROMPT = "no shot prompt"


def cast_member(row: Row) -> CastMember:
    current = row.get("current") or {}
    card = current.get("card") or {}
    return CastMember(id=str(row["id"]), code=str(row["code"]), name=str(row["name"]), kind=str(row["kind"]),
                      version=current.get("version"), wardrobe_anchor=str(current.get("wardrobe_anchor") or ""),
                      voice_pin=str(current.get("voice_pin") or ""), appearance=str(card.get("appearance") or ""),
                      gender=str(card.get("gender") or ""))


PLATE_SIZE = {"16:9": (1536, 1024), "9:16": (1024, 1536)}  # the painter's sizes (`adapters.images.SIZE_FOR_ASPECT`)


def black_png(aspect: str) -> bytes:
    """A black PNG of the painter's size for this aspect (plan/2026-11-12b): what a black plate is, made by code."""
    w, h = PLATE_SIZE.get(aspect, PLATE_SIZE["16:9"])
    raw = (b"\x00" + b"\x00" * (w * 3)) * h

    def chunk(tag: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)

    head = struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0)
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", head) + chunk(b"IDAT", zlib.compress(raw, 9)) + chunk(b"IEND", b"")


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
    # plan/2026-11-11b §4.4: the scene's shots and their accepted FINAL frames (shot id → `{id, storage_path}`), for
    # the same-setup frame. Empty: no same-setup frame is attached.
    shots: list[Row] = field(default_factory=list)
    accepted: dict[str, Row] = field(default_factory=dict)
    genre: str = ""  # plan/2026-11-12b: the production's genre phrase (`contracts.memory.genre_of`); "" = general
    conditions: dict[str, str] = field(default_factory=dict)  # plan/2026-11-12c: character id -> the scene's condition
    # plan/2026-11-23d §2.2: the scene's Scene board rows (every version; the current one is read). Empty: no board,
    # and a shot prompt is never out of date because of one.
    boards: list[Row] = field(default_factory=list)

    def __post_init__(self) -> None:
        self.aspect = production_aspect(self.production)
        self.by_id = {str(c["id"]): c for c in self.canon}
        self.members = {str(c["id"]): cast_member(c) for c in self.canon}

    @classmethod
    def of(cls, payload: Mapping[str, Any]) -> World:
        return cls(production=payload["production"], canon=payload["canon"], scene=payload["scene"],
                   lines=payload.get("lines") or [], looks=payload.get("looks") or {},
                   shots=payload.get("shots") or [], accepted=payload.get("accepted") or {},
                   genre=str(payload.get("genre") or ""), conditions=dict(payload.get("conditions") or {}),
                   boards=list(payload.get("boards") or []))

    def approved_panel(self, shot: Row) -> Any:
        """The shot's panel on the current approved board, still showing the shot (`contracts.board.approved_panel`),
        or None."""
        return board_kit.approved_panel(self.boards, shot)

    def _own(self, shot: Row) -> tuple[list[Any], list[str], Staging]:
        items = sceneplan.scene_items(self.scene, self.lines)
        own = shot_items(items, int(shot["block_start"]), int(shot["block_end"]))
        characters = [c for c in self.canon if c["kind"] == "character"]
        cast_ids = shot_cast(own, characters, shot)
        return own, cast_ids, staging(own, characters, shot, cast_ids=cast_ids)

    def plate(self, shot: Row) -> bool:
        """plan/2026-11-12b: a cut to black or a title card, with no one in it, is a black plate made by code."""
        own, cast_ids, _ = self._own(shot)
        return not cast_ids and not any(i.kind == "dialogue" for i in own) and black_plate(i.text for i in own)

    def staged(self, shot: Row) -> Staging:
        return self._own(shot)[2]

    def setup(self, shot: Row) -> SetupFrame | None:
        """The accepted frame of the first earlier shot of this shot's camera setup (`contracts.frame_brief`), among
        those drawn for the camera their shot has now: a frame of a shot the Camera agent designed after it was drawn
        (no picture pin) or whose picture moved since would hand its old angle and framing on (the audit of
        2026-11-21). An accepted row read without its pins is kept as before."""
        return setup_frame(shot, self.shots, self.current_accepted())

    def current_accepted(self) -> dict[str, Row]:
        by_id = {str(s.get("id")): s for s in self.shots}
        out: dict[str, Row] = {}
        for sid, f in self.accepted.items():
            s = by_id.get(sid)
            if s is not None and "pins" in f and agent_camera(s):
                made = ((f.get("pins") or {}).get("picture") or {}) if isinstance(f.get("pins"), Mapping) else {}
                if not made or camera_changes(made, self.pins_now(s, frame=True)["picture"], head="x"):
                    continue
            out[sid] = f
        return out

    def planned(self, shot: Row) -> list[PlannedReference]:
        """The pictures this frame wants, in their fixed order (`contracts.frame_brief.plan_references`)."""
        staged = self._own(shot)[2]
        return plan_references(self.scene, shot, self.canon, staged.on_screen, self.looks, setup=self.setup(shot),
                               limit=MAX_REFERENCES)

    def reference_choices(self, shot: Row) -> list[Row]:
        """For each picture the frame wants: `{id, role, choices: [{label, path, bucket}]}`, in the order they are
        attached: the people the camera SEES, the place, another place, what they hold, then the same-setup frame. A
        person wearing a look is offered the look sheet first and the base sheet next; the system takes the first that
        can be read, and leaves one with none out. Someone only heard is never attached: their sheet would put their
        face in the frame."""
        return [{"id": p.id, "role": p.role,
                 "choices": [{"label": label, "path": path, "bucket": "frames" if p.role == "setup" else "references"}
                             for label, path in p.choices]}
                for p in self.planned(shot)]

    def missing(self, shot: Row) -> list[str]:
        return missing_references(self.planned(shot))

    def cast(self, shot: Row, cast_ids: list[str]) -> list[CastMember]:
        """The people in the shot, each dressed in the look the scene uses, if any."""
        out = [self.members[c].model_copy(update={"look": look_wardrobe(self.looks[c])}) if c in self.looks
               else self.members[c] for c in cast_ids if c in self.members]
        return [m.model_copy(update={"condition": self.conditions[m.id]}) if m.id in self.conditions else m
                for m in out]

    def camera(self, shot: Row) -> tuple[CameraSettings, CameraSettings]:
        """(the recommendation, the camera as it stands: the recommendation with a person's changes on top)."""
        scene = self.scene
        default = default_camera(str(shot.get("framing") or "MS"), heading=str(scene.get("heading") or ""),
                                 time_of_day=str(scene.get("time_of_day") or ""))
        try:
            recommended = CameraSettings.model_validate((shot.get("design") or {}).get("recommended")
                                                        or default.model_dump())
        except ValueError:
            recommended = default
        return recommended, recommended.with_overrides(shot.get("camera_overrides") or {})

    def pins_now(self, shot: Row, *, frame: bool = False) -> Row:
        """The shot's pins as it stands (plan/2026-11-20d D8): the shot, its script, its canon, the looks it is painted
        with, and the camera's picture and motion. `frame`: a frame's pins (the looks; and the picture carries the
        opening of the shot prompt it is drawn from, when one is current)."""
        own, cast_ids, _ = self._own(shot)
        recommended, camera = self.camera(shot)
        pins = pins_for(shot_version=int(shot.get("version") or 1), scene=self.scene, items=own, cast_ids=cast_ids,
                        versions={k: m.version for k, m in self.members.items()}, edits=PersonEdits.of(shot),
                        looks=self.looks)
        record = self.shot_prompt(shot) if frame else None
        opening = picture_pins.opening_text((record or {}).get("opening"))
        return picture_pins.pinned(pins, camera, recommended, agent_camera(shot), opening=opening,
                                   video_note=PersonEdits.of(shot).video_note)

    def shot_prompt_reasons(self, shot: Row) -> list[str]:
        """Why the shot's stored shot prompt (`design.shot_prompt`) no longer fits it (D8): the camera's picture or
        motion, the script, the shot, the cast or the looks moved. ["no shot prompt"] when there is none."""
        record = (shot.get("design") or {}).get("shot_prompt")
        if not isinstance(record, Mapping) or not record.get("frame"):
            return [NO_SHOT_PROMPT]
        made = record.get("pins") or {}
        if not made:
            return [NO_SHOT_PROMPT]
        _, cast_ids, _ = self._own(shot)
        now = self.pins_now(shot)
        worn = look_pins(shot_canon_ids(self.scene, cast_ids, PersonEdits.of(shot)), self.looks)
        reasons = stale_reasons(made, shot_version=int(now["shot_version"]), script_hash=str(now["script_hash"]),
                                canon=self.members, looks=worn, picture=now["picture"], motion=now["motion"],
                                designed=bool(agent_camera(shot)))
        if set(made.get("canon") or {}) != set(now["canon"]) and not reasons:
            reasons.append("Different people or place in the shot.")
        board = board_kit.board_reason(record, self.boards, shot)  # D2: the approved panel wins over an older prompt
        if board:
            reasons.append(board)
        return reasons

    def shot_prompt(self, shot: Row) -> Mapping[str, Any] | None:
        """The shot's stored shot prompt while it is current (D5), else None: the frame is then painted from the code's
        own words."""
        record = (shot.get("design") or {}).get("shot_prompt")
        return record if isinstance(record, Mapping) and not self.shot_prompt_reasons(shot) else None

    def brief(self, shot: Row, labels: list[str], *, board: list[str] | None = None) -> FrameBrief:
        """The first frame's brief naming exactly `labels` as its attached images (`contracts.frame_brief`), in the
        shot prompt's words for the picture while it is current (plan/2026-11-20d D5)."""
        staged = self._own(shot)[2]
        recommended, camera = self.camera(shot)
        record = self.shot_prompt(shot)
        return frame_brief(ir=shot.get("ir") or {}, camera=camera, aspect_ratio=self.aspect,
                           cast=self.cast(shot, staged.on_screen), references=labels, recommended=recommended,
                           unseen=unseen_sentence(staged, {k: m.name for k, m in self.members.items()}),
                           hands=" ".join(p for p in (self.hands(shot).sentence, opens_line(shot)) if p),
                           scene=self.scene, shot=shot, genre=self.genre, board=board or (),
                           shot_prompt=(record or {}).get("frame"), vehicles=self.vehicle_lines(shot))

    def vehicle_lines(self, shot: Row) -> list[str]:
        """The frame's words for the shot's vehicles (plan/2026-11-24b §2.4): the place sentence of a shot INSIDE one,
        with its seat sides, and where the others stand."""
        found = vehicles.shot_vehicles(shot, self.canon, PersonEdits.of(shot).vehicles)
        place = str((self.by_id.get(str(self.scene.get("location_id") or "")) or {}).get("name") or "")
        return vehicles.frame_lines(found, self.by_id, place)

    def preview_labels(self, shot: Row) -> list[str]:
        """The labels the renderer will attach, when every first choice can be read (what the shot screen shows)."""
        return [p.label for p in self.planned(shot) if p.choices]

    def names(self) -> list[str]:
        """Every person's and place's name in the production: what a rewrite of a section must still name."""
        return [str(c["name"]) for c in self.canon if c.get("kind") in ("character", "location") and c.get("name")]

    def compose(self, shot: Row, labels: list[str], board: list[str] | None = None) -> tuple[str, Row]:
        """→ (the frame prompt naming exactly `labels` as its attached images, the pins). The pins cover everyone in
        the shot, heard too (a voice's card is still part of the shot); the People line names only who is seen. The
        picture pin (plan/2026-11-20d D8) marks the frame out of date when the camera's picture changes, or when the
        shot prompt it was drawn from is rewritten."""
        return self.brief(shot, labels, board=board).text(), self.pins_now(shot, frame=True)

    def hands(self, shot: Row) -> Hands:
        """Who holds what as the shot opens (`contracts.holding`), for the people the camera sees."""
        staged = self._own(shot)[2]
        return hands_for(self.scene, shot, [self.members[c].name for c in staged.on_screen if c in self.members])

    def expected(self, shot: Row, board: list[str] | None = None) -> Row:
        """What the vision check compares the picture with: `{seen, unseen, frame}`. A frame painted from its Scene
        board panel (`board`, plan/2026-11-14 §3.5) is also checked for a leftover mannequin and the planned state."""
        staged = self._own(shot)[2]
        record = self.shot_prompt(shot)  # D5: a frame painted from the shot prompt is checked against the same words
        words = (record or {}).get("frame") or {}
        text = (" ".join(str(words.get(k) or "") for k in ("composition", "people")).strip() if record
                else expected_frame(shot.get("ir") or {}, self.scene))
        state = next((x for x in board or [] if x.startswith("Each person at the opening")), "")
        return {"seen": [identity_line(m) for m in self.cast(shot, staged.on_screen)],
                "unseen": [f"{self.members[c].name} (heard {source_phrase(staged.voice_source)}, not in the place)"
                           for c in staged.heard_only if c in self.members],
                "frame": text, "hands": self.hands(shot).expect, "board": bool(board), "state": state}

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
    if expected.get("board") and answer.get("mannequin") is True:  # plan/2026-11-14 §3.5
        checks.append({"label": "A mannequin or clay stand-in is left in the frame", "tone": "advisory"})
    if expected.get("state") and answer.get("state_match") is False:
        what = " ".join(str(answer.get("state_problem") or "").split())[:120]
        checks.append({"label": f"State · {what or 'not as planned'}", "tone": "advisory"})
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
