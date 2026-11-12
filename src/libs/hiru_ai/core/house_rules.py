"""House rules: the studio's own craft rules, always given to the agents that subscribe to them (plan/2026-11-12 §3.1).

A rule is one file in `hiru_ai/house_rules/`: a short YAML header, a `---` line, then the rule's text.

    id: H-12
    topics: [objects, sound]
    kind: default          # default: the production's direction or a scene note may override it; must: nothing does
    why: A voice from a device reads as invented unless its source is seen.
    version: 2
    ---
    Implied things. A script often implies an object it does not name: ...

An agent subscribes in its manifest with `house_rules: [objects, sound]` (or `*`) and the `house_rules` middleware,
which appends the matching rules to the END of the system prompt. Unlike a knowledge base, nothing is searched: a
subscribed rule is always given. The rules change only with a deploy, so an agent's block is the same bytes on every
call and the cached prompt prefix stays cached. A rule is guidance a person reads and changes, never code: what must
hold whatever a model writes belongs in a check.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from functools import cache
from pathlib import Path

import yaml

from hiru_ai.core.errors import ManifestError

FOLDER = Path(__file__).resolve().parents[1] / "house_rules"
ALL = "*"
KINDS = ("default", "must")
_ID = re.compile(r"^H-\d{2,3}$")
_TOPIC = re.compile(r"^[a-z][a-z0-9_]*$")
_HEADER_KEYS = {"id", "topics", "kind", "why", "version"}
HEADING = (
    "HOUSE RULES (the studio's own rules. A `default` rule yields to the production's direction and to the scene's "
    "notes; a `must` rule never does. When you follow a production's direction over a default rule, say so.)"
)


@dataclass(frozen=True)
class Rule:
    id: str
    topics: tuple[str, ...]
    kind: str
    why: str
    version: int
    text: str
    file: str

    @property
    def label(self) -> str:
        return f"{self.id} v{self.version}"


def _whole(x: object) -> bool:
    return isinstance(x, int) and not isinstance(x, bool)


def parse(path: Path) -> Rule:
    """One rule file, or ManifestError naming the file and what is wrong with it."""
    raw = path.read_text(encoding="utf-8").replace("\r\n", "\n")
    head, sep, body = raw.partition("\n---\n")
    if not sep:
        raise ManifestError(f"house rule {path.name}: the header must end with a line '---'")
    try:
        meta = yaml.safe_load(head) or {}
    except yaml.YAMLError as exc:
        raise ManifestError(f"house rule {path.name}: the header is not YAML ({exc})") from exc
    if not isinstance(meta, dict) or set(meta) != _HEADER_KEYS:
        raise ManifestError(f"house rule {path.name}: the header has exactly {', '.join(sorted(_HEADER_KEYS))}")
    rid, topics, kind, why, version = (meta[k] for k in ("id", "topics", "kind", "why", "version"))
    text = " ".join(body.split())
    problems = [
        *([] if isinstance(rid, str) and _ID.match(rid) else [f"id {rid!r} is not like H-12"]),
        *(
            []
            if isinstance(topics, list) and topics and all(isinstance(t, str) and _TOPIC.match(t) for t in topics)
            else ["topics is a list of lower-case words"]
        ),
        *([] if kind in KINDS else [f"kind is one of {', '.join(KINDS)}"]),
        *([] if isinstance(why, str) and why.strip() else ["why is a sentence"]),
        *([] if _whole(version) and version >= 1 else ["version is 1 or more"]),
        *([] if text else ["the rule has no text"]),
    ]
    if problems:
        raise ManifestError(f"house rule {path.name}: " + "; ".join(problems))
    return Rule(
        id=rid, topics=tuple(topics), kind=kind, why=" ".join(why.split()), version=version, text=text, file=path.name
    )


def load(folder: Path = FOLDER) -> tuple[Rule, ...]:
    """Every rule in `folder`, sorted by id (so the block's bytes never move). Ids are unique."""
    rules = sorted((parse(p) for p in sorted(folder.glob("*.md"))), key=lambda r: r.id)
    seen: dict[str, str] = {}
    for r in rules:
        if r.id in seen:
            raise ManifestError(f"house rule id {r.id} is in both {seen[r.id]} and {r.file}")
        seen[r.id] = r.file
    return tuple(rules)


@cache
def rules() -> tuple[Rule, ...]:
    """The deployed rules, read once."""
    return load()


def topics(given: tuple[Rule, ...] | None = None) -> set[str]:
    """Every topic some rule has."""
    return {t for r in (rules() if given is None else given) for t in r.topics}


def select(subscribed: tuple[str, ...] | list[str], given: tuple[Rule, ...] | None = None) -> list[Rule]:
    """The rules an agent subscribed to: every rule for `*`, else each rule with a topic in `subscribed`."""
    if not subscribed:
        return []
    pool = rules() if given is None else given
    if ALL in subscribed:
        return list(pool)
    wanted = set(subscribed)
    return [r for r in pool if wanted & set(r.topics)]


def block(chosen: list[Rule]) -> str:
    """The text appended to the system prompt: the heading, then one line a rule."""
    return HEADING + "\n" + "\n".join(f"- {r.id} ({r.kind}) {r.text}" for r in chosen)


def appended(system: str, subscribed: tuple[str, ...] | list[str]) -> str:
    """The system prompt as sent: the agent's own, then its rules' block (unchanged when it subscribes to none)."""
    chosen = select(subscribed)
    return f"{system}\n\n{block(chosen)}" if chosen else system
