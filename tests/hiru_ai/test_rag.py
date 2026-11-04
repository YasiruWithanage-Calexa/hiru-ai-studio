"""Phase 3: retrieval primitives, rerankers and the knowledge bases (plan/2026-11-03 §7).

Nothing here reaches a model or a database: embeddings and the reranker are scripted fakes, the store is in memory.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import pytest
from langchain_core.embeddings import Embeddings

from hiru_ai.cli.main import main
from hiru_ai.core import llm
from hiru_ai.core.context import RunContext
from hiru_ai.core.fakes import FakeKnowledge, FakeSearch
from hiru_ai.core.registry import Registry, default
from hiru_ai.core.scope import corpora_of, scope_for
from hiru_ai.core.testing import ScriptedChatModel
from hiru_ai.rag import knowledge
from hiru_ai.rag.embeddings import embed_query, embed_texts
from hiru_ai.rag.hits import passages, to_hit
from hiru_ai.rag.ranking import (
    CANDIDATES,
    apply_order,
    candidates_for,
    mode_of,
    order_by_relevance,
    rerank_user,
)
from hiru_ai.rag.rerankers import LLMReranker
from hiru_ai.rag.retrievers import HybridRetriever, KeywordRetriever, MatchChunksRetriever, TechniqueRetriever
from hiru_ai.rag.scope import ready_documents

PRODUCTION = uuid4()


def row(n: int, **more: Any) -> dict[str, Any]:
    return {"id": str(UUID(int=n)), "corpus": "craft", "document_id": None, "source": "knowledge_base/craft/x.md",
            "ord": n,
            "heading": f"H{n}", "context_header": f"T — H{n}", "content": f"text {n}", "meta": {}, "score": 1.0 / n,
            **more}


def cid(n: int) -> str:
    return str(UUID(int=n))


def rows(count: int = 5) -> list[dict[str, Any]]:
    return [row(n) for n in range(1, count + 1)]


class Vec(Embeddings):
    def __init__(self, fail: bool = False) -> None:
        self.fail, self.batches = fail, []

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        if self.fail:
            raise RuntimeError("down")
        self.batches.append(list(texts))
        return [[float(len(t)), 0.0] for t in texts]

    def embed_query(self, text: str) -> list[float]:
        return self.embed_documents([text])[0]


# ── the rules both the API and the retrievers use ──────────────────────────────────────────────


def test_a_reranker_needs_a_pool_and_no_reranker_fetches_exactly_k():
    assert candidates_for(6, rerank=True) == CANDIDATES == 30
    assert candidates_for(6, rerank=False) == 6


def test_the_mode_says_whether_the_vector_half_ran():
    assert mode_of([0.1]) == "hybrid" and mode_of(None) == "text"


def test_a_rerank_keeps_relevant_passages_best_first_and_ties_in_arrival_order():
    ranking = [{"n": 0, "relevance": 1}, {"n": 1, "relevance": 3}, {"n": 2, "relevance": 0}, {"n": 3, "relevance": 3},
               {"n": 9, "relevance": 3}]  # 9 does not exist: ignored
    assert order_by_relevance(ranking, 5) == [1, 3, 0]  # 2 is unrelated, 4 was never scored
    assert apply_order(["a", "b", "c", "d"], [2, 0]) == ["c", "a"]


def test_the_rerank_user_message_is_the_one_the_api_always_sent():
    assert rerank_user("who?", ["alpha", "b" * 900]) == f"Question: who?\n\nPassages:\n[0]\nalpha\n\n[1]\n{'b' * 700}"


def test_only_ready_documents_with_a_wanted_role_are_searchable():
    docs = [{"id": "1", "status": "ready", "detected_role": "script", "confirmed_role": None},
            {"id": "2", "status": "processing", "detected_role": "script"},
            {"id": "3", "status": "ready", "detected_role": "script", "confirmed_role": "bible"},
            {"id": "4", "status": "ready", "detected_role": None, "confirmed_role": None}]
    from contracts.documents import DocumentRole

    assert list(ready_documents(docs)) == ["1", "3", "4"]
    assert list(ready_documents(docs, [DocumentRole.SCRIPT])) == ["1"], "a confirmed role beats the detected one"
    assert list(ready_documents(docs, [DocumentRole.BIBLE])) == ["3"]


def test_a_row_becomes_a_cited_hit():
    doc_id = str(uuid4())
    doc = {"id": doc_id, "filename": "script.pdf"}
    hit = to_hit(row(1, document_id=doc_id, vector_rank=1, meta={"page_start": 2, "page_end": 3}), {doc_id: doc}, True)
    assert hit.matched_by == ["vector", "rerank"] and hit.citation.filename == "script.pdf"
    assert (hit.citation.page_start, hit.citation.page_end) == (2, 3)
    assert passages([row(1)]) == ["T — H1\ntext 1"]


def test_the_api_side_modules_need_no_langchain():
    code = ("import sys; import hiru_ai.rag.ranking, hiru_ai.rag.scope, hiru_ai.rag.hits; "
            "assert 'langchain_core' not in sys.modules, 'the API would need LangChain'")
    done = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, check=False)  # noqa: S603
    assert done.returncode == 0, done.stderr


# ── retrievers ─────────────────────────────────────────────────────────────────────────────────


def retriever(cls: Any, search: FakeSearch, **kw: Any) -> Any:
    return cls(search=search, production_id=PRODUCTION, corpora=["craft"], k=3, **kw)


def test_documents_come_back_in_the_databases_order_and_the_scope_is_what_the_caller_set():
    search = FakeSearch(chunks=rows())
    got = retriever(MatchChunksRetriever, search, document_ids=["d1"]).invoke("shot size")
    assert [d.metadata["id"] for d in got] == [cid(1), cid(2), cid(3)] and got[0].page_content == "text 1"
    assert search.asked == [{"query": "shot size", "embedding": None, "production_id": str(PRODUCTION),
                             "corpora": ["craft"], "document_ids": ["d1"], "k": 3}]


def test_the_keyword_retriever_never_embeds_even_when_given_an_embedder():
    search = FakeSearch(chunks=rows())
    retriever(KeywordRetriever, search, embedder=lambda q: [1.0]).invoke("q")
    assert search.asked[0]["embedding"] is None


def test_the_hybrid_retriever_embeds_and_says_which_mode_ran():
    search = FakeSearch(chunks=rows())
    r = retriever(HybridRetriever, search, embedder=lambda q: [1.0, 2.0])
    found = r.retrieve("q")
    assert found.mode == "hybrid" and not found.reranked and len(found.rows) == 3
    assert search.asked[0]["embedding"] == [1.0, 2.0]
    assert retriever(HybridRetriever, FakeSearch(chunks=rows()), embedder=lambda q: None).retrieve("q").mode == "text"


def test_with_a_reranker_a_pool_is_fetched_reordered_and_cut_to_k():
    search = FakeSearch(chunks=rows(5))
    seen: list[Any] = []

    def rerank(query: str, texts: Any) -> list[int]:
        seen.append((query, list(texts)))
        return [4, 0, 2]  # c5, c1, c3 survive

    r = retriever(HybridRetriever, search, reranker=rerank)
    found = r.retrieve("q")
    assert [x["id"] for x in found.rows] == [cid(5), cid(1), cid(3)] and found.reranked
    assert search.asked[0]["k"] == CANDIDATES and len(seen[0][1]) == 5
    docs = r.invoke("q")
    assert docs[0].metadata["reranked"] is True and docs[0].metadata["mode"] == "text"


def test_a_reranker_that_has_no_answer_leaves_the_fusion_order():
    r = retriever(HybridRetriever, FakeSearch(chunks=rows(5)), reranker=lambda q, t: None)
    found = r.retrieve("q")
    assert [x["id"] for x in found.rows] == [cid(1), cid(2), cid(3)] and not found.reranked


def test_one_row_is_not_reranked():
    called: list[int] = []
    r = retriever(HybridRetriever, FakeSearch(chunks=rows(1)), reranker=lambda q, t: called.append(1) or [0])
    assert not r.retrieve("q").reranked and not called


def test_techniques_are_absent_safe():
    class Broken:
        def techniques(self, *a: Any) -> list[Any]:
            raise RuntimeError("rpc down")

    assert TechniqueRetriever(search=Broken(), k=2).rows("powerless") == []
    search = FakeSearch(techniques=[{"name": "Dolly zoom", "effect_text": "Unease. (Dolly zoom)"}])
    docs = TechniqueRetriever(search=search, k=2, embedder=lambda q: [0.5]).invoke("unease")
    assert docs[0].page_content.startswith("Unease") and search.asked[0]["embedding"] == [0.5]


# ── embeddings and the LLM reranker ────────────────────────────────────────────────────────────


def test_a_query_is_not_embedded_without_a_model_or_when_the_call_fails():
    assert embed_query("q", "t") is None  # tests run with an empty key
    assert embed_query("q", "t", embeddings=Vec(fail=True)) is None
    assert embed_query("q", "t", embeddings=Vec()) == [1.0, 0.0]


def test_texts_are_embedded_in_batches_and_all_none_without_a_model():
    assert embed_texts(["a", "b"], "t") == [None, None]
    model = Vec()
    out = embed_texts([str(n) for n in range(5)], "t", embeddings=model, batch=2)
    assert len(out) == 5 and [len(b) for b in model.batches] == [2, 2, 1]
    with pytest.raises(RuntimeError):  # an index must not be half-built in silence
        embed_texts(["a"], "t", embeddings=Vec(fail=True))


def test_the_llm_reranker_orders_by_score_and_reports_its_tokens():
    model = ScriptedChatModel(replies=[{"ranking": [{"n": 0, "relevance": 1}, {"n": 1, "relevance": 3},
                                                    {"n": 2, "relevance": 0}]}])
    usage: list[dict[str, Any]] = []
    with llm.use_models(model):
        assert LLMReranker(usage.append)("who is Kamala?", ["a", "b", "c"]) == [1, 0]
    system, user = model.calls[0]
    assert system.content.startswith("You judge which passages") and "Question: who is Kamala?" in user.content
    assert [u["phase"] for u in usage] == ["search.rerank"]


def test_the_llm_reranker_degrades_to_none():
    assert LLMReranker()("q", ["a", "b"]) is None  # no model
    with llm.use_models(ScriptedChatModel(replies=[])):  # the model fails
        assert LLMReranker()("q", ["a", "b"]) is None
    with llm.use_models(ScriptedChatModel(replies=[{"ranking": []}])):
        assert LLMReranker()("q", []) is None


# ── knowledge bases ────────────────────────────────────────────────────────────────────────────

REG = default()
MODEL = "text-embedding-3-large"


def fake_embed(texts: list[str]) -> list[list[float] | None]:
    return [[float(len(t))] for t in texts]


def test_the_plans_knowledge_bases_exist_and_say_who_fills_each():
    ungrouped = {i for i in REG.ids("knowledge_base") if not REG.get("knowledge_base", i).group}  # the adam group's
    assert ungrouped == {"craft", "guides", "rules", "cinematography", "techniques",  # base is tested in tests/adam
                         "production_docs"}
    assert REG.get("knowledge_base", "techniques").manifest.fed_by == "cinematography"  # type: ignore[union-attr]
    assert REG.get("knowledge_base", "production_docs").manifest.ingest == "upload"  # type: ignore[union-attr]


def test_a_base_filled_by_uploads_or_by_another_base_is_not_ingested_from_files():
    for ident in ("production_docs", "techniques"):
        with pytest.raises(Exception, match="fills it"):
            knowledge.load(ident, REG)


def test_the_craft_base_chunks_its_files_with_the_one_chunker():
    items = knowledge.load("craft", REG).items(MODEL)
    sources = {i.row["source"] for i in items}
    assert "knowledge_base/craft/cinematography.md" in sources and len(sources) == 9
    first = items[0]
    assert first.row["corpus"] == "craft" and first.row["meta"]["specialty"] == "audience"
    assert first.text == f"{first.row['context_header']}\n\n{first.row['content']}"
    assert first.row["content_hash"] == knowledge.content_hash(MODEL, first.text)
    assert knowledge.content_hash("other-model", first.text) != first.row["content_hash"]


def test_craft_guides_and_rules_share_a_corpus_but_not_their_rows():
    store = FakeKnowledge()
    for ident in ("craft", "guides", "rules"):
        knowledge.load(ident, REG).ingest(store, fake_embed, MODEL)
    by_prefix = {p: sum(r["source"].startswith(p) for r in store.chunk_rows)
                 for p in ("knowledge_base/craft/", "knowledge_base/guides/", "knowledge_base/rules/")}
    assert all(by_prefix.values()) and {r["corpus"] for r in store.chunk_rows} == {"craft"}
    again = knowledge.load("guides", REG).ingest(store, fake_embed, MODEL)  # re-running one base leaves the others
    assert again.chunks == by_prefix["knowledge_base/guides/"]
    assert {p: sum(r["source"].startswith(p) for r in store.chunk_rows) for p in by_prefix} == by_prefix


def test_an_unchanged_chunk_keeps_its_embedding_and_only_new_text_is_embedded():
    store, calls = FakeKnowledge(), []

    def embed(texts: list[str]) -> list[list[float] | None]:
        calls.append(len(texts))
        return fake_embed(texts)

    kb = knowledge.load("guides", REG)
    first = kb.ingest(store, embed, MODEL)
    assert first.embedded == first.chunks and first.reused == 0
    second = kb.ingest(store, embed, MODEL)
    assert second.embedded == 0 and second.reused == second.chunks and calls[-1] == 0
    third = kb.ingest(store, embed, "another-model")  # a new model changes every hash
    assert third.embedded == third.chunks


def test_with_no_embeddings_the_rows_are_still_written_for_keyword_search():
    store = FakeKnowledge()
    report = knowledge.load("guides", REG).ingest(store, lambda texts: [None] * len(texts), MODEL)
    assert report.embedded == 0 and report.chunks == len(store.chunk_rows)
    assert {r["embedding"] for r in store.chunk_rows} == {None}
    assert {r["embedding_model"] for r in store.chunk_rows} == {""}


def test_a_dry_run_reads_the_files_and_writes_and_embeds_nothing():
    store = FakeKnowledge()

    def boom(texts: list[str]) -> list[list[float] | None]:
        raise AssertionError("a dry run embeds nothing")

    report = knowledge.load("rules", REG).ingest(store, boom, MODEL, dry_run=True)
    assert report.dry_run and report.chunks > 0 and store.chunk_rows == []


def test_the_technique_table_is_merged_embedded_and_replaced_whole():
    store = FakeKnowledge(techniques=[{"id": 1, "name": "stale"}])
    report = knowledge.load("cinematography", REG).ingest(store, fake_embed, MODEL)
    assert report.techniques == 576 == len(store.technique_rows) and "stale" not in str(store.technique_rows[:3])
    assert all(r["embedding_model"] == MODEL for r in store.technique_rows)
    short = knowledge.load("cinematography", REG).ingest(FakeKnowledge(), fake_embed, MODEL, dry_run=True,
                                                         include_short_form=True)
    assert short.techniques == 576 + 79


def test_removing_a_file_from_a_base_removes_its_chunks(tmp_path: Path):
    root = tmp_path / "hiru_ai"
    from hiru_ai.cli import scaffold

    scaffold.create("knowledge_base", "notes", root)
    sources = root / "knowledge_bases" / "notes" / "sources"
    (sources / "notes.md").write_text("# One\n\n" + "alpha " * 30 + "\n\n# Two\n\n" + "beta " * 30, encoding="utf-8")
    path = root / "knowledge_bases" / "notes" / "component.yaml"  # a lone base: its steps live in the real registry
    path.write_text(path.read_text(encoding="utf-8").replace("uses: [extract_text, chunk]\n", ""), encoding="utf-8")
    reg = Registry(root).discover()
    assert [str(p) for p in reg.validate()] == []
    store = FakeKnowledge()
    kb = knowledge.load("notes", reg)
    kb.ingest(store, fake_embed, MODEL)
    assert {r["source"] for r in store.chunk_rows} == {"knowledge_base/notes/notes.md"}
    kb.manifest.files.clear()
    kb.ingest(store, fake_embed, MODEL)
    assert store.chunk_rows == []


def test_validate_catches_a_base_that_lists_a_missing_file_or_names_no_feeder(tmp_path: Path):
    from hiru_ai.cli import scaffold

    root = tmp_path / "hiru_ai"
    scaffold.create("knowledge_base", "notes", root)
    (root / "knowledge_bases" / "notes" / "sources" / "notes.md").unlink()
    text = [str(p) for p in Registry(root).discover().validate()]
    assert any("notes.md" in t and "not in sources" in t for t in text)
    path = root / "knowledge_bases" / "notes" / "component.yaml"
    path.write_text(path.read_text(encoding="utf-8").replace("ingest: files", "ingest: none"), encoding="utf-8")
    assert any("fed_by" in str(p) for p in Registry(root).discover().validate())


def test_the_cli_ingest_dry_run_lists_every_base_and_writes_nothing(capsys: pytest.CaptureFixture[str]):
    assert main(["ingest", "--all", "--dry-run"]) == 0
    out = capsys.readouterr().out
    assert "craft: would index" in out and "cinematography: would index 0 chunks and 576 techniques" in out
    assert main(["ingest"]) == 2


# ── from the knowledge an agent lists to what it may search ────────────────────────────────────


def test_an_agents_knowledge_ids_become_corpora_and_techniques_have_none():
    assert corpora_of(["craft", "rules", "techniques", "production_docs"], REG) == ("craft", "production_docs")


def test_a_manifest_can_narrow_a_run_but_never_widen_it():
    wide = RunContext(production_id=PRODUCTION)
    assert scope_for(wide, ["craft"], REG).corpora == ("craft",)
    narrowed = RunContext(production_id=PRODUCTION, corpora=("production_docs",))
    assert scope_for(narrowed, ["craft", "production_docs"], REG).corpora == ("production_docs",)
    assert scope_for(narrowed, ["craft"], REG).corpora == (), "nothing in common: nothing is searchable"


def test_search_kb_only_reads_what_the_agents_scope_allows():
    from hiru_ai.tools.search_kb import tool

    search = FakeSearch(chunks=rows())
    ctx = scope_for(RunContext(production_id=PRODUCTION, ports=_ports(search)), ["craft"], REG)
    out = tool.run(tool.Args(query="shot size", k=2), ctx)
    assert [p["cite"] for p in out.passages] == [cid(1), cid(2)] and search.asked[0]["corpora"] == ["craft"]
    with pytest.raises(Exception, match="no knowledge base"):
        tool.run(tool.Args(query="shot size"), scope_for(RunContext(production_id=PRODUCTION, ports=_ports(search)),
                                                         ["techniques"], REG))


def _ports(search: FakeSearch) -> Any:
    from hiru_ai.core.context import Ports

    return Ports(search=search)


def test_the_cli_ingest_json_is_not_needed_but_a_case_still_runs_search_kb(tmp_path: Path):
    case = tmp_path / "case.json"
    case.write_text(json.dumps({"production_id": str(PRODUCTION), "corpora": ["craft"], "args": {"query": "light"},
                                "fixtures": {"chunks": rows()}}), encoding="utf-8")
    assert main(["run", "tool", "search_kb", "--input", str(case)]) == 0
