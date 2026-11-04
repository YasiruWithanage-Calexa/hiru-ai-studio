"""The parity safety net (plan/2026-11-03 Phase 0).

A *case* is a JSON fixture: what goes in (`input`: the scenario and the payload), what the fake
model says (`model`: scripted replies by schema name) and what today's engine did (`expected`).
`expected` is a normalised *outcome*: the pipeline's result, the job bookkeeping, the rows the fake
store ended up holding and the model calls made, in order. Ids are renamed by first appearance and
timestamps blanked, so a run is comparable with a recording made on another day.

The same fixtures later run against the new graphs: an adapter takes an `engine` name
(`legacy` today; `graph` once a system is migrated) and must return the same outcome.
"""
from __future__ import annotations

import dataclasses
import hashlib
import itertools
import json
import os
import re
import sys
from collections.abc import Callable, Iterator, Mapping
from contextlib import contextmanager
from datetime import date, datetime
from enum import Enum
from pathlib import Path
from typing import Any
from uuid import UUID

from tests.services.fakes import FakeLLM

ROOT = Path(__file__).resolve().parents[2]
FIXTURES = Path(__file__).parent / "fixtures"
for _service in sorted((ROOT / "src" / "services").iterdir()):  # each function runs from its own folder
    if _service.is_dir() and str(_service) not in sys.path:
        sys.path.insert(0, str(_service))
UPDATE = os.environ.get("PARITY_UPDATE") == "1"  # PARITY_UPDATE=1 pytest tests/parity rewrites `expected`

_UUID = re.compile(r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}")
# A 12- or 16-hex content hash, bare or versioned ("v1:..."). The engines hash row ids into these (a script's
# hash covers its line and character ids), and some of those ids are drawn once per test process, so a
# digest differs between processes. It is renamed by first appearance like an id: equal digests stay
# equal and different ones stay different, which is what staleness checks depend on.
_DIGEST = re.compile(r"^(v\d+:)?(?=[0-9]*[a-f])[0-9a-f]{12}(?:[0-9a-f]{4})?$")
_STAMP = re.compile(r"\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:?\d{2})?")


class Normaliser:
    """Turns anything an engine produced into plain JSON that does not depend on the run."""

    def __init__(self) -> None:
        self._ids: dict[str, str] = {}
        self._digests: dict[str, str] = {}

    def _id(self, raw: str) -> str:
        return self._ids.setdefault(raw.lower(), f"<id:{len(self._ids) + 1}>")

    def text(self, s: str) -> str:
        if m := _DIGEST.match(s):
            return (m.group(1) or "") + self._digests.setdefault(s, f"<digest:{len(self._digests) + 1}>")
        return _UUID.sub(lambda m: self._id(m.group(0)), _STAMP.sub("<ts>", s))

    def __call__(self, v: Any) -> Any:
        if v is None or isinstance(v, bool | int):
            return v
        if isinstance(v, float):
            return round(v, 6)
        if isinstance(v, str):
            return self.text(v)
        if isinstance(v, UUID):
            return self._id(str(v))
        if isinstance(v, datetime | date):
            return "<ts>"
        if isinstance(v, Enum):
            return self(v.value)
        if isinstance(v, bytes | bytearray):
            return f"<bytes:{len(v)}:{hashlib.sha256(bytes(v)).hexdigest()[:8]}>"
        if isinstance(v, Mapping):
            return {self.text(str(k)): self(x) for k, x in v.items()}
        if isinstance(v, set | frozenset):
            return sorted((self(x) for x in v), key=lambda x: json.dumps(x, sort_keys=True))
        if isinstance(v, list | tuple):
            return [self(x) for x in v]
        if hasattr(v, "model_dump"):
            return self(v.model_dump(mode="json"))
        if dataclasses.is_dataclass(v) and not isinstance(v, type):
            return self(dataclasses.asdict(v))
        return f"<{type(v).__name__}>"


@contextmanager
def seeded_ids(seed: str = "parity") -> Iterator[None]:
    """Make `uuid.uuid4()` repeat itself: ids come out in a fixed order for the length of a run.

    Content hashes in the engines (a scene's script hash, a reading's basis) are computed over row ids, so
    renaming ids afterwards would not make them comparable; making the ids themselves repeat does.
    """
    counter = itertools.count()
    real = os.urandom

    def urandom(n: int) -> bytes:
        if n != 16:  # uuid4 asks for exactly 16 bytes; everything else keeps real randomness
            return real(n)
        return hashlib.sha256(f"{seed}:{next(counter)}".encode()).digest()[:16]

    os.urandom = urandom
    try:
        yield
    finally:
        os.urandom = real


def sha(text: str) -> str:
    return "sha:" + hashlib.sha256(text.encode("utf-8")).hexdigest()[:12]


def replies(model: Mapping[str, Any]) -> dict[str, Callable[[str, str], dict[str, Any]]]:
    """The fixture's scripted model: `{"replies": {schema_name: [reply, ...]}}`, each used in order.

    A schema with no reply left raises, exactly as an unreachable model does, so the engine's
    absent-safe path (rules only) is part of what is recorded. Give the result to a FakeLLM
    (or a subclass) as its `responders`.
    """
    queues = {name: list(items) for name, items in (model.get("replies") or {}).items()}

    def answer(name: str) -> Callable[[str, str], dict[str, Any]]:
        def reply(system: str, user: str) -> dict[str, Any]:
            if not queues[name]:
                raise RuntimeError(f"no scripted reply left for {name}")
            return queues[name].pop(0)  # type: ignore[no-any-return]
        return reply

    return {name: answer(name) for name in queues}


def model_calls(llm: FakeLLM) -> list[dict[str, Any]]:
    """The model calls made, in order: schema, tier, phase and a hash of the system prompt (its static,
    cacheable prefix must not drift when the code moves)."""
    return [{"schema": c["schema"], "tier": c["tier"], "phase": c["phase"], "system": sha(c["system"])}
            for c in llm.calls]


def jobs_outcome(jobs: Any) -> dict[str, Any]:
    """FakeJobs → the bookkeeping a person (the status bar, the next hop) would see."""
    return {"status": jobs.status, "fields": jobs.fields, "events": jobs.events, "advanced": jobs.advanced}


def state(store: Any, *names: str) -> dict[str, Any]:
    """The named attributes of a fake store: the rows it ended up holding."""
    return {n: getattr(store, n) for n in names}


# ── fixtures ───────────────────────────────────────────────────────────────────────────────


def path_for(service: str, case: str) -> Path:
    return FIXTURES / service / f"{case}.json"


def load_all() -> list[tuple[str, str, dict[str, Any]]]:
    out = []
    for p in sorted(FIXTURES.glob("*/*.json")):
        out.append((p.parent.name, p.stem, json.loads(p.read_text(encoding="utf-8"))))
    return out


def dump(path: Path, fixture: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(fixture, indent=1, ensure_ascii=False, sort_keys=True) + "\n", encoding="utf-8")


def outcome(raw: dict[str, Any]) -> dict[str, Any]:
    """Normalise one adapter result (one Normaliser per run: ids are numbered across the whole outcome)."""
    return json.loads(json.dumps(Normaliser()(raw), sort_keys=True, ensure_ascii=False))  # type: ignore[no-any-return]
