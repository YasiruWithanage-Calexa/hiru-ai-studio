"""Screen 0b, the live structure build: start it, read where it is, answer its questions.

The browser follows a running build through Supabase Realtime (`job_events`, `questions`,
`episodes`, `scenes`, `shots`); `GET .../build` is the snapshot a page opened mid-build starts
from, drawn entirely from the job's events, so both views agree.
"""
from __future__ import annotations

import logging
from datetime import datetime
from typing import Annotated, Any
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from pydantic import BaseModel

from api.deps.authz import ProductionAccess, require_permission
from api.deps.db import get_repos
from api.repositories import Repos, Row
from api.services.ai import UsageContext, get_ai
from api.workers import task_manager
from contracts.build import (
    AGENT_LABEL,
    BUILD_PIPELINE,
    STAGE_LABEL,
    Agent,
    AnswerRequest,
    Question,
    QuestionStatus,
    Stage,
)
from contracts.documents import DocumentRole, DocumentStatus
from contracts.jobs import JobEventType, JobKind, JobStatus
from contracts.roles import Permission

_logger = logging.getLogger(__name__)
router = APIRouter(prefix="/v1/productions/{production_id}", tags=["build"])
ReposDep = Annotated[Repos, Depends(get_repos)]
CanView = Annotated[ProductionAccess, Depends(require_permission(Permission.VIEW))]
CanBuild = Annotated[ProductionAccess, Depends(require_permission(Permission.MANAGE_DOCUMENTS))]
CanAnswer = Annotated[ProductionAccess, Depends(require_permission(Permission.ANSWER_QUESTIONS))]
ACTIVE = (JobStatus.PENDING, JobStatus.RUNNING, JobStatus.WAITING_INPUT)


class BuildStarted(BaseModel):
    job_id: UUID
    # Ready documents read before the extracted text was kept; re-ingest them to include them.
    needs_reingest: list[str]


class StageView(BaseModel):
    stage: Stage
    label: str
    state: str  # "done" | "active" | "pending"
    detail: str = ""


class AgentView(BaseModel):
    agent: str
    label: str
    status: str  # "done" | "working" | "waiting"
    detail: str = ""


class MessageView(BaseModel):
    seq: int
    kind: str  # "agent" | "warning" | "question"
    agent: str | None
    agent_label: str
    text: str
    chips: list[str] = []
    at: datetime | None = None


class Summary(BaseModel):
    episodes: int
    scenes: int
    shots: int


class BuildView(BaseModel):
    job_id: UUID | None
    status: JobStatus | None
    error: str | None = None
    stages: list[StageView]
    agents: list[AgentView]
    messages: list[MessageView]
    open_questions: int
    summary: Summary


class AnswerResult(BaseModel):
    question: Question
    resumed: bool  # the last open question was answered and the build carries on


def _label(agent: str | None) -> str:
    try:
        return AGENT_LABEL[Agent(agent or "")]
    except ValueError:
        return (agent or "").replace("_", " ").capitalize()


def view(job: Row | None, events: list[Row], open_questions: int, summary: Summary) -> BuildView:
    stages = {s: StageView(stage=s, label=STAGE_LABEL[s], state="pending") for s in Stage}
    agents: dict[str, AgentView] = {}
    messages: list[MessageView] = []
    for e in events:
        payload: dict[str, Any] = e.get("payload") or {}
        agent = e.get("agent")
        if e["type"] == JobEventType.STAGE:
            try:
                st = stages[Stage(str(payload.get("stage")))]
            except ValueError:
                continue
            st.state = "done" if payload.get("state") == "done" else "active"
            st.detail = str(payload.get("text") or st.detail)
        if agent:
            agents[agent] = AgentView(agent=agent, label=_label(agent), status="working",
                                      detail=str(payload.get("text") or ""))
        if e["type"] in (JobEventType.AGENT_STEP, JobEventType.WARNING, JobEventType.QUESTION):
            kind = {"agent_step": "agent", "warning": "warning", "question": "question"}[e["type"]]
            messages.append(MessageView(seq=e["seq"], kind=kind, agent=agent, agent_label=_label(agent),
                                        text=str(payload.get("text") or ""), chips=list(payload.get("chips") or []),
                                        at=e.get("created_at")))
    state = JobStatus(job["status"]) if job else None
    for a in agents.values():
        if state in (JobStatus.DONE, JobStatus.FAILED, JobStatus.CANCELLED):
            a.status = "done"
        elif state is JobStatus.WAITING_INPUT:
            a.status = "waiting"
    # Every agent but the one that spoke last has finished its part.
    if state in (JobStatus.RUNNING, JobStatus.PENDING) and agents:
        last = next((e.get("agent") for e in reversed(events) if e.get("agent")), None)
        for a in agents.values():
            if a.agent != last:
                a.status = "done"
    if state is JobStatus.DONE:
        stages[Stage.REVIEW].state = "active"
    return BuildView(job_id=job["id"] if job else None, status=state, error=job.get("error") if job else None,
                     stages=list(stages.values()), agents=list(agents.values()), messages=messages,
                     open_questions=open_questions, summary=summary)


async def _summary(repos: Repos, production_id: UUID) -> Summary:
    return Summary(episodes=len(await repos.episodes.list(production_id)),
                   scenes=len(await repos.scenes.list(production_id)),
                   shots=len(await repos.shots.list(production_id)))


@router.post("/build", response_model=BuildStarted, status_code=status.HTTP_202_ACCEPTED)
async def start_build(production_id: UUID, access: CanBuild, repos: ReposDep) -> BuildStarted:
    latest = await repos.jobs.latest(production_id, JobKind.STRUCTURE_BUILD.value)
    if latest and latest["status"] in ACTIVE:
        raise HTTPException(status.HTTP_409_CONFLICT, "A build is already running for this production.")
    docs = await repos.documents.list(production_id)
    ready = [d for d in docs if d["status"] == DocumentStatus.READY]
    if not ready:
        raise HTTPException(status.HTTP_409_CONFLICT, "Upload documents and wait until they are read first.")
    if any(d["status"] in (DocumentStatus.UPLOADED, DocumentStatus.PROCESSING) for d in docs):
        raise HTTPException(status.HTTP_409_CONFLICT, "Some documents are still being read. Start the build "
                                                      "when they are ready.")
    needs = [d["filename"] for d in ready if not d.get("text_path")
             and (d.get("confirmed_role") or d.get("detected_role")) in
             (DocumentRole.SCRIPT, DocumentRole.OUTLINE, DocumentRole.BIBLE, DocumentRole.CANON_INDEX)]
    job_id = await task_manager.dispatch(JobKind.STRUCTURE_BUILD, repos, actor_user_id=access.user.id,
                                         production_id=production_id, pipeline=list(BUILD_PIPELINE),
                                         state={"build": True})
    await repos.audit.record(action="build.start", entity="job", entity_id=str(job_id),
                             actor_user_id=access.user.id, production_id=production_id)
    return BuildStarted(job_id=job_id, needs_reingest=needs)


@router.get("/build", response_model=BuildView)
async def get_build(production_id: UUID, _: CanView, repos: ReposDep) -> BuildView:
    job = await repos.jobs.latest(production_id, JobKind.STRUCTURE_BUILD.value)
    events = await repos.jobs.events(UUID(str(job["id"]))) if job else []
    open_q = len(await repos.questions.list(production_id, QuestionStatus.OPEN.value))
    return view(job, events, open_q, await _summary(repos, production_id))


@router.get("/questions", response_model=list[Question])
async def list_questions(production_id: UUID, _: CanView, repos: ReposDep,
                         status_: Annotated[QuestionStatus | None, Query(alias="status")] = None) -> list[Question]:
    rows = await repos.questions.list(production_id, status_.value if status_ else None)
    return [Question.model_validate(r) for r in rows]


async def _remember(repos: Repos, production_id: UUID, question: Row, body: AnswerRequest,
                    access: ProductionAccess, request: Request) -> None:
    """An answered question becomes production memory (PLAN.md §6.2), so the director knows in
    Episode 7 what was settled during the build. Never fails the answer it records."""
    labels = {o["value"]: o.get("label") or o["value"] for o in question.get("options") or []}
    answer = labels.get(body.value or "", body.value or "") if body.value else (body.text or "")
    text = f"{question.get('scope') or 'Build'}: {question['body']} Answer: {answer}"[:2000]
    try:
        ai = get_ai(request)
        embedding = await ai.embed_query(text, UsageContext(repos, access.user.id, production_id))
        source = {"question_id": str(question["id"]), "key": question["key"]}
        await repos.memory.add({"id": str(uuid4()), "production_id": str(production_id), "kind": "answer",
                                "text": text, "source_ref": source, "created_by": str(access.user.id)},
                               embedding, ai.settings.embedding_model)
    except Exception:
        _logger.exception("could not store the answer in production memory question=%s", question["id"])


@router.post("/questions/{question_id}/answer", response_model=AnswerResult)
async def answer_question(production_id: UUID, question_id: UUID, body: AnswerRequest, access: CanAnswer,
                          repos: ReposDep, request: Request) -> AnswerResult:
    row = await repos.questions.get(production_id, question_id)
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Question not found.")
    if row["status"] != QuestionStatus.OPEN:
        raise HTTPException(status.HTTP_409_CONFLICT, "This question has already been answered.")
    values = {o["value"] for o in row.get("options") or []}
    if body.value is not None and body.value not in values:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "That is not one of the answers offered.")
    if body.value is None and not row.get("allow_text"):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "Pick one of the answers offered.")
    updated = await repos.questions.answer(question_id, body.model_dump(), access.user.id)
    if updated is None:
        raise HTTPException(status.HTTP_409_CONFLICT, "This question has already been answered.")
    await repos.audit.record(action="question.answer", entity="question", entity_id=str(question_id),
                             actor_user_id=access.user.id, production_id=production_id,
                             diff={"key": row["key"], "answer": body.model_dump()})
    await _remember(repos, production_id, row, body, access, request)
    resumed = False
    if row.get("job_id"):
        job = await repos.jobs.get(UUID(str(row["job_id"])))
        if (job and job["status"] == JobStatus.WAITING_INPUT
                and await repos.questions.open_count(UUID(str(job["id"]))) == 0):
            resumed = await task_manager.resume(repos, job, {"build": True})
    return AnswerResult(question=Question.model_validate(updated), resumed=resumed)
