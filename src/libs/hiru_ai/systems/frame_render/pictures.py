"""The Scene board's pictures (plan/2026-11-14): Pillow work kept out of `contracts`, which stays standalone. Cut a
painted board along its gutters, paste a locked panel back, make the repaint mask, draw the numbered sheet, cut a base
sheet's portrait for a face sheet. Ported from the storyboard lab (`lab/storyboard/run.py`, `faces.py`)."""
from __future__ import annotations

import io
from collections.abc import Iterable, Mapping, Sequence
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


def cell_boxes(board_png: bytes, n: int) -> list[tuple[int, int, int, int]]:
    """The box (x0, y0, x1, y1) of each of `n` panels, in reading order, cut along the painted gutters."""
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


def repaint_mask(size: tuple[int, int], boxes: Iterable[Sequence[int]]) -> bytes:
    """D7 method A: a PNG the size of the board, opaque everywhere and fully transparent over `boxes` (the image
    model paints only where the mask is transparent)."""
    from PIL import Image, ImageDraw

    mask = Image.new("RGBA", size, (0, 0, 0, 255))
    draw = ImageDraw.Draw(mask)
    for x0, y0, x1, y1 in boxes:
        draw.rectangle((int(x0), int(y0), int(x1) - 1, int(y1) - 1), fill=(0, 0, 0, 0))
    return _png(mask)


def image_size(data: bytes) -> tuple[int, int]:
    size = _image(data).size
    return int(size[0]), int(size[1])


SHEET_TAG = "#c8102e"  # Hiru red, the code-drawn "SHOT N" tag


def scene_sheet(shots: Sequence[BoardShot], cells: Mapping[str, bytes], cell_size: tuple[int, int] | None = None
                ) -> bytes:
    """Every shot of the board, in order, on one numbered sheet: a painted shot's panel (`cells`: shot id → PNG) with
    a red "SHOT N" tag drawn by code, a black plate as a black cell carrying its script line (lab `scene_sheet`)."""
    from PIL import Image, ImageDraw, ImageFont

    first = next((cells[s.id] for s in shots if s.id in cells), None)
    cw, ch = cell_size or (_image(first).size if first else (384, 216))
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
            sheet.paste(_image(cells[shot.id]).resize((cw, ch)), (x, y))
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
