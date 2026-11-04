"""`hiru-ai list | validate | new | run | ingest | graph | catalog | studio | remove | eval | mcp | review`.

Exit status: 0 fine, 1 `validate` found errors, 2 the command itself could not run.
"""
from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from dataclasses import replace
from pathlib import Path
from typing import Any
from uuid import UUID

import httpx

from hiru_ai.cli import scaffold
from hiru_ai.core import manifest as mf
from hiru_ai.core.errors import HiruAIError, ToolRefused
from hiru_ai.core.registry import PACKAGE_ROOT, Registry


def _registry(root: str | None) -> Registry:
    return Registry(Path(root).resolve() if root else PACKAGE_ROOT).discover()


def cmd_list(args: argparse.Namespace) -> int:
    reg = _registry(args.root)
    rows = [(k, i, c.manifest.status, c.manifest.version, c.manifest.summary)
            for (k, i), c in sorted(reg.components.items(), key=lambda kv: (mf.KINDS.index(kv[0][0]), kv[0][1]))
            if args.kind in (None, k) and (not args.group or c.group == args.group)]
    if args.group and args.group not in reg.group_ids():
        print(f"error: no group {args.group!r}; groups: {', '.join(sorted(reg.group_ids())) or 'none'}",
              file=sys.stderr)
        return 2
    for problem in reg.errors:
        print(problem, file=sys.stderr)
    if not rows and not reg.errors:
        print(f"no parts in the {args.group} group yet; make one with: "
              f"hiru-ai new agent {args.group}_<name> --group {args.group}" if args.group
              else "no parts yet; make one with: hiru-ai new agent <id>")
    for kind, ident, status, version, summary in rows:
        print(f"{kind:15s} {ident:24s} {status:12s} v{version:<3d} {summary}")
    return 0


def cmd_validate(args: argparse.Namespace) -> int:
    reg = _registry(args.root)
    problems = reg.validate(imports=not args.no_import)
    for p in problems:
        print(p)
    errors = [p for p in problems if p.level == "error"]
    print(f"{len(reg.components)} parts, {len(errors)} errors, {len(problems) - len(errors)} warnings")
    return 1 if errors else 0


def cmd_new(args: argparse.Namespace) -> int:
    root = Path(args.root).resolve() if args.root else PACKAGE_ROOT
    try:
        written = scaffold.create(args.kind, args.id, root, pattern=args.pattern, effect=args.effect,
                                  wraps=args.wraps, group=args.group)
    except HiruAIError as exc:
        print(f"error: {exc}", file=sys.stderr)
        if isinstance(exc, ToolRefused):  # what a model would also be told, so a person sees whether the tool teaches
            for label, text in (("how to fix", exc.how_to_fix), ("example", exc.example)):
                if text:
                    print(f"  {label}: {text}", file=sys.stderr)
        return 2
    for path in written:
        print(f"wrote {path.relative_to(root)}")
    print("next: edit the TODOs, then `hiru-ai validate`")
    return 0


def _load_case(path: str) -> dict[str, Any]:
    text = sys.stdin.read() if path == "-" else Path(path).read_text(encoding="utf-8")
    try:
        case = json.loads(text)
    except json.JSONDecodeError as exc:
        raise HiruAIError(f"{path}: not valid JSON ({exc})") from exc
    if not isinstance(case, dict):
        raise HiruAIError(f"{path}: a case is a JSON object")
    return case


def _run_agent(reg: Registry, ident: str, case: dict[str, Any], *, live: bool) -> dict[str, Any]:
    """An agent on a case `{"input": {...}, "reply": {...}}`. The default answers from the case's scripted `reply` (no
    network, no cost); with no `reply` it shows the messages it would send. `--live` asks the real model: only a
    person runs that, because it costs money."""
    from hiru_ai.core import agents, llm
    from hiru_ai.core.context import RunContext
    from hiru_ai.core.testing import ScriptedChatModel

    agent = agents.Agent(reg, ident)
    inp = agent.input_cls.model_validate(case.get("input") or {})
    system, user = agent.messages(inp)
    shown: dict[str, Any] = {"agent": ident, "tier": agent.manifest.model, "phase": agent.phase,
                             "prompt_sha": agent.prompt.sha, "system": system, "user": user}
    if live:
        return {**shown, "output": agent.run(inp, RunContext()).model_dump(mode="json")}
    if "reply" in case:
        with llm.use_models(ScriptedChatModel(replies=[case["reply"]])):
            return {**shown, "output": agent.run(inp, RunContext()).model_dump(mode="json")}
    return shown


def cmd_run(args: argparse.Namespace) -> int:
    """Run one step or tool alone, on a case file. Tools get in-memory fakes unless `--live` (then the real
    adapters from the environment; a tool that writes also needs `--allow-writes`)."""
    from hiru_ai.core.context import RunContext
    from hiru_ai.core.fakes import ports_from

    reg = _registry(args.root)
    comp = reg.get(args.kind, args.id)
    case = _load_case(args.input)
    if args.kind == "agent":
        out = _run_agent(reg, args.id, case, live=args.live)
    elif args.kind == "step":
        out = reg.resolve("step", args.id, comp.manifest.entry)(case)  # type: ignore[union-attr]
    else:
        manifest = comp.manifest
        if args.live and getattr(manifest, "effect", "read") == "write" and not args.allow_writes:
            raise HiruAIError(f"tool {args.id} writes stored data; --live needs --allow-writes (it is the hosted dev "
                              "database: ask first)")
        if args.live:
            from hiru_ai.adapters import images, supabase_rest

            ports = supabase_rest.build_ports()
            if "images" in manifest.ports:  # type: ignore[union-attr]
                ports = replace(ports, images=images.build())
        else:
            ports = ports_from(case.get("fixtures") or {})
        production, scene = case.get("production_id"), case.get("scene_id")
        ctx = RunContext(production_id=UUID(production) if production else None, ports=ports,
                         corpora=tuple(case.get("corpora") or ()), scene_id=UUID(scene) if scene else None,
                         said=str(case.get("said") or ""))
        module = reg.module("tool", args.id, "tool")
        wanted = dict(case.get("args") or {})
        if args.format and "response_format" in module.Args.model_fields:
            wanted.setdefault("response_format", args.format)
        try:
            out = module.run(module.Args.model_validate(wanted), ctx).model_dump(mode="json")
        except httpx.HTTPError as exc:  # only a live run talks HTTP
            raise HiruAIError(f"the database or storage could not be reached: {exc}") from exc
        from hiru_ai.core import tooling

        budget = int(getattr(manifest, "max_result_tokens", 1500))
        out, cut = tooling.fit(out, budget, tooling.narrow_hint(module.Args))
        print(f"result is about {tooling.tokens_of(tooling.dumps(out))} tokens (budget {budget})"
              + ("; it was cut" if cut else ""), file=sys.stderr)
    print(json.dumps(out, ensure_ascii=False, indent=2, default=str))
    return 0


def cmd_mcp(args: argparse.Namespace) -> int:
    """The read and stage tools over MCP on stdio. The scope is this command line's, never the caller's."""
    from hiru_ai.cli import mcp
    from hiru_ai.core.context import RunContext
    from hiru_ai.core.fakes import ports_from

    reg = _registry(args.root)
    corpora = tuple(c for c in args.corpora.split(",") if c)
    if args.fixtures:
        case = _load_case(args.fixtures)
        production, scene = case.get("production_id"), case.get("scene_id")
        ctx = RunContext(production_id=UUID(production) if production else None,
                         ports=ports_from(case.get("fixtures") or {}), corpora=tuple(case.get("corpora") or corpora),
                         scene_id=UUID(scene) if scene else None)
    else:
        if not args.production:
            raise HiruAIError("give --production <uuid> (the one production this server may read) or --fixtures")
        from hiru_ai.adapters import supabase_rest

        ctx = RunContext(production_id=UUID(args.production), ports=supabase_rest.build_ports(), corpora=corpora,
                         scene_id=UUID(args.scene) if args.scene else None)
    return mcp.run(reg, ctx)


def cmd_review(args: argparse.Namespace) -> int:
    """The monthly look at tool use, from a log file."""
    from hiru_ai.cli import review

    reg = _registry(args.root)
    listed = [i for i in reg.ids("tool") if getattr(reg.get("tool", i).manifest, "effect", "") != "write"
              and reg.refs_to("tool", i)]
    with Path(args.log).open(encoding="utf-8", errors="replace") as fh:
        print(review.report(review.read(fh), listed))
    return 0


def cmd_ingest(args: argparse.Namespace) -> int:
    """Index knowledge bases: prose into `chunks`, technique tables into `craft_techniques`. Derived state: the files
    in each base's sources/ are the truth, and a run replaces that base's rows. Embeds when OPENAI__API_KEY is set."""
    from hiru_ai.core import llm
    from hiru_ai.core.fakes import FakeKnowledge
    from hiru_ai.core.settings import get_settings
    from hiru_ai.rag import knowledge
    from hiru_ai.rag.embeddings import embed_texts

    reg = _registry(args.root)
    ingestable = [i for i in reg.ids("knowledge_base") if getattr(reg.get("knowledge_base", i).manifest, "ingest", "")
                  in ("files", "tables")]
    wanted = ingestable if args.all else args.kb
    if not wanted:
        print("name a knowledge base or use --all; ingestable: " + ", ".join(ingestable))
        return 2
    model = get_settings().openai.embedding_model
    on = llm.models_enabled()
    print(f"embeddings: {'ON (' + model + ')' if on else 'OFF (no OPENAI__API_KEY): keyword search only'}")
    if args.dry_run:
        store: Any = FakeKnowledge()
    else:
        from hiru_ai.adapters import supabase_rest

        store = supabase_rest.build_knowledge_store()
    for ident in wanted:
        try:
            kb = knowledge.load(ident, reg)
            report = kb.ingest(store, lambda texts: embed_texts(texts, "knowledge.embed"), model,
                               dry_run=args.dry_run, include_short_form=args.include_short_form)
        except httpx.HTTPError as exc:
            raise HiruAIError(f"the database could not be reached: {exc}") from exc
        for source, n in report.by_source.items():
            print(f"  {source}: {n} chunks")
        if report.techniques:
            print(f"  {report.techniques} techniques")
        verb = "would index" if args.dry_run else "indexed"
        print(f"{ident}: {verb} {report.chunks} chunks and {report.techniques} techniques"
              + ("" if args.dry_run else f" ({report.embedded} embedded now, {report.reused} reused)"))
    if not on and not args.dry_run:
        print("re-run after setting OPENAI__API_KEY to add embeddings")
    return 0


def cmd_graph(args: argparse.Namespace) -> int:
    from hiru_ai.cli import tools

    text = tools.draw(_registry(args.root), args.id)
    if args.out:
        Path(args.out).write_text(text, encoding="utf-8")
        print(f"wrote {args.out}")
    else:
        print(text, end="")
    return 0


def cmd_catalog(args: argparse.Namespace) -> int:
    from hiru_ai.cli import tools

    text = tools.catalog(_registry(args.root))
    target = Path(args.out) if args.out else Path(tools.CATALOG)
    if args.check:
        current = target.read_text(encoding="utf-8") if target.is_file() else ""
        if current != text:
            print(f"{target} is out of date: run `hiru-ai catalog`", file=sys.stderr)
            return 1
        print(f"{target} is current")
        return 0
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(text, encoding="utf-8")
    print(f"wrote {target}")
    return 0


def cmd_studio(args: argparse.Namespace) -> int:
    from hiru_ai.cli import tools

    target = Path(args.out or tools.STUDIO)
    target.write_text(tools.studio(_registry(args.root)), encoding="utf-8")
    print(f"wrote {target}; run `langgraph dev` to open the systems")
    return 0


def cmd_remove(args: argparse.Namespace) -> int:
    from hiru_ai.cli import tools

    if args.group:
        if args.kind or args.id:
            raise HiruAIError("give a part (<kind> <id>) or --group <id>, not both")
        lines = tools.remove_group(_registry(args.root), args.group, yes=args.yes)
    elif args.kind and args.id:
        lines = tools.remove(_registry(args.root), args.kind, args.id, yes=args.yes)
    else:
        raise HiruAIError("name a part (<kind> <id>) or a group (--group <id>)")
    for line in lines:
        print(line)
    if not args.yes:
        print("nothing changed; add --yes to do it, then `hiru-ai validate`")
    return 0


def cmd_eval(args: argparse.Namespace) -> int:
    from hiru_ai.cli import evals

    if args.ab:
        sides = tuple(args.ab.split(","))
        if len(sides) != 2 or not args.agent:
            print("--ab needs one agent and two manifests: hiru-ai eval <agent> --ab old.yaml,current", file=sys.stderr)
            return 2
        runs = evals.run_ab(_registry(args.root), args.agent, (sides[0], sides[1]), live=args.live)
        print(evals.report_ab(args.agent, (sides[0], sides[1]), runs))
        return 0 if all(r.passed for run in runs for r in run) else 1
    results = evals.run_all(_registry(args.root), args.agent, live=args.live,
                            prompt=Path(args.prompt) if args.prompt else None, tools=args.tools)
    print(evals.report(results))
    return 0 if results and all(r.passed for r in results) else 1


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="hiru-ai", description="Parts of the Hiru AI package: list, check, create.")
    p.add_argument("--root", help="another hiru_ai folder to work on (tests)")
    sub = p.add_subparsers(dest="command", required=True)
    ls = sub.add_parser("list", help="every part with its status")
    ls.add_argument("kind", nargs="?", choices=mf.KINDS)
    ls.add_argument("--group", help="only the parts of this group (agents/<group>/, ...)")
    ls.set_defaults(run=cmd_list)
    val = sub.add_parser("validate", help="check ids, schemas, prompts, evals and references")
    val.add_argument("--no-import", action="store_true", help="skip importing each part's code")
    val.set_defaults(run=cmd_validate)
    new = sub.add_parser("new", help="scaffold a part")
    new.add_argument("kind", choices=mf.KINDS)
    new.add_argument("id")
    new.add_argument("--pattern", default="sequential", help="panel pattern")
    new.add_argument("--effect", default="read", choices=("read", "stage", "write"),
                     help="tool: what a call may change (read = nothing, stage = leaves a card, write = systems only)")
    new.add_argument("--wraps", default="", metavar="STEP", help="tool: the step it is a thin wrapper for")
    new.add_argument("--group", default="", help="write the part into <layer>/<group>/ (its id starts '<group>_')")
    new.set_defaults(run=cmd_new)
    run = sub.add_parser("run", help="run one step, tool or agent alone on a case file")
    run.add_argument("kind", choices=("step", "tool", "agent"))
    run.add_argument("id")
    run.add_argument("--input", required=True, help="a JSON case file ('-' reads stdin)")
    run.add_argument("--live", action="store_true",
                     help="tools: the real adapters instead of in-memory fakes; agents: the real model (costs money)")
    run.add_argument("--allow-writes", action="store_true", help="with --live, let a tool that writes do so")
    run.add_argument("--format", choices=("concise", "detailed"),
                     help="tools: the response_format to ask for (unless the case sets one)")
    run.set_defaults(run=cmd_run)
    mcp = sub.add_parser("mcp", help="serve the read and stage tools over MCP on stdio (scope = this command line)")
    mcp.add_argument("--production", help="the one production the server may read (a uuid)")
    mcp.add_argument("--scene", help="the scene tools default to (a uuid)")
    mcp.add_argument("--corpora", default="production_docs,memory", help="the corpora search_kb may read")
    mcp.add_argument("--fixtures", metavar="CASE", help="offline: in-memory ports from a tool's examples/basic.json")
    mcp.set_defaults(run=cmd_mcp)
    rev = sub.add_parser("review", help="per-tool calls, errors and cut answers from a log file (the monthly look)")
    rev.add_argument("log", help="a log file holding the `hiru_ai.tool` lines")
    rev.set_defaults(run=cmd_review)
    ing = sub.add_parser("ingest", help="index knowledge bases into the database")
    ing.add_argument("kb", nargs="*", help="knowledge base ids (see `hiru-ai list knowledge_base`)")
    ing.add_argument("--all", action="store_true", help="every base that is ingested from files or tables")
    ing.add_argument("--dry-run", action="store_true", help="show what would be indexed; write nothing, embed nothing")
    ing.add_argument("--include-short-form", action="store_true",
                     help="also index the ad / social / video-format terms (left out for Hiru's drama)")
    ing.set_defaults(run=cmd_ingest)
    gr = sub.add_parser("graph", help="a system or panel as Mermaid text")
    gr.add_argument("id")
    gr.add_argument("--out", help="write to a file instead of printing")
    gr.set_defaults(run=cmd_graph)
    cat = sub.add_parser("catalog", help="write docs/AI_CATALOG.md (every part, owner, tier, uses, used by)")
    cat.add_argument("--check", action="store_true", help="fail when the file is out of date (CI)")
    cat.add_argument("--out", help="another file")
    cat.set_defaults(run=cmd_catalog)
    st = sub.add_parser("studio", help="write langgraph.json so LangGraph Studio opens every system and panel")
    st.add_argument("--out", help="another file")
    st.set_defaults(run=cmd_studio)
    ev = sub.add_parser("eval", help="run every agent's eval cases (scripted by default; --live asks the real model)")
    ev.add_argument("agent", nargs="?", help="one agent id (default: all)")
    ev.add_argument("--live", action="store_true", help="the real model answers the inputs (costs money)")
    ev.add_argument("--prompt", help="another system prompt file for the agent: the other side of an A/B")
    ev.add_argument("--ab", metavar="OLD,NEW",
                    help="two manifests of the agent (a component.yaml path, `current`, or `base` / `tools` for the "
                         "single call and its with_tools form): the same cases through each, with tokens, model "
                         "calls, tool calls and tool errors side by side")
    ev.add_argument("--tools", action="store_true", help="only the agent's `with_tools` form (agents that have one)")
    ev.set_defaults(run=cmd_eval)
    rm = sub.add_parser("remove", help="delete a part, or a whole --group, and list what names it "
                                       "(dry run without --yes)")
    rm.add_argument("kind", nargs="?", choices=mf.KINDS)
    rm.add_argument("id", nargs="?")
    rm.add_argument("--group", default="", help="remove a group: its folder in every layer and its other folders")
    rm.add_argument("--yes", action="store_true", help="do it")
    rm.set_defaults(run=cmd_remove)
    return p


def main(argv: Sequence[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):  # Sinhala and arrows in output; a Windows console defaults to cp1252
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
    args = parser().parse_args(argv)
    try:
        return int(args.run(args))
    except HiruAIError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
