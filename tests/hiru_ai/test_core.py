"""Settings, tiers, prompts, run context, checkpoints and the test double itself."""
from __future__ import annotations

from pathlib import Path
from uuid import uuid4

import pytest
from langgraph.graph import END, START, StateGraph
from typing_extensions import TypedDict

from hiru_ai.core import models as models_mod
from hiru_ai.core.checkpoint import saver, thread_config
from hiru_ai.core.context import RunContext
from hiru_ai.core.errors import ManifestError
from hiru_ai.core.prompts import Prompt
from hiru_ai.core.settings import AISettings, OpenAISettings, get_settings
from hiru_ai.core.testing import ScriptedChatModel
from hiru_ai.core.usage import UsageCallback, row, safely

# ── settings and tiers ───────────────────────────────────────────────────────────────────────


def test_settings_read_the_names_the_services_already_deploy(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("OPENAI__API_KEY", "sk-abc")
    monkeypatch.setenv("OPENAI__MODEL_HIGH", "gpt-next")
    monkeypatch.setenv("SUPABASE__DB_URL", "postgresql://x")
    get_settings.cache_clear()
    try:
        s = get_settings()
        assert s.openai.enabled and s.openai.model_high == "gpt-next" and s.supabase.db_url == "postgresql://x"
        assert "sk-abc" not in repr(s)  # the key never reaches a log line
    finally:
        get_settings.cache_clear()


def test_the_default_tiers_are_the_ones_the_engines_use_today():
    s = AISettings(openai=OpenAISettings())
    # Raphael's tiers are fixed in core/raphael_models.yaml (not settings) and checked in its group's tests
    # (tests/raphael/test_models_file.py), so removing it stays clean.
    got = {n: (t.model, t.effort) for n in models_mod.tier_names()
           if not n.startswith("raphael") and (t := models_mod.resolve(n, s))}
    assert got == {"ultra": ("gpt-5", "high"), "high": ("gpt-5", "medium"), "medium": ("gpt-5-mini", "low"),
                   "low": ("gpt-5-nano", "minimal"), "vision": ("gpt-5-mini", ""),
                   "fixer": ("gpt-5", "low"),  # the big rung of Adam's fixer ladder (plan/2026-11-05)
                   "author": ("gpt-5", "medium"), "repair": ("gpt-5", "low"),  # Shot Planner David (plan/2026-11-05e)
                   "jonathan": ("gpt-6.1-sol", "high"),  # Shot Planner Jonathan (plan/2026-11-06b)
                   "zora": ("gpt-6.1-sol", "low"),  # Zora: Jonathan's model at a lower effort (plan/2026-11-06e D7)
                   "reader": ("gpt-5", "medium"),  # the document reader: the author's model (plan/2026-11-06f Q1)
                   # Sable (plan/2026-11-08 §4.4): the average tier and the deep one a turn may move up to once
                   "sable": ("gpt-5-mini", "low"), "sable_deep": ("gpt-5", "medium")}
    assert all(models_mod.resolve(n, s).fallbacks == () for n in got)  # today's behaviour: no fallback tiers


def test_models_yaml_naming_a_setting_that_does_not_exist_is_refused(tmp_path: Path):
    bad = tmp_path / "m.yaml"
    bad.write_text("tiers:\n  a: { model: model_zzz }\nembed: { model: embedding_model, dimensions: "
                   "embedding_dimensions }\nimage: { model: model_image }\n", encoding="utf-8")
    file = models_mod.load_models.__wrapped__(bad)  # type: ignore[attr-defined]
    with pytest.raises(ManifestError, match="unknown OpenAI setting"):
        models_mod.resolve("a", AISettings(), file)


# ── prompts ──────────────────────────────────────────────────────────────────────────────────


def test_a_prompt_is_static_text_with_a_stable_hash(tmp_path: Path):
    path = tmp_path / "system.md"
    path.write_text("You are the editor.\n", encoding="utf-8")
    p = Prompt.load(path)
    assert p.text == "You are the editor.\n" and p.sha == Prompt.load(path).sha and len(p.sha) == 12
    assert p.system("Craft notes.") == "You are the editor.\n\n\nCraft notes."  # static first, then more static blocks
    assert p.system() == p.text
    path.write_text("You are the editor!\n", encoding="utf-8")
    assert Prompt.load(path).sha != p.sha


def test_a_missing_or_empty_prompt_is_a_manifest_error(tmp_path: Path):
    with pytest.raises(ManifestError, match="missing"):
        Prompt.load(tmp_path / "nope.md")
    (tmp_path / "empty.md").write_text(" \n", encoding="utf-8")
    with pytest.raises(ManifestError, match="empty"):
        Prompt.load(tmp_path / "empty.md")


# ── run context ──────────────────────────────────────────────────────────────────────────────


def test_the_run_context_stamps_ids_on_usage_rows_and_keys_threads_by_job():
    job, production, actor = uuid4(), uuid4(), uuid4()
    seen: list[dict[str, object]] = []
    ctx = RunContext(production_id=production, actor_user_id=actor, job_id=job, usage_sink=seen.append)
    sink = ctx.sink()
    assert sink is not None
    sink(row("p", "m", 1, 0, 2))
    assert seen == [{"phase": "p", "model": "m", "input_tokens": 1, "cached_input_tokens": 0, "output_tokens": 2,
                     "job_id": str(job), "production_id": str(production), "actor_user_id": str(actor)}]
    assert ctx.thread_id == str(job) and RunContext().thread_id == "adhoc" and RunContext().sink() is None


def test_usage_rows_have_exactly_the_token_usage_columns():
    assert set(row("p", "m")) == {"phase", "model", "input_tokens", "cached_input_tokens", "output_tokens"}


def test_safely_swallows_a_failing_sink():
    def boom(_: dict[str, object]) -> None:
        raise RuntimeError("down")

    safely(boom, row("p", "m"))
    safely(None, row("p", "m"))


# ── checkpoints ──────────────────────────────────────────────────────────────────────────────


class State(TypedDict):
    n: int


def test_without_a_database_the_checkpointer_is_in_memory_and_a_job_resumes_by_thread():
    def bump(state: State) -> State:
        return {"n": state["n"] + 1}

    graph = StateGraph(State)
    graph.add_node("bump", bump)
    graph.add_edge(START, "bump")
    graph.add_edge("bump", END)
    job = uuid4()
    with saver("") as (checkpointer, durable):
        assert durable is False
        app = graph.compile(checkpointer=checkpointer)
        assert app.invoke({"n": 1}, thread_config(job)) == {"n": 2}
        assert app.get_state(thread_config(job)).values == {"n": 2}  # the thread is the job
        assert app.get_state(thread_config(uuid4())).values == {}


# ── the test double ──────────────────────────────────────────────────────────────────────────


def test_the_scripted_model_answers_in_order_records_calls_and_runs_dry_like_an_unreachable_model():
    model = ScriptedChatModel(replies=["one", {"a": 1}])
    rows: list[dict[str, object]] = []
    cb = UsageCallback(rows.append, "p")
    assert model.invoke("hi", config={"callbacks": [cb]}).content == "one"
    assert model.invoke("again").content == '{"a": 1}'
    with pytest.raises(RuntimeError, match="no scripted reply"):
        model.invoke("third")
    assert len(model.calls) == 3 and rows[0]["input_tokens"] == 100 and rows[0]["model"] == "scripted"
