"""beat_finder hooks. Ported from `script_split/engine/beats.py` (`listing`).

The free rules in `contracts.beats` are the fallback and the validator: the system keeps the rules' reading for any
block this agent leaves out or gets wrong, so the picture clock never misses a block. A reading never rewrites a block.
"""
from __future__ import annotations

from hiru_ai.agents.beat_finder.schema import Input


def user_message(inp: Input) -> str:
    rows = []
    for i in inp.items:
        if i.is_line:
            who = f"{i.speaker}, {i.delivery}" if i.delivery else i.speaker
            rows.append(f"[{i.index}] DIALOGUE ({who}): {i.text}")
        else:
            rows.append(f"[{i.index}] {i.kind.upper()}: {i.text}")
    return "<script>\n" + "\n".join(rows) + "\n</script>"
