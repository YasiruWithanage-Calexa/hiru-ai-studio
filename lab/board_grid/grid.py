"""The lab's cutter: find the grid that is REALLY painted, not only the one that was asked for (fix 2), and the checks
that say a cut is bad (fix 3). Pure Pillow; nothing under `src/` changes.

The product's `pictures.cell_boxes` looks for a gutter only within size/(parts*6) of each even split of the grid it
ASKED for, and silently falls back to the even split. A board painted in another grid is then cut through its panels.

Here, per axis: every THIN interior run of gutter-white lines is a gutter (a wide one is an empty cell or a drawn
white card). The grid is the number of parts k whose even
splits explain every gutter found (each gutter within the product's reach of a split), with the fewest splits left
without a gutter; a tie goes to the grid asked for. A split with a gutter cuts at the gutter, one without at the even
split (the product's fallback, for panels painted touching). Cells that are all white are empty cells, not panels.
When the found grid holds fewer panels than shots, the asked grid is cut as the product does, and the checks judge it.
"""
from __future__ import annotations

import io
from collections.abc import Sequence
from typing import Any

WHITE = 230  # a pixel this bright is gutter-white (the product's value)
LINE_WHITE = 0.85  # a line this white across the sheet is a gutter line (the product's value)
EMPTY = 0.97  # a cell (or part of a crop) this white is an empty cell: a drawn white card still has its outline
PURE_LINE = 0.99  # a line this white across a crop is a gutter running through it
SOME_PAINT = 0.30  # a part of a crop with at least this much non-white is painted
EMPTY_PART = 0.15  # an empty run this share of a crop's height or width is an empty cell inside it
MAX_PARTS = 6
THIN = 0.02  # a gutter is thin: at most this share of the sheet (painted gutters are 3-10 px of 1024-1536)


def image(data: bytes) -> Any:
    from PIL import Image

    return Image.open(io.BytesIO(data)).convert("RGB")


def _white_lines(g: Any, box: Sequence[int], axis: str, step: int = 2) -> list[float]:
    """Per line (a row when axis is 'y', a column when 'x') inside `box`: the share of gutter-white pixels."""
    x0, y0, x1, y1 = (int(v) for v in box)
    px = g.load()
    if axis == "y":
        xs = range(x0, x1, step)
        return [sum(px[x, y] > WHITE for x in xs) / max(len(xs), 1) for y in range(y0, y1)]
    ys = range(y0, y1, step)
    return [sum(px[x, y] > WHITE for y in ys) / max(len(ys), 1) for x in range(x0, x1)]


def _runs(flags: Sequence[bool]) -> list[tuple[int, int]]:
    out, start = [], None
    for i, f in enumerate([*flags, False]):
        if f and start is None:
            start = i
        elif not f and start is not None:
            out.append((start, i))
            start = None
    return out


def _axis(white: Sequence[float], asked: int) -> list[tuple[int, int]]:
    """The spans of one axis (see the module note)."""
    size = len(white)
    runs = _runs([v > LINE_WHITE for v in white])
    margin = max(round(0.01 * size), 2)  # a white run this close to the sheet's edge is its margin, not a gutter
    lead = runs[0][1] if runs and runs[0][0] <= margin else 0
    tail = runs[-1][0] if runs and runs[-1][1] >= size - margin else size
    gutters = [(a, b) for a, b in runs if a > margin and b < size - margin and b - a <= max(THIN * size, 4)]

    extent = tail - lead  # the painted extent: white left under or beside the grid is not part of it

    def split(i: int, k: int) -> int:
        return lead + round(i * extent / k)

    def plan(k: int) -> tuple[int, list[tuple[int, int] | None]] | None:
        reach = max(extent // (k * 6), 1)
        cuts: list[tuple[int, int] | None] = []
        used = set()
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

    best = None
    for k in range(1, MAX_PARTS + 1):
        p = plan(k)
        if p is None:
            continue
        key = (p[0], k != asked)
        if best is None or key < best[0]:
            best = (key, k, p[1])
    if best is None:  # nothing explains every gutter: the product's cut of the grid asked for
        k = asked
        cuts = [None] * (k - 1)
    else:
        _, k, cuts = best
    spans, start = [], lead
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
    crop = im.crop(tuple(int(v) for v in box)).convert("L").resize((64, 64))
    data = list(crop.getdata())
    return sum(v > WHITE for v in data) / len(data)


def found_grid(data: bytes, asked: tuple[int, int]) -> dict[str, Any]:
    """What is painted: its columns and rows, every cell's box, the non-empty cells in reading order (the panels)."""
    im = image(data)
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
    """Fix 3: (why these boxes are a bad CUT, why the panels are the wrong SHAPE for the sheet). The shape comes from
    the sheet itself: a tall sheet's panels should be tall, a wide one's wide."""
    im = image(data)
    g = im.convert("L")
    w, h = im.size
    want = 9 / 16 if h > w else 16 / 9
    cut, shape = [], []
    for i, b in enumerate(boxes, 1):
        bw, bh = b[2] - b[0], b[3] - b[1]
        if white_share(im, b) >= EMPTY:
            cut.append(f"panel {i} empty")
            continue
        cut += [f"panel {i}: {p}" for p in _inside(g, b, "y") + _inside(g, b, "x")]
        ratio = bw / max(bh, 1)
        if not (want / 1.5 <= ratio <= want * 1.5):
            shape.append(f"panel {i} {bw}x{bh}")
    return cut, shape


def cut(data: bytes, n: int, asked: tuple[int, int]) -> tuple[list[tuple[int, int, int, int]], str]:
    """Fix 2: the boxes of `n` panels from the grid really painted. → (boxes, '' or how it was cut)."""
    g = found_grid(data, asked)
    if len(g["panels"]) >= n:
        return list(g["panels"][:n]), f"{g['cols']}x{g['rows']}"
    from hiru_ai.systems.frame_render import pictures as pics

    return [tuple(b) for b in pics.cell_boxes(data, n)], (
        f"found {len(g['panels'])} panels in {g['cols']}x{g['rows']}; cut as asked")


def crop(data: bytes, box: Sequence[int]) -> bytes:
    buf = io.BytesIO()
    image(data).crop(tuple(int(v) for v in box)).save(buf, format="PNG")
    return buf.getvalue()


def contact(data: bytes, boxes: Sequence[Sequence[int]], height: int = 240) -> bytes:
    """The crops side by side, so a person sees at a glance what each shot would get."""
    from PIL import Image

    im = image(data)
    crops = [im.crop(tuple(int(v) for v in b)) for b in boxes]
    crops = [c.resize((max(round(c.width * height / c.height), 1), height)) for c in crops]
    sheet = Image.new("RGB", (sum(c.width for c in crops) + 6 * (len(crops) + 1), height + 12), "#808080")
    x = 6
    for c in crops:
        sheet.paste(c, (x, 6))
        x += c.width + 6
    buf = io.BytesIO()
    sheet.save(buf, format="PNG")
    return buf.getvalue()
