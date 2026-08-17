import json
from datetime import datetime
from uuid import UUID

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from api.core.db import get_pool
from api.core.jobs import enqueue_job

router = APIRouter(prefix="/eval", tags=["eval"])


class EvalRunRequest(BaseModel):
    session_id: UUID | None = None


class EvalRunSummary(BaseModel):
    id: UUID
    run_type: str
    avg_retrieval_hit_rate: float | None
    avg_answer_correctness: float | None
    avg_faithfulness: float | None
    avg_answer_relevancy: float | None
    question_count: int | None
    started_at: datetime
    completed_at: datetime | None


class EvalResultDetail(BaseModel):
    id: int
    labeled_qa_id: int
    generated_answer: str | None
    retrieved_source_refs: list[str]
    retrieval_hit: bool
    answer_correctness: float | None
    faithfulness: float | None
    answer_relevancy: float | None
    retries_used: int | None


class EvalRunDetail(EvalRunSummary):
    results: list[EvalResultDetail]


@router.post("/run")
async def start_eval_run(body: EvalRunRequest) -> dict:
    payload: dict = {}
    if body.session_id:
        payload["session_id"] = str(body.session_id)
    job_id = await enqueue_job("eval_benchmark", payload)
    return {"job_id": str(job_id)}


@router.get("/runs", response_model=list[EvalRunSummary])
async def list_eval_runs() -> list[EvalRunSummary]:
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT id, run_type, avg_retrieval_hit_rate, avg_answer_correctness,
                   avg_faithfulness, avg_answer_relevancy, question_count,
                   started_at, completed_at
            FROM eval_runs
            ORDER BY started_at DESC
            LIMIT 50
            """
        )
    return [
        EvalRunSummary(
            id=UUID(row["id"]) if isinstance(row["id"], str) else row["id"],
            run_type=row["run_type"],
            avg_retrieval_hit_rate=row["avg_retrieval_hit_rate"],
            avg_answer_correctness=row["avg_answer_correctness"],
            avg_faithfulness=row["avg_faithfulness"],
            avg_answer_relevancy=row["avg_answer_relevancy"],
            question_count=row["question_count"],
            started_at=datetime.fromisoformat(row["started_at"])
            if isinstance(row["started_at"], str)
            else row["started_at"],
            completed_at=datetime.fromisoformat(row["completed_at"])
            if row["completed_at"] and isinstance(row["completed_at"], str)
            else row["completed_at"],
        )
        for row in rows
    ]


@router.get("/runs/{run_id}", response_model=EvalRunDetail)
async def get_eval_run(run_id: UUID) -> EvalRunDetail:
    pool = await get_pool()
    async with pool.acquire() as conn:
        run = await conn.fetchrow(
            """
            SELECT id, run_type, avg_retrieval_hit_rate, avg_answer_correctness,
                   avg_faithfulness, avg_answer_relevancy, question_count,
                   started_at, completed_at
            FROM eval_runs WHERE id = $1
            """,
            run_id,
        )
        if run is None:
            raise HTTPException(status_code=404, detail="Eval run not found")

        result_rows = await conn.fetch(
            """
            SELECT id, labeled_qa_id, generated_answer, retrieved_source_refs,
                   retrieval_hit, answer_correctness, faithfulness,
                   answer_relevancy, retries_used
            FROM eval_results WHERE eval_run_id = $1
            ORDER BY id
            """,
            run_id,
        )

    results = []
    for row in result_rows:
        refs = row["retrieved_source_refs"]
        if isinstance(refs, str):
            refs = json.loads(refs)
        results.append(
            EvalResultDetail(
                id=row["id"],
                labeled_qa_id=row["labeled_qa_id"],
                generated_answer=row["generated_answer"],
                retrieved_source_refs=refs or [],
                retrieval_hit=bool(row["retrieval_hit"]),
                answer_correctness=row["answer_correctness"],
                faithfulness=row["faithfulness"],
                answer_relevancy=row["answer_relevancy"],
                retries_used=row["retries_used"],
            )
        )

    return EvalRunDetail(
        id=UUID(run["id"]) if isinstance(run["id"], str) else run["id"],
        run_type=run["run_type"],
        avg_retrieval_hit_rate=run["avg_retrieval_hit_rate"],
        avg_answer_correctness=run["avg_answer_correctness"],
        avg_faithfulness=run["avg_faithfulness"],
        avg_answer_relevancy=run["avg_answer_relevancy"],
        question_count=run["question_count"],
        started_at=datetime.fromisoformat(run["started_at"])
        if isinstance(run["started_at"], str)
        else run["started_at"],
        completed_at=datetime.fromisoformat(run["completed_at"])
        if run["completed_at"] and isinstance(run["completed_at"], str)
        else run["completed_at"],
        results=results,
    )
