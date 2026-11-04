"""Reach another part by id, never by import.

Two steps of the same layer may not import each other (an import-linter contract), but a few of them really do
build on one another: the scene kernel words its refusals with the refusal screen, the serializer reads the feeling
step. Such a part names the other in its manifest (`uses: [refusal_screen]`, so `validate` and `remove` see the
link) and asks for its code here. The other part is imported the first time it is asked for, like any other.
"""
from __future__ import annotations

from functools import lru_cache
from types import ModuleType

from hiru_ai.core.registry import Registry


@lru_cache(maxsize=1)
def _registry() -> Registry:
    return Registry().discover()


def module(kind: str, ident: str, name: str = "logic") -> ModuleType:
    """`<part>/<name>.py` of an active part. A disabled or missing part raises `UnknownComponent`."""
    registry = _registry()
    registry.get(kind, ident)  # refuses a disabled part
    return registry.module(kind, ident, name)


def step(ident: str, name: str = "logic") -> ModuleType:
    return module("step", ident, name)
