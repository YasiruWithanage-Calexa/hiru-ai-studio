"""document_role: `{"filename": "ep1.fountain", "text": "INT. ..."}` → the rules' guess.

The model is the `role_classifier` agent's; this step is the free half. `ask_model` says whether to ask it.
"""
from __future__ import annotations

from typing import Any

from hiru_ai.steps.document_role.logic import LLM_THRESHOLD, detect_by_rules


def run(payload: dict[str, Any]) -> dict[str, Any]:
    guess = detect_by_rules(str(payload["filename"]), str(payload["text"]))
    return {"role": guess.role.value, "confidence": guess.confidence, "reason": guess.reason, "source": guess.source,
            "ask_model": guess.confidence < LLM_THRESHOLD}
