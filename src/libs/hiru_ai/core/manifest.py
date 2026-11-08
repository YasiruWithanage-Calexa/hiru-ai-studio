"""The schema of `component.yaml`: one manifest per part, one model per kind.

A manifest says what a part IS and what it NEEDS by id (tools, knowledge bases, member agents). It never
imports anything. The registry reads manifests; `validate` checks that every id they name exists.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Annotated, Any, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from hiru_ai.core.errors import ManifestError

# kind → folder under hiru_ai/ (also the layer order, lowest first)
LAYERS: dict[str, str] = {
    "knowledge_base": "knowledge_bases",
    "tool": "tools",
    "step": "steps",
    "agent": "agents",
    "panel": "panels",
    "system": "systems",
}
KINDS = tuple(LAYERS)

ID_PATTERN = r"^[a-z][a-z0-9_]{1,40}$"
ID_RE = re.compile(ID_PATTERN)
ComponentId = Annotated[str, Field(pattern=ID_PATTERN)]
Status = Literal["active", "experimental", "disabled"]


class _Base(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: ComponentId
    version: int = Field(1, ge=1)
    summary: str = Field(min_length=3)
    status: Status = "active"
    owner: str = ""

    def refs(self) -> list[tuple[str, str]]:
        """(kind, id) of every other part this one names."""
        return []


class ToolsForm(BaseModel):
    """The `react` form of an agent that answers in one call today (plan/2026-11-04 §8). It is used only when the
    agent's id is in `AGENT_TOOLS` (or an eval asks for it), so a form can be built, tested and measured before it
    replaces anything; going back is taking the id out of the list. Whatever a form leaves out is the agent's own."""

    model_config = ConfigDict(extra="forbid")

    tools: list[ComponentId] = Field(min_length=1)
    prompts: dict[str, str] = {"system": "prompts/system.tools.md"}
    middleware: list[str] | None = None  # None = the agent's own
    knowledge: list[ComponentId] | None = None
    max_tool_calls: int | None = Field(None, ge=1, le=20)
    max_model_calls: int | None = Field(None, ge=1, le=10)
    gate: list[ComponentId] = []


class AgentManifest(_Base):
    kind: Literal["agent"] = "agent"
    model: str  # a tier from core/models.yaml
    # Seconds a call may take, replacing the tier's own: an agent that writes a long answer says so here
    # (plan/2026-11-05 R2: a call cut off by a timeout may still be billed, is retried, and never reaches
    # `token_usage`).
    timeout_s: float | None = Field(None, gt=0, le=900)
    # one typed call | a create_agent tool loop | plain text, streamed (a reply a person reads as it is written)
    shape: Literal["structured", "react", "text"] = "structured"
    input: str  # "schema:Input", relative to the agent's folder
    output: str
    prompts: dict[str, str] = {"system": "prompts/system.md"}
    phase: str = ""  # the token_usage `phase` of its calls (default "agent.<id>"); the engines' own are kept
    tools: list[ComponentId] = []  # at most MAX_TOOLS, never a tool whose effect is `write` (validate)
    knowledge: list[ComponentId] = []
    middleware: list[str] = []
    # Production memory topics the agent is given (plan/2026-11-05d); `*` = every topic. `fact` and `must` entries
    # reach it whatever the topic. Needs `production_memory` in `middleware`.
    memory: list[str] = []
    writes_dialogue: bool = False  # only approved parts may change a spoken line (language_guard)
    # react: the loop is capped (plan/2026-11-04 D2); `limits` in `middleware` turns the caps on
    max_tool_calls: int = Field(6, ge=1, le=20)  # tool calls in one run
    max_model_calls: int = Field(4, ge=1, le=10)  # model rounds in one run
    gate: list[ComponentId] = []  # `stage` tools that stop for a person before they run (hitl); a staged card is
    #                               already a person's gate, so this is for a system that wants a second one
    # `tiering` (plan/2026-11-08 §4.4): the tier a turn moves up to, once, when the work needs it; the tool whose call
    # asks for it; and which signals are on (model, refusals, cap, stage). Empty `deep_model` = no tiering.
    deep_model: str = ""
    escalate_tool: ComponentId | None = None
    escalate_on: list[Literal["model", "refusals", "cap", "stage"]] = ["model", "refusals", "cap", "stage"]
    # How many tools this agent may see: MAX_TOOLS unless the manifest says more, up to MAX_TOOLS_WIDE. A wide list is
    # for an agent whose questions span the production (Sable, plan/2026-11-08 §2.3); it must stay fixed and sorted
    # so it is part of the cached prompt prefix.
    tool_cap: int = Field(8, ge=1, le=24)
    with_tools: ToolsForm | None = None  # the same agent as a tool loop, switched on by AGENT_TOOLS (see ToolsForm)

    def form(self, with_tools: bool) -> AgentManifest:
        """The manifest as it runs: itself, or (with tools, when it has that form) its `react` form."""
        if not (with_tools and self.with_tools):
            return self
        f = self.with_tools
        update: dict[str, Any] = {"shape": "react", "tools": list(f.tools), "prompts": {**self.prompts, **f.prompts},
                                  "gate": list(f.gate), "with_tools": None}
        for name in ("middleware", "knowledge", "max_tool_calls", "max_model_calls"):
            if getattr(f, name) is not None:
                update[name] = getattr(f, name)
        return self.model_copy(update=update)

    def refs(self) -> list[tuple[str, str]]:
        tools = [*self.tools, *(self.with_tools.tools if self.with_tools else [])]
        return [("tool", t) for t in dict.fromkeys(tools)] + [("knowledge_base", k) for k in self.knowledge]


Effect = Literal["read", "stage", "write"]
MAX_TOOLS = 8  # tools one agent may see (OpenAI's soft limit is 20; fewer tools, fewer wrong choices)
MAX_TOOLS_WIDE = 24  # the most an agent's `tool_cap` may allow (plan/2026-11-08 §2.3: past ~30, OpenAI's tool_search)


class ToolManifest(_Base):
    """What a tool is. `effect` says what a call can change:

    read   nothing, anywhere; free to call
    stage  makes a pending card a person accepts; never changes the plan, the script or the canon itself
    write  changes stored data; no agent may list it, only a system calls it in code (`hiru-ai run --live` refuses it
           without --allow-writes)
    """

    kind: Literal["tool"] = "tool"
    entry: str = "tool:run"  # "module:callable" relative to the tool's folder
    ports: list[str] = []  # which RunContext ports it uses: scenes, canon, structure, docs, search, files, images, jobs
    uses: list[ComponentId] = []  # steps it calls by id (core.parts); never by import
    effect: Effect = "read"
    # The longer text that becomes the tool's description beside `summary`: what it returns, when to use it, when NOT to
    # use it and which tool to use instead, one example (plan/2026-11-04 §4.7). `summary` stays one line for the
    # catalog.
    guide: str = ""
    max_result_tokens: int = Field(1500, ge=200, le=8000)  # a result over this is cut, with a hint (tooling)
    examples: list[str] = ["examples/basic.json"]  # runnable cases, relative to the tool's folder

    @model_validator(mode="before")
    @classmethod
    def _writes_alias(cls, data: Any) -> Any:
        """`writes: true|false` is the one-release alias of `effect: write|read` (plan/2026-11-04 §6)."""
        if isinstance(data, dict) and "writes" in data:
            data = dict(data)
            writes = data.pop("writes")
            if "effect" in data:
                raise ValueError("give `effect`, not `effect` and `writes`")
            data["effect"] = "write" if writes else "read"
        return data

    @property
    def writes(self) -> bool:
        return self.effect == "write"

    def refs(self) -> list[tuple[str, str]]:
        return [("step", s) for s in self.uses]


class StepManifest(_Base):
    kind: Literal["step"] = "step"
    entry: str = "step:run"  # deterministic: no model
    input: str = ""
    output: str = ""
    uses: list[ComponentId] = []  # other steps it calls by id (core.parts); never by import
    tools: list[ComponentId] = []  # `read` tools it calls by id (core.parts); the director's read path is one

    def refs(self) -> list[tuple[str, str]]:
        return [("step", s) for s in self.uses] + [("tool", t) for t in self.tools]


class SourceFile(BaseModel):
    model_config = ConfigDict(extra="forbid")

    path: str  # relative to the knowledge base's sources folder
    meta: dict[str, Any] = {}  # stored with every chunk of the file (`chunks.meta`), e.g. {specialty: audience}


class KnowledgeBaseManifest(_Base):
    """A corpus: where its text comes from, how it is chunked, and which table its rows live in.

    ingest: files = prose files under `sources`, chunked into `chunks`; tables = CSV tables loaded into
    `craft_techniques`; upload = the people's own documents, ingested by the doc_ingest job, not by `hiru-ai ingest`;
    none = the base only describes a table another base fills (`fed_by`).
    """

    kind: Literal["knowledge_base"] = "knowledge_base"
    corpus: str
    store: Literal["chunks", "techniques"] = "chunks"
    ingest: Literal["files", "tables", "upload", "none"] = "files"
    entry: str = "ingest:build"  # "module:callable" in the base's folder, for ingest files|tables
    sources: str = "sources"
    source_prefix: str = ""  # the `chunks.source` prefix this base owns; rows under it are replaced as a set
    files: list[SourceFile] = []
    chunking: dict[str, Any] = {}
    embed: str = "embed"  # the embedding entry of models.yaml
    uses: list[ComponentId] = []  # steps it calls by id (core.parts)
    fed_by: ComponentId | None = None  # another knowledge base that fills this one's table

    def refs(self) -> list[tuple[str, str]]:
        return [("step", s) for s in self.uses] + ([("knowledge_base", self.fed_by)] if self.fed_by else [])


PATTERNS = ("sequential", "fanout", "board", "critics_judge", "generate_critique", "router", "human_gate")
# what each pattern needs of a panel: the roles it must name, as "kind"
PATTERN_ROLES: dict[str, dict[str, str]] = {
    "board": {"settle": "step"},
    "critics_judge": {"judge": "step"},
    "generate_critique": {"writer": "agent", "critic": "agent"},
}


class Member(BaseModel):
    """One agent on a panel. `name` is how the pattern knows it (a craft on a board, a lens among critics; default: the
    agent's id). `owns` is what it may DO (the operations the kernel lets it write); `wins` is what it WINS when two
    members write the same path ("set.sound_mode", "beat.set.camera", "split"; the most specific entry wins)."""

    model_config = ConfigDict(extra="forbid")

    agent: ComponentId
    name: str = ""
    owns: list[str] = []
    wins: list[str] = []

    @property
    def label(self) -> str:
        return self.name or self.agent


class PanelManifest(_Base):
    kind: Literal["panel"] = "panel"
    pattern: str  # a core/patterns shape: board, critics_judge, generate_critique...
    members: list[Member] = []
    settle: str = ""  # "step:<id>": board: who wins a collision
    review: list[str] = []  # ["agent:<id>"]: board: advisors heard after the changes landed
    judge: str = ""  # "step:<id>": critics_judge: scores the candidate plans (lower wins)
    reviser: str = ""  # "agent:<id>": critics_judge: writes the one revised plan from the critics' notes
    writer: str = ""  # "agent:<id>": generate_critique
    critic: str = ""  # "agent:<id>": generate_critique
    max_rounds: int = Field(1, ge=0, le=3)  # generate_critique: revisions at most; never open-ended

    def roles(self) -> list[tuple[str, tuple[str, str]]]:
        """(role, (kind, id)) for every single-valued role that is set."""
        named = (("settle", self.settle), ("judge", self.judge), ("reviser", self.reviser), ("writer", self.writer),
                 ("critic", self.critic))
        return [(role, _ref(text)) for role, text in named if text]

    def refs(self) -> list[tuple[str, str]]:
        out = [("agent", m.agent) for m in self.members]
        out += [ref for _, ref in self.roles()]
        out += [_ref(r) for r in self.review]
        return out


class SystemManifest(_Base):
    kind: Literal["system"] = "system"
    job_kind: str = ""  # contracts.jobs.JobKind value this system serves
    panels: list[ComponentId] = []
    agents: list[ComponentId] = []
    steps: list[ComponentId] = []
    tools: list[ComponentId] = []

    def refs(self) -> list[tuple[str, str]]:
        return ([("panel", p) for p in self.panels] + [("agent", a) for a in self.agents]
                + [("step", s) for s in self.steps] + [("tool", t) for t in self.tools])


Manifest = AgentManifest | ToolManifest | StepManifest | KnowledgeBaseManifest | PanelManifest | SystemManifest
_BY_KIND: dict[str, type[_Base]] = {
    "agent": AgentManifest, "tool": ToolManifest, "step": StepManifest,
    "knowledge_base": KnowledgeBaseManifest, "panel": PanelManifest, "system": SystemManifest,
}


class GroupManifest(BaseModel):
    """`group.yaml`: a folder inside a layer (`agents/adam/`) that holds one product's parts apart from the rest
    (plan/2026-11-04b §5.0). A group is not a part: it has no code, only a name, an owner and a switch. Switching it
    off (`status: disabled`) switches off every part in it, in that layer.

    `folders` (on the group's system layer) is the group's removal list: repo-relative folders that go with it, so
    `hiru-ai remove --group <id>` knows them all. `outside` names what lives in another repo (said, never deleted)."""

    model_config = ConfigDict(extra="forbid")

    id: ComponentId
    version: int = Field(1, ge=1)
    summary: str = ""
    owner: str = ""
    status: Literal["active", "disabled"] = "active"
    folders: list[str] = []
    outside: list[str] = []
    # Parts OUTSIDE any group that this group's parts in this layer may name as they are (plan/2026-11-08 §4.3): an
    # assistant that reads the whole production uses the shared read and stage tools instead of copies. A planner group
    # leaves it empty and copies what it needs (its parts must not change under it). Removing the group never touches
    # a shared part.
    shared: list[ComponentId] = []


def load_group(path: Path) -> GroupManifest:
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            raise ManifestError(f"{path}: a group.yaml is a mapping with an `id`")
        return GroupManifest.model_validate(data)
    except (OSError, yaml.YAMLError) as exc:
        raise ManifestError(f"{path}: {exc}") from exc
    except ValidationError as exc:
        problems = "; ".join(f"{'.'.join(str(p) for p in e['loc']) or 'group'}: {e['msg']}" for e in exc.errors())
        raise ManifestError(f"{path}: {problems}") from exc


def _ref(text: str) -> tuple[str, str]:
    """"step:board_settle" → ("step", "board_settle")."""
    kind, _, ident = text.partition(":")
    if kind not in KINDS or not ident:
        raise ManifestError(f"bad reference {text!r}; expected '<kind>:<id>' with kind one of {', '.join(KINDS)}")
    return kind, ident


def parse(data: Any, where: str = "component.yaml") -> Manifest:
    """A manifest from loaded YAML. `kind` picks the model; errors name the file and the field."""
    if not isinstance(data, dict) or "kind" not in data:
        raise ManifestError(f"{where}: a manifest is a mapping with a `kind`")
    model = _BY_KIND.get(str(data["kind"]))
    if model is None:
        raise ManifestError(f"{where}: unknown kind {data['kind']!r}; use one of {', '.join(KINDS)}")
    try:
        manifest: Manifest = model.model_validate(data)  # type: ignore[assignment]
        manifest.refs()  # a malformed reference ("step:") fails here, not later
    except ValidationError as exc:
        problems = "; ".join(f"{'.'.join(str(p) for p in e['loc']) or 'manifest'}: {e['msg']}" for e in exc.errors())
        raise ManifestError(f"{where}: {problems}") from exc
    return manifest


def load(path: Path) -> Manifest:
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        raise ManifestError(f"{path}: {exc}") from exc
    return parse(data, str(path))
