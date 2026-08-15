import json
from typing import Any
from uuid import UUID, uuid4

from api.core.db import get_pool
from api.core.logging import logger
from api.core.redis_client import cache_job_status


async def enqueue_job(job_type: str, payload: dict[str, Any]) -> UUID:
    job_id = uuid4()
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO jobs (id, job_type, status, payload)
            VALUES ($1, $2, 'pending', $3)
            """,
            job_id,
            job_type,
            json.dumps(payload),
        )
    await cache_job_status(
        str(job_id),
        {"id": str(job_id), "job_type": job_type, "status": "pending", "error": None},
    )
    logger.info("job_enqueued", job_id=str(job_id), job_type=job_type)

    from api.core.config import settings

    if settings.run_worker_in_api:
        await _kick_job(job_id)
    return job_id


async def _kick_job(job_id: UUID) -> None:
    """Process a just-enqueued job immediately so SQLite local-dev does not stall."""
    try:
        from worker.scheduler import claim_job_by_id, dispatch_job

        job = await claim_job_by_id(job_id)
        if job is not None:
            await dispatch_job(job)
    except Exception:
        logger.exception("job_kick_failed", job_id=str(job_id))


async def get_job(job_id: UUID) -> dict[str, Any] | None:
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT id, job_type, status, payload, result_ref, error, attempts, created_at, updated_at
            FROM jobs WHERE id = $1
            """,
            job_id,
        )
    if row is None:
        return None
    created_at = row["created_at"]
    updated_at = row["updated_at"]
    if hasattr(created_at, "isoformat"):
        created_at = created_at.isoformat()
    if hasattr(updated_at, "isoformat"):
        updated_at = updated_at.isoformat()
    return {
        "id": str(row["id"]),
        "job_type": row["job_type"],
        "status": row["status"],
        "payload": json.loads(row["payload"]) if isinstance(row["payload"], str) else row["payload"],
        "result_ref": row["result_ref"],
        "error": row["error"],
        "attempts": row["attempts"],
        "created_at": created_at,
        "updated_at": updated_at,
    }
