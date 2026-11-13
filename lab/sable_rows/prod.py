"""The production as Sable sees it (2026-11-13): aware of everything, changing only the open scene.

    p = Production.load(path)          the lab's story copy of "test" (`story.py`)
    p.card()                            the PRODUCTION CARD, written by code, the same bytes every message (cached by
                                        the provider): episodes with synopses, every scene in one line (place, who
                                        speaks, what happens), the canon with its cards
    p.read_scene("E1S3")                one scene in full: the script with its lines and the shots (the one lookup)
    p.coverage("E2S2")                  a scene as clips for the row kernel (`lab/zora_rows/coverage.py`)
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from coverage import Coverage

Row = dict[str, Any]
REF = re.compile(r"^\s*E?(\d+)\s*S(\d+)\s*$", re.I)


@dataclass
class Production:
    data: Row

    @classmethod
    def load(cls, path: Path) -> Production:
        return cls(json.loads(path.read_text(encoding="utf-8")))

    @property
    def episode_no(self) -> dict[str, int]:
        return {e["id"]: int(e["number"]) for e in self.data["episodes"]}

    def label(self, scene: Row) -> str:
        return f"E{self.episode_no[scene['episode_id']]}S{scene['number']}"

    def scenes(self) -> list[Row]:
        return sorted(self.data["scenes"], key=lambda s: (self.episode_no[s["episode_id"]], int(s["number"])))

    def scene(self, ref: str) -> Row | None:
        m = REF.match(ref or "")
        if not m:
            return None
        ep, n = int(m.group(1)), int(m.group(2))
        return next((s for s in self.scenes() if self.episode_no[s["episode_id"]] == ep and int(s["number"]) == n), None)

    def characters(self) -> list[Row]:
        return [{"id": c["id"], "code": c["code"], "name": c["name"], "kind": c["kind"]} for c in self.data["canon"]
                if c["kind"] == "character"]

    def scene_data(self, scene: Row) -> Row:
        """The scene in the export's shape for `Coverage.from_data`. A classic shot has no intent: who is on screen is
        read from the lines it covers (the seed's shots carry no picture yet)."""
        shots = [dict(s) for s in self.data["shots"] if s["scene_id"] == scene["id"]]
        lines = [ln for ln in self.data["lines"] if ln["scene_id"] == scene["id"]]
        dialogue = [i for i, b in enumerate(scene["script"]) if b.get("kind") == "dialogue"]
        speaker_at = {dialogue[i]: ln["speaker"] for i, ln in enumerate(sorted(lines, key=lambda r: int(r["ord"])))
                      if i < len(dialogue)}
        for s in shots:
            intent = dict(s.get("intent") or {})
            if not intent.get("on_screen"):
                who = [speaker_at[b] for b in range(int(s["block_start"]), int(s["block_end"])) if b in speaker_at]
                intent["on_screen"] = list(dict.fromkeys(who))
            s["intent"] = intent
        return {"production": self.data["production"], "scene": scene, "shots": shots, "lines": lines,
                "characters": self.characters()}

    def coverage(self, ref: str) -> Coverage:
        scene = self.scene(ref)
        if scene is None:
            raise KeyError(ref)
        return Coverage.from_data(self.scene_data(scene))

    def _actions(self, scene: Row) -> str:
        acts = [str(b.get("text") or "") for b in scene["script"] if b.get("kind") != "dialogue" and b.get("text")]
        return " … ".join(acts)

    def card(self) -> str:
        p = self.data
        eps = "\n".join(f"E{e['number']}: {e.get('synopsis') or ''}" for e in sorted(p["episodes"],
                                                                                       key=lambda e: e["number"]))
        rows = []
        for s in self.scenes():
            who = sorted({ln["speaker"] for ln in self.data["lines"] if ln["scene_id"] == s["id"]})
            rows.append(f"{self.label(s)} {s['heading']} · speaks: {', '.join(who) or '-'} · {self._actions(s)}")
        canon = []
        for c in self.data["canon"]:
            card = c.get("card") or {}
            facts = "; ".join(f"{k} {v}" for k, v in card.items() if k != "summary" and v)
            canon.append(f"{c['name']} ({c['code']}, {c['kind']}): {card.get('summary', '')}" + (f" ({facts})" if facts else ""))
        return (f"PRODUCTION: {p['production']['title']}\n\nEPISODES\n{eps}\n\nSCENES (what happens in each; who "
                f"speaks)\n" + "\n".join(rows) + "\n\nCANON\n" + "\n".join(canon))

    def read_scene(self, ref: str) -> str:
        scene = self.scene(ref)
        if scene is None:
            return f"There is no scene {ref}. Scenes: " + ", ".join(self.label(s) for s in self.scenes())
        cov = Coverage.from_data(self.scene_data(scene))
        return f"{self.label(scene)}\n{cov.render(only=set())}"
