"""What a panel's `graph.py` needs to turn its manifest into a graph: the active members, and agents and steps by id.

A panel never imports an agent or a step module. It asks its kit for a member by name and runs it; the kit builds the
agent through the registry the first time, so removing a member from the YAML (or setting its agent to
`status: disabled`) removes it from the graph and nothing else changes. A member that fails (no key, a bad answer) is
`None`, never an exception: the panel degrades the way the engine it replaces did.
"""
from __future__ import annotations

import logging
from types import ModuleType
from typing import Any

from pydantic import BaseModel

from hiru_ai.core import agents, parts
from hiru_ai.core.context import RunContext
from hiru_ai.core.manifest import Member, PanelManifest, _ref
from hiru_ai.core.registry import Registry

_logger = logging.getLogger(__name__)


class PanelKit:
    def __init__(self, panel_id: str, ctx: RunContext | None = None, registry: Registry | None = None,
                 manifest: PanelManifest | None = None) -> None:
        self.registry = registry or parts._registry()
        found = manifest or self.registry.get("panel", panel_id).manifest
        if not isinstance(found, PanelManifest):  # pragma: no cover - the registry keys by kind
            raise TypeError(f"{panel_id} is not a panel")
        self.id, self.manifest, self.ctx = panel_id, found, ctx or RunContext()
        self._agents: dict[str, agents.Agent] = {}

    # ── members ─────────────────────────────────────────────────────────────────────────────

    def members(self) -> list[Member]:
        """The members whose agent is switched on, in manifest order."""
        out = []
        for member in self.manifest.members:
            comp = self.registry.components.get(("agent", member.agent))
            if comp is not None and comp.manifest.status != "disabled":
                out.append(member)
        return out

    def member(self, name: str) -> Member | None:
        return next((m for m in self.members() if m.label == name), None)

    def names(self) -> list[str]:
        return [m.label for m in self.members()]

    # ── running ─────────────────────────────────────────────────────────────────────────────

    def agent(self, ident: str) -> agents.Agent:
        if ident not in self._agents:
            self._agents[ident] = agents.build(ident, self.registry)
        return self._agents[ident]

    def ask(self, agent_id: str, inp: BaseModel | dict[str, Any]) -> Any | None:
        """The agent's Output, or None when it could not answer. The agent's own fallback (a manifest with
        `absent_safe`) answers first; this catches only what is left, so one failing member never stops the others."""
        try:
            return self.agent(agent_id).run(inp, self.ctx)
        except Exception:
            _logger.warning("panel %s: %s failed", self.id, agent_id, exc_info=True)
            return None

    def role(self, name: str) -> tuple[str, str]:
        """("agent", "scene_planner") for the panel's `reviser`, `writer`, `settle`... Raises if it is not set."""
        for role, ref in self.manifest.roles():
            if role == name:
                return ref
        raise KeyError(f"panel {self.id} has no {name!r}")

    def has(self, name: str) -> bool:
        return any(role == name for role, _ in self.manifest.roles())

    def step(self, ref: str, module: str = "logic") -> ModuleType:
        kind, ident = _ref(ref) if ":" in ref else ("step", ref)
        return parts.module(kind, ident, module)

    def advisors(self) -> list[str]:
        """Agent ids of the manifest's `review:` entries that are switched on."""
        out = []
        for ref in self.manifest.review:
            kind, ident = _ref(ref)
            comp = self.registry.components.get((kind, ident))
            if comp is not None and comp.manifest.status != "disabled":
                out.append(ident)
        return out
