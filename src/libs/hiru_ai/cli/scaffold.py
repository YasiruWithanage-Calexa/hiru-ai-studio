"""`hiru-ai new <kind> <id>`: write a part's folder with everything `validate` asks for.

One new folder, no edits elsewhere. What it writes passes `hiru-ai validate` and its own tests straight away; the
person then replaces the TODOs.
"""
from __future__ import annotations

from pathlib import Path

from hiru_ai.core import manifest as mf
from hiru_ai.core.errors import HiruAIError

TITLE = "TODO - one sentence on what this part does"


def _write(folder: Path, files: dict[str, str]) -> list[Path]:
    written = []
    for rel, text in files.items():
        path = folder / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        written.append(path)
    return written


def _manifest(ident: str, kind: str, extra: str = "", summary: str = TITLE) -> str:
    return (f"id: {ident}\nkind: {kind}\nversion: 1\nsummary: {summary}\nstatus: experimental\n{extra}")


def _agent(ident: str, camel: str, pkg: str = "") -> dict[str, str]:
    pkg = pkg or ident
    return {
        "component.yaml": _manifest(ident, "agent", (
            "model: medium                 # a tier from core/models.yaml\n"
            "shape: structured             # structured = one typed call | react = create_agent tool loop\n"
            "input: schema:Input\n"
            "output: schema:Output\n"
            "prompts: { system: prompts/system.md }\n"
            "tools: []                     # tool ids\n"
            "knowledge: []                 # knowledge base ids\n"
            "middleware: [usage, untrusted_text, absent_safe, static_first]\n"
            "writes_dialogue: false\n")),
        "schema.py": (
            f'"""Typed seams of the {ident} agent. It knows nothing about the panel that uses it."""\n'
            "from __future__ import annotations\n\nfrom pydantic import BaseModel\n\n\n"
            "class Input(BaseModel):\n    text: str\n\n\n"
            "class Output(BaseModel):\n    answer: str\n"),
        "agent.py": (
            f'"""The {ident} agent\'s hooks. The builder (core) wires them to the manifest."""\n'
            "from __future__ import annotations\n\nfrom hiru_ai.agents." + pkg + ".schema import Input, Output\n\n\n"
            "def user_message(inp: Input) -> str:\n"
            '    """Per-item data goes here, in the user message. The system prompt stays static."""\n'
            "    return inp.text\n\n\n"
            "def fallback(inp: Input) -> Output | None:\n"
            '    """The rules-only answer when there is no key or the call fails; None = there is none."""\n'
            "    return None\n"),
        "prompts/system.md": (f"You are the {camel} agent. TODO: write the charter. Keep this file static:\n"
                              "per-item data goes in the user message, never here.\n"),
        "evals/cases.yaml": (
            "# Eval cases: what the agent is asked (input), what the model is scripted to answer (reply, or\n"
            "# `model: unavailable` for the no-key path) and what the agent must then return (expect: a subset of\n"
            "# the Output). Two at least. Run with: hiru-ai run agent <id> --input case.json\n"
            "- name: typical\n  input: { text: TODO a normal request }\n  reply: { answer: TODO }\n"
            "  expect: { answer: TODO }\n"
            "- name: edge\n  input: { text: TODO an awkward request }\n  reply: { answer: TODO }\n"
            "  expect: { answer: TODO }\n"),
        f"tests/test_agent_{ident}.py": (
            f'"""Tests that live with the {ident} agent (ADR 0006): deleting the folder deletes them."""\n'
            "from __future__ import annotations\n\nfrom pathlib import Path\n\nimport yaml\n\n"
            "from hiru_ai.core.prompts import Prompt\n"
            f"from hiru_ai.agents.{pkg} import agent\n"
            f"from hiru_ai.agents.{pkg}.schema import Input, Output\n\n"
            "HERE = Path(__file__).resolve().parents[1]\n\n\n"
            "def test_the_prompt_is_static_text():\n"
            '    assert Prompt.load(HERE / "prompts" / "system.md").text.strip()\n\n\n'
            "def test_the_hooks_use_the_agents_own_types():\n"
            '    assert isinstance(agent.user_message(Input(text="x")), str)\n'
            '    answer = agent.fallback(Input(text="x"))\n'
            '    assert answer is None or isinstance(answer, Output)\n\n\n'
            "def test_there_are_eval_cases():\n"
            '    cases = yaml.safe_load((HERE / "evals" / "cases.yaml").read_text(encoding="utf-8"))\n'
            "    assert len(cases) >= 2 and all(c.get(\"name\") for c in cases)\n"),
    }


def _tool(ident: str, effect: str = "read", wraps: str = "", pkg: str = "") -> dict[str, str]:
    """A tool folder that passes `validate` and its own tests: the contract of plan/2026-11-04 §4 filled in. `wraps`
    names the step whose logic the tool is a thin wrapper for (ADR 0009); a tool never takes that step's id."""
    ports = "[staging]" if effect == "stage" else "[]"
    uses = f"[{wraps}]" if wraps else "[]"
    base = "tooling.ToolArgs" if effect == "read" else "BaseModel"
    body = (f'    result = parts.module("step", "{wraps}", "step").run({{"text": args.text}})  # TODO: the payload\n'
            "    return Result(text=str(result))\n") if wraps else "    return Result(text=args.text)\n"
    return {
        "component.yaml": _manifest(ident, "tool", (
            "entry: tool:run\n"
            f"ports: {ports}        # RunContext ports it uses: scenes, canon, structure, docs, search, files, images, "
            "jobs, staging\n"
            f"uses: {uses}         # steps it calls by id (hiru_ai.core.parts); a tool never takes its step's id\n"
            f"effect: {effect}    # read = changes nothing | stage = leaves a card | write = systems only\n"
            "max_result_tokens: 1500\n"
            "guide: |\n"
            "  TODO what it returns, in a sentence a new hire understands.\n"
            "  Use it when TODO. Example: {\"text\": \"x\"}.\n"
            "  Do not use it for TODO (use another_tool instead).\n")),
        "tool.py": (
            f'"""The {ident} tool: one action a model may call. Typed arguments; scope from the run."""\n'
            "from __future__ import annotations\n\n"
            "from langchain_core.tools import StructuredTool\nfrom pydantic import BaseModel, Field\n\n"
            "from hiru_ai.core import parts, tooling\nfrom hiru_ai.core.context import RunContext\n\n\n"
            f"class Args({base}):\n"
            "    # Only what a model may choose. The production, actor, scene in scope and ports come from the run.\n"
            '    text: str = Field(description="TODO what the model gives")\n\n\n'
            "class Result(BaseModel):\n    text: str\n\n\n"
            "def run(args: Args, ctx: RunContext) -> Result:\n"
            '    """TODO. Raise ToolRefused(message, how_to_fix=..., example=...) for what the tool must refuse."""\n'
            f"{body}\n\n"
            "def as_tool() -> StructuredTool:\n"
            '    return tooling.from_part(__package__ or "", Args, run)\n'),
        "examples/basic.json": '{"args": {"text": "x"}}\n',
        f"tests/test_tool_{ident}.py": (
            f"from hiru_ai.core.context import RunContext\nfrom hiru_ai.tools.{pkg or ident} import tool\n\n\n"
            "def test_it_runs_alone():\n"
            '    assert tool.run(tool.Args(text="x"), RunContext())\n'),
    }


def _step(ident: str, pkg: str = "") -> dict[str, str]:
    return {
        "component.yaml": _manifest(ident, "step", (
            "entry: step:run\n"
            "uses: []         # other steps it calls by id (hiru_ai.core.parts); never by import\n")),
        "step.py": (
            f'"""The {ident} step: deterministic, no model. JSON in, JSON out; wrap the rule in `contracts` here."""\n'
            "from __future__ import annotations\n\nfrom typing import Any\n\n\n"
            "def run(payload: dict[str, Any]) -> dict[str, Any]:\n"
            '    """TODO"""\n'
            "    return dict(payload)\n"),
        "examples/basic.json": '{"a": 1}\n',
        f"tests/test_step_{ident}.py": (
            f"from hiru_ai.steps.{pkg or ident} import step\n\n\n"
            'def test_it_runs_alone():\n    assert step.run({"a": 1}) == {"a": 1}\n'),
    }


# What a new panel's graph.py builds, per pattern: the library call with do-nothing members, to be replaced.
_STATE = "class State(TypedDict, total=False):\n    text: str\n\n\n"
_PANEL_BUILD = {
    "sequential": ("from typing import TypedDict\n\n", _STATE, "sequential(State, [])"),
    "fanout": ("", "", "fanout(lambda item, state: item)"),
    "board": ("", "", "board(lambda task, state: None, lambda outputs: outputs)"),
    "critics_judge": ("", "", "critics_judge(lambda lens, state: None, lambda results: [], None, "
                              "lambda candidate, state: (0,))"),
    "generate_critique": ("", "", "generate_critique(lambda state, notes: None, lambda state, draft: [], "
                                  "lambda state, draft, revised: draft)"),
    "router": ("", "", 'router(lambda state: "", {})'),
    "human_gate": ("", "", "human_gate(durable=False, default=lambda questions: {})"),
}
_ROLES = {"board": "settle: step:TODO_STEP\n", "critics_judge": "judge: step:TODO_STEP\n",
          "generate_critique": "writer: agent:TODO_AGENT\ncritic: agent:TODO_AGENT\n"}

_PANEL_GRAPH = """\"\"\"The {ident} panel: the `{pattern}` pattern, configured by component.yaml.

TODO: replace the do-nothing members with calls to the manifest's agents (see panels/director_board/graph.py for the
shape). A panel asks its kit for members by name and never imports an agent module.
\"\"\"
from __future__ import annotations

{typing}from typing import Any

from langgraph.graph.state import CompiledStateGraph

from hiru_ai.core.context import RunContext
from hiru_ai.core.manifest import PanelManifest
from hiru_ai.core.patterns import {pattern}
from hiru_ai.core.registry import Registry

ID = "{ident}"


{state}def build(ctx: RunContext | None = None, registry: Registry | None = None,
          manifest: PanelManifest | None = None) -> CompiledStateGraph[Any, Any, Any, Any]:
    return {call}


def blank(registry: Registry | None = None,
          manifest: PanelManifest | None = None) -> CompiledStateGraph[Any, Any, Any, Any]:
    return build(registry=registry, manifest=manifest)
"""

_PANEL_TEST = """\"\"\"Tests that live with the {ident} panel (ADR 0006).\"\"\"
from __future__ import annotations

from hiru_ai.panels.{pkg} import graph


def test_it_compiles():
    assert graph.blank() is not None
"""


def _panel(ident: str, pattern: str, pkg: str = "") -> dict[str, str]:
    if pattern not in _PANEL_BUILD:
        raise HiruAIError(f"unknown pattern {pattern!r}; use one of {', '.join(_PANEL_BUILD)}")
    typing, state, call = _PANEL_BUILD[pattern]
    return {
        "component.yaml": _manifest(ident, "panel", f"pattern: {pattern}\nmembers: []\n{_ROLES.get(pattern, '')}"),
        "graph.py": _PANEL_GRAPH.format(ident=ident, pattern=pattern, typing=typing, state=state, call=call),
        f"tests/test_panel_{ident}.py": _PANEL_TEST.format(ident=ident, pkg=pkg or ident),
    }



def _groups(root: Path) -> dict[str, set[str]]:
    """Group id → the layer folders that hold it (a folder with a group.yaml inside a layer)."""
    found: dict[str, set[str]] = {}
    for layer in mf.LAYERS.values():
        for gy in sorted((root / layer).glob("*/group.yaml")):
            found.setdefault(gy.parent.name, set()).add(layer)
    return found


def _taken(root: Path, kind: str, ident: str) -> list[str]:
    """The other kinds that already have a part with this id, directly in a layer or inside any group."""
    return [k for k in mf.KINDS if k != kind and any(
        any(True for _ in (root / mf.LAYERS[k]).glob(pattern))
        for pattern in (f"{ident}/component.yaml", f"*/{ident}/component.yaml"))]


def create(kind: str, ident: str, root: Path, *, pattern: str = "sequential", package: str = "hiru_ai",
           effect: str = "read", wraps: str = "", group: str = "") -> list[Path]:
    """Write the folder for a new part under `root`. Refuses an id that is taken or malformed. `effect` and `wraps`
    are for a tool: what a call may change, and the step it is a thin wrapper for. `group` puts the part inside that
    group's folder in its layer (`agents/adam/`); the id must then start with `<group>_`, and an id with another
    group's prefix is refused anywhere else (plan/2026-11-04b §5.0)."""
    if kind not in mf.LAYERS:
        raise HiruAIError(f"unknown kind {kind!r}; use one of {', '.join(mf.KINDS)}")
    if not mf.ID_RE.match(ident):
        raise HiruAIError(f"{ident!r} is not a valid id: lower-case letters, digits and _, starting with a letter")
    groups = _groups(root)
    layer = mf.LAYERS[kind]
    if group:
        if layer not in groups.get(group, set()):
            raise HiruAIError(f"there is no group {group!r} in {layer}/ (a folder {layer}/{group}/ with a group.yaml)")
        if not ident.startswith(f"{group}_"):
            raise HiruAIError(f"a part of the {group} group has an id that starts with '{group}_'")
    else:
        for other in sorted(groups):
            if ident.startswith(f"{other}_"):
                raise HiruAIError(f"ids starting with '{other}_' belong to the {other} group: "
                                  f"use --group {other} (it writes the part into {layer}/{other}/)")
    folder = root / layer / group / ident if group else root / layer / ident
    pkg = f"{group}.{ident}" if group else ident
    if folder.exists() or any((root / layer).glob(f"*/{ident}/component.yaml")) or (root / layer / ident).exists():
        raise HiruAIError(f"{kind} {ident!r} already exists in {layer}/")
    if kind == "tool":
        if effect not in ("read", "stage", "write"):
            raise HiruAIError(f"unknown effect {effect!r}; use read, stage or write")
        steps = root / mf.LAYERS["step"]
        if wraps and not ((steps / group / wraps if group else steps / wraps) / "component.yaml").is_file():
            raise HiruAIError(f"--wraps {wraps!r} is not a step in {steps / group if group else steps}")
        if wraps == ident:
            raise HiruAIError("a tool never takes the id of the step it wraps; give the tool its own name")
    if kind == "tool" and (taken := _taken(root, kind, ident)):
        raise HiruAIError(f"{ident!r} is already a {taken[0]}; ids are unique across kinds")
    camel = ident.replace("_", " ")
    files = {
        "agent": lambda: _agent(ident, camel, pkg),
        "tool": lambda: _tool(ident, effect, wraps, pkg),
        "step": lambda: _step(ident, pkg),
        "knowledge_base": lambda: {
            "component.yaml": _manifest(ident, "knowledge_base", (
                f"corpus: {ident}\nstore: chunks\ningest: files\nsources: sources\n"
                f"source_prefix: knowledge_base/{ident}/   # chunks.source starts with this\n"
                "chunking: { script_like: false }\nembed: embed\nuses: [extract_text, chunk]\n"
                "files:\n  - { path: notes.md, meta: { specialty: TODO } }\n")),
            "sources/notes.md": f"# {camel}\n\nTODO: the text agents may search. Headings split it into passages.\n",
            "ingest.py": (
                f'"""The {ident} knowledge base. All behaviour comes from component.yaml."""\n'
                "from __future__ import annotations\n\nfrom pathlib import Path\n\n"
                "from hiru_ai.core.manifest import KnowledgeBaseManifest\n"
                "from hiru_ai.rag.knowledge import KnowledgeBase\n\n\n"
                "def build(manifest: KnowledgeBaseManifest, folder: Path) -> KnowledgeBase:\n"
                "    return KnowledgeBase(manifest, folder)\n")},
        "panel": lambda: _panel(ident, pattern, pkg),
        "system": lambda: {"component.yaml": _manifest(ident, "system", "agents: []\npanels: []\nsteps: []\n")},
    }[kind]()
    layer_init = folder.parent / "__init__.py"
    if not layer_init.exists():
        _write(folder.parent, {"__init__.py": f'"""{mf.LAYERS[kind]}."""\n'})
    return _write(folder, {"__init__.py": f'"""The {ident} {kind.replace("_", " ")}."""\n', **files})
