"""A PDF's text, page by page, with `/ActualText` honoured (plan/2026-11-15 phase 1). Mechanical: it decodes the
file and reads nothing in the story.

Two byte-identical copies, one per engine, as the extractor itself is kept (contracts must stay standalone, and a
function's zip carries only its own folder and contracts): `hiru_ai/steps/extract_text/pdf_text.py` and
`services/doc_ingest/doc_ingest/engine/pdf_text.py`; tests/contracts/test_pdf_text.py holds them equal.

Chrome/Skia and Word draw complex scripts as glyphs in VISUAL order and put the true Unicode in a marked-content span:

    /Span <</ActualText <FEFF0D9C0DDA>>> BDC  <glyphs>  EMC        -> "ගේ"

pypdf's `extract_text()` reads only the glyphs, so Sinhala came out with its vowel signs first and ligature letters lost
("ෙදන්නා" for "දෙන්නා"). Two engines read the span instead, and gave the same 301 lines and 313 Sinhala words on the
person's two scripts (lab/llm_reader, run5 and runs/readers):

  poppler  `pdftotext -enc UTF-8 -layout` (the person's choice, D7), when the program is on the PATH;
  walker   this module's content-stream walker over pypdf's own font maps: inside an ActualText span the span's text is
           written once in place of its glyphs; lines are rebuilt from the text positions. Pure Python, so it runs in a
           Cloud Run function built from source, where poppler cannot be installed.

`PDF_TEXT__ENGINE` = auto (poppler when present, else the walker) | poppler | walker. Every line's spacing is collapsed,
so both engines hand on the same lines.
"""

from __future__ import annotations

import io
import os
import shutil
import subprocess
import tempfile
from typing import Any, Literal

Engine = Literal["poppler", "walker"]
Matrix = tuple[float, float, float, float, float, float]
_ID: Matrix = (1.0, 0.0, 0.0, 1.0, 0.0, 0.0)
_SAME_LINE = 2.0  # points: fragments within this height of each other are one line
POPPLER_TIMEOUT_S = 120


def engine() -> Engine:
    """The engine to use: the setting, and for `auto` whether `pdftotext` is on the PATH."""
    want = os.environ.get("PDF_TEXT__ENGINE", "auto").strip().lower()
    if want == "walker":
        return "walker"
    if want == "poppler" or shutil.which("pdftotext"):
        return "poppler"
    return "walker"


def pages(data: bytes, *, use: Engine | None = None) -> list[list[str]]:
    """Each page's lines, in reading order, spacing collapsed, empty lines dropped. Raises what pypdf raises on a file
    it cannot read (the caller turns that into its own message)."""
    if (use or engine()) == "poppler":
        return _poppler(data)
    from pypdf import PdfReader

    reader = PdfReader(io.BytesIO(data))
    if reader.is_encrypted:
        reader.decrypt("")
    return [page_lines(p) for p in reader.pages]


def _poppler(data: bytes) -> list[list[str]]:
    exe = shutil.which("pdftotext")
    if exe is None:
        raise subprocess.SubprocessError("pdftotext is not installed")
    with tempfile.TemporaryDirectory() as tmp:
        src, out = os.path.join(tmp, "in.pdf"), os.path.join(tmp, "out.txt")
        with open(src, "wb") as f:
            f.write(data)
        # fixed arguments and our own temporary files: nothing from the document reaches the command line
        subprocess.run([exe, "-enc", "UTF-8", "-layout", src, out], check=True, capture_output=True,  # noqa: S603
                       timeout=POPPLER_TIMEOUT_S)
        with open(out, encoding="utf-8", errors="replace") as f:
            raw = f.read()
    chunks = raw.split("\f")
    if chunks and not chunks[-1].strip():
        chunks = chunks[:-1]  # pdftotext ends the last page with a form feed
    return [_collapse(c.split("\n")) for c in chunks]


def _collapse(lines: list[str]) -> list[str]:
    return [t for t in (" ".join(x.split()) for x in lines) if t]


# ── the walker ───────────────────────────────────────────────────────────────────────────────────────────────────


def _mul(a: Matrix, b: Matrix) -> Matrix:
    return (a[0] * b[0] + a[1] * b[2], a[0] * b[1] + a[1] * b[3], a[2] * b[0] + a[3] * b[2],
            a[2] * b[1] + a[3] * b[3], a[4] * b[0] + a[5] * b[2] + b[4], a[4] * b[1] + a[5] * b[3] + b[5])


def _actual(args: list[Any], props: Any) -> str | None:
    from pypdf.generic import DictionaryObject

    if len(args) < 2:
        return None
    d = args[1]
    if not isinstance(d, DictionaryObject) and props is not None:  # a named property list: /Span /MC0 BDC
        d = props.get(d)
        d = d.get_object() if d is not None else None
    if isinstance(d, DictionaryObject) and "/ActualText" in d:
        return str(d["/ActualText"])
    return None


def _decode(font: Any, raw: bytes) -> str:
    if font is None:
        return ""
    enc = font.encoding
    chars = raw.decode(enc, "surrogatepass") if isinstance(enc, str) else "".join(enc.get(b, chr(b)) for b in raw)
    return "".join(font.character_map.get(c, c) for c in chars)


def _bytes(s: Any) -> bytes:
    return bytes(s.original_bytes if hasattr(s, "original_bytes") else s)


def page_lines(page: Any) -> list[str]:
    """One page's lines (pypdf `PageObject`): glyph codes through the font's own map, an ActualText span's text in
    place of its glyphs, lines from the text positions."""
    from pypdf._font import Font  # pypdf 6.19's font maps (requirements pin it)
    from pypdf.generic import ContentStream

    res = page.get("/Resources") or {}
    fonts: dict[str, Any] = {}
    for name, ref in (res.get("/Font") or {}).items():
        try:
            fonts[str(name)] = Font.from_font_resource(ref.get_object())
        except Exception:  # a font pypdf cannot map: its glyphs give no text, as they would in extract_text
            fonts[str(name)] = None
    props = res.get("/Properties")
    frags: list[tuple[float, float, str]] = []
    ctm: Matrix = _ID
    saved: list[Matrix] = []
    tm: Matrix = _ID
    tlm: Matrix = _ID
    font: Any = None
    leading = 0.0
    spans: list[dict[str, Any]] = []

    def emit(text: str) -> None:
        span = next((s for s in reversed(spans) if s["text"] is not None), None)
        if span is not None:
            if span["done"]:
                return
            span["done"], text = True, span["text"]
        if text:
            m = _mul(tm, ctm)
            frags.append((round(m[5], 1), m[4], text))

    contents = page.get_contents()
    if contents is None:
        return []
    for args, op in ContentStream(contents, page.pdf).operations:
        if op == b"q":
            saved.append(ctm)
        elif op == b"Q" and saved:
            ctm = saved.pop()
        elif op == b"cm":
            ctm = _mul(tuple(float(a) for a in args), ctm)  # type: ignore[arg-type]
        elif op == b"BT":
            tm = tlm = _ID
        elif op == b"Tf":
            font = fonts.get(str(args[0]))
        elif op == b"TL":
            leading = float(args[0])
        elif op == b"Tm":
            tm = tlm = tuple(float(a) for a in args)  # type: ignore[assignment]
        elif op in (b"Td", b"TD"):
            if op == b"TD":
                leading = -float(args[1])
            tm = tlm = _mul((1.0, 0.0, 0.0, 1.0, float(args[0]), float(args[1])), tlm)
        elif op == b"T*":
            tm = tlm = _mul((1.0, 0.0, 0.0, 1.0, 0.0, -leading), tlm)
        elif op in (b"Tj", b"'", b'"'):
            if op != b"Tj":
                tm = tlm = _mul((1.0, 0.0, 0.0, 1.0, 0.0, -leading), tlm)
            emit(_decode(font, _bytes(args[-1])))
        elif op == b"TJ":
            emit("".join(_decode(font, _bytes(a)) for a in args[0] if not isinstance(a, (int, float))))
        elif op in (b"BDC", b"BMC"):
            spans.append({"text": _actual(args, props) if op == b"BDC" else None, "done": False})
        elif op == b"EMC" and spans:
            spans.pop()
    lines: list[list[tuple[float, str]]] = []
    ys: list[float] = []
    for y, x, t in sorted(frags, key=lambda f: (-f[0], f[1])):
        if ys and abs(ys[-1] - y) <= _SAME_LINE:
            lines[-1].append((x, t))
        else:
            ys.append(y)
            lines.append([(x, t)])
    return _collapse(["".join(t for _, t in sorted(parts, key=lambda p: p[0])) for parts in lines])
