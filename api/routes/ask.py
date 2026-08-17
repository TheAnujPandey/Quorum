import asyncio
import json
import random
import time
from uuid import uuid4

from fastapi import APIRouter, HTTPException

from api.core.config import settings
from api.core.logging import logger
from api.models.schemas import AskRequest, AskResponse, Citation, ConfidenceScore
from backend.agent.graph import run_agent
from backend.agent.llm_context import llm_overrides

router = APIRouter(prefix="/ask", tags=["ask"])


async def _log_live_sample(
    session_id: str,
    question: str,
    result: dict,
    elapsed_ms: int,
) -> None:
    """Fire-and-forget: log self_check scores as a live_sample eval result."""
    try:
        from api.core.db import get_pool

        pool = await get_pool()
        run_id = uuid4()
        confidence = result.get("confidence", {})

        async with pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO eval_runs
                  (id, run_type, avg_faithfulness, avg_answer_relevancy, question_count, completed_at)
                VALUES ($1, 'live_sample', $2, $3, 1, now())
                """,
                run_id,
                confidence.get("faithfulness"),
                confidence.get("answer_relevancy"),
            )
            refs = [c.get("source_ref", "") for c in result.get("citations", [])]
            await conn.execute(
                """
                INSERT INTO eval_results
                  (eval_run_id, generated_answer, retrieved_source_refs,
                   retrieval_hit, faithfulness, answer_relevancy, retries_used)
                VALUES ($1, $2, $3, $4, $5, $6, $7)
                """,
                run_id,
                result.get("answer", "")[:2000],
                json.dumps(refs),
                len(refs) > 0,
                confidence.get("faithfulness"),
                confidence.get("answer_relevancy"),
                result.get("retries_used", 0),
            )
    except Exception as exc:
        logger.warning("live_sample_log_failed", error=str(exc))


@router.post("", response_model=AskResponse)
async def ask(body: AskRequest) -> AskResponse:
    start = time.perf_counter()
    overrides = {}
    if body.openai_api_key:
        overrides["api_key"] = body.openai_api_key
    if body.model:
        overrides["model"] = body.model

    effective_key = overrides.get("api_key") or settings.openai_api_key
    if not effective_key or not effective_key.strip():
        raise HTTPException(
            status_code=422,
            detail="No OpenAI API key provided. Set it on the Settings page (http://localhost:3000/settings) or in the server .env file.",
        )

    token = llm_overrides.set(overrides)
    try:
        result = await asyncio.wait_for(
            run_agent(str(body.session_id), body.question),
            timeout=settings.ask_timeout_seconds,
        )
    except asyncio.TimeoutError:
        logger.error("ask_timeout", session_id=str(body.session_id))
        raise HTTPException(status_code=504, detail="Request timed out") from None
    except Exception as exc:
        logger.error("ask_failed", session_id=str(body.session_id), error=str(exc))
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    finally:
        llm_overrides.reset(token)

    elapsed_ms = int((time.perf_counter() - start) * 1000)
    logger.info(
        "ask_completed",
        session_id=str(body.session_id),
        retries_used=result["retries_used"],
        insufficient=result["insufficient"],
        execution_time_ms=elapsed_ms,
    )

    if random.random() < settings.live_eval_sample_rate:
        asyncio.create_task(
            _log_live_sample(str(body.session_id), body.question, result, elapsed_ms)
        )

    confidence = result["confidence"]
    return AskResponse(
        answer=result["answer"],
        citations=[Citation(**c) for c in result["citations"]],
        confidence=ConfidenceScore(**confidence),
        retries_used=result["retries_used"],
        execution_time_ms=elapsed_ms,
        insufficient=result["insufficient"],
    )
