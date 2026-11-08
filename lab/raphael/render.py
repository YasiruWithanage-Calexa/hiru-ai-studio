"""The page a person reads: DaVinci's page (the intended cut, the bin by moment, the notes, the checks, Jonathan beside it),
titled for Raphael and with the length against both the target and the cap. One self-contained HTML file."""
from __future__ import annotations

from html import escape
from typing import Any

from davinci import checks, render
from davinci.checks import Fault
from davinci.state import Bin


def build(reading: Any, work: Bin, found: list[Fault], stopped: str, detail: str, source: str,
          jonathan: dict[str, Any] | None = None, turns: int = 0) -> str:
    n = work.counts()
    cap = checks.limit_s(reading)
    length = (f"{n['take_s']} s of takes ({n['must_take_s']} s must) against a target of {reading.guide_s:g} s and a cap of "
              f"{cap:g} s" if cap else f"{n['take_s']} s of takes")
    html = render.page(f"Raphael bin: {reading.title}", source, reading.words(), work, found, checks.measures(reading, work),
                       stopped, detail, jonathan)
    html = html.replace("<th>DaVinci</th>", "<th>Raphael</th>")
    extra = f"<p><b>Length:</b> {escape(length)}. <b>Turns used:</b> {turns}.</p>"
    return html.replace("</p>", "</p>" + extra, 1) if "</p>" in html else html + extra
