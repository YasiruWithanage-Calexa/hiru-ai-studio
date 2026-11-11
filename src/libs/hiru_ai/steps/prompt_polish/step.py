"""prompt_polish: the code around the `prompt_writer` agent. JSON in, JSON out, no model (`contracts.prompt_polish`).

    {"op": "request", "kind": "first_frame" | "video", "sections": [{key, title, text}], "names": [...]}
        -> {"request": {kind, sections: [{key, title, text, keep}]}}      (only the sections the writer may reword)
    {"op": "merge", "request": {...}, "answer": {"sections": [{key, text}]}}
        -> {"texts": {key: text}, "kept_code": {key: why}, "checks": [{label, tone}], "record": {key: {stamp, text}}}

A system with a prompt in sections asks for the request, sends it to the agent if it has any section, and merges the
answer: `texts` are the sections to replace, `record` is what a first frame stores on its shot (`design.frame_polish`).
"""
from __future__ import annotations

from typing import Any

from contracts import prompt_polish as pp


def run(payload: dict[str, Any]) -> dict[str, Any]:
    op = payload["op"]
    if op == "request":
        req = pp.request(payload["kind"], payload.get("sections") or [], payload.get("names") or [])
        return {"request": req.model_dump()}
    if op == "merge":
        req = pp.Request.model_validate(payload["request"])
        answer = {str(s.get("key")): str(s.get("text") or "")
                  for s in (payload.get("answer") or {}).get("sections") or [] if isinstance(s, dict)}
        merged = pp.merge(req, answer)
        titles = {s.key: s.title for s in req.sections}
        return {"texts": merged.texts, "kept_code": merged.kept_code, "checks": pp.report(merged, titles),
                "record": pp.frame_record(req, merged)}
    raise ValueError(f"unknown op {op!r}")
