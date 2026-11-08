"""A scripted run of the orchestrator with NO model (plan/2026-11-08d phase 0: the free part).

`Rehearsal` is a `Backend` that answers from the hand-written tables below: a director that follows a fixed script of tool
calls (including a refused `finish`, a check that finds a fault and a repair that re-sends only the clip that failed), a
coverage planner that returns the menu of Episode 1, and a clip writer that builds each design from the clip's own fields.
It exercises the REAL loop, tools, checks, money rules and page, so a paid run is not the first time any of them runs. The
tables are one person's hand-written example of coverage, not a model's judgement: the page it produces says so. The
dollars it reports are pretend (priced as gpt-5 and gpt-5-mini would be) and go to a ledger of their own, never the lab's.
"""
from __future__ import annotations

import json
import re
import threading
from collections.abc import Callable
from typing import Any

from cinematic import pack

from . import checks
from .brain import Call, Reply
from .money import Usage
from .orchestrator import Orchestrator

PLACE = ("A Colombo roadside in heavy monsoon rain: a wet road, tuk-tuks and traffic, Kasun's small three-wheeler and tea "
         "counter on the pavement")
LIGHT = "Flat, heavy-overcast monsoon daylight, soft and cool, wet surfaces catching the glow of shop fronts and headlights"
WIDE_PLACE = "A rain-soaked Colombo road seen from above: tuk-tuks, a family car, shop fronts, the three-wheeler small on the kerb"
LOOKS = {"Kasun": "Kasun, plain T-shirt soaked dark, dark jeans, sandals, short black hair wet, light stubble",
         "Anudi": "Anudi, elegant blouse and trousers, simple jewellery, a stylish handbag, long dark hair, an umbrella"}
CODES = {"Kasun": "C01", "Anudi": "C02"}

# moment: (sequence, title, blocks, what, feeling, the cut uses, what the people do (the same words in every angle), performance)
MOMENTS: dict[int, tuple[str, str, list[int], str, str, str, str, str]] = {
    1: ("A", "The stall in the rain", [0, 1, 2], "Kasun works his stall in the monsoon", "wet, small, hungry for more",
        "the wide master, then Kasun close: the place first, the ambition second", "Kasun pours tea for a customer under the awning",
        "He works with practised ease; his eyes drift past the customer."),
    2: ("A", "One day", [3], "Kasun's thought", "private hope", "Kasun close with lips closed, the thought heard over rain",
        "Kasun stands still behind the counter, lips closed, looking up the road", "His eyes stop being a vendor's and become someone planning."),
    3: ("A", "She arrives", [4], "Anudi steps out of the family car", "a different world arrives",
        "the wide across the road, Anudi small and bright against the grey", "Anudi steps out of the family car and opens her umbrella",
        "She moves like someone who has never had to hurry."),
    4: ("B", "The dropped phone", [5, 6], "She drops her phone; Kasun picks it up and runs", "the trigger",
        "the master, the phone as an insert, Kasun running in a track", "Anudi's phone slips from her hand and lands near the three-wheeler; Kasun lifts it and runs after her",
        "He does not decide; his feet do."),
    5: ("B", "Miss! Your phone!", [7, 8, 9], "He calls after her; she turns and thanks him", "the first contact",
        "the master two-shot, then the singles as the lines land", "Kasun holds the phone out to Anudi; she turns toward him and her face opens",
        "He is out of breath and shy; she is surprised and then warm."),
    6: ("B", "Her curiosity", [10, 11, 12, 13, 14], "She asks; he answers with his story", "warmth, a connection",
        "the two-shot as the master, Anudi's face as she listens", "Anudi looks over the little stall; Kasun smiles and answers; Anudi smiles back",
        "He is proud and shy; she is moved by it."),
    7: ("C", "The call", [15, 16, 17, 18, 19], "Her father's call ends the moment", "the world closes in",
        "Anudi alone in the frame, the call cutting the warmth", "Anudi's phone lights; she lifts it, listens, her smile fades, she looks back at Kasun",
        "The light goes out of her face; she gives him one last look."),
    8: ("C", "She leaves", [20, 21, 22], "She walks away; Kasun watches", "longing, a promise",
        "the wide as she walks, then Kasun alone, the narrator over his face", "Anudi walks away through the rain; Kasun watches her go",
        "He does not move until she is gone."),
}

# (moment, role, setup, blocks, lines, speaks, over, size, angle, lens, technique, why, take_s, handle_in, handle_out, priority, who)
Row = tuple[int, str, str, list[int], list[str], bool, str, str, str, str, str, str, int, float, float, str, list[str]]
MENU: list[Row] = [
    (1, "master", "B", [0, 1, 2], [], False, "", "WIDE", "eye level", "28mm: place and man together", "locked_off",
     "The place is a character: the rain, the traffic, the little stall.", 6, 1.0, 1.0, "must", ["Kasun"]),
    (2, "single", "F", [3], ["L3"], False, "", "CU", "eye level", "100mm: his thought, closer than anyone has been", "slow_creep",
     "The thought is heard over his face, lips closed: the dream is private.", 6, 1.0, 1.0, "must", ["Kasun"]),
    (3, "master", "H", [4], [], False, "", "WIDE", "eye level", "35mm: two worlds across a road", "locked_off",
     "Her car, her umbrella: the other world, across the road from his.", 4, 0.5, 0.5, "must", ["Anudi"]),
    (4, "master", "K", [5, 6], [], False, "", "WIDE", "eye level", "35mm: the whole accident", "locked_off",
     "The drop and the run in one wide, so the editor has the geography.", 8, 1.0, 1.0, "must", ["Anudi", "Kasun"]),
    (5, "master", "P", [7, 8, 9], ["L7", "L9"], True, "", "TWO", "eye level", "35mm: both in one frame", "locked_off",
     "The meeting in one frame: the editor can cut away and always come back.", 8, 0.5, 0.5, "must", ["Kasun", "Anudi"]),
    (5, "single", "Q", [7], ["L7"], True, "", "MCU", "eye level", "85mm: his call", "locked_off",
     "His face as he calls: shy and out of breath.", 4, 0.5, 0.5, "should", ["Kasun"]),
    (5, "single", "S", [8, 9], ["L9"], True, "", "CU", "eye level", "100mm: the warmth arrives", "locked_off",
     "Her thanks: the first warmth of the scene.", 6, 1.0, 1.0, "should", ["Anudi"]),
    (6, "master", "U", [10, 11, 12], ["L11"], True, "", "TWO", "eye level", "35mm: two people and the stall", "locked_off",
     "She looks at his little business and asks: the two-shot is the safe cut.", 8, 0.5, 0.5, "must", ["Kasun", "Anudi"]),
    (6, "master", "V", [13, 14], ["L13"], True, "", "TWO", "eye level", "35mm: his answer, her smile", "locked_off",
     "His story and her smile: the long line has its own take.", 8, 0.5, 0.5, "must", ["Kasun", "Anudi"]),
    (7, "reaction", "B", [15, 16], ["L16"], False, "Anudi", "MCU", "eye level", "85mm: she listens", "locked_off",
     "The father is only a voice: we watch it land on her face.", 8, 0.5, 0.5, "must", ["Anudi"]),
    (7, "single", "D", [17, 18, 19], ["L19"], True, "", "MCU", "eye level", "85mm: one last look", "locked_off",
     "The smile goes, then one last look: she promises without promising.", 6, 0.5, 0.5, "must", ["Anudi"]),
    (8, "master", "G", [20, 21], [], False, "", "WIDE", "eye level", "35mm: she goes, he stays", "locked_off",
     "She leaves and he watches, in one wide.", 6, 0.5, 0.5, "must", ["Anudi", "Kasun"]),
    (8, "single", "I", [22], ["L22"], False, "", "CU", "eye level", "100mm: the narrator over his face", "slow_creep",
     "The narrator's line over Kasun watching her go: the promise the scene ends on.", 8, 0.5, 0.5, "must", ["Kasun"]),
]
# the one clip the scripted director plans itself (a hard one: the phone's fall)
OWN: Row = (4, "insert", "L", [5], [], False, "", "INSERT", "high", "50mm: the phone falls", "tilt_reveal",
            "The camera follows the phone down to the wet ground: the trigger.", 4, 1.0, 1.0, "should", [])


def who_of(clip: dict[str, Any]) -> list[str]:
    """The people the hand-written table shows in a clip (a model's clip writer reads them from the plan instead)."""
    for row in [*MENU, OWN]:
        if row[0] == clip["moment"] and row[2] == clip["setup"] and row[1] == clip["role"] and row[3] == clip["blocks"]:
            return row[16]
    return []


def menu_entry(row: Row) -> dict[str, Any]:
    (moment, role, setup, blocks, lines, speaks, over, size, angle, lens, technique, why, take, hin, hout, pri, _who) = row
    return {"moment": moment, "role": role, "setup": setup, "blocks": blocks, "lines": lines, "speaks": speaks, "over": over,
            "size": size, "angle": angle, "lens": lens, "technique": technique, "why": why, "take_s": take,
            "handle_in_s": hin, "handle_out_s": hout, "priority": pri, "editor_note": ""}


def edit_plan() -> dict[str, Any]:
    seqs = {"A": ("The world", "Establish the rain, the stall and the other world", [1, 3]),
            "B": ("The meeting", "A dropped phone becomes a first conversation", [4, 6]),
            "C": ("The call", "The father's call closes the moment; she leaves", [7, 8])}
    return {"treatment": {
        "logline": "A street-food vendor returns a stranger's phone and, for one rainy minute, the two of them forget their worlds.",
        "arc": [{"beat": "his small world", "blocks": {"first": 0, "last": 3}, "feeling": "hunger for more"},
                {"beat": "the meeting", "blocks": {"first": 4, "last": 14}, "feeling": "warmth growing"},
                {"beat": "the call and the leaving", "blocks": {"first": 15, "last": 22}, "feeling": "longing, a promise"}],
        "approach": "Wide for the world, long lenses for intimacy; a still camera except where a thing falls or someone runs.",
        "colour_script": [{"sequence": k, "palette": "cool grey-teal with the tea's warmth", "light": LIGHT, "grade": g}
                          for k, g in (("A", "cold and desaturated"), ("B", "warmth returning to skin"), ("C", "cooling again"))],
        "geography": "Kasun's stall is screen left; the road and her car are screen right; she crosses toward him and leaves to the right.",
        "key_image": "Anudi small in the rain, walking away, Kasun still behind his stall.",
        "advice": ["The scene is ~60 s in the cut; the bin is far larger by design."]},
        "sequences": [{"id": k, "title": t, "purpose": p, "shots": {"first": a, "last": b}} for k, (t, p, (a, b)) in seqs.items()],
        "moments": [{"n": n, "sequence": m[0], "blocks": m[2], "what": m[3], "feeling": m[4], "cut_uses": m[5]}
                    for n, m in MOMENTS.items()],
        "editor_notes": []}


def design(clip: dict[str, Any], who: list[str], broken: bool = False) -> dict[str, Any]:
    """The Veo design of one clip, built from its own fields: every angle of a moment shares the place, the light and the
    people's looks word for word, and describes the action in the same words."""
    n = int(clip["moment"])
    aerial = clip["technique"].startswith("drone") or clip["role"] in ("establishing", "atmosphere")
    _seq, _t, _b, _w, _f, _c, action, perf = MOMENTS[n]
    place = WIDE_PLACE if aerial else PLACE
    light = "Cold fluorescent white light" if broken else LIGHT
    h_in, h_out, take = float(clip["handle_in_s"]), float(clip["handle_out_s"]), int(clip["take_s"])
    start, end = h_in, take - h_out
    shown = "the wet road and the rain" if not who else " and ".join(who)
    lead = f"0-{start:g}s"
    body = f"{start:g}-{end:g}s"
    tail = f"{end:g}-{take}s"
    heard = f" while line {', '.join(clip['lines'])} is heard" if clip["lines"] and not clip["speaks"] else ""
    perform = f" to line {', '.join(clip['lines'])}" if clip["speaks"] else ""
    return {
        "setting": place,
        "cinematography": {"camera": f"{clip['lens'].split(':')[0]} lens, {clip['technique'].replace('_', ' ')}", "angle": clip["angle"],
                           "framing": f"{clip['size']} on {shown}", "movement": clip["technique"].replace("_", " "),
                           "white_balance": "cool 5200K", "color_tone": "cool, desaturated teal-grey with warm tea steam",
                           "depth_of_field": "Shallow, soft background", "lens_artifacts": "rain streaks, headlight flare"},
        "lighting": light,
        "subjects": [{"id": CODES[w], "description": LOOKS[w], "action": action,
                      "position": "centre of frame" if len(who) == 1 else "left" if i == 0 else "right"}
                     for i, w in enumerate(who)],
        "beats": [{"time": lead, "camera": f"{clip['size']} settled", "director_line": "The frame holds before the action.",
                   "action": "The frame settles.", "performance": "Stillness."},
                  {"time": body, "camera": f"{clip['size']}, {clip['technique'].replace('_', ' ')}",
                   "director_line": clip["why"], "action": f"{action}{perform}{heard}.", "performance": perf},
                  {"time": tail, "camera": f"{clip['size']} holds", "director_line": "The action finishes and the frame holds.",
                   "action": "The frame holds.", "performance": "Stillness."}],
        "audio": "heavy rain, traffic, wet tyres",
        "first_frame": {"composition": f"{clip['size']} on {shown}, rain across the frame", "subjects": who, "setting": place,
                        "lighting": light}}


def sound(clip: dict[str, Any]) -> dict[str, Any]:
    return {"ambience": "heavy rain, traffic, wet tyres", "effects": "", "music": "", "silence": not clip["speaks"] and not clip["lines"]}


class Rehearsal:
    """A `Backend` with no model. `bind(orchestrator)` lets the director's script read the run's state."""

    def __init__(self) -> None:
        self.i = 0
        self.orch: Orchestrator | None = None
        self.broken_once = {"c07"}  # a clip whose first design uses another light, so the check finds it and the repair runs
        self.steps: list[tuple[str, Callable[[Orchestrator], dict[str, Any]]]] = self.script()

    def bind(self, orch: Orchestrator) -> None:
        self.orch = orch

    # the director -------------------------------------------------------------------------------

    def script(self) -> list[tuple[str, Callable[[Orchestrator], dict[str, Any]]]]:
        def clip_ids(o: Orchestrator) -> list[str]:
            return [c.id for c in o.work.clips]

        def failed(o: Orchestrator) -> list[str]:
            return sorted({i for f in checks.blocking(checks.check_all(o.reading, o.work)) if f.owner == "clip_writer" for i in f.clips})

        return [
            ("read_bin", lambda o: {"moment": 0}),
            ("finish", lambda o: {"editor_notes": ["(too early)"]}),  # refused: there is no edit plan, no coverage
            ("write_edit_plan", lambda o: edit_plan()),
            ("plan_coverage", lambda o: {"moments": [1, 2, 3], "brief": "Sequence A: the world. Plain coverage with an establishing and B-roll."}),
            ("plan_coverage", lambda o: {"moments": [4, 5, 6], "brief": "Sequence B: the meeting. Cover each line from the master and the singles; a whip pair."}),
            ("plan_coverage", lambda o: {"moments": [7, 8], "brief": "Sequence C: the call. The father is a voice; show the listener."}),
            ("add_clips", lambda o: {"clips": [menu_entry(OWN)]}),
            ("write_clips", lambda o: {"clip_ids": clip_ids(o), "note": ""}),
            ("check", lambda o: {}),
            ("write_clips", lambda o: {"clip_ids": failed(o), "note": "Copy the lighting sentence word for word into this clip."}),
            ("check", lambda o: {}),
            ("finish", lambda o: {"editor_notes": [
                "Masters (setups B, H, K, P, U, V, G) are the cut; the two Q/S singles and the insert are the only alternates: the bin is held to the given length plus 50%.",
                "Avoided: a dolly zoom on the phone call (Veo is unreliable); the father is never shown; a speed ramp on the run is post only.",
                "Dialogue plays under the chosen audio: only the masters and the speakers' singles perform lines."]})]

    def step(self, *, system: str, items: list[dict[str, Any]], previous_id: str | None, tools: list[dict[str, Any]],
             model: str, effort: str, max_output: int) -> Reply:
        assert self.orch is not None, "bind() the orchestrator first"
        if self.i >= len(self.steps):
            return Reply(id=f"r{self.i}", text="Done.", usage=Usage(2000, 1500, 100, 50))
        name, args = self.steps[self.i]
        self.i += 1
        return Reply(id=f"r{self.i}", calls=[Call(id=f"call{self.i}", name=name, args=json.dumps(args(self.orch)))],
                     usage=Usage(input_tokens=9000, cached_tokens=7000, output_tokens=1800, reasoning_tokens=1200))

    # the workers --------------------------------------------------------------------------------

    def structured(self, *, system: str, user: str, schema: dict[str, Any], model: str, effort: str, max_output: int) -> Reply:
        kind = schema["title"]
        if kind == "coverage_menu":
            plan = json.loads(re.search(r"<edit_plan>\n(.*?)\n</edit_plan>", user, re.S).group(1))  # type: ignore[union-attr]
            asked = {m["n"] for m in plan["moments"] if m["asked_for"]}
            clips = []
            for row in MENU:
                if row[0] in asked:
                    clips.append(menu_entry(row))
            return Reply(id="w", text=json.dumps({"clips": clips}),
                         usage=Usage(input_tokens=7000, cached_tokens=0, output_tokens=7000, reasoning_tokens=2500))
        wanted = json.loads(re.search(r"<clips>\n(.*?)\n</clips>", user, re.S).group(1))  # type: ignore[union-attr]
        designs = []
        for c in wanted:
            bad = c["id"] in self.broken_once
            self.broken_once.discard(c["id"])
            designs.append({"id": c["id"], "ir": design(c, who_of(c), broken=bad), "sound": sound(c)})
        return Reply(id="w", text=json.dumps({"designs": designs}),
                     usage=Usage(input_tokens=6000, cached_tokens=0, output_tokens=6000 + 700 * len(wanted), reasoning_tokens=1500))


def reading() -> pack.Reading:
    from pathlib import Path

    return pack.load(Path(__file__).resolve().parents[1] / "cinematic" / "input" / "reading.yaml")


# ── the staged rehearsal (plan B): the same scene through plan, repair, design, re-design ─────────


def staged_plan(*, first: bool) -> dict[str, Any]:
    """The director's one answer as a table. `first=True` is the draft with three things wrong: moment 3's must clip is missing
    (two coverage faults: block b4 and the moment itself) and the narrator's clip covers its block but lists no line id (code's
    `mend` adds it). `first=False` is the repaired plan (the same table, whole)."""
    rows = list(MENU)
    at = next(i for i, r in enumerate(rows) if r[0] == 4) + 1
    rows.insert(at, OWN)  # the phone's fall is shot after the wide of the accident
    if first:
        rows = [r for r in rows if r[0] != 3]
        rows = [(*r[:4], [], *r[5:]) if r[4] == ["L22"] else r for r in rows]
    plan = edit_plan()
    plan["editor_notes"] = [
        "Masters (setups B, H, K, P, U, V, G) are the cut; the Q and S singles and the insert are the only alternates: the bin is "
        "held to the given length plus 50%.",
        "Avoided: a dolly zoom on the phone call (Veo is unreliable); the father is never shown; a speed ramp on the run is post only.",
        "Dialogue plays under the chosen audio: only the masters and the speakers' singles perform lines."]
    who: dict[int, list[str]] = {}
    for r in [*MENU, OWN]:
        for w in r[16]:
            if w not in who.setdefault(r[0], []):
                who[r[0]].append(w)
    looks = [{"moment": n, "setting": PLACE, "lighting": LIGHT,
              "people": [{"id": CODES[w], "description": LOOKS[w]} for w in who.get(n, [])]} for n in MOMENTS]
    return {"edit_plan": plan, "clips": [menu_entry(r) for r in rows], "looks": looks}


class StagedRehearsal:
    """A `Backend` with no model for the staged runner. It answers the plan call with a flawed draft and the repair call with the
    corrected plan, and each clip-writer call with a design built from the clip's own fields. Two designs are flawed on purpose:
    one writes another light and another look for Kasun (the look sheet must overwrite them: no fault is left), one puts the
    voice-only father in frame (code cannot mend it: a re-design of that clip alone must). `calls` records what was asked."""

    def __init__(self, *, repair: str = "good") -> None:
        self.repair = repair  # good | same | worse: what the repair call returns
        self.calls: list[tuple[str, list[str]]] = []
        self.messages: list[str] = []  # every user message the runner sent, so a test can read what a model would see
        self.father_once = True
        self.light_once = True
        self._lock = threading.Lock()

    def step(self, **_: Any) -> Reply:
        raise AssertionError("the staged runner calls no tools")

    def structured(self, *, system: str, user: str, schema: dict[str, Any], model: str, effort: str, max_output: int) -> Reply:
        kind = schema["title"]
        self.messages.append(user)
        if kind == "shot_plan":
            repairing = "<faults>" in user
            with self._lock:
                self.calls.append(("repair" if repairing else "plan", []))
            plan = staged_plan(first=not repairing or self.repair != "good")
            if repairing and self.repair == "worse":
                plan["clips"] = plan["clips"][:6]  # a repair that makes things worse: most of the bin is gone
            return Reply(id="p", text=json.dumps(plan), usage=Usage(input_tokens=12000, cached_tokens=0, output_tokens=18000,
                                                                      reasoning_tokens=12000))
        wanted = json.loads(re.search(r"<clips>\n(.*?)\n</clips>", user, re.S).group(1))  # type: ignore[union-attr]
        redo = "<faults>" in user
        with self._lock:
            self.calls.append(("redesign" if redo else "design", [c["id"] for c in wanted]))
            designs = []
            for c in wanted:
                ir = design(c, who_of(c))
                if not redo and c["moment"] == 7 and c["role"] == "reaction" and self.father_once:
                    self.father_once = False
                    ir["subjects"].append({"id": "C03", "description": "Father, polo shirt", "action": "waits", "position": "left"})
                if not redo and c["moment"] == 5 and c["role"] == "single" and self.light_once:
                    self.light_once = False
                    ir["lighting"] = "Cold fluorescent white light"
                    if ir["subjects"]:
                        ir["subjects"][0]["description"] = "Kasun in a red shirt"
                designs.append({"id": c["id"], "ir": ir, "sound": sound(c)})
        return Reply(id="w", text=json.dumps({"designs": designs}),
                     usage=Usage(input_tokens=6000, cached_tokens=0, output_tokens=6000 + 700 * len(wanted), reasoning_tokens=1500))
