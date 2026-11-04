"""`hiru-ai mcp`: the read and stage tools over the Model Context Protocol (plan/2026-11-04 §9.2).

    hiru-ai mcp --production <uuid> [--scene <uuid>] [--corpora production_docs,memory]
    hiru-ai mcp --fixtures examples.json            offline, on in-memory ports (a tool's examples/basic.json)

A stdio server (newline-delimited JSON-RPC 2.0, protocol 2025-06-18) that answers `initialize`, `ping`, `tools/list` and
`tools/call`. What it exposes follows the tool contract:

  * every active tool whose `effect` is `read` or `stage`; a `write` tool is never listed and a call to it is an unknown
    tool. `readOnlyHint` is true for a `read` tool, `destructiveHint` is false for all of them.
  * `inputSchema` is the tool's `Args`, `outputSchema` its `Result`; the description is the one an agent reads
    (summary + guide). A result is the tool's own JSON, already cut to its token budget, as text and as
    `structuredContent`.
  * a refused call or a bad argument is a TOOL error (`isError: true`) whose text carries `how_to_fix` and `example`, so
    the caller can correct itself, not a protocol error.

The scope is the launcher's, never the caller's (CLAUDE.md "AI and RAG"): the production, the scene and the corpora come
from the command line of whoever starts the process, as a `RunContext` comes from the trusted payload for an agent.
A `stage` tool leaves its card in an in-memory list that lives as long as the process; nothing is saved anywhere, and no
tool listed here can change stored data. Logs go to stderr, never stdout.
"""
from __future__ import annotations

import json
import sys
from collections.abc import Iterable
from types import SimpleNamespace
from typing import Any, TextIO

from pydantic import ValidationError

from hiru_ai.core import tooling
from hiru_ai.core.context import RunContext
from hiru_ai.core.manifest import ToolManifest
from hiru_ai.core.registry import Registry

PROTOCOL = "2025-06-18"
NAME, VERSION = "hiru-ai", "1"
INVALID_PARAMS, METHOD_NOT_FOUND, PARSE_ERROR, INVALID_REQUEST = -32602, -32601, -32700, -32600


class McpServer:
    def __init__(self, reg: Registry, ctx: RunContext) -> None:
        self.reg, self.ctx = reg, ctx
        self.exposed = sorted(i for (k, i), c in reg.components.items() if k == "tool" and c.manifest.status == "active"
                              and isinstance(c.manifest, ToolManifest) and c.manifest.effect != "write")

    # ── what is listed ─────────────────────────────────────────────────────────────────────────────────────────────

    def definition(self, ident: str) -> dict[str, Any]:
        manifest = self.reg.get("tool", ident).manifest
        assert isinstance(manifest, ToolManifest)
        module = self.reg.module("tool", ident, "tool")
        return {"name": ident, "title": ident.replace("_", " ").capitalize(),
                "description": tooling.description(manifest.summary, manifest.guide),
                "inputSchema": module.Args.model_json_schema(), "outputSchema": module.Result.model_json_schema(),
                "annotations": {"readOnlyHint": manifest.effect == "read", "destructiveHint": False,
                                "idempotentHint": manifest.effect == "read", "openWorldHint": False}}

    # ── a call ─────────────────────────────────────────────────────────────────────────────────────────────────────

    def call(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        module = self.reg.module("tool", name, "tool")
        try:
            module.Args.model_validate(arguments)
        except ValidationError as exc:  # a TOOL error: the caller reads it and calls again
            problems = "; ".join(f"{'.'.join(str(p) for p in e['loc']) or 'arguments'}: {e['msg']}"
                                 for e in exc.errors())
            return self._error({"error": f"the arguments are not valid ({problems})",
                                "how_to_fix": "Fix the arguments to match inputSchema and call again."})
        text = module.as_tool().func(SimpleNamespace(context=self.ctx), **arguments)
        data = json.loads(text)
        if isinstance(data, dict) and "error" in data:
            return self._error(data)
        return {"content": [{"type": "text", "text": text}], "isError": False,
                **({"structuredContent": data} if isinstance(data, dict) else {})}

    @staticmethod
    def _error(data: dict[str, Any]) -> dict[str, Any]:
        return {"content": [{"type": "text", "text": json.dumps(data, ensure_ascii=False)}], "isError": True}

    # ── the protocol ───────────────────────────────────────────────────────────────────────────────────────────────

    def handle(self, message: Any) -> dict[str, Any] | None:
        """The response to one JSON-RPC message, or None for a notification."""
        if not isinstance(message, dict) or message.get("jsonrpc") != "2.0" or "method" not in message:
            ident = message.get("id") if isinstance(message, dict) else None
            return _failure(ident, INVALID_REQUEST, "invalid request")
        method, ident, params = message["method"], message.get("id"), message.get("params") or {}
        if ident is None:  # a notification (initialized, cancelled ...) is not answered
            return None
        if method == "initialize":
            return _success(ident, {"protocolVersion": PROTOCOL, "capabilities": {"tools": {"listChanged": False}},
                                    "serverInfo": {"name": NAME, "version": VERSION},
                                    "instructions": "Read-only tools over one production, plus tools that stage a "
                                                    "card for a person; nothing here changes stored data."})
        if method == "ping":
            return _success(ident, {})
        if method == "tools/list":
            return _success(ident, {"tools": [self.definition(i) for i in self.exposed]})
        if method == "tools/call":
            name, arguments = params.get("name"), params.get("arguments") or {}
            if name not in self.exposed:
                return _failure(ident, INVALID_PARAMS, f"unknown tool: {name}")
            if not isinstance(arguments, dict):
                return _failure(ident, INVALID_PARAMS, "arguments must be an object")
            return _success(ident, self.call(str(name), arguments))
        return _failure(ident, METHOD_NOT_FOUND, f"method not found: {method}")

    def serve(self, lines: Iterable[str], out: TextIO) -> None:
        for line in lines:
            if not line.strip():
                continue
            try:
                response = self.handle(json.loads(line))
            except json.JSONDecodeError:
                response = _failure(None, PARSE_ERROR, "parse error")
            if response is not None:
                out.write(json.dumps(response, ensure_ascii=False) + "\n")
                out.flush()


def _success(ident: Any, result: dict[str, Any]) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": ident, "result": result}


def _failure(ident: Any, code: int, message: str) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": ident, "error": {"code": code, "message": message}}


def run(reg: Registry, ctx: RunContext, stdin: Iterable[str] | None = None, stdout: TextIO | None = None) -> int:
    McpServer(reg, ctx).serve(stdin if stdin is not None else sys.stdin, stdout or sys.stdout)
    return 0
