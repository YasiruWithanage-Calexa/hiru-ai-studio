"""plan/2026-11-04 Phase 3: the tools over MCP, a span per tool call, and the monthly review of how tools are used."""
from __future__ import annotations

import io
import json
import logging
from contextlib import contextmanager
from types import SimpleNamespace
from typing import Any

import pytest

from hiru_ai.cli import mcp, review
from hiru_ai.core import telemetry
from hiru_ai.core.registry import default
from hiru_ai.core.telemetry import ToolEvent
from hiru_ai.core.testing import example_ctx, example_of

REG = default()


def server(tool: str = "plan_try") -> mcp.McpServer:
    return mcp.McpServer(REG, example_ctx(example_of(tool)))


def ask(srv: mcp.McpServer, method: str, params: dict[str, Any] | None = None, ident: int = 1) -> dict[str, Any]:
    out = srv.handle({"jsonrpc": "2.0", "id": ident, "method": method, "params": params or {}})
    assert out is not None
    return out


# ── MCP ──────────────────────────────────────────────────────────────────────────────────────────────────────────────


def test_initialize_names_the_protocol_and_offers_tools():
    result = ask(server(), "initialize", {"protocolVersion": "2025-06-18"})["result"]
    assert result["protocolVersion"] == mcp.PROTOCOL and "tools" in result["capabilities"]


def test_every_read_and_stage_tool_is_listed_and_no_write_tool_ever_is():
    listed = {t["name"]: t for t in ask(server(), "tools/list")["result"]["tools"]}
    for ident in REG.ids("tool"):
        effect = REG.get("tool", ident).manifest.effect  # type: ignore[union-attr]
        assert (ident in listed) == (effect != "write"), ident
    assert not {"scene_write", "shot_write", "canon_write", "structure_write", "image_generate"} & set(listed)


def test_a_listed_tool_carries_the_agents_description_the_schemas_and_hints_from_its_effect():
    listed = {t["name"]: t for t in ask(server(), "tools/list")["result"]["tools"]}
    read, stage = listed["shot_read"], listed["change_propose"]
    assert read["annotations"]["readOnlyHint"] is True and stage["annotations"]["readOnlyHint"] is False
    assert all(t["annotations"]["destructiveHint"] is False for t in listed.values())
    assert "Do not use" in read["description"]
    assert read["inputSchema"]["type"] == "object" and "properties" in read["outputSchema"]


def test_a_call_returns_the_tools_json_as_text_and_as_structured_content():
    result = ask(server(), "tools/call", {"name": "plan_try", "arguments": example_of("plan_try")["args"]})["result"]
    assert result["isError"] is False
    assert json.loads(result["content"][0]["text"]) == result["structuredContent"]
    assert result["structuredContent"]["nothing_saved"] is True


def test_a_refused_call_is_a_tool_error_that_teaches():
    srv = server("shot_read")
    result = ask(srv, "tools/call", {"name": "shot_read", "arguments": {"shot": "S99", "scene": "E1S2"}})["result"]
    body = json.loads(result["content"][0]["text"])
    assert result["isError"] is True and "how_to_fix" in body and "structuredContent" not in result


def test_arguments_that_do_not_fit_the_schema_are_a_tool_error_naming_the_field():
    result = ask(server(), "tools/call", {"name": "plan_try", "arguments": {"ops": []}})["result"]
    assert result["isError"] is True and "ops" in result["content"][0]["text"]


def test_an_unknown_tool_and_a_write_tool_are_protocol_errors():
    for name in ("nope", "scene_write"):
        assert ask(server(), "tools/call", {"name": name, "arguments": {}})["error"]["code"] == mcp.INVALID_PARAMS


def test_a_stage_tool_leaves_its_card_in_the_servers_memory_only():
    srv = server("change_propose")
    args = {"summary": "Open on a close-up.", "ops": [{"op": "set", "shot": 1, "field": "framing", "value": "CU"}]}
    result = ask(srv, "tools/call", {"name": "change_propose", "arguments": args})["result"]
    assert result["isError"] is False and result["structuredContent"]["staged"] is True
    assert [c["kind"] for c in srv.ctx.ports.staging.staged()] == ["change"]  # type: ignore[union-attr]


def test_a_notification_is_not_answered_and_bad_input_is_a_json_rpc_error():
    srv = server()
    assert srv.handle({"jsonrpc": "2.0", "method": "notifications/initialized"}) is None
    assert ask(srv, "no/such")["error"]["code"] == mcp.METHOD_NOT_FOUND
    out = io.StringIO()
    srv.serve(["not json\n", "\n", json.dumps({"jsonrpc": "2.0", "id": 7, "method": "ping"}) + "\n"], out)
    lines = [json.loads(x) for x in out.getvalue().splitlines()]
    assert lines[0]["error"]["code"] == mcp.PARSE_ERROR and lines[1] == {"jsonrpc": "2.0", "id": 7, "result": {}}


def test_the_cli_serves_over_stdin_and_stdout(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str],
                                              tmp_path: Any):
    from hiru_ai.cli.main import main

    case = tmp_path / "case.json"
    case.write_text(json.dumps(example_of("shot_read")), encoding="utf-8")
    request = json.dumps({"jsonrpc": "2.0", "id": 1, "method": "tools/list"}) + "\n"
    monkeypatch.setattr("sys.stdin", io.StringIO(request))
    assert main(["mcp", "--fixtures", str(case)]) == 0
    assert json.loads(capsys.readouterr().out)["result"]["tools"]


def test_without_a_production_or_fixtures_the_server_refuses_to_start(capsys: pytest.CaptureFixture[str]):
    from hiru_ai.cli.main import main

    assert main(["mcp"]) == 2 and "--production" in capsys.readouterr().err


# ── a span per tool call ─────────────────────────────────────────────────────────────────────────────────────────────


class Span:
    def __init__(self) -> None:
        self.attributes: dict[str, Any] = {}

    def set_attribute(self, key: str, value: Any) -> None:
        self.attributes[key] = value


def test_a_tool_call_is_a_span_with_its_id_version_effect_and_cost_but_never_its_arguments(
        monkeypatch: pytest.MonkeyPatch):
    from opentelemetry import trace

    spans: list[tuple[str, Span]] = []

    class Tracer:
        @contextmanager
        def start_as_current_span(self, name: str) -> Any:
            span = Span()
            spans.append((name, span))
            yield span

    monkeypatch.setattr(trace, "get_tracer", lambda name: Tracer())
    ctx = example_ctx(example_of("shot_read"))
    REG.module("tool", "shot_read", "tool").as_tool().func(SimpleNamespace(context=ctx), shot="S01", scene="E1S2")
    assert [name for name, _ in spans] == ["tool shot_read"]
    attrs = spans[0][1].attributes
    assert attrs["hiru.tool.id"] == "shot_read" and attrs["hiru.tool.effect"] == "read"
    assert attrs["hiru.tool.result_tokens"] > 0 and attrs["hiru.tool.error"] == ""
    assert not any("S01" in str(v) for v in attrs.values())


def test_the_span_is_a_no_op_without_opentelemetry(monkeypatch: pytest.MonkeyPatch):
    import builtins

    real = builtins.__import__

    def refuse(name: str, *a: Any, **k: Any) -> Any:
        if name.startswith("opentelemetry"):
            raise ImportError(name)
        return real(name, *a, **k)

    monkeypatch.setattr(builtins, "__import__", refuse)
    with telemetry.tool_span("x", 1, "read") as finish:
        finish(ToolEvent("x", 1.0, 1))


# ── the monthly review ───────────────────────────────────────────────────────────────────────────────────────────────


def lines(*events: ToolEvent) -> list[str]:
    return [f"INFO hiru_ai.tool: tool={e.tool} ms={e.ms} result_tokens={e.result_tokens} error={e.error or '-'} "
            f"truncated={e.truncated}" for e in events]


def test_the_review_reads_the_tool_lines_the_runtime_logs(caplog: pytest.LogCaptureFixture):
    caplog.set_level(logging.INFO, logger="hiru_ai.tool")
    telemetry.log_tool_event(ToolEvent("shot_read", 12.5, 300, "refused", True))
    use = review.read(caplog.text.splitlines())
    assert use["shot_read"].calls == 1 and use["shot_read"].refused == 1 and use["shot_read"].cut == 1


def test_a_tool_that_fails_or_is_refused_too_often_is_flagged_with_what_to_fix():
    events = [ToolEvent("shot_read", 5.0, 100, "refused")] * 3 + [ToolEvent("shot_read", 5.0, 100)] * 7
    text = review.report(review.read(lines(*events)))
    assert "shot_read" in text and "30% of calls fail or are refused" in text and "guide" in text


def test_a_tool_whose_answers_are_often_cut_is_flagged_and_one_never_called_is_listed():
    events = [ToolEvent("scene_read", 5.0, 1800, "", True)] * 5 + [ToolEvent("scene_read", 5.0, 200)] * 5
    text = review.report(review.read(lines(*events)), listed=["scene_read", "frame_read"])
    assert "50% of answers are cut" in text and "frame_read: never called" in text


def test_a_clean_month_has_nothing_to_look_at_and_an_empty_log_says_so():
    ok = review.report(review.read(lines(*[ToolEvent("canon_read", 4.0, 90)] * 20)))
    assert "To look at" not in ok and "20 calls, 0 errors" in ok
    assert "no tool calls" in review.report(review.read(["unrelated line"]))


def test_the_cli_reads_a_log_file(tmp_path: Any, capsys: pytest.CaptureFixture[str]):
    from hiru_ai.cli.main import main

    log = tmp_path / "app.log"
    log.write_text("\n".join(lines(ToolEvent("canon_read", 4.0, 90))), encoding="utf-8")
    assert main(["review", str(log)]) == 0
    assert "canon_read" in capsys.readouterr().out
