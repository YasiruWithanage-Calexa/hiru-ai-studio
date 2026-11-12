"""The production's genre in the video prompt, the shot writers' FORMAT line and the frame renderer (plan/2026-11-12b).
No genre keeps every text byte for byte as before."""

from __future__ import annotations

from typing import Any

from hiru_ai.core import agents, house_rules, parts


def _rules() -> Any:
    return parts.step("serialize", "shots").get_schema()


def test_the_video_style_names_the_genre():
    style = parts.step("serialize", "logic").medium_style(_rules(), "action and crime thriller")
    assert style == ("Photorealistic live-action footage of a Sri Lankan action and crime thriller, real optics and "
                     "natural imperfections.")


def test_without_a_genre_the_video_style_is_as_before():
    rules = _rules()
    assert parts.step("serialize", "logic").medium_style(rules, "") == rules.rule("medium_style")
    assert "television drama" in rules.rule("medium_style")


def _prod(genre: str = "") -> Any:
    model = parts.step("serialize", "model")
    row = {"id": "p1", "title": "Ekama", "orientation": "horizontal", "settings": {}}
    prod = model.production_input(row, [], None)
    prod.genre = genre
    return prod


def test_the_shot_writers_format_line_names_the_genre():
    block = parts.step("serialize", "shots").production_block
    genre = "action and crime thriller"
    assert f"FORMAT: Sri Lankan {genre}, live action, 16:9." in block(_prod(genre))
    assert "FORMAT: Sri Lankan television drama, live action, 16:9." in block(_prod())


def test_the_renderers_world_carries_the_genre_into_the_brief():
    world_cls = parts.step("frame_compose", "logic").World
    payload = {"production": {"id": "p1", "orientation": "horizontal"}, "canon": [],
               "scene": {"heading": "EXT. CANAL - DAWN", "time_of_day": "dawn"}, "lines": []}
    shot = {"id": "s1", "scene_id": "sc1", "framing": "WS", "ir": {}, "design": {}, "block_start": 0, "block_end": 0}
    with_genre = world_cls.of({**payload, "genre": "crime thriller"}).brief(shot, [])
    without = world_cls.of(payload).brief(shot, [])
    assert with_genre.text().startswith("Photorealistic still frame from a Sri Lankan crime thriller,")
    assert without.text().startswith("Photorealistic still frame from a Sri Lankan television drama,")


def test_h13_is_deployed_and_the_raphael_planners_are_given_it():
    rules = {r.id: r for r in house_rules.rules()}
    assert rules["H-13"].kind == "default" and "genre" in rules["H-13"].topics
    assert "the genre sets the tension" in rules["H-13"].text
    for name in ("raphael_planner", "raphael_cinematic"):
        assert "genre" in agents.build(name).manifest.house_rules


# ── black plates (plan/2026-11-12b, after the live check) ───────────────────────────────────────────────────────────


def _plate_world(blocks: list[dict[str, Any]]) -> Any:
    world_cls = parts.step("frame_compose", "logic").World
    return world_cls.of({"production": {"id": "p1", "orientation": "horizontal"}, "canon": [],
                         "scene": {"heading": "EXT. CANAL - DAWN", "script": blocks}, "lines": []})


def test_a_shot_of_a_cut_to_black_or_a_title_is_a_plate_and_an_action_is_not():
    world = _plate_world([{"kind": "action", "text": "She calls Dinu. No answer."},
                          {"kind": "cut", "text": "Cut to black."},
                          {"kind": "action", "text": "TITLE: EKAMA SAKSHIYA."}])
    shot = {"id": "s", "framing": "WS", "ir": {}, "design": {}}
    assert world.plate({**shot, "block_start": 1, "block_end": 3})
    assert not world.plate({**shot, "block_start": 0, "block_end": 2})
    assert not world.plate({**shot, "block_start": 0, "block_end": 0})  # a shot with no blocks is painted


def test_the_black_plate_is_a_black_png_of_the_painters_size():
    import io

    from PIL import Image

    logic = parts.step("frame_compose", "logic")
    im = Image.open(io.BytesIO(logic.black_png("16:9")))
    assert im.size == (1536, 1024) and im.getextrema() == ((0, 0), (0, 0), (0, 0))
    assert Image.open(io.BytesIO(logic.black_png("9:16"))).size == (1024, 1536)


def test_the_renderer_stores_a_plate_without_painting():
    from types import SimpleNamespace

    from contracts.frame_brief import BLACK_PLATE
    from hiru_ai.systems.frame_render import graph

    stored: dict[str, Any] = {}
    files = SimpleNamespace(upload=lambda b, p, d, m: stored.update(bucket=b, path=p, data=d, mime=m))
    frames = SimpleNamespace(finish_frame=lambda fid, f: stored.update(fid=fid, fields=f))
    ctx = SimpleNamespace(need=lambda name: {"files": files, "frames": frames}[name])
    scenes = SimpleNamespace(production_id="p1", production={"orientation": "horizontal"})
    assert graph.black_plate(ctx, scenes, {"id": "f1"}, {"id": "s1"}) == "done"  # type: ignore[arg-type]
    assert stored["bucket"] == "frames" and stored["path"] == "p1/s1/f1.png" and stored["data"].startswith(b"\x89PNG")
    assert stored["fields"]["status"] == "done" and stored["fields"]["prompt"] == BLACK_PLATE
    assert stored["fields"]["reference_ids"] == []


def test_h13_v2_puts_the_genre_into_the_light():
    rule = {r.id: r for r in house_rules.rules()}["H-13"]
    assert rule.version == 2
    assert "never means soft, flat, even light" in rule.text and "deep shadow" in rule.text
