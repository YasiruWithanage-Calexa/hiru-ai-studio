"""PDF text that honours /ActualText (free, no model). A prototype for doc_ingest.engine.extract.

Chrome/Skia (and Word) draw complex scripts as glyphs in VISUAL order and put the true Unicode in a marked-content span:
    /Span <</ActualText <FEFF0D9C0DDA>>> BDC  <glyphs>  EMC        -> "ගේ"
pypdf's `extract_text()` reads only the glyphs (it collects text and hands it over at ET, after the span has closed), so
Sinhala comes out with vowel signs first and letters lost. This walks the content stream itself: glyph codes go through
the font's own character map (pypdf's `Font`), except inside an ActualText span, where the span's text is written once
in place of its glyphs. Lines are rebuilt from the text positions. Nothing here reads the story: it decodes the file.

    python lab/llm_reader/actualtext.py <file.pdf> <out.txt>
"""

from __future__ import annotations

import sys
from typing import Any

from pypdf import PdfReader
from pypdf._font import Font
from pypdf.generic import ContentStream, DictionaryObject

Matrix = tuple[float, float, float, float, float, float]
ID: Matrix = (1, 0, 0, 1, 0, 0)


def mul(a: Matrix, b: Matrix) -> Matrix:
    return (a[0] * b[0] + a[1] * b[2], a[0] * b[1] + a[1] * b[3], a[2] * b[0] + a[3] * b[2],
            a[2] * b[1] + a[3] * b[3], a[4] * b[0] + a[5] * b[2] + b[4], a[4] * b[1] + a[5] * b[3] + b[5])


def _actual(args: list[Any], props: Any) -> str | None:
    if len(args) < 2:
        return None
    d = args[1]
    if not isinstance(d, DictionaryObject) and props is not None:  # a named property list: /Span /MC0 BDC
        d = props.get(d)
        d = d.get_object() if d is not None else None
    if isinstance(d, DictionaryObject) and "/ActualText" in d:
        return str(d["/ActualText"])
    return None


def _decode(font: Font | None, raw: bytes) -> str:
    if font is None:
        return ""
    enc = font.encoding
    chars = raw.decode(enc, "surrogatepass") if isinstance(enc, str) else "".join(enc.get(b, chr(b)) for b in raw)
    return "".join(font.character_map.get(c, c) for c in chars)


def page_text(page: Any) -> str:
    res = page["/Resources"]
    fonts = {str(n): Font.from_font_resource(f.get_object()) for n, f in (res.get("/Font") or {}).items()}
    props = res.get("/Properties")
    frags: list[tuple[float, float, str]] = []
    ctm, stack_q = ID, []
    tm = tlm = ID
    font: Font | None = None
    leading = 0.0
    spans: list[dict[str, Any]] = []

    def emit(text: str) -> None:
        span = next((s for s in reversed(spans) if s["text"] is not None), None)
        if span is not None:
            if span["done"]:
                return
            span["done"], text = True, span["text"]
        if text:
            m = mul(tm, ctm)
            frags.append((round(m[5], 1), m[4], text))

    for args, op in ContentStream(page.get_contents(), page.pdf).operations:
        if op == b"q":
            stack_q.append(ctm)
        elif op == b"Q" and stack_q:
            ctm = stack_q.pop()
        elif op == b"cm":
            ctm = mul(tuple(float(a) for a in args), ctm)  # type: ignore[arg-type]
        elif op == b"BT":
            tm = tlm = ID
        elif op == b"Tf":
            font = fonts.get(str(args[0]))
        elif op == b"TL":
            leading = float(args[0])
        elif op == b"Tm":
            tm = tlm = tuple(float(a) for a in args)  # type: ignore[assignment]
        elif op in (b"Td", b"TD"):
            if op == b"TD":
                leading = -float(args[1])
            tm = tlm = mul((1, 0, 0, 1, float(args[0]), float(args[1])), tlm)
        elif op == b"T*":
            tm = tlm = mul((1, 0, 0, 1, 0, -leading), tlm)
        elif op in (b"Tj", b"'", b'"'):
            if op != b"Tj":
                tm = tlm = mul((1, 0, 0, 1, 0, -leading), tlm)
            emit(_decode(font, bytes(args[-1].original_bytes if hasattr(args[-1], "original_bytes") else args[-1])))
        elif op == b"TJ":
            emit("".join(_decode(font, bytes(a.original_bytes if hasattr(a, "original_bytes") else a))
                         for a in args[0] if not isinstance(a, (int, float)) and hasattr(a, "__len__")))
        elif op in (b"BDC", b"BMC"):
            spans.append({"text": _actual(args, props) if op == b"BDC" else None, "done": False})
        elif op == b"EMC" and spans:
            spans.pop()
    lines: list[list[tuple[float, str]]] = []
    ys: list[float] = []
    for y, x, t in sorted(frags, key=lambda f: (-f[0], f[1])):
        if ys and abs(ys[-1] - y) <= 2.0:
            lines[-1].append((x, t))
        else:
            ys.append(y)
            lines.append([(x, t)])
    out = [" ".join("".join(t for _, t in sorted(parts, key=lambda p: p[0])).split()) for parts in lines]
    return "\n".join(ln for ln in out if ln)


def main() -> None:
    reader = PdfReader(sys.argv[1])
    with open(sys.argv[2], "w", encoding="utf-8") as f:
        f.write("\n\f\n".join(page_text(p) for p in reader.pages) + "\n")


if __name__ == "__main__":
    main()
