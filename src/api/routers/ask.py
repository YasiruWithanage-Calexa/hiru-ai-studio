"""Ask the production (the "Ask" dialog on the drama overview): a short answer that cites the
production's own documents, canon cards and recorded decisions (PLAN.md §7 "Citations").

Scope is decided here from trusted data (the production in the path, the sources asked for);
the model only writes the answer from numbered sources and cites them. Without a model the
person gets the sources themselves, and says so: absent-safe, never an error.
"""
from __future__ import annotations

import re
from enum import StrEnum
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from api.deps.authz import ProductionAccess, require_permission
from api.deps.db import get_repos
from api.repositories import Repos, Row
from api.services import retrieval
from api.services.ai import AI, UsageContext, answer, get_ai
from contracts.canon import name_key
from contracts.documents import Corpus, SearchRequest
from contracts.roles import Permission

router = APIRouter(prefix="/v1/productions/{production_id}", tags=["ask"])
MAX_SOURCES = 6
NO_MODEL = "These are the closest passages in the production's material:"


class Scope(StrEnum):
    EVERYTHING = "everything"
    DOCUMENTS = "documents"
    CANON = "canon"
    DECISIONS = "decisions"


class AskRequest(BaseModel):
    query: str = Field(min_length=1, max_length=1000)
    scope: Scope = Scope.EVERYTHING


class AnswerPart(BaseModel):
    text: str | None = None
    cite: int | None = None


class Source(BaseModel):
    n: int
    kind: Literal["document", "canon", "decision"]
    title: str
    where: str
    quote: str
    canon_id: UUID | None = None
    document_id: UUID | None = None


class AskResponse(BaseModel):
    query: str
    answer: list[AnswerPart]
    sources: list[Source]
    answered_by_model: bool


_CITE = re.compile(r"\[(\d+)\]")


def parts(text: str, count: int) -> list[AnswerPart]:
    """"Kamala is 52 [1]." → text and cite parts; numbers outside the sources stay as text."""
    out: list[AnswerPart] = []
    last = 0
    for match in _CITE.finditer(text):
        n = int(match.group(1))
        if not 1 <= n <= count:
            continue
        if match.start() > last:
            out.append(AnswerPart(text=text[last:match.start()]))
        out.append(AnswerPart(cite=n))
        last = match.end()
    if last < len(text):
        out.append(AnswerPart(text=text[last:]))
    return out


def canon_matches(canon: list[Row], query: str, limit: int = 3) -> list[Row]:
    """Canon cards whose name, alias or card text shares words with the question."""
    words = {w for w in name_key(query).split() if len(w) > 2}
    scored = []
    for c in canon:
        card = (c.get("current") or {}).get("card") or {}
        names = [str(c["name"]), *(c.get("aliases") or [])]
        hay = set(name_key(" ".join([*names, *(str(v) for v in card.values())])).split())
        name_hit = any(name_key(n) and name_key(n) in name_key(query) for n in names)
        score = len(words & hay) + (5 if name_hit else 0)
        if score:
            scored.append((score, c))
    return [c for _, c in sorted(scored, key=lambda sc: (-sc[0], str(sc[1]["code"])))[:limit]]


def _card_text(c: Row) -> str:
    current = c.get("current") or {}
    card = current.get("card") or {}
    bits = [f"{k}: {v}" for k, v in card.items() if v]
    if current.get("voice_pin"):
        bits.append(f"voice pin: {current['voice_pin']}")
    return f"{c['code']} {c['name']} — " + "; ".join(bits)


@router.post("/ask", response_model=AskResponse)
async def ask(production_id: UUID, body: AskRequest,
              access: Annotated[ProductionAccess, Depends(require_permission(Permission.VIEW))],
              repos: Annotated[Repos, Depends(get_repos)], ai: Annotated[AI, Depends(get_ai)]) -> AskResponse:
    sources: list[Source] = []
    texts: list[str] = []
    corpora = {Scope.EVERYTHING: [Corpus.PRODUCTION_DOCS, Corpus.MEMORY], Scope.DOCUMENTS: [Corpus.PRODUCTION_DOCS],
               Scope.DECISIONS: [Corpus.MEMORY], Scope.CANON: []}[body.scope]
    if body.scope in (Scope.EVERYTHING, Scope.CANON):
        for c in canon_matches(await repos.canon.list(production_id), body.query):
            text = _card_text(c)
            texts.append(text)
            sources.append(Source(n=len(sources) + 1, kind="canon", title=f"{c['code']} · {c['name']}",
                                  where="Canon card", quote=text.split(" — ", 1)[-1][:400], canon_id=c["id"]))
    if corpora:
        found = await retrieval.search(repos, ai, production_id=production_id, actor_user_id=access.user.id,
                                       req=SearchRequest(query=body.query, corpora=corpora, k=MAX_SOURCES))
        for hit in found.hits[: MAX_SOURCES - len(sources)]:
            pages = hit.citation.page_start
            where = " · ".join(b for b in (hit.heading, f"p. {pages}" if pages else "") if b)
            decision = hit.corpus == Corpus.MEMORY
            texts.append(hit.content)
            sources.append(Source(n=len(sources) + 1, kind="decision" if decision else "document",
                                  title="Production decision" if decision else hit.citation.filename or "Document",
                                  where=where or hit.context_header, quote=hit.content[:400],
                                  document_id=hit.citation.document_id))
    if not sources:
        return AskResponse(query=body.query, sources=[], answered_by_model=False,
                           answer=[AnswerPart(text="Nothing in this production's material matches that question.")])
    written = await answer(ai, body.query, texts, UsageContext(repos, access.user.id, production_id))
    if written:
        return AskResponse(query=body.query, answer=parts(written, len(sources)), sources=sources,
                           answered_by_model=True)
    fallback = [AnswerPart(text=NO_MODEL + " ")]
    for s in sources:
        fallback.append(AnswerPart(cite=s.n))
    return AskResponse(query=body.query, answer=fallback, sources=sources, answered_by_model=False)
