"""Retrieval quality gate (PLAN.md §7). Run after any change to chunking, headers, embeddings,
the search SQL, the corpus or the probes.

    python scripts/eval_retrieval.py                     # ingest fixtures, run probes, compare
    python scripts/eval_retrieval.py --skip-ingest -v    # probes only, print every rank
    python scripts/eval_retrieval.py --update-thresholds # accept the current numbers as baseline

1. Ingests tests/fixtures/corpus into a dedicated eval production through the REAL doc_ingest
   pipeline (extract → role → chunk → headers → embed), so the eval measures what ships.
2. Runs tests/eval/retrieval_probes.json against `match_chunks` / `match_craft_techniques`
   (the retriever itself; reranking is measured separately once a key is configured).
3. Reports recall@1, recall@k and MRR per suite, and fails if any is below
   tests/eval/thresholds.json for the current mode ("text" without a key, "hybrid" with one).
Run `scripts/ingest_knowledge.py` first so the craft suites have a corpus.
"""
from __future__ import annotations

import argparse
import json
import mimetypes
import sys
import uuid

from _common import ROOT, Rest, load_env, vector

load_env()

from doc_ingest.engine import pipeline  # noqa: E402
from doc_ingest.runtime.config import get_config  # noqa: E402
from doc_ingest.runtime.llm import LLM  # noqa: E402
from doc_ingest.runtime.store import Store  # noqa: E402

from contracts.jobs import DispatchPayload, JobKind  # noqa: E402

CORPUS = ROOT / "tests" / "fixtures" / "corpus"
PROBES = ROOT / "tests" / "eval" / "retrieval_probes.json"
THRESHOLDS = ROOT / "tests" / "eval" / "thresholds.json"
EVAL_PRODUCTION = "e0000000-0000-4000-8000-00000000e001"
NS = uuid.UUID("6f1c2f0e-9a51-4c43-8f39-2f1c0c0de0a1")


def ingest(db: Rest, store: Store, llm: LLM) -> None:
    db.insert("productions", {"id": EVAL_PRODUCTION, "title": "Retrieval eval — Harbour Lights (fixtures)",
                              "orientation": "horizontal"}, upsert=True)
    actor = db.get("profiles", select="id", limit="1")
    if not actor:
        sys.exit("No users yet: run scripts/create_admin.py first (jobs need an actor).")
    for path in sorted(p for p in CORPUS.iterdir() if p.name != "README.md"):
        data = path.read_bytes()
        doc_id = str(uuid.uuid5(NS, path.name))
        mime = "text/markdown" if path.suffix == ".md" else (mimetypes.guess_type(path.name)[0] or "text/plain")
        storage_path = f"{EVAL_PRODUCTION}/{doc_id}/{path.name}"
        db.upload("documents", storage_path, data, mime)
        db.insert("documents", {"id": doc_id, "production_id": EVAL_PRODUCTION, "filename": path.name,
                                "mime_type": mime, "size_bytes": len(data), "sha256": f"eval-{doc_id}",
                                "storage_path": storage_path, "status": "uploaded"}, upsert=True)
        job_id = str(uuid.uuid4())
        db.insert("jobs", {"id": job_id, "kind": JobKind.DOC_INGEST.value, "production_id": EVAL_PRODUCTION,
                           "requested_by": actor[0]["id"], "request": {"document_id": doc_id}})
        payload = DispatchPayload(job_id=uuid.UUID(job_id), kind=JobKind.DOC_INGEST,
                                  actor_user_id=uuid.UUID(actor[0]["id"]),
                                  production_id=uuid.UUID(EVAL_PRODUCTION), state={"document_id": doc_id})
        result = pipeline.run(payload, store, llm)
        print(f"  ingested {path.name}: {result.get('role')} · {result.get('chunks')} chunks · "
              f"{result.get('embedded')} embedded")


def rank_of(hits: list[dict], expect: list[dict], filenames: dict[str, str]) -> int | None:
    for i, hit in enumerate(hits, start=1):
        name = filenames.get(str(hit.get("document_id")), "") if hit.get("document_id") else hit.get("source", "")
        for e in expect:
            target = e.get("file") or e.get("source")
            if name == target and e.get("heading", "").lower() in (hit.get("heading") or "").lower():
                return i
    return None


def metrics(ranks: list[int | None], k: int) -> dict[str, float]:
    n = max(len(ranks), 1)
    return {"recall_at_1": round(sum(1 for r in ranks if r == 1) / n, 3),
            f"recall_at_{k}": round(sum(1 for r in ranks if r and r <= k) / n, 3),
            "mrr": round(sum(1 / r for r in ranks if r and r <= k) / n, 3)}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--skip-ingest", action="store_true")
    parser.add_argument("--update-thresholds", action="store_true")
    parser.add_argument("-k", type=int, default=5)
    parser.add_argument("-v", "--verbose", action="store_true")
    parser.add_argument("--runs", type=int, default=1, help="full ingest + probe runs; the worst is kept")
    args = parser.parse_args()

    config = get_config()
    db, llm = Rest(), LLM(config)
    store = Store(config.supabase_url, config.service_role_key)
    mode = "hybrid" if llm.enabled else "text"
    print(f"mode: {mode}")

    # Hybrid runs are not byte-identical: model-written passage headers change between ingests,
    # so their embeddings (and ranks) move a little. The baseline is therefore the WORST of
    # `--runs` full ingests, and hybrid comparisons allow TOLERANCE. Keyword mode is
    # deterministic and compared exactly.
    runs: list[dict[str, dict[str, float]]] = []
    for n in range(args.runs):
        if not args.skip_ingest:
            ingest(db, store, llm)
        runs.append(evaluate(db, llm, args.k, args.verbose and n == 0))
        if args.runs > 1:
            print(f"  run {n + 1}: " + " · ".join(f"{s} mrr={m['mrr']:.2f}" for s, m in runs[-1].items()))
    results = {s: {k: min(r[s][k] for r in runs) for k in runs[0][s]} for s in runs[0]}

    print(f"\nresults ({mode}{', worst of ' + str(args.runs) + ' runs' if args.runs > 1 else ''}):")
    for suite, m in results.items():
        print(f"  {suite:<11} " + "  ".join(f"{k}={v:.2f}" for k, v in m.items()))

    thresholds = json.loads(THRESHOLDS.read_text(encoding="utf-8")) if THRESHOLDS.exists() else {}
    if args.update_thresholds:
        thresholds[mode] = results
        THRESHOLDS.write_text(json.dumps(thresholds, indent=2) + "\n", encoding="utf-8")
        print(f"thresholds for '{mode}' updated")
        return
    floor = thresholds.get(mode)
    if not floor:
        print(f"no thresholds for '{mode}' yet: run with --update-thresholds to set the baseline")
        return
    tol = TOLERANCE[mode]
    failures = [f"{s}.{k}: {results[s][k]:.2f} < {v:.2f} (tolerance {tol})" for s, ms in floor.items()
                for k, v in ms.items() if results.get(s, {}).get(k, 0) + tol + 1e-9 < v]
    if failures:
        print("REGRESSION:\n  " + "\n  ".join(failures))
        sys.exit(1)
    print("no regression against the baseline")


TOLERANCE = {"text": 0.0, "hybrid": 0.05}


def evaluate(db: Rest, llm: LLM, k: int, verbose: bool) -> dict[str, dict[str, float]]:
    probes = json.loads(PROBES.read_text(encoding="utf-8"))
    filenames = {d["id"]: d["filename"] for d in db.get("documents", production_id=f"eq.{EVAL_PRODUCTION}",
                                                        select="id,filename")}

    def embed(q: str) -> str | None:
        return vector(llm.embed([q], phase="eval.embed")[0]) if llm.enabled else None

    results: dict[str, dict[str, float]] = {}
    for suite, corpora, production in (("production", ["production_docs"], EVAL_PRODUCTION),
                                       ("craft", ["craft"], None)):
        ranks = []
        for p in probes[suite]:
            hits = db.rpc("match_chunks", {"query_text": p["query"], "query_embedding": embed(p["query"]),
                                           "p_production_id": production, "p_corpora": corpora,
                                           "match_count": k})
            r = rank_of(hits, p["expect"], filenames)
            ranks.append(r)
            if verbose or r is None:
                top = [(filenames.get(str(h["document_id"]), h["source"]), h["heading"]) for h in hits[:3]]
                print(f"  {suite}/{p['id']}: rank {r or 'MISS'}" + ("" if r else f"   top: {top}"))
        results[suite] = metrics(ranks, k)

    ranks = []
    for p in probes["techniques"]:
        hits = db.rpc("match_craft_techniques", {"query_text": p["query"], "query_embedding": embed(p["query"]),
                                                 "match_count": k})
        names = [h["name"] for h in hits]
        r = next((i for i, n in enumerate(names, start=1) if n in p["expect"]), None)
        ranks.append(r)
        if verbose or r is None:
            print(f"  techniques/{p['id']}: rank {r or 'MISS'}" + ("" if r else f"   top: {names[:3]}"))
    results["techniques"] = metrics(ranks, k)
    return results


if __name__ == "__main__":
    main()
