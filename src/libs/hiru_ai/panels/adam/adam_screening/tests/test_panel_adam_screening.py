"""Tests that live with the adam_screening panel (ADR 0006)."""
from __future__ import annotations

from hiru_ai.panels.adam.adam_screening import graph


def test_it_compiles():
    assert graph.blank() is not None
