"""views_writer hooks (plan/2026-11-24). The person's method, proven in `lab/location_views`: ONE picture of a place
in six named views keeps the place the same in every board panel and first frame. This agent writes the six views from
what the production knows about the place; `contracts.canon.views_sheet_prompt` paints them. A person may edit the
views before painting, and then this agent is not called. No fallback: without a model nothing is painted.
"""
from __future__ import annotations

import json

from hiru_ai.agents.views_writer.schema import Input


def user_message(inp: Input) -> str:
    return f"<place>\n{json.dumps(inp.model_dump(), ensure_ascii=False, indent=1)}\n</place>\n\nWrite the six views."
