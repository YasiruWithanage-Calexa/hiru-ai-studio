"""The registry: every part is found by id, never by importing a sibling.

`Registry.discover()` reads each `component.yaml` under the layer folders (agents/, tools/, ...), and under a GROUP
folder inside a layer (`agents/adam/`, marked by a `group.yaml`; plan/2026-11-04b §5.0). Code asks for
`registry.get("agent", "translator")`; a part's own code is imported lazily, the first time `module()` is asked
for it, so a cold start only loads what a run uses.

`validate()` is the check behind `hiru-ai validate`: ids resolve, no active part names a disabled or missing one,
schemas import, prompts and eval cases exist, dialogue writers are approved, and the references have no cycle.
"""
from __future__ import annotations

import importlib
import importlib.util
import os
import re
import sys
from dataclasses import dataclass, fields
from pathlib import Path
from types import ModuleType
from typing import Any

import yaml
from pydantic import BaseModel

from contracts.memory import topic_key
from hiru_ai.core import manifest as mf
from hiru_ai.core.context import Ports
from hiru_ai.core.errors import ManifestError, UnknownComponent
from hiru_ai.core.middleware import ALL_NAMES as MIDDLEWARE
from hiru_ai.core.middleware import REACT_NAMES
from hiru_ai.core.models import tier_names

PACKAGE_ROOT = Path(__file__).resolve().parents[1]

# The only parts that may change a spoken line (CLAUDE.md: "No other agent writes a line"). Adding one is a
# deliberate edit of this set, reviewed as a change to that rule.
DIALOGUE_WRITERS = frozenset({"translator"})

# a tool's `guide` must say when NOT to use it (plan/2026-11-04 §4.7)
GUIDE_NOT_USE = re.compile(r"\b(do not use|don't use|not for)\b", re.IGNORECASE)

Key = tuple[str, str]  # (kind, id)


def _subfolders(layer: Path) -> list[Path]:
    """The folders a layer or a group holds, in a fixed order; `__pycache__` and dot folders are not parts."""
    if not layer.is_dir():
        return []
    return sorted(p for p in layer.iterdir() if p.is_dir() and not p.name.startswith(("_", ".")))
PORT_NAMES = tuple(f.name for f in fields(Ports))  # what a tool's `ports:` may name


@dataclass(frozen=True)
class Component:
    manifest: mf.Manifest
    folder: Path
    package: str  # dotted import path of the folder, e.g. "hiru_ai.agents.translator"
    group: str = ""  # the group folder it lives in ("adam"), or "" for a part directly in its layer

    @property
    def key(self) -> Key:
        return (self.manifest.kind, self.manifest.id)


@dataclass(frozen=True)
class Problem:
    where: str
    message: str
    level: str = "error"  # error | warning

    def __str__(self) -> str:
        return f"{self.level}: {self.where}: {self.message}"


class Registry:
    def __init__(self, root: Path = PACKAGE_ROOT, package: str = "hiru_ai") -> None:
        self.root = root
        self.package = package
        self.components: dict[Key, Component] = {}
        self.errors: list[Problem] = []  # unreadable manifests and duplicate ids found by discover()
        self.groups: dict[tuple[str, str], mf.GroupManifest] = {}  # (layer folder, group id) → its group.yaml

    # ── discovery ───────────────────────────────────────────────────────────────────────────

    def discover(self) -> Registry:
        self.components, self.errors, self.groups = {}, [], {}
        for kind, layer in mf.LAYERS.items():
            for folder in _subfolders(self.root / layer):
                if (folder / "component.yaml").is_file():
                    if (folder / "group.yaml").is_file():
                        self.errors.append(Problem(str(folder), "has both component.yaml and group.yaml: "
                                                                "a folder is a part or a group, not both"))
                        continue
                    self._add(kind, layer, folder, group=None)
                elif (folder / "group.yaml").is_file():
                    self._add_group(kind, layer, folder)
                else:
                    self.errors.append(Problem(str(folder), "has neither component.yaml (a part) nor group.yaml "
                                                            "(a group of parts): a stray or misspelt folder"))
        self._overlay()
        return self

    def _add_group(self, kind: str, layer: str, folder: Path) -> None:
        try:
            group = mf.load_group(folder / "group.yaml")
        except ManifestError as exc:
            self.errors.append(Problem(str(folder / "group.yaml"), str(exc)))
            return
        if group.id != folder.name:
            self.errors.append(Problem(str(folder / "group.yaml"), f"id {group.id!r} must equal the folder name"))
            return
        self.groups[(layer, group.id)] = group
        for sub in _subfolders(folder):
            if (sub / "component.yaml").is_file():
                self._add(kind, layer, sub, group=group)
            elif (sub / "group.yaml").is_file():
                self.errors.append(Problem(str(sub), "a group holds parts, not another group"))
            else:
                self.errors.append(Problem(str(sub), "has no component.yaml: a stray or misspelt folder in the "
                                                     f"{group.id} group"))

    def _add(self, kind: str, layer: str, folder: Path, group: mf.GroupManifest | None) -> None:
        path = folder / "component.yaml"
        try:
            manifest = mf.load(path)
        except ManifestError as exc:
            self.errors.append(Problem(str(path), str(exc)))
            return
        if manifest.kind != kind:
            self.errors.append(Problem(str(path), f"kind {manifest.kind!r} does not belong in {layer}/"))
            return
        if manifest.id != folder.name:
            self.errors.append(Problem(str(path), f"id {manifest.id!r} must equal the folder name"))
            return
        if (kind, manifest.id) in self.components:
            self.errors.append(Problem(str(path), f"{kind} {manifest.id!r} is already defined in "
                                                  f"{self.components[(kind, manifest.id)].folder}"))
            return
        if group is not None and group.status == "disabled":  # a switched-off group switches off its parts
            manifest = manifest.model_copy(update={"status": "disabled"})
        dotted = f"{self.package}.{layer}.{group.id + '.' if group else ''}{folder.name}"
        self.components[(kind, manifest.id)] = Component(manifest, folder, dotted, group.id if group else "")

    def _overlay(self) -> None:
        """`HIRU_AI__DISABLE=agent:advisor,tool:x` switches parts off for this environment without editing a manifest
        (a disabled part is left out of its panels and refused by `get`; `validate` says who still names it). An id that
        names nothing is a problem, not a silent no-op: a typo must not look like it worked."""
        for entry in (e.strip() for e in os.environ.get("HIRU_AI__DISABLE", "").split(",") if e.strip()):
            kind, _, ident = entry.partition(":")
            comp = self.components.get((kind, ident))
            if comp is None:
                self.errors.append(Problem("HIRU_AI__DISABLE", f"{entry!r} names no part"))
                continue
            self.components[(kind, ident)] = Component(comp.manifest.model_copy(update={"status": "disabled"}),
                                                       comp.folder, comp.package, comp.group)

    # ── lookup ──────────────────────────────────────────────────────────────────────────────

    def get(self, kind: str, ident: str, *, include_disabled: bool = False) -> Component:
        comp = self.components.get((kind, ident))
        if comp is None or (comp.manifest.status == "disabled" and not include_disabled):
            raise UnknownComponent(f"no {'active ' if comp is None else ''}{kind} {ident!r}")
        return comp

    def ids(self, kind: str, *, include_disabled: bool = False) -> list[str]:
        return [i for (k, i), c in self.components.items()
                if k == kind and (include_disabled or c.manifest.status != "disabled")]

    def refs_to(self, kind: str, ident: str) -> list[Key]:
        """Every part that names this one (what `hiru-ai remove` must clean up)."""
        return [key for key, c in self.components.items() if (kind, ident) in c.manifest.refs()]

    # ── lazy code ───────────────────────────────────────────────────────────────────────────

    def module(self, kind: str, ident: str, name: str) -> ModuleType:
        """Import `<part>/<name>.py` the first time it is asked for."""
        comp = self.get(kind, ident, include_disabled=True)
        dotted = f"{comp.package}.{name}"
        if self.root == PACKAGE_ROOT:
            # Always through the import system, which holds the module's lock: a function plans scenes in several
            # threads, and a thread that finds a module another thread is still executing in `sys.modules` would be
            # handed it half built ("partially initialized module ... has no attribute 'user_message'").
            return importlib.import_module(dotted)
        if dotted in sys.modules:
            return sys.modules[dotted]
        path = comp.folder / f"{name}.py"  # a registry over another folder (tests, the CLI scaffold check)
        spec = importlib.util.spec_from_file_location(dotted, path)
        if spec is None or spec.loader is None:
            raise ManifestError(f"cannot load {path}")
        mod = importlib.util.module_from_spec(spec)
        sys.modules[dotted] = mod
        spec.loader.exec_module(mod)
        return mod

    def resolve(self, kind: str, ident: str, ref: str) -> Any:
        """"schema:Input" (or "<id>.schema:Input") → the object, imported from the part's folder."""
        module, _, attr = ref.partition(":")
        module = module.removeprefix(f"{ident}.")
        if not module or not attr:
            raise ManifestError(f"{kind} {ident}: {ref!r} is not 'module:name'")
        try:
            return getattr(self.module(kind, ident, module), attr)
        except (ImportError, AttributeError, SyntaxError, FileNotFoundError) as exc:
            raise ManifestError(f"{kind} {ident}: cannot resolve {ref!r}: {exc}") from exc

    # ── validate ────────────────────────────────────────────────────────────────────────────

    def validate(self, *, imports: bool = True) -> list[Problem]:
        out = list(self.errors)
        for key, comp in sorted(self.components.items()):
            out += self._check(key, comp, imports)
        out += self._cycles()
        return out

    def _check(self, key: Key, comp: Component, imports: bool) -> list[Problem]:
        kind, ident = key
        m = comp.manifest
        where = f"{kind} {ident}"
        out: list[Problem] = self._check_group(where, comp)
        # A panel's member that is switched off is left out of the graph: that is the point of `status: disabled`.
        left_out = {("agent", x.agent) for x in m.members} if isinstance(m, mf.PanelManifest) else set()
        for ref_kind, ref_id in m.refs():
            target = self.components.get((ref_kind, ref_id))
            if target is None:
                out.append(Problem(where, f"names {ref_kind} {ref_id!r}, which does not exist"))
            elif target.manifest.status == "disabled" and m.status != "disabled":
                level = "warning" if (ref_kind, ref_id) in left_out else "error"
                suffix = "; the panel runs without it" if level == "warning" else ""
                out.append(Problem(where, f"names {ref_kind} {ref_id!r}, which is disabled{suffix}", level))
        if isinstance(m, mf.AgentManifest):
            out += self._check_agent(where, comp, m, imports)
        elif isinstance(m, mf.ToolManifest | mf.StepManifest):
            out += self._check_entry(where, comp, m.entry, imports)
            if isinstance(m, mf.ToolManifest) and (stray := [n for n in m.ports if n not in PORT_NAMES]):
                out.append(Problem(where, f"ports {', '.join(stray)} are not run ports ({', '.join(PORT_NAMES)})"))
            if isinstance(m, mf.ToolManifest):
                out += self._check_tool(where, comp, m)
        elif isinstance(m, mf.KnowledgeBaseManifest):
            out += self._check_knowledge_base(where, comp, m, imports)
        elif isinstance(m, mf.PanelManifest):
            out += self._check_panel(where, comp, m, imports)
        elif isinstance(m, mf.SystemManifest):
            out += self._check_system(where, comp, m, imports)
        return out

    def group_ids(self) -> set[str]:
        return {group for _, group in self.groups}

    def _check_group(self, where: str, comp: Component) -> list[Problem]:
        """The rules that keep a group apart (plan/2026-11-04b §5.0): ids carry the group's prefix (so one never
        collides with an existing part), a grouped part names only parts of its own group, and nothing outside a
        group names one inside it."""
        out: list[Problem] = []
        m = comp.manifest
        if comp.group and not m.id.startswith(f"{comp.group}_"):
            out.append(Problem(where, f"is in the {comp.group} group, so its id must start with '{comp.group}_'"))
        for other in sorted(self.group_ids() - {comp.group}):
            if m.id.startswith(f"{other}_"):
                out.append(Problem(where, f"its id starts with '{other}_', which only parts of the {other} group "
                                          f"carry: put it in <layer>/{other}/ or rename it"))
        layer = mf.LAYERS.get(m.kind, "")
        shared = set(self.groups[(layer, comp.group)].shared) if (layer, comp.group) in self.groups else set()
        for ref_kind, ref_id in m.refs():
            target = self.components.get((ref_kind, ref_id))
            if target is None or target.group == comp.group:
                continue
            if comp.group and not target.group and ref_id in shared:
                continue  # an ungrouped part the group's group.yaml says it shares (plan/2026-11-08 §4.3)
            if comp.group:
                out.append(Problem(where, f"names {ref_kind} {ref_id!r}, which is outside the {comp.group} group: a "
                                          "grouped part names only its own group (copy what it needs into the group, "
                                          "with an ORIGIN.md)"))
            else:
                out.append(Problem(where, f"names {ref_kind} {ref_id!r}, which belongs to the {target.group} group: "
                                          "nothing outside a group names a part inside it"))
        return out

    def _check_tool(self, where: str, comp: Component, m: mf.ToolManifest) -> list[Problem]:
        """The tool contract (plan/2026-11-04 §4): a unique id, a guide that says when NOT to use it, examples that
        exist, and a `stage` tool that can reach the staging port."""
        out: list[Problem] = []
        for other in mf.KINDS:
            if other != "tool" and (other, m.id) in self.components:
                out.append(Problem(where, f"its id is also {other} {m.id!r}; ids are unique across kinds "
                                          "(a tool never takes the id of the step it wraps)"))
        if not m.guide.strip():
            out.append(Problem(where, "has no `guide`: what it returns, when to use it, when NOT to and which tool to "
                                      "use instead, one example"))
        elif not GUIDE_NOT_USE.search(m.guide):
            out.append(Problem(where, "its `guide` does not say when NOT to use the tool (write a line starting "
                                      "'Do not use ...' and name the tool to use instead)"))
        out += [Problem(where, f"example {rel!r} is missing") for rel in m.examples
                if not (comp.folder / rel).is_file()]
        if m.effect == "stage" and "staging" not in m.ports:
            out.append(Problem(where, "effect: stage, but `staging` is not in ports "
                                     "(a stage tool leaves its card there)"))
        if m.effect == "write" and "staging" in m.ports:
            out.append(Problem(where, "a write tool does not use the staging port"))
        return out

    def _check_system(self, where: str, comp: Component, m: mf.SystemManifest, imports: bool) -> list[Problem]:
        out: list[Problem] = []
        if m.job_kind:
            from contracts.jobs import JobKind

            if m.job_kind not in {k.value for k in JobKind}:
                out.append(Problem(where, f"job_kind {m.job_kind!r} is not a contracts.jobs.JobKind"))
        if not (comp.folder / "graph.py").is_file():
            out.append(Problem(where, "has no graph.py with `run(payload, ctx)` (what a function's handler calls)"))
        elif imports:
            out += self._check_entry(where, comp, "graph:run", imports)
        return out

    def _check_panel(self, where: str, comp: Component, m: mf.PanelManifest, imports: bool) -> list[Problem]:
        out: list[Problem] = []
        if m.pattern not in mf.PATTERNS:
            out.append(Problem(where, f"pattern {m.pattern!r} is not one of {', '.join(mf.PATTERNS)}"))
        for role, kind in mf.PATTERN_ROLES.get(m.pattern, {}).items():
            if not getattr(m, role):
                out.append(Problem(where, f"pattern {m.pattern} needs `{role}: {kind}:<id>`"))
        for role, (kind, ident) in m.roles():
            want = {"settle": "step", "judge": "step"}.get(role, "agent")
            if kind != want:
                out.append(Problem(where, f"`{role}` must name a {want}, not {kind} {ident!r}"))
        for ref in m.review:
            if mf._ref(ref)[0] != "agent":
                out.append(Problem(where, f"`review` entries must be agents, not {ref!r}"))
        labels = [x.label for x in m.members]
        out += [Problem(where, f"two members are called {n!r}; give one a `name`") for n in sorted(set(labels))
                if labels.count(n) > 1]
        if m.pattern == "board":
            from contracts.directorops import Op

            known = set(Op.model_fields["op"].annotation.__args__)  # type: ignore[union-attr]
            for member in m.members:
                for entry in member.owns:
                    if entry not in known:
                        out.append(Problem(where, f"member {member.label} owns {entry!r}, which is not an operation"))
                for win in member.wins:
                    if win != "*" and win.split(".")[0] not in known and ".".join(win.split(".")[:2]) not in known:
                        out.append(Problem(where, f"member {member.label} wins {win!r}, not an operation path"))
        if not m.members and m.pattern in ("board", "critics_judge"):
            out.append(Problem(where, "has no members", "warning"))
        if imports:
            out += self._check_entry(where, comp, "graph:build", imports) if (comp.folder / "graph.py").is_file() else [
                Problem(where, "has no graph.py (the wiring that configures its pattern)", "warning")]
        return out

    def _check_knowledge_base(self, where: str, comp: Component, m: mf.KnowledgeBaseManifest,
                              imports: bool) -> list[Problem]:
        out: list[Problem] = []
        if m.embed != "embed":
            out.append(Problem(where, f"embed {m.embed!r} is not an entry of models.yaml (only 'embed')"))
        if m.ingest in ("files", "tables"):
            if not (comp.folder / m.sources).is_dir():
                out.append(Problem(where, f"sources folder {m.sources!r} is missing"))
            out += self._check_entry(where, comp, m.entry, imports)
        if m.ingest == "files":
            if not m.source_prefix.endswith("/"):
                out.append(Problem(where, "source_prefix must end with '/' (rows under it are replaced as a set)"))
            if not m.files:
                out.append(Problem(where, "ingest: files but no files are listed"))
            out += [Problem(where, f"file {f.path!r} is not in {m.sources}/") for f in m.files
                    if not (comp.folder / m.sources / f.path).is_file()]
        if m.ingest == "none" and not m.fed_by:
            out.append(Problem(where, "ingest: none needs `fed_by`, the base that fills its table"))
        if m.fed_by:
            feeder = self.components.get(("knowledge_base", m.fed_by))
            if feeder is not None and getattr(feeder.manifest, "store", None) != m.store:
                out.append(Problem(where, f"fed_by {m.fed_by!r} writes a different store than {m.store!r}"))
        return out

    def _check_agent(self, where: str, comp: Component, m: mf.AgentManifest, imports: bool) -> list[Problem]:
        out: list[Problem] = []
        if m.model not in tier_names():
            out.append(Problem(where, f"model tier {m.model!r} is not in models.yaml ({', '.join(tier_names())})"))
        unknown = [n for n in m.middleware if n not in MIDDLEWARE]
        if unknown:
            out.append(Problem(where, f"unknown middleware {', '.join(unknown)}"))
        if m.shape == "structured" and (stray := [n for n in m.middleware if n in REACT_NAMES]):
            out.append(Problem(where, f"{', '.join(stray)} apply to react agents; a structured agent is one call "
                                      "(its retries and fallbacks are the tier's, in models.yaml)"))
        out += self._check_agent_tools(where, m)
        out += self._check_memory(where, m)
        if m.knowledge and m.shape == "structured":
            out.append(Problem(where, "lists knowledge bases, but a structured agent is one call and cannot search; "
                                      "make it a react agent or let its system retrieve and pass the passages in"))
        if m.knowledge and m.shape == "react" and "search_kb" not in m.tools:
            out.append(Problem(where, "lists knowledge bases but not the search_kb tool that reads them"))
        if m.writes_dialogue and m.id not in DIALOGUE_WRITERS:
            out.append(Problem(where, "writes_dialogue is limited to the approved parts "
                                      f"({', '.join(sorted(DIALOGUE_WRITERS))}); see registry.DIALOGUE_WRITERS"))
        for label, rel in m.prompts.items():
            prompt = comp.folder / rel
            if not prompt.is_file() or not prompt.read_text(encoding="utf-8").strip():
                out.append(Problem(where, f"prompt {label!r} ({rel}) is missing or empty"))
        if m.with_tools:
            out += self._check_tools_form(f"{where} (with_tools)", comp, m)
        out += self._check_evals(where, comp.folder)
        if imports:
            for label, ref in (("input", m.input), ("output", m.output)):
                try:
                    obj = self.resolve("agent", m.id, ref)
                except ManifestError as exc:
                    out.append(Problem(where, str(exc)))
                    continue
                if not (isinstance(obj, type) and issubclass(obj, BaseModel)):
                    out.append(Problem(where, f"{label} {ref!r} is not a pydantic model"))
        return out

    def _check_memory(self, where: str, m: mf.AgentManifest) -> list[Problem]:
        """`memory:` topics need the middleware that reads them (in the form that runs, and in the tools form), and are
        lower-case words or `*`."""
        out: list[Problem] = []
        if not m.memory:
            return out
        if bad := [t for t in m.memory if t != "*" and t != topic_key(t)]:
            out.append(Problem(where, f"memory topics are lower case words joined by _ (or *): {', '.join(bad)}"))
        forms = [("", m.middleware)] + ([(" (with_tools)", m.with_tools.middleware)]
                                        if m.with_tools and m.with_tools.middleware is not None else [])
        for label, names in forms:
            if "production_memory" not in names:
                out.append(Problem(where + label, "lists memory topics but not the production_memory middleware that "
                                                  "reads them"))
        return out

    def _check_tools_form(self, where: str, comp: Component, m: mf.AgentManifest) -> list[Problem]:
        """The `react` form of an agent is held to the rules of a react agent: a short list of tools none of which
        writes, middleware that exists, and a prompt written for it."""
        form = m.form(True)
        out = self._check_agent_tools(where, form)
        if unknown := [n for n in form.middleware if n not in MIDDLEWARE]:
            out.append(Problem(where, f"unknown middleware {', '.join(unknown)}"))
        if form.knowledge and "search_kb" not in form.tools:
            out.append(Problem(where, "lists knowledge bases but not the search_kb tool that reads them"))
        prompt = comp.folder / form.prompts["system"]
        if not prompt.is_file() or not prompt.read_text(encoding="utf-8").strip():
            out.append(Problem(where, f"prompt {form.prompts['system']!r} is missing or empty"))
        elif form.prompts["system"] == m.prompts["system"]:
            out.append(Problem(where, "uses the same system prompt as the single call: write one that says which "
                                      "tool to use for what (prompts/system.tools.md)"))
        if form.shape != "react":  # pragma: no cover - ToolsForm always makes a react agent
            out.append(Problem(where, "must be a react agent"))
        return out

    def _check_agent_tools(self, where: str, m: mf.AgentManifest) -> list[Problem]:
        """Least privilege and a short list (plan/2026-11-04 §4.3, §1): no tool that writes, at most `MAX_TOOLS`."""
        out: list[Problem] = []
        cap = max(mf.MAX_TOOLS, min(m.tool_cap, mf.MAX_TOOLS_WIDE))
        if len(m.tools) > cap:
            out.append(Problem(where, f"lists {len(m.tools)} tools; an agent sees at most {cap}"
                                      + ("" if cap > mf.MAX_TOOLS else " (a wider list says so with `tool_cap`)")))
        if m.deep_model or m.escalate_tool or "tiering" in m.middleware:
            out += self._check_tiering(where, m)
        if len(set(m.tools)) != len(m.tools):
            out.append(Problem(where, "lists a tool twice"))
        for tool_id in m.tools:
            tool = self.components.get(("tool", tool_id))
            if tool is not None and isinstance(tool.manifest, mf.ToolManifest) and tool.manifest.effect == "write":
                out.append(Problem(where, f"lists tool {tool_id!r}, which writes stored data; a model changes data "
                                          "only by `stage` (a card a person accepts); "
                                          "only a system calls a write tool"))
        for tool_id in m.gate:
            if tool_id not in m.tools:
                out.append(Problem(where, f"gate names {tool_id!r}, which is not one of its tools"))
            else:
                tool = self.components.get(("tool", tool_id))
                if tool is not None and isinstance(tool.manifest, mf.ToolManifest) and tool.manifest.effect != "stage":
                    out.append(Problem(where, f"gate names {tool_id!r}, whose effect is {tool.manifest.effect}; "
                                              "only a stage tool is gated"))
        return out

    def _check_tiering(self, where: str, m: mf.AgentManifest) -> list[Problem]:
        """`tiering` (plan/2026-11-08 §4.4): a react agent, a known deep tier other than its own, and an escalation tool
        that is one of its tools."""
        from hiru_ai.core.models import tier_names

        out: list[Problem] = []
        if "tiering" not in m.middleware:
            out.append(Problem(where, "names a deep_model or an escalate_tool but not the tiering middleware"))
        if m.shape != "react":
            out.append(Problem(where, "tiering switches the model inside a tool loop: the agent must be react"))
        if not m.deep_model:
            out.append(Problem(where, "uses tiering without a deep_model"))
        elif m.deep_model not in tier_names() or m.deep_model == m.model:
            out.append(Problem(where, f"deep_model {m.deep_model!r} must be a tier of models.yaml other than its own"))
        if m.escalate_tool and m.escalate_tool not in m.tools:
            out.append(Problem(where, f"escalate_tool {m.escalate_tool!r} is not one of its tools"))
        return out

    def _check_evals(self, where: str, folder: Path) -> list[Problem]:
        files = sorted((folder / "evals").glob("*.yaml"))
        if not files:
            return [Problem(where, "has no eval cases (evals/*.yaml)")]
        cases = 0
        for path in files:
            try:
                data = yaml.safe_load(path.read_text(encoding="utf-8"))
            except yaml.YAMLError as exc:
                return [Problem(where, f"{path.name} is not valid YAML: {exc}")]
            if not isinstance(data, list) or not all(isinstance(c, dict) and "name" in c for c in data):
                return [Problem(where, f"{path.name} must be a list of cases, each with a name")]
            cases += len(data)
        return [] if cases else [Problem(where, "has no eval cases (evals/*.yaml)")]

    def _check_entry(self, where: str, comp: Component, entry: str, imports: bool) -> list[Problem]:
        if not imports:
            return []
        try:
            obj = self.resolve(comp.manifest.kind, comp.manifest.id, entry)
        except ManifestError as exc:
            return [Problem(where, str(exc))]
        return [] if callable(obj) else [Problem(where, f"entry {entry!r} is not callable")]

    def _cycles(self) -> list[Problem]:
        out: list[Problem] = []
        state: dict[Key, int] = {}  # 1 = on the current path, 2 = done

        def visit(key: Key, path: list[Key]) -> None:
            state[key] = 1
            comp = self.components.get(key)
            for ref in comp.manifest.refs() if comp else []:
                if state.get(ref) == 1:
                    loop = [*path[path.index(ref):], ref] if ref in path else [ref]
                    cycle = " -> ".join(f"{k} {i}" for k, i in loop)
                    out.append(Problem(f"{key[0]} {key[1]}", f"reference cycle: {cycle}"))
                elif ref not in state:
                    visit(ref, [*path, ref])
            state[key] = 2

        for key in sorted(self.components):
            if key not in state:
                visit(key, [key])
        return out


def default() -> Registry:
    """The registry over the real package, discovered."""
    return Registry().discover()
