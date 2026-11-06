"""A part's code is imported once, whole, however many threads ask for it at the same moment (a function plans scenes in
parallel: the first call of every thread reaches the same agent)."""
from __future__ import annotations

import sys
import threading
from typing import Any

from hiru_ai.core.registry import default


def test_threads_asking_for_a_part_at_once_all_get_it_whole():
    registry = default()
    dotted = "hiru_ai.agents.adam.adam_take.agent"
    for name in [m for m in sys.modules if m == dotted]:
        del sys.modules[name]
    barrier, got, errors = threading.Barrier(8), [], []

    def ask() -> None:
        barrier.wait()
        try:
            got.append(hasattr(registry.module("agent", "adam_take", "agent"), "user_message"))
        except Exception as exc:
            errors.append(exc)

    threads: list[Any] = [threading.Thread(target=ask) for _ in range(8)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    assert not errors and got == [True] * 8
