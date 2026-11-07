"""reader_checks: the document reader's checks, JSON in, JSON out. The rules are `contracts.doc_read_quality` and
`contracts.doc_read_checks`, the same code the reader's run uses in both engines.

    {"op": "quality", "pages": ["...", ...]}                       -> {"mode": "text" | "pages", "corrupt_pages": [..]}
    {"op": "pieces", "text": "...", "role": "script"}              -> {"pieces": [{kind, first_page, ...}, ...]}
    {"op": "check", "text": "...", "role": "script", "piece": 0,
     "answer": {...PieceRead...}}                                  -> {"problems": ["...", ...]}
"""
from __future__ import annotations

from dataclasses import asdict
from typing import Any

from contracts.doc_read import PieceRead
from contracts.doc_read_checks import check_piece
from contracts.doc_read_quality import layout, pieces, quality
from contracts.screenplay import page_furniture


def run(payload: dict[str, Any]) -> dict[str, Any]:
    op = payload["op"]
    if op == "quality":
        found = quality(list(payload["pages"]))
        return {"mode": found.mode, "corrupt_pages": found.corrupt_pages}
    text = str(payload["text"])
    doc = layout(text)
    plan = pieces(doc, role=str(payload.get("role") or "script"))
    if op == "pieces":
        return {"pieces": [asdict(p) for p in plan]}
    if op == "check":
        mode = quality(text.split("\f")).mode
        piece = plan[int(payload.get("piece") or 0)]
        answer = PieceRead.model_validate(payload["answer"])
        return {"problems": [p.sentence for p in check_piece(answer, piece, doc, mode, page_furniture(text))]}
    raise ValueError(f"unknown op {op!r}")
