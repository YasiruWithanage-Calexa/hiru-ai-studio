"""Phase 2 exit (plan/2026-11-04b §10, §7): the adam_film_grammar knowledge base has 40 devices with all their fields,
the principles, the house and Veo notes, and a question a director would ask finds the right device.

The probe test runs OFFLINE with a small keyword ranker, a proxy for the database's full-text half. It shows the texts
are findable by the way a director asks; the real check is the same queries through `search_kb` after
`hiru-ai ingest adam_film_grammar`, which writes to the hosted dev database and so waits for a person.
"""
from __future__ import annotations

import json
import math
import re
from collections import Counter
from typing import Any

import pytest
from tests.adam import gold

from hiru_ai.core.fakes import FakeKnowledge
from hiru_ai.core.registry import Registry
from hiru_ai.rag import knowledge

REG = Registry().discover()
KB = knowledge.load("adam_film_grammar", REG)
SRC = KB.sources

DEVICE_FIELDS = ("Ask it as", "What it does to the viewer", "Use it when", "Do not use it when", "Allowed kind",
                 "Veo feasibility", "On a card", "Example (a Hiru-style scene)")
PRINCIPLE_FIELDS = ("Source", "The idea", "What Adam takes", "Use it when", "Do not use it when")
KINDS_OF_DEVICE = ("baseline", "reaction", "listener", "insert_detail", "hands", "pov", "atmosphere", "hold", "plant",
                   "transition", "empty_frame", "implied_action", "move", "performance", "sound choice",
                   "camera choice", "composition", "size choice", "treatment", "cut_in", "plain script moments",
                   "hold /", "empty_frame /")
VEO = ("good", "risky", "post-only")


def fields_of(text: str) -> dict[str, str]:
    return {m.group(1): m.group(2).strip() for m in re.finditer(r"^\*\*(.+?)\.\*\*\s+(.+?)$", text, re.M)}


def devices() -> list[Any]:
    return sorted((SRC / "devices").glob("*.md"))


def test_the_base_is_in_the_group_with_its_own_source_prefix():
    comp = REG.get("knowledge_base", "adam_film_grammar")
    assert comp.group == "adam" and comp.package == "hiru_ai.knowledge_bases.adam.adam_film_grammar"
    assert KB.manifest.source_prefix == "knowledge_base/adam_film_grammar/"
    others = {c.manifest.source_prefix for k, c in REG.components.items()
              if k[0] == "knowledge_base" and k[1] != "adam_film_grammar"}
    assert not any(KB.manifest.source_prefix.startswith(o) or o.startswith(KB.manifest.source_prefix)
                   for o in others if o)  # no other base writes under it


def test_there_are_forty_devices_each_with_every_field():
    files = devices()
    assert len(files) == 40, len(files)
    titles = set()
    for path in files:
        text = path.read_text(encoding="utf-8")
        got = fields_of(text)
        missing = [f for f in DEVICE_FIELDS if not got.get(f)]
        assert not missing, f"{path.name} lacks {missing}"
        assert text.count("\n# ") == 1  # one device per chunk
        titles.add(re.search(r"^# (.+)$", text, re.M).group(1))  # type: ignore[union-attr]
    assert len(titles) == 40


def test_each_devices_allowed_kind_is_one_of_the_plans_or_says_what_it_is_instead():
    for path in devices():
        kind = fields_of(path.read_text(encoding="utf-8"))["Allowed kind"]
        assert any(kind.startswith(k) for k in KINDS_OF_DEVICE), f"{path.name}: {kind}"


def test_each_device_rates_its_veo_feasibility():
    manifest = {f.path: f.meta for f in KB.manifest.files}
    for path in devices():
        veo = fields_of(path.read_text(encoding="utf-8"))["Veo feasibility"]
        assert any(veo.startswith(v) for v in VEO), f"{path.name}: {veo}"
        assert manifest[f"devices/{path.name}"]["veo"] in ("good", "risky", "post-only")


def test_the_devices_cover_the_plans_first_list():
    text = " ".join(p.read_text(encoding="utf-8").lower() for p in devices())
    for needle in ("baseline", "smile that outlives", "listener", "reaction before", "plant", "cup gone cold",
                   "hands", "subjective sound", "silence before", "pre-lap", "sound arriving", "rack focus", "push-in",
                   "pull-out", "high angle", "low angle", "foreground", "negative space", "empty frame", "pov insert",
                   "reveal", "held wide", "match cut", "mirror", "weather", "walk-and-talk", "back", "standing",
                   "unanswered", "interrupted", "delayed", "cut on the look", "enter late", "leave early", "button",
                   "callback", "long take", "intercut", "contrast cut", "pillow"):
        assert needle in text, needle


def test_there_is_one_principle_for_each_source_in_the_plan():
    files = sorted((SRC / "principles").glob("*.md"))
    assert len(files) >= 15
    for path in files:
        got = fields_of(path.read_text(encoding="utf-8"))
        assert all(got.get(f) for f in PRINCIPLE_FIELDS), path.name
        assert len(path.read_text(encoding="utf-8").split()) < 330  # paraphrased rules, not long quotes


def test_the_house_and_veo_notes_exist_and_the_house_notes_say_they_are_a_draft():
    house = (SRC / "house-drama-notes.md").read_text(encoding="utf-8")
    assert "DRAFT" in house and "not" in house.lower()
    veo = (SRC / "veo-feasibility.md").read_text(encoding="utf-8")
    for needle in ("4, 6 or 8", "2.2 words", "Readable text", "Mirrors", "Crowds", "Workarounds"):
        assert needle in veo, needle


def test_the_manifest_lists_every_source_file_and_nothing_else():
    listed = {f.path for f in KB.manifest.files}
    on_disk = {p.relative_to(SRC).as_posix() for p in SRC.rglob("*.md")}
    assert listed == on_disk and len(listed) == 58


def test_an_ingest_dry_run_makes_chunks_for_every_file_under_the_prefix():
    report = KB.ingest(FakeKnowledge(), lambda texts: [None] * len(texts), "test-model", dry_run=True)
    assert report.chunks >= 58 and len(report.by_source) == 58
    assert all(s.startswith("knowledge_base/adam_film_grammar/") for s in report.by_source)
    items = KB.items("test-model")
    assert all(i.row["corpus"] == "craft" and i.row["source"].startswith(KB.manifest.source_prefix) for i in items)
    assert all(i.row["context_header"] for i in items)


def test_a_real_ingest_into_the_fake_store_replaces_only_its_own_rows():
    other = {"corpus": "craft", "source": "knowledge_base/craft/editing.md", "content_hash": "x", "embedding": None}
    store = FakeKnowledge(chunks=[other])
    KB.ingest(store, lambda texts: [None] * len(texts), "test-model")
    assert other in store.chunk_rows  # the craft base's rows are untouched
    assert sum(r["source"].startswith(KB.manifest.source_prefix) for r in store.chunk_rows) >= 58
    again = len(store.chunk_rows)
    KB.ingest(store, lambda texts: [None] * len(texts), "test-model")
    assert len(store.chunk_rows) == again  # idempotent


# ── the probes, with a small offline keyword ranker ─────────────────────────────────────────────


STOP = frozenset("a an the to of in on for and or is are do does how what which can i my it that this with when so you "
                 "we they be as at by from if no not into than then them their there these those up out over".split())


def stem(word: str) -> str:
    for suffix in ("ing", "ed", "es", "s"):
        if word.endswith(suffix) and len(word) > len(suffix) + 3:
            return word[: -len(suffix)]
    return word


def tokens(text: str) -> list[str]:
    return [stem(w) for w in re.findall(r"[a-z]+", text.lower()) if w not in STOP and len(w) > 1]


def rank(query: str, rows: list[dict[str, Any]]) -> list[str]:
    """Sources best-first by BM25 over each chunk's header and content."""
    docs = [(r["source"], Counter(tokens(f"{r['context_header']} {r['content']}"))) for r in rows]
    n, avg = len(docs), sum(sum(c.values()) for _, c in docs) / len(docs)
    df = Counter(t for _, c in docs for t in c)
    scored = []
    for source, c in docs:
        length = sum(c.values())
        norm = 1.2 * (0.25 + 0.75 * length / avg)
        score = sum(math.log(1 + (n - df[t] + 0.5) / (df[t] + 0.5)) * c[t] * 2.2 / (c[t] + norm)
                    for t in set(tokens(query)) if t in c)
        scored.append((score, source))
    best: dict[str, float] = {}
    for score, source in scored:
        best[source] = max(best.get(source, 0.0), score)
    return [s for s, _ in sorted(best.items(), key=lambda kv: (-kv[1], kv[0]))]


PROBES = json.loads((gold.GOLD / "kb_probes.json").read_text(encoding="utf-8"))


@pytest.mark.parametrize("probe", PROBES["probes"], ids=lambda p: p["id"])
def test_a_question_a_director_would_ask_finds_the_right_device(probe: dict[str, Any]):
    rows = [i.row for i in KB.items("test-model")]
    top = [s.removeprefix(KB.manifest.source_prefix) for s in rank(probe["query"], rows)[: PROBES["k"]]]
    assert any(e in top for e in probe["expect"]), f"{probe['query']!r} -> {top}"


def test_there_are_ten_probes_and_none_repeats_a_devices_title():
    assert len(PROBES["probes"]) == 10
    titles = {re.search(r"^# (.+)$", p.read_text(encoding="utf-8"), re.M).group(1).lower()  # type: ignore[union-attr]
              for p in devices()}
    assert not any(p["query"].lower().rstrip("?") in titles for p in PROBES["probes"])
