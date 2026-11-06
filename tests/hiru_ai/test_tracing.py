"""Tracing (ADR 0008): both keys are needed, and tests never send a trace."""
from __future__ import annotations

from pydantic import SecretStr

from hiru_ai.core import telemetry
from hiru_ai.core.settings import AISettings


def test_both_keys_needed() -> None:
    assert not AISettings(_env_file=None, langfuse_public_key="", langfuse_secret_key=SecretStr("")).tracing
    assert not AISettings(_env_file=None, langfuse_public_key="pk", langfuse_secret_key=SecretStr("")).tracing
    assert AISettings(_env_file=None, langfuse_public_key="pk", langfuse_secret_key=SecretStr("sk")).tracing


def test_quotes_a_launcher_kept_are_dropped() -> None:
    s = AISettings(_env_file=None, langfuse_public_key='"pk"', langfuse_secret_key="'sk'",
                   langfuse_base_url='"https://jp.cloud.langfuse.com"')
    assert (s.langfuse_public_key, s.langfuse_secret_key.get_secret_value()) == ("pk", "sk")
    assert s.langfuse_base_url == "https://jp.cloud.langfuse.com"


def test_tests_never_trace() -> None:
    keys = AISettings(_env_file=None, langfuse_public_key="pk", langfuse_secret_key=SecretStr("sk"))
    assert telemetry.enable_tracing(keys) is False
    assert not telemetry._enabled
