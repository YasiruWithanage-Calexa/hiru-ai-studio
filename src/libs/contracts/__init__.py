"""Shared wire contracts for the Hiru API and every Cloud Run function.

STANDALONE by rule: this package imports only pydantic and the standard library. Services
under `src/services/` bundle it and import nothing else from this repo, so anything added here
must stay free of `api`, Supabase, LangGraph or any provider SDK (guarded by
`tests/test_isolation.py`).
"""
