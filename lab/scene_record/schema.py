"""The scene record: ONE plan of a scene that the planner writes and the board, blocking plate and frames read.

Shape follows "Shot Breakdown: The Deed, Scene 3" (Part 3) with three changes for AI video, where every shot is a
separate world and continuity exists only if it is written down:

* POSITIONS ARE NUMBERS. The floor plan is metres (x east, y north). Marks, landmarks and cameras are points, so code
  can work out the 180 degree side, the 30 degree change, who is on which side of the frame, which way an eyeline or
  a walk reads on screen, where the key light falls, and whether a framing can be the size it claims. The model never
  writes "frame left"; code derives it.
* CUT POINTS replace "link: cut" + handles. Shot N ends on cut point K and shot N+1 starts on K: one record of where
  everyone is (a mark), their posture, what each hand holds and what is under way, so the end of one clip and the
  start of the next are written from the same facts.
* PROP STATES are one timeline by cut point (holder, hand, place, seen), so a prop is in one hand at a time and is
  never on screen before the story reveals it.

Wire models have no defaults (OpenAI strict structured output): every field is required, empty is "" or [].
"""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

Size = Literal["EWS", "WS", "FS", "MLS", "MS", "MCU", "CU", "ECU", "INSERT"]
ShotType = Literal["master", "two_shot", "single", "ots", "pov", "insert", "cutaway", "black", "title"]
Angle = Literal["eye", "low", "high", "overhead", "ground"]
Height = Literal["ground", "knee", "seated_eye", "standing_eye", "high", "overhead"]
Posture = Literal["standing", "walking", "seated", "kneeling", "lying", "rising", "sitting_down", "kneeling_down",
                  "leaning", "crouching"]
Hand = Literal["left", "right", "both", ""]
CutType = Literal["first", "cut", "match_on_action"]
Move = Literal["static", "pan", "tilt", "dolly_in", "dolly_out", "track", "handheld", "crane"]
LandmarkKind = Literal["fixed", "path", "water", "light", "door", "furniture", "area", "wall"]
Rule = Literal["180", "30_degree", "eyeline", "screen_direction", "size_intensity", "length_intensity", "frame_missing",
               "size_geometry", "establish", "progression", "face_hidden", "setups"]
Role = Literal["establishing", "master", "side", "tracking", "reaction", "ots", "reverse", "pov", "detail", "cutaway"]


class Wire(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Pt(Wire):
    x: float
    y: float


class Landmark(Wire):
    id: str = Field(description="short id, e.g. 'gate', 'path', 'window', 'sky'")
    name: str
    kind: LandmarkKind
    points: list[Pt] = Field(description="an object: one point; a path: its centre line, points in order; water, a "
                             "field, a room floor: an AREA, its corner points in order (3 or more)")
    width: float = Field(default=0, ge=0, description="metres: a path's width, an object's size across; 0 = default")


class Mark(Wire):
    id: str = Field(description="M1, M2 ...")
    who: str = Field(description="the person's id")
    beat: int
    x: float
    y: float
    posture: Posture
    facing: str = Field(description="what they face: a person id, a landmark id, or north/south/east/west")
    moves_to: list[Pt] = Field(description="[] if they stay; one point where a walk or crawl ends")
    along: str = Field(description="the path landmark id a walk follows, else ''")
    label: str = Field(default="", description="2 to 5 words for the blocking plan: 'stops, sees the body', 'kneels'")


class Axis(Wire):
    from_beat: int
    a: str = Field(description="person or landmark id")
    b: str = Field(description="person or landmark id")
    camera_side: Literal["north", "south", "east", "west"]


class Camera(Wire):
    """A SETUP: one camera position a crew lights once and takes several shots from."""

    id: str = Field(description="C1, C2, C3 ...")
    name: str
    role: Role = Field(default="master", description="what this setup is for")
    covers: str = Field(default="", description="2 to 5 words: the zone or action it covers ('walking zone', 'the "
                        "discovery', 'hand and key')")
    x: float
    y: float
    height: Height
    looks_at: str = Field(description="what it looks at by default: a person id, landmark id or prop id")
    lens_mm: int = Field(description="its default lens")


class Beat(Wire):
    n: int
    blocks: list[int] = Field(description="the script blocks this beat covers, in order")
    what: str
    intensity: int = Field(ge=1, le=10)
    dominant: str = Field(description="a person id, or 'balanced'")


class KeyMoment(Wire):
    beat: int
    what: str
    shots: list[str] = Field(description="the shot ids that deliver it")


class PropState(Wire):
    prop: str
    from_cut: str = Field(description="the cut point id this state starts at (K0 is the opening)")
    holder: str = Field(description="person id holding or wearing it, else ''")
    hand: Hand
    place: str = Field(description="where it is in words: 'inside his closed right fist', 'in her dress pocket'")
    on: str = Field(description="landmark id it rests on ('table'), else '' (then it is where its holder is)")
    seen: bool = Field(description="false while the story has not shown it yet")


class InCut(Wire):
    who: str
    mark: str = Field(description="the mark id they are on or moving from")
    progress: float = Field(ge=0, le=1, description="0 at the mark, 1 at its moves_to; 0 when the mark does not move")
    posture: Posture
    left_hand: str = Field(description="a prop id held in the left hand, else ''")
    right_hand: str = Field(description="a prop id held in the right hand, else ''")
    look_at: str = Field(description="person, landmark or prop id they look at, else ''")
    state: str = Field(description="body and expression only, e.g. 'breathing hard, eyes on the fist'. Never clothes.")


class CutPoint(Wire):
    id: str = Field(description="K0 = the opening; K1, K2 ... in cut order")
    moment: str = Field(description="the instant, in one sentence")
    under_way: str = Field(description="the movement in progress at this instant for a match on action, else ''")
    people: list[InCut]


class Break(Wire):
    rule: Rule
    reason: str


class Shot(Wire):
    id: str = Field(description="1, 2, 3 ... in CUT ORDER")
    beat: int
    blocks: list[int]
    purpose: str
    type: ShotType
    camera: str = Field(description="the setup's camera id; '' only for a black or title card")
    lens_mm: int = Field(default=0, ge=0, description="this shot's lens from that setup; 0 = the setup's lens")
    looks_at: str = Field(default="", description="what this shot pans to from that setup; '' = the setup's target")
    subject: str = Field(description="person, prop or landmark id the shot is on")
    in_frame: list[str] = Field(description="every person and prop id visible")
    size: Size
    angle: Angle
    move: Move
    move_why: str = Field(description="the story reason for the move; '' when static")
    f_stop: float
    focus: str
    start: str = Field(description="cut point id the shot opens on")
    end: str = Field(description="cut point id the shot ends on")
    cut_in: CutType
    overlap_in_s: float = Field(ge=0, le=2, description="seconds of the previous shot's action repeated at the start")
    overlap_out_s: float = Field(ge=0, le=2, description="seconds of the next shot's action carried past the end")
    duration_s: int = Field(ge=1, le=15)
    action: str = Field(description="what the camera sees happen, in order. People and props by name. Never clothes.")
    lines: list[str] = Field(description="line ids spoken in this shot")
    breaks: list[Break]


class Light(Wire):
    key: str = Field(description="landmark id of the key light's source (a window, lamp, the sky)")
    style: str
    by_beat: list[str] = Field(description="palette and contrast per beat, in beat order")


class SceneRecord(Wire):
    scene: str
    dramatic_goal: str
    pov: str = Field(description="the person the audience discovers things with")
    objectives: list[str] = Field(description="'<id>: wants … / blocked by …' per person")
    subtext: str
    key_moment: KeyMoment
    beats: list[Beat]
    landmarks: list[Landmark]
    marks: list[Mark]
    axes: list[Axis]
    cameras: list[Camera]
    light: Light
    prop_states: list[PropState]
    cuts: list[CutPoint]
    shots: list[Shot]
