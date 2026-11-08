"""The shapes of the DaVinci lab (plan/2026-11-08d §2, §3, §4).

    EditPlanW   the intended cut: treatment, sequences, moments. The director writes it; it is a reference for the editor.
    MenuW       one clip as a coverage planner (or the director) proposes it: role, covers, handles, technique, priority.
    IrW         one clip's Veo design (`ir`) and sound, as the clip writer writes it.
    Clip        a bin entry: the menu entry + the id and slate code assigned + the design once written.

The closed lists are the plan's: ROLES (§2.2), PRIORITIES, TECHNIQUES (§3, one move per clip). What Veo cannot do (a dolly
zoom, a split diopter) is not in TECHNIQUES, and the words are refused in any text by `checks.feasibility`. The post-only
techniques (speed ramp, freeze frame, punch-in, split screen) are not clips: the director names them in `editor_notes`.

Like the wire shapes of `contracts.david.wire`, nothing has a default (strict mode cannot hold a model to one).
"""
from __future__ import annotations

from typing import Any, Literal

from cinematic.schema import SIZES, SequenceW, Size, SpanW, TreatmentW  # the cinematic lab's treatment and sizes
from contracts.david.wire import SoundW, _Wire
from hiru_ai.agents.david.wire_schema import inline, ir_schema

ROLES: tuple[str, ...] = ("master", "single", "ots", "two_shot", "reaction", "insert", "cutaway", "establishing",
                          "atmosphere", "clean_entry", "clean_exit", "pov", "transition_out", "transition_in")
Role = Literal["master", "single", "ots", "two_shot", "reaction", "insert", "cutaway", "establishing", "atmosphere",
               "clean_entry", "clean_exit", "pov", "transition_out", "transition_in"]
Priority = Literal["must", "should", "nice"]
PRIORITIES: tuple[str, ...] = ("must", "should", "nice")

TECHNIQUES: tuple[str, ...] = (
    "locked_off",
    "drone_establishing", "drone_reveal", "drone_pull_away", "top_down", "orbit",  # aerial
    "crash_zoom", "snap_zoom", "slow_creep",  # zoom (a dolly zoom is refused)
    "dolly_in", "dolly_out", "tracking", "lead", "follow", "arc", "crane", "steadicam", "handheld",  # moving
    "whip_pan", "slow_pan_reveal", "tilt_reveal",  # pan / tilt
    "low_angle", "high_angle", "dutch", "worms_eye", "overhead",  # angle
    "rack_focus", "shallow_isolation", "foreground_framing",  # focus / lens (a split diopter is refused)
    "push_past_foreground", "pull_back", "enter_held_frame",  # reveal
    "silhouette", "shadow_before_person", "flare", "light_across_face",  # light
    "slow_motion", "timelapse", "hyperlapse",  # time
    "whip_out", "whip_in", "match_cut", "object_wipe", "focus_out", "focus_in")  # transition halves
Technique = Literal[
    "locked_off",
    "drone_establishing", "drone_reveal", "drone_pull_away", "top_down", "orbit",
    "crash_zoom", "snap_zoom", "slow_creep",
    "dolly_in", "dolly_out", "tracking", "lead", "follow", "arc", "crane", "steadicam", "handheld",
    "whip_pan", "slow_pan_reveal", "tilt_reveal",
    "low_angle", "high_angle", "dutch", "worms_eye", "overhead",
    "rack_focus", "shallow_isolation", "foreground_framing",
    "push_past_foreground", "pull_back", "enter_held_frame",
    "silhouette", "shadow_before_person", "flare", "light_across_face",
    "slow_motion", "timelapse", "hyperlapse",
    "whip_out", "whip_in", "match_cut", "object_wipe", "focus_out", "focus_in"]
NO_DIALOGUE = ("slow_motion", "timelapse", "hyperlapse")  # plan §3: slow motion carries no dialogue
AERIAL = ("drone_establishing", "drone_reveal", "drone_pull_away", "top_down", "orbit")
TRANSITION = ("transition_out", "transition_in")
SCHEMA_EDIT, SCHEMA_MENU, SCHEMA_IR, SCHEMA_PLAN = "edit_plan", "coverage_menu", "clip_designs", "shot_plan"


# ── the intended cut (§2.1) ──────────────────────────────────────────────────────────────────────


class MomentW(_Wire):
    n: int
    sequence: str  # a sequence id
    blocks: list[int]  # the script blocks of this moment (every block belongs to one moment)
    what: str  # what happens, in plain words
    feeling: str  # what the audience should feel
    cut_uses: str  # which clip (role and angle) the intended cut uses here, and why


class EditPlanW(_Wire):
    treatment: TreatmentW
    sequences: list[SequenceW]  # `shots` here is the first and last MOMENT number
    moments: list[MomentW]
    editor_notes: list[str]  # risky match cuts; techniques left for post; what was avoided because Veo cannot do it


# ── the shoot bin (§2.2) ─────────────────────────────────────────────────────────────────────────


class MenuW(_Wire):
    moment: int  # the moment this clip covers (MomentW.n)
    role: Role
    setup: str  # one capital letter: clips from the same camera position share it (the slate's "B")
    blocks: list[int]  # the script blocks the clip overlaps ([] for an establishing, atmosphere or transition clip)
    lines: list[str]  # line ids (L7) heard on this clip, never the words
    speaks: bool  # the person's lips perform the line in this clip (D2); false: it plays silent under the chosen audio
    over: str  # "" or who is SHOWN while a line is heard (a listener or reaction clip)
    size: Size
    angle: str  # eye level, low, high, dutch ...
    lens: str  # the lens and why
    technique: Technique
    why: str  # one sentence: the story reason for this clip and for its technique
    take_s: Literal[4, 6, 8]  # what Veo makes
    handle_in_s: float  # about 1 s of the take before the action starts
    handle_out_s: float  # about 1 s after it ends
    priority: Priority
    editor_note: str  # what the editor can do with it ("" when nothing to add)


class MenuListW(_Wire):
    clips: list[MenuW]


# ── the staged plan (plan B §2.1): the intended cut, the whole menu and the look sheet in ONE answer ──────────


class PersonLookW(_Wire):
    id: str  # the person's code from <production> (C01): the same id a clip's subject carries
    description: str  # how they look in this moment: clothes, hair, state. Code copies it into every clip that shows them


class LookW(_Wire):
    """What stays the same across every angle of one moment. Code writes these words into the clips' designs."""

    moment: int
    setting: str  # ONE sentence: the place
    lighting: str  # ONE sentence: the physical light (rain stays rain)
    people: list[PersonLookW]  # each person SHOWN in the moment, never one who is only heard


class PlanW(_Wire):
    edit_plan: EditPlanW  # the intended cut; its `editor_notes` are the director's notes for the editor
    clips: list[MenuW]  # the whole coverage menu, in the order it will be shot
    looks: list[LookW]  # one per moment


class IrW(_Wire):
    id: str  # the clip's id (c01)
    ir: dict[str, Any]  # setting, cinematography{...}, lighting, subjects[], beats[], audio, first_frame{...}
    sound: SoundW


class IrListW(_Wire):
    designs: list[IrW]


class Clip(MenuW):
    """A bin entry. `ir` and `sound` are None until a clip writer has written them."""

    id: str
    slate: str
    ir: dict[str, Any] | None = None
    sound: SoundW | None = None


def design_schema(wire: type[_Wire], name: str) -> dict[str, Any]:
    """`wire`'s strict JSON schema, flat, with the clip schema's camera design as the type of every `ir`."""
    raw = wire.model_json_schema()
    flat = inline(raw, raw.get("$defs") or {})
    design = ir_schema()

    def put(node: Any) -> Any:
        if isinstance(node, dict):
            out = {k: put(v) for k, v in node.items()}
            props = out.get("properties")
            if isinstance(props, dict) and "ir" in props:
                out["properties"] = {**props, "ir": design}
            return out
        if isinstance(node, list):
            return [put(v) for v in node]
        return node

    return {**put(flat), "title": name}


def edit_schema() -> dict[str, Any]:
    return design_schema(EditPlanW, SCHEMA_EDIT)


def menu_schema() -> dict[str, Any]:
    return design_schema(MenuListW, SCHEMA_MENU)


def plan_schema() -> dict[str, Any]:
    return design_schema(PlanW, SCHEMA_PLAN)


def ir_list_schema() -> dict[str, Any]:
    return design_schema(IrListW, SCHEMA_IR)


__all__ = [
    "AERIAL",
    "NO_DIALOGUE",
    "PRIORITIES",
    "ROLES",
    "SIZES",
    "TECHNIQUES",
    "TRANSITION",
    "Clip",
    "EditPlanW",
    "IrListW",
    "IrW",
    "LookW",
    "MenuListW",
    "MenuW",
    "MomentW",
    "PersonLookW",
    "PlanW",
    "SequenceW",
    "SpanW",
    "edit_schema",
    "ir_list_schema",
    "menu_schema",
    "plan_schema",
]
