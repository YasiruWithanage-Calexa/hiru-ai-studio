"""L1 retrieval primitives: query embeddings, retrievers over the `Search` port, rerankers, knowledge-base ingest.

Kept light on purpose. `ranking`, `scope` and `hits` are plain Python plus `contracts`, so the API imports them
without LangChain; the retrievers and rerankers are the LangChain-facing parts.
"""
