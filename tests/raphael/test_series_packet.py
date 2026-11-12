"""Raphael reads what the drama is first inside its <packet> (plan/2026-11-12b). Here, not in tests/breakdown: only the
raphael folders may import Raphael's code."""

from __future__ import annotations

from contracts.breakdown import packet, series
from contracts.breakdown import run as brun
from contracts.raphael.packet import render as raphael_render
from contracts.raphael.packet import scene_from_packet
from tests.breakdown.test_breakdown_run import _upload
from tests.breakdown.test_series import WithSeries


def test_raphael_reads_the_series_first_inside_the_packet():
    bd = brun.create([_upload()], WithSeries().calls(), workers=1).memory
    p = packet.assemble(bd, "E01-S01")
    _, ids = scene_from_packet(p)
    text = raphael_render(p, ids)
    assert text.startswith(series.HEADING)
    assert "Genre: action (main), crime thriller (main), love (thread)" in text
    assert "murder" not in text.split("SCENE E01-S01", 1)[0]  # the premise line is the reader's words
    assert "This scene: place " in text
    without = {k: v for k, v in p.items() if k != "J_series"}
    assert raphael_render(without, ids) == text.split("\n\n", 1)[1]  # nothing else moved
