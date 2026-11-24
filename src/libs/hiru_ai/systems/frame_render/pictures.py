"""The Scene board's pictures (plan/2026-11-14): Pillow work kept out of `contracts`, which stays standalone. Cut a
painted board along its gutters, paste a locked panel back, draw the numbered sheet (cells cut from a grid and panels
painted alone side by side, plan/2026-11-17), cut a base sheet's portrait for a face sheet. Ported from the storyboard
lab (`lab/storyboard/run.py`, `faces.py`)."""
from __future__ import annotations

import io
import re
from collections.abc import Mapping, Sequence
from typing import Any

from contracts.board import BoardShot, grid_for
from contracts.canon import PORTRAIT_SHARE


def _image(data: bytes) -> Any:
    from PIL import Image

    return Image.open(io.BytesIO(data)).convert("RGB")


def _png(im: Any) -> bytes:
    buf = io.BytesIO()
    im.save(buf, format="PNG")
    return buf.getvalue()


def _gutters(white: list[float], parts: int, size: int) -> list[tuple[int, int]]:
    """The cell spans along one axis: the painted gutters (runs of mostly-white lines) found near each even split,
    falling back to the even split where no gutter is found (lab `run.py _gutters`)."""
    spans, start = [], 0
    for k in range(1, parts):
        even, reach = round(k * size / parts), max(size // (parts * 6), 1)
        band = [i for i in range(max(even - reach, 0), min(even + reach, size)) if white[i] > 0.85]
        if band:
            lo, hi = min(band), max(band)
            spans.append((start, lo))
            start = hi + 1
        else:
            spans.append((start, even))
            start = even
    spans.append((start, size))
    a, b = spans[0]
    while a < b and white[a] > 0.85:
        a += 1
    spans[0] = (a, b)
    a, b = spans[-1]
    while b > a and white[b - 1] > 0.85:
        b -= 1
    spans[-1] = (a, b)
    return spans


def _even_boxes(board_png: bytes, n: int) -> list[tuple[int, int, int, int]]:
    """The cut before plan/2026-11-22, kept as the fallback: the grid ASKED for (`grid_for(n)`), each line at the
    painted gutter near its even split, else at the even split itself."""
    im = _image(board_png)
    cols, rows = grid_for(n)
    w, h = im.size
    px = im.convert("L").load()
    xs_s, ys_s = range(0, w, 4), range(0, h, 4)
    row_white = [sum(px[x, y] > 230 for x in xs_s) / len(xs_s) for y in range(h)]
    col_white = [sum(px[x, y] > 230 for y in ys_s) / len(ys_s) for x in range(w)]
    ys, xs = _gutters(row_white, rows, h), _gutters(col_white, cols, w)
    boxes = []
    for i in range(n):
        r, c = divmod(i, cols)
        boxes.append((xs[c][0], ys[r][0], xs[c][1], ys[r][1]))
    return boxes


# ── the grid that was painted (plan/2026-11-22, ported unchanged from lab/board_grid/grid.py) ─────────────────
#
# The image model sometimes paints another grid than the one asked for (asked 3 across and 2 down, painted 3 and 3
# with a row of empty cells). Per axis: every THIN run of gutter-white lines away from the sheet's edge is a gutter (a
# wide one is an empty cell or a drawn white card). The grid is the number of parts k whose even splits, over the
# PAINTED extent, explain every gutter found, with the fewest splits left without a gutter; a tie goes to the grid
# asked for. A split with a gutter cuts at the gutter, one without at the even split (panels painted touching). Cells
# that are all white are empty cells, not panels. When the found grid holds fewer panels than shots, the grid asked
# for is cut as before (`_even_boxes`), and `cut_problems` judges it.

WHITE = 230  # a pixel this bright is gutter-white
LINE_WHITE = 0.85  # a line this white across the sheet is a gutter line
EMPTY = 0.97  # a cell (or part of a crop) this white is an empty cell: a drawn white card still has its outline
PURE_LINE = 0.99  # a line this white across a crop is a gutter running through it
SOME_PAINT = 0.30  # a part of a crop with at least this much non-white is painted
EMPTY_PART = 0.15  # an empty run this share of a crop's height or width is an empty cell inside it
MAX_PARTS = 6
THIN = 0.02  # a gutter is thin: at most this share of the sheet (painted gutters are 3-10 px of 1024-1536)

Box = tuple[int, int, int, int]
_Run = tuple[int, int]


def _white_lines(g: Any, box: Sequence[int], axis: str, step: int = 2) -> list[float]:
    """Per line (a row when axis is 'y', a column when 'x') inside `box`: the share of gutter-white pixels."""
    x0, y0, x1, y1 = (int(v) for v in box)
    px = g.load()
    if axis == "y":
        xs = range(x0, x1, step)
        return [sum(px[x, y] > WHITE for x in xs) / max(len(xs), 1) for y in range(y0, y1)]
    ys = range(y0, y1, step)
    return [sum(px[x, y] > WHITE for y in ys) / max(len(ys), 1) for x in range(x0, x1)]


def _runs(flags: Sequence[bool]) -> list[_Run]:
    out: list[_Run] = []
    start: int | None = None
    for i, f in enumerate([*flags, False]):
        if f and start is None:
            start = i
        elif not f and start is not None:
            out.append((start, i))
            start = None
    return out


def _axis(white: Sequence[float], asked: int) -> list[_Run]:
    """The spans of one axis (see the note above)."""
    size = len(white)
    runs = _runs([v > LINE_WHITE for v in white])
    margin = max(round(0.01 * size), 2)  # a white run this close to the sheet's edge is its margin, not a gutter
    lead = runs[0][1] if runs and runs[0][0] <= margin else 0
    tail = runs[-1][0] if runs and runs[-1][1] >= size - margin else size
    gutters = [(a, b) for a, b in runs if a > margin and b < size - margin and b - a <= max(THIN * size, 4)]

    extent = tail - lead  # the painted extent: white left under or beside the grid is not part of it

    def split(i: int, k: int) -> int:
        return lead + round(i * extent / k)

    def plan(k: int) -> tuple[int, list[_Run | None]] | None:
        reach = max(extent // (k * 6), 1)
        cuts: list[_Run | None] = []
        used: set[_Run] = set()
        for i in range(1, k):
            even = split(i, k)
            near = [g for g in gutters if g[0] - reach <= even <= g[1] + reach and g not in used]
            hit = min(near, key=lambda g: abs((g[0] + g[1]) / 2 - even)) if near else None
            if hit:
                used.add(hit)
            cuts.append(hit or None)
        if len(used) < len(gutters):
            return None  # a gutter this grid does not explain
        return sum(c is None for c in cuts), cuts

    best: tuple[tuple[int, bool], int, list[_Run | None]] | None = None
    for k in range(1, MAX_PARTS + 1):
        p = plan(k)
        if p is None:
            continue
        key = (p[0], k != asked)
        if best is None or key < best[0]:
            best = (key, k, p[1])
    cuts: list[_Run | None]
    if best is None:  # nothing explains every gutter: the cut of the grid asked for
        k = asked
        cuts = [None] * (k - 1)
    else:
        _, k, cuts = best
    spans: list[_Run] = []
    start = lead
    for i, c in enumerate(cuts, 1):
        if c:
            spans.append((start, c[0]))
            start = c[1]
        else:
            even = split(i, k)
            spans.append((start, even))
            start = even
    spans.append((start, tail))
    return spans


def white_share(im: Any, box: Sequence[int]) -> float:
    x0, y0, x1, y1 = (int(v) for v in box)
    crop_ = im.crop((x0, y0, x1, y1)).convert("L").resize((64, 64))
    data = list(crop_.getdata())
    return sum(v > WHITE for v in data) / len(data)


def found_grid(data: bytes, asked: tuple[int, int]) -> dict[str, Any]:
    """What is painted: its columns and rows, every cell's box, the non-empty cells in reading order (the panels)."""
    im = _image(data)
    g = im.convert("L")
    w, h = im.size
    ys = _axis(_white_lines(g, (0, 0, w, h), "y", 4), asked[1])
    xs = _axis(_white_lines(g, (0, 0, w, h), "x", 4), asked[0])
    cells = [(x0, y0, x1, y1) for (y0, y1) in ys for (x0, x1) in xs]
    panels = [c for c in cells if white_share(im, c) < EMPTY]
    return {"cols": len(xs), "rows": len(ys), "cells": cells, "panels": panels}


def _inside(g: Any, box: Sequence[int], axis: str) -> list[str]:
    """A gutter running through a crop: two painted parts in one crop, or an empty cell beside a painted part."""
    x0, y0, x1, y1 = (int(v) for v in box)
    m = max(round(0.03 * (x1 - x0 if axis == "y" else y1 - y0)), 1)  # skip the crop's own edges
    inner = (x0 + m, y0, x1 - m, y1) if axis == "y" else (x0, y0 + m, x1, y1 - m)
    lines = _white_lines(g, inner, axis, 1)
    size = len(lines)
    edge = max(round(0.03 * size), 1)
    thin = max(THIN * max(g.size), 4)
    pure = _runs([v > PURE_LINE for v in lines])
    word = "rows" if axis == "y" else "columns"
    # A wide white band at the crop's start or end, beside paint: the gutter ran straight into an empty cell.
    for a, b in pure:
        if (a <= edge or b >= size - edge) and (b - a) / size >= EMPTY_PART and (b - a) / size < 0.9:
            return [f"an empty cell inside the crop ({word})"]
    gaps = [r for r in pure if r[0] > edge and r[1] < size - edge and r[1] - r[0] <= thin]
    if not gaps:
        return []
    bounds = [0, *[v for r in gaps for v in r], size]
    parts = [(bounds[i], bounds[i + 1]) for i in range(0, len(bounds), 2)]
    painted = [p for p in parts if 1 - sum(lines[p[0]:p[1]]) / max(p[1] - p[0], 1) >= SOME_PAINT]
    empty = [p for p in parts if (p[1] - p[0]) / size >= EMPTY_PART
             and sum(lines[p[0]:p[1]]) / max(p[1] - p[0], 1) >= EMPTY]
    if len(painted) >= 2:
        return [f"two panels in one crop (a gutter across it, {word})"]
    if painted and empty:
        return [f"an empty cell inside the crop ({word})"]
    return []


def check(data: bytes, boxes: Sequence[Sequence[int]]) -> tuple[list[str], list[str]]:
    """(why these boxes are a bad CUT, why the panels are the wrong SHAPE for the sheet). The shape comes from the
    sheet itself: a tall sheet's panels should be tall, a wide one's wide. Only the cut fails a part (§3.2)."""
    im = _image(data)
    g = im.convert("L")
    w, h = im.size
    want = 9 / 16 if h > w else 16 / 9
    cut_: list[str] = []
    shape: list[str] = []
    for i, b in enumerate(boxes, 1):
        bw, bh = b[2] - b[0], b[3] - b[1]
        if white_share(im, b) >= EMPTY:
            cut_.append(f"panel {i} empty")
            continue
        cut_ += [f"panel {i}: {p}" for p in _inside(g, b, "y") + _inside(g, b, "x")]
        ratio = bw / max(bh, 1)
        if not (want / 1.5 <= ratio <= want * 1.5):
            shape.append(f"panel {i} {bw}x{bh}")
    return cut_, shape


def cut_problems(board_png: bytes, boxes: Sequence[Sequence[int]]) -> list[str]:
    """Why these boxes are a bad cut of this board: empty when every crop holds one panel and nothing else."""
    return check(board_png, boxes)[0]


def cell_boxes(board_png: bytes, n: int) -> list[Box]:
    """The box (x0, y0, x1, y1) of each of `n` panels, in reading order, from the grid that was PAINTED (see the note
    above); the grid asked for (`grid_for(n)`) only breaks ties, and is cut as before when too few panels are found."""
    found = found_grid(board_png, grid_for(n))
    if len(found["panels"]) >= n:
        return list(found["panels"][:n])
    return _even_boxes(board_png, n)


def draw_cut(board_png: bytes, boxes: Sequence[Sequence[int]], problems: Sequence[str]) -> bytes:
    """The board with the cut drawn on it (2026-11-24, to see why a part was rejected): each box outlined and
    numbered, red when a problem names its panel ("panel 3: ..."), green when it was fine."""
    from PIL import ImageDraw, ImageFont

    im = _image(board_png)
    draw = ImageDraw.Draw(im)
    bad = {int(m.group(1)) for p in problems if (m := re.match(r"panel (\d+)", p))}
    width = max(round(max(im.size) / 300), 3)
    try:
        font: Any = ImageFont.load_default(size=max(im.size) // 30)
    except TypeError:  # an older Pillow: no sized default font
        font = ImageFont.load_default()
    for i, b in enumerate(boxes, 1):
        x0, y0, x1, y1 = (int(v) for v in b)
        colour = "#e00000" if i in bad else "#00b050"
        draw.rectangle((x0, y0, x1 - 1, y1 - 1), outline=colour, width=width)
        draw.text((x0 + 2 * width, y0 + 2 * width), str(i), fill=colour, font=font, stroke_width=2,
                  stroke_fill="white")
    return _png(im)


def crop(board_png: bytes, box: Sequence[int]) -> bytes:
    x0, y0, x1, y1 = (int(v) for v in box)
    return _png(_image(board_png).crop((x0, y0, x1, y1)))


def paste(board_png: bytes, cells: Mapping[int, bytes], boxes: Mapping[int, Sequence[int]]) -> bytes:
    """The board with each `cells[i]` pasted back into `boxes[i]` (a locked panel kept through a whole repaint)."""
    im = _image(board_png)
    for i, data in cells.items():
        x0, y0, x1, y1 = (int(v) for v in boxes[i])
        im.paste(_image(data).resize((max(x1 - x0, 1), max(y1 - y0, 1))), (x0, y0))
    return _png(im)


def image_size(data: bytes) -> tuple[int, int]:
    size = _image(data).size
    return int(size[0]), int(size[1])


SHEET_TAG = "#c8102e"  # Hiru red, the code-drawn "SHOT N" tag
SHEET_BACK = "#1f1f1f"  # behind a cell whose shape is not the sheet's cell shape
SHEET_CELL = 768  # the longest side of a sheet cell: a panel painted alone (1024x1536) is drawn smaller


def _cell_size(sizes: Sequence[tuple[int, int]]) -> tuple[int, int]:
    """The sheet's cell: the smallest cell (a grid cut, when there is one), its longest side at most `SHEET_CELL`."""
    w, h = min(sizes, key=lambda s: s[0] * s[1])
    scale = min(1.0, SHEET_CELL / max(w, h))
    return max(round(w * scale), 1), max(round(h * scale), 1)


def scene_sheet(shots: Sequence[BoardShot], cells: Mapping[str, bytes], cell_size: tuple[int, int] | None = None
                ) -> bytes:
    """Every shot of the board, in order, on one numbered sheet: a painted shot's panel (`cells`: shot id → PNG) with
    a red "SHOT N" tag drawn by code, a black plate as a black cell carrying its script line (lab `scene_sheet`).
    Cells of different sizes (a cell cut from a grid beside a panel painted alone) are drawn at one size, each FIT
    inside it and centred, never stretched. The size: `cell_size`, else the smallest cell's (at most `SHEET_CELL`)."""
    from PIL import Image, ImageDraw, ImageFont

    sizes = [_image(cells[s.id]).size for s in shots if s.id in cells]
    cw, ch = cell_size or (_cell_size(sizes) if sizes else (384, 216))
    cols, rows = grid_for(len(shots))
    gap = 8
    sheet = Image.new("RGB", (cols * cw + (cols + 1) * gap, rows * ch + (rows + 1) * gap), "white")
    draw = ImageDraw.Draw(sheet)
    tag_px = max(18, ch // 12)
    tag_font = ImageFont.load_default(size=tag_px)
    text_font = ImageFont.load_default(size=max(14, ch // 18))
    for i, shot in enumerate(shots):
        r, c = divmod(i, cols)
        x, y = gap + c * (cw + gap), gap + r * (ch + gap)
        if shot.id in cells:
            pic = _image(cells[shot.id])
            scale = min(cw / pic.width, ch / pic.height)
            w, h = max(round(pic.width * scale), 1), max(round(pic.height * scale), 1)
            draw.rectangle((x, y, x + cw - 1, y + ch - 1), fill=SHEET_BACK)
            sheet.paste(pic.resize((w, h)), (x + (cw - w) // 2, y + (ch - h) // 2))
        else:
            draw.rectangle((x, y, x + cw - 1, y + ch - 1), fill="black")
            words, line, lines = shot.text.split(), "", []
            for w in words:
                if draw.textlength(f"{line} {w}".strip(), font=text_font) > cw - 40:
                    lines.append(line)
                    line = w
                else:
                    line = f"{line} {w}".strip()
            lines.append(line)
            draw.multiline_text((x + cw / 2, y + ch / 2), "\n".join(t for t in lines if t), font=text_font,
                                fill="#bbbbbb", anchor="mm", align="center")
        label = f"SHOT {shot.number}"
        tw = draw.textlength(label, font=tag_font)
        pad = 6
        draw.rectangle((x, y, x + tw + 2 * pad, y + tag_px + 2 * pad), fill=SHEET_TAG)
        draw.text((x + pad, y + pad), label, font=tag_font, fill="white")
    return _png(sheet)


def portrait_crop(sheet_png: bytes) -> bytes:
    """The portrait panel of a base character sheet (its right-hand 26.5 %), as PNG bytes."""
    from PIL import Image

    im = Image.open(io.BytesIO(sheet_png)).convert("RGB")
    w, h = im.size
    buf = io.BytesIO()
    im.crop((round(w * (1 - PORTRAIT_SHARE)), 0, w, h)).save(buf, format="PNG")
    return buf.getvalue()
