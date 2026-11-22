"""The grid that was painted (plan/2026-11-22): the board cutter reads the grid the image model REALLY painted, and
`cut_problems` names a crop that holds two panels or an empty cell. Ported unchanged from `lab/board_grid/grid.py`;
the parity tests run the lab's own cutter on the lab's boards and skip when the lab's inputs are not on disk."""
from __future__ import annotations

import io
import json
import sys
from pathlib import Path

import pytest
from PIL import Image, ImageDraw

from contracts import board as kit
from hiru_ai.systems.frame_render import pictures as pics

LAB = Path(__file__).resolve().parents[2] / "lab" / "board_grid"
BAD_STORED = ("34683023", "63817917", "72c07de3")  # the three the product cut wrong (lab sweep, 2026-11-22)


def sheet(panels: list[tuple[int, int, int, int]], w: int = 1024, h: int = 1536,
          empty: list[tuple[int, int, int, int]] = (), card: tuple[int, int, int, int] | None = None) -> bytes:
    """White sheet; each panel a textured grey picture; `empty` cells drawn as thin grey outlines (as the model
    draws them); `card` a panel that is a white card with an orange outline (a drawn phone screen)."""
    im = Image.new("RGB", (w, h), "white")
    d = ImageDraw.Draw(im)
    for i, (x0, y0, x1, y1) in enumerate(panels):
        d.rectangle((x0, y0, x1 - 1, y1 - 1), fill=(50 + 12 * i, 70, 90))
        for k in range(y0, y1, 40):
            d.line((x0, k, x1 - 1, k + 20), fill=(30, 40 + 5 * i, 60), width=3)
    for x0, y0, x1, y1 in empty:
        d.rectangle((x0, y0, x1 - 1, y1 - 1), outline=(200, 200, 200), width=1)
    if card:
        x0, y0, x1, y1 = card
        d.rectangle((x0, y0, x1 - 1, y1 - 1), fill=(250, 250, 248))
        d.rectangle((x0, y0, x1 - 1, y0 + 40), fill=(205, 205, 205))
        d.rectangle((x0, y1 - 60, x1 - 1, y1 - 1), fill=(215, 215, 215))  # the stored cards end on a grey band
        d.rounded_rectangle((x0 + 30, y0 + 200, x1 - 30, y0 + 360), radius=30, outline=(240, 160, 40), width=5)
    buf = io.BytesIO()
    im.save(buf, format="PNG")
    return buf.getvalue()


def grid_boxes(cols: int, rows: int, w: int, h: int, gutter: int = 6, height: int | None = None
               ) -> list[tuple[int, int, int, int]]:
    """The cells of an even grid; `height` paints only that much of the sheet (white left below)."""
    h_used = height or h
    cw, ch = (w - gutter * (cols - 1)) // cols, (h_used - gutter * (rows - 1)) // rows
    return [(c * (cw + gutter), r * (ch + gutter), c * (cw + gutter) + cw, r * (ch + gutter) + ch)
            for r in range(rows) for c in range(cols)]


def near(a: tuple[int, ...], b: tuple[int, ...], px: int = 8) -> bool:
    return all(abs(x - y) <= px for x, y in zip(a, b, strict=True))


def test_asked_three_by_two_painted_three_by_three_with_an_empty_row():
    cells = grid_boxes(3, 3, 1024, 1536)
    png = sheet(cells[:6], empty=cells[6:])
    old = pics._even_boxes(png, 6)
    assert pics.cut_problems(png, old), "the old cut runs through the second row: two panels in one crop"
    boxes = pics.cell_boxes(png, 6)
    assert all(near(b, c) for b, c in zip(boxes, cells[:6], strict=True)), boxes
    assert pics.cut_problems(png, boxes) == []


def test_asked_two_across_painted_two_down():
    cells = grid_boxes(1, 2, 1024, 1536)
    png = sheet(cells)
    assert pics.cut_problems(png, pics._even_boxes(png, 2)), "two strips, each half of both panels"
    boxes = pics.cell_boxes(png, 2)
    assert all(near(b, c) for b, c in zip(boxes, cells, strict=True)), boxes
    assert pics.cut_problems(png, boxes) == []


def test_panels_painted_touching_are_cut_at_the_even_split():
    cells = grid_boxes(4, 3, 1536, 1024, gutter=0)
    png = sheet(cells[:10], w=1536, h=1024)
    boxes = pics.cell_boxes(png, 10)
    assert len(boxes) == 10 and pics.cut_problems(png, boxes) == []
    assert near(boxes[5], cells[5], 4)


def test_white_left_under_the_grid_is_not_part_of_it():
    cells = grid_boxes(2, 2, 1024, 1536, height=1200)  # the gutter at ~597, outside the old search (640-896)
    png = sheet(cells[:3])
    old = pics._even_boxes(png, 3)
    assert pics.cut_problems(png, old), "the even split at 768 puts empty white into a crop"
    boxes = pics.cell_boxes(png, 3)
    assert all(near(b, c) for b, c in zip(boxes, cells[:3], strict=True)), boxes
    assert pics.cut_problems(png, boxes) == []


def test_a_drawn_white_card_is_a_panel_not_an_empty_cell():
    cells = grid_boxes(3, 3, 1024, 1536)
    png = sheet(cells[:8], card=cells[8])
    boxes = pics.cell_boxes(png, 9)
    assert all(near(b, c) for b, c in zip(boxes, cells, strict=True)), boxes
    assert pics.cut_problems(png, boxes) == []


def test_a_clean_board_cuts_as_before():
    cells = grid_boxes(3, 2, 1024, 1536)
    png = sheet(cells)
    assert all(near(a, b, 2) for a, b in zip(pics.cell_boxes(png, 6), pics._even_boxes(png, 6), strict=True))


def test_an_empty_crop_is_named():
    cells = grid_boxes(2, 2, 1024, 1536)
    png = sheet(cells[:3], empty=cells[3:])
    assert pics.cut_problems(png, cells) == ["panel 4 empty"]


# ── parity with the lab (skipped when lab/board_grid/ is not on disk) ─────────────────────────────────────────


def _lab():
    if not (LAB / "grid.py").exists() or not (LAB / "input" / "boards").exists():
        pytest.skip("lab/board_grid inputs are not on disk")
    sys.path.insert(0, str(LAB))
    try:
        import grid  # type: ignore[import-not-found]
    finally:
        sys.path.remove(str(LAB))
    return grid


def _stored() -> list[tuple[str, bytes, list[list[int]]]]:
    out = []
    for jf in sorted((LAB / "input" / "boards").glob("*.json")):
        b = json.loads(jf.read_text(encoding="utf-8"))
        cells = sorted((c for c in b.get("cells") or [] if c.get("panel")), key=lambda c: c["panel"])
        png = jf.with_suffix(".png")
        if png.exists() and cells and all(c.get("box") for c in cells):
            out.append((b["id"], png.read_bytes(), [c["box"] for c in cells]))
    return out


def test_parity_with_the_lab_on_every_stored_board():
    grid = _lab()
    boards = _stored()
    assert boards
    for bid, png, saved in boards:
        n = len(saved)
        assert pics.cell_boxes(png, n) == [tuple(b) for b in grid.cut(png, n, kit.grid_for(n))[0]], bid
        assert pics.cut_problems(png, saved) == grid.check(png, saved)[0], bid


def test_the_three_bad_stored_cuts_are_found_and_mended():
    _lab()
    flagged = []
    for bid, png, saved in _stored():
        if pics.cut_problems(png, saved):
            flagged.append(bid[:8])
            assert pics.cut_problems(png, pics.cell_boxes(png, len(saved))) == [], bid
        else:
            assert pics.cut_problems(png, pics.cell_boxes(png, len(saved))) == [], f"the new cut broke {bid}"
    assert sorted(flagged) == sorted(BAD_STORED)


def test_parity_with_the_lab_on_run_001():
    grid = _lab()
    run = LAB / "runs" / "run_001"
    pngs = sorted(p for p in run.glob("[ABC][123].png"))
    if not pngs:
        pytest.skip("lab/board_grid run_001 is not on disk")
    for p in pngs:
        png = p.read_bytes()
        boxes = pics.cell_boxes(png, 6)
        assert boxes == [tuple(b) for b in grid.cut(png, 6, (3, 2))[0]], p.name
        assert pics.cut_problems(png, boxes) == [], p.name


# ── the writer never names a grid (§3.3) ──────────────────────────────────────────────────────────────────────


def test_the_writers_layout_sentences_never_reach_the_board():
    w = kit.Writer.of({
        "world": "Paint one unified storyboard image in a four-column, four-row grid, reading left to right. Fill "
                 "the first fourteen cells and leave the final two cells blank. Soft overcast light from the road. "
                 "Rain falls straight down.",
        "geography": "The road runs across the foreground.",
        "panels": [{"shot": n, "zone": "road", "camera": f"Camera {n}.", "background": "the shop at left",
                    "picture": "The red mannequin waits.", "people": []} for n in range(1, 7)],
        "conflicts": []})
    prompt = kit.board_prompt(w, list(range(1, 7)), [], kit.colours_for(["Kasun"]), kit.TALL)
    assert "laid out in a grid 3 panels across and 2 down" in prompt, "the head sentence alone names the grid"
    assert "four-column" not in prompt and "fourteen cells" not in prompt
    assert "World (every panel): Soft overcast light from the road. Rain falls straight down." in prompt


def test_the_writer_is_not_told_a_grid():
    note = kit.writer_message({"shots": [{}] * 14}, kit.colours_for(["Kasun"]))
    assert "Write the storyboard: 14 panels, one per shot in shot order." in note
    assert "across" not in note.split("</scene>")[-1] and " down." not in note.split("</scene>")[-1]


def test_the_layout_filter_is_the_labs_b_variant_exactly():
    """Golden: the World paragraph of the saved prompt of board 34683023 (lab variant A), filtered, is variant B's."""
    a = LAB / "input" / "love_p2" / "board.json"
    b = LAB / "runs" / "run_001" / "B_prompt.txt"
    if not (a.exists() and b.exists()):
        pytest.skip("lab/board_grid run_001 is not on disk")
    saved = json.loads(a.read_text(encoding="utf-8"))["prompt"]
    world_a = next(x for x in saved.split("\n") if x.startswith("World (every panel): "))
    world_b = next(x for x in b.read_text(encoding="utf-8").split("\n") if x.startswith("World (every panel): "))
    prefix = "World (every panel): "
    assert world_a != world_b
    assert prefix + kit.board_layout_free(world_a[len(prefix):]) == world_b
