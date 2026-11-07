"""A fake document reader for the ingest tests of both engines (plan/2026-11-06f): it answers from the message it is
sent, so the answer passes the real checks. Text mode: one scene per heading, every line an action block pointing at
its own line. Pages mode: one scene per page and a transcription that names the page."""
from __future__ import annotations

import re
from typing import Any

from contracts.screenplay import SCENE_HEADING, parse_heading

_NUMBERED = re.compile(r"^L(\d{4,}) (.*)$", re.MULTILINE)
_PAGES = re.compile(r'pages="(\d+)-(\d+)"')
EMPTY_CANON: dict[str, Any] = {"characters": [], "locations": [], "props": []}


def _scene(heading: str, location: str, time: str, lines: list[int], blocks: list[dict[str, Any]]) -> dict[str, Any]:
    return {"number": "1", "heading": heading, "int_ext": "", "location": location or "somewhere",
            "sub_location": "", "time_of_day": time, "clock": "", "stated_seconds": 0, "flashback": False,
            "lines": lines, "blocks": blocks}


def piece_answer(message: str) -> dict[str, Any]:
    """A `PieceRead` that passes the checks for the piece this message describes."""
    first, last = (int(x) for x in _PAGES.search(message).groups())  # type: ignore[union-attr]
    if 'mode="pages"' in message:
        scenes = [_scene(f"PAGE {p}", "somewhere", "", [], [
            {"kind": "action", "speaker": "", "cue": "", "delivery": "", "text": f"clean page {p}", "src": []}])
            for p in range(first, last + 1)]
        return {"canon": EMPTY_CANON, "episodes": [{"number": 0, "title": "", "stated_runtime": "", "scenes": scenes}],
                "transcription": [{"page": p, "text": f"clean page {p}"} for p in range(first, last + 1)]}
    text = {int(n): t for n, t in _NUMBERED.findall(message)}
    numbers = sorted(text)
    heads = [n for n in numbers if SCENE_HEADING.match(text[n])]
    scenes = []
    for k, h in enumerate(heads):
        end = heads[k + 1] - 1 if k + 1 < len(heads) else numbers[-1]
        heading = parse_heading(text[h])
        blocks = [{"kind": "action", "speaker": "", "cue": "", "delivery": "", "text": text[n], "src": [n, n]}
                  for n in range(h + 1, end + 1) if text.get(n, "").strip()]
        scenes.append(_scene(text[h], heading.location, heading.time_of_day, [h, end], blocks))
    return {"canon": EMPTY_CANON, "episodes": [{"number": 1, "title": "", "stated_runtime": "", "scenes": scenes}],
            "transcription": []}


def canon_answer(message: str) -> dict[str, Any]:
    first, last = (int(x) for x in _PAGES.search(message).groups())  # type: ignore[union-attr]
    pages = ([{"page": p, "text": f"clean page {p}"} for p in range(first, last + 1)]
             if 'mode="pages"' in message else [])
    return {"canon": EMPTY_CANON, "transcription": pages}
