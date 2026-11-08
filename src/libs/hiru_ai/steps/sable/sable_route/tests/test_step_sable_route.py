"""sable_route (plan/2026-11-08 Phase 2): the closed rule list, table-driven."""
from __future__ import annotations

import pytest

from hiru_ai.steps.sable.sable_route import step

CASES = [
    ("What did we decide about Nimal's costume?", 0, "sable", ""),
    ("Which scenes in episode 3 still have no shots?", 0, "sable", ""),
    ("Does S04 in E1S2 overrun?", 0, "sable", ""),
    ("Why is the opening shot a wide?", 0, "sable", ""),
    ("Think carefully: is the coverage of E1S2 enough?", 0, "sable_deep", "asked_for_depth"),
    ("Compare E1S2 with E1S3", 0, "sable_deep", "asked_for_depth"),
    ("Review the whole episode 2 for continuity", 0, "sable_deep", "asked_for_depth"),
    ("What happens in every scene of episode 2?", 0, "sable_deep", "whole_episode"),
    ("Check E1S2, E1S3 and E2S1 for the timing", 0, "sable_deep", "many_scenes"),
    ("Check E1S2 and e1s2 again", 0, "sable", ""),  # the same scene twice is one scene
    ("Look at this", 1, "sable_deep", "attachment"),
    ("word " * 601, 0, "sable_deep", "long_message"),
    ("", 0, "sable", ""),
]


@pytest.mark.parametrize(("message", "attachments", "tier", "rule"), CASES)
def test_the_rules(message, attachments, tier, rule):
    assert step.run({"message": message, "attachments": attachments}) == {"tier": tier, "rule": rule}


def test_the_rule_list_is_closed_and_named():
    assert [name for name, _ in step.RULES] == ["attachment", "long_message", "asked_for_depth", "whole_episode",
                                                "many_scenes"]
