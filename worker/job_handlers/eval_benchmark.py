import json
import uuid
from collections.abc import Awaitable, Callable
from typing import Any

from api.core.db import get_pool
from api.core.logging import logger
from backend.agent.graph import run_agent

ProgressCallback = Callable[[str, int, str], Awaitable[None]]


def _retrieval_hit(retrieved_refs: list[str], expected_ref: str | None) -> bool:
    if not expected_ref:
        return True
    expected = expected_ref.lower()
    return any(expected in ref.lower() or ref.lower() in expected for ref in retrieved_refs)


def _answer_score(answer: str, expected: str) -> float:
    if not expected.strip():
        return 0.0
    answer_l = answer.lower()
    expected_l = expected.lower()
    if expected_l in answer_l:
        return 1.0
    expected_tokens = {t for t in expected_l.split() if len(t) > 3}
    if not expected_tokens:
        return 0.5 if answer.strip() else 0.0
    hits = sum(1 for t in expected_tokens if t in answer_l)
    return round(hits / len(expected_tokens), 2)


async def run_eval_benchmark(
    payload: dict[str, Any],
    on_progress: ProgressCallback | None = None,
) -> dict[str, Any]:
    session_id = payload.get("session_id")

    async def report(stage: str, progress_pct: int, message: str = "") -> None:
        if on_progress:
            await on_progress(stage, progress_pct, message)

    pool = await get_pool()
    async with pool.acquire() as conn:
        if session_id:
            rows = await conn.fetch(
                """
                SELECT id, session_id, question, expected_answer, expected_source_ref
                FROM labeled_qa WHERE session_id = $1::uuid
                """,
                uuid.UUID(session_id),
            )
        else:
            rows = await conn.fetch(
                """
                SELECT id, session_id, question, expected_answer, expected_source_ref
                FROM labeled_qa
                """
            )

    if not rows:
        raise ValueError("No labeled Q&A pairs found. Run seed script first.")

    run_id = uuid.uuid4()
    eval_session = str(rows[0]["session_id"]) if rows[0]["session_id"] else session_id
    if not eval_session:
        raise ValueError("labeled_qa rows need a session_id — upload data and seed Q&A for that session")

    await report("evaluating", 5, f"Running benchmark ({len(rows)} questions)")

    results: list[dict[str, Any]] = []
    total = len(rows)

    for idx, row in enumerate(rows, start=1):
        q_session = str(row["session_id"]) if row["session_id"] else eval_session
        agent_result = await run_agent(q_session, row["question"])
        retrieved_refs = [c["source_ref"] for c in agent_result["citations"]]
        hit = _retrieval_hit(retrieved_refs, row["expected_source_ref"])
        correctness = _answer_score(agent_result["answer"], row["expected_answer"])
        faithfulness = float(agent_result["confidence"].get("faithfulness", 0.0))
        relevancy = float(agent_result["confidence"].get("answer_relevancy", 0.0))

        results.append(
            {
                "labeled_qa_id": row["id"],
                "generated_answer": agent_result["answer"],
                "retrieved_source_refs": retrieved_refs,
                "retrieval_hit": hit,
                "answer_correctness": correctness,
                "faithfulness": faithfulness,
                "answer_relevancy": relevancy,
                "retries_used": agent_result["retries_used"],
            }
        )
        pct = 5 + int((idx / total) * 90)
        await report("evaluating", pct, f"Question {idx}/{total}")

    hit_rate = sum(1 for r in results if r["retrieval_hit"]) / len(results)
    avg_correctness = sum(r["answer_correctness"] for r in results) / len(results)
    avg_faith = sum(r["faithfulness"] for r in results) / len(results)
    avg_rel = sum(r["answer_relevancy"] for r in results) / len(results)

    async with pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO eval_runs (
                id, run_type, avg_retrieval_hit_rate, avg_answer_correctness,
                avg_faithfulness, avg_answer_relevancy, question_count, completed_at
            ) VALUES ($1, 'benchmark', $2, $3, $4, $5, $6, datetime('now'))
            """,
            run_id,
            hit_rate,
            avg_correctness,
            avg_faith,
            avg_rel,
            len(results),
        )
        for result in results:
            await conn.execute(
                """
                INSERT INTO eval_results (
                    eval_run_id, labeled_qa_id, generated_answer, retrieved_source_refs,
                    retrieval_hit, answer_correctness, faithfulness, answer_relevancy, retries_used
                ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)
                """,
                run_id,
                result["labeled_qa_id"],
                result["generated_answer"],
                json.dumps(result["retrieved_source_refs"]),
                1 if result["retrieval_hit"] else 0,
                result["answer_correctness"],
                result["faithfulness"],
                result["answer_relevancy"],
                result["retries_used"],
            )

    await report("evaluating", 100, "Benchmark complete")
    logger.info("eval_benchmark_completed", run_id=str(run_id), questions=len(results))

    return {
        "eval_run_id": str(run_id),
        "question_count": len(results),
        "avg_retrieval_hit_rate": hit_rate,
        "avg_answer_correctness": avg_correctness,
        "avg_faithfulness": avg_faith,
        "avg_answer_relevancy": avg_rel,
    }
