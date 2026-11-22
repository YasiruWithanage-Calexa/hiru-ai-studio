"""plan/2026-11-22c: a chat's video note (how a shot plays) is staged, accepted and saved without moving the shot's
version, so its first frame stays current while its prompts go out of date."""
from __future__ import annotations

import pytest

from contracts.producer import PersonEdits
from hiru_ai.core.errors import ToolRefused
from hiru_ai.tools.sable.sable_shot_change import tool as propose
from tests.sable.test_scene_edits import _accept, rows_of, sable_ctx

SOFTER = {"op": "video_note", "shot": 1, "value": "Her voice softer, calm and romantic."}


def test_a_video_note_is_staged_as_a_card_and_saved_only_on_accept():
    ctx = sable_ctx()
    out = propose.run(propose.Args(summary="A softer, calmer S01.", ops=[SOFTER]), ctx)
    (card,) = ctx.ports.staging.staged()
    assert card["ops"][0]["op"]["op"] == "video_note"
    assert out.changes == ["S01 · video note: - → Her voice softer, calm and romantic."]
    assert all(not PersonEdits.of(s).video_note for s in rows_of(ctx))


def test_an_accepted_video_note_keeps_the_version_so_the_first_frame_stays_current():
    ctx = sable_ctx()
    propose.run(propose.Args(summary="A softer, calmer S01.", ops=[SOFTER]), ctx)
    (card,) = ctx.ports.staging.staged()
    first = dict(rows_of(ctx)[0])
    out = _accept(ctx, card)
    assert out.ok, out.text
    after = rows_of(ctx)[0]
    assert PersonEdits.of(after).video_note == "Her voice softer, calm and romantic."
    assert int(after.get("version") or 1) == int(first.get("version") or 1)
    assert PersonEdits.of(after).dop_note == PersonEdits.of(first).dop_note  # nothing else moved


def test_a_note_with_a_picture_change_still_moves_the_version():
    ctx = sable_ctx()
    size = {"op": "set", "shot": 1, "field": "size", "value": "CU"}
    propose.run(propose.Args(summary="Closer and softer.", ops=[SOFTER, size]), ctx)
    (card,) = ctx.ports.staging.staged()
    first = dict(rows_of(ctx)[0])
    assert _accept(ctx, card).ok
    assert int(rows_of(ctx)[0]["version"]) == int(first.get("version") or 1) + 1


def test_a_video_note_over_600_characters_is_refused():
    ctx = sable_ctx()
    with pytest.raises(ToolRefused, match="600"):
        propose.run(propose.Args(summary="Long.", ops=[{"op": "video_note", "shot": 1, "value": "a " * 400}]), ctx)
