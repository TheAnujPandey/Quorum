import json
import os
import socket
from typing import Any, Awaitable, Callable
from uuid import UUID

from api.core.db import _use_sqlite, get_pool
from api.core.logging import logger
from api.core.redis_client import cache_job_status

WORKER_ID = f"{socket.gethostname()}-{os.getpid()}"


async def claim_pending_jobs(batch_size: int) -> list[dict[str, Any]]:
    pool = await get_pool()
    if _use_sqlite():
        return await _claim_sqlite(pool, batch_size)

    async with pool.acquire() as conn:
        async with conn.transaction():
            rows = await conn.fetch(
                """
                SELECT id, job_type, status, payload, attempts
                FROM jobs
                WHERE status = 'pending'
                ORDER BY created_at
                LIMIT $1
                FOR UPDATE SKIP LOCKED
                """,
                batch_size,
            )
            claimed = []
            for row in rows:
                updated = await conn.fetchrow(
                    """
                    UPDATE jobs
                    SET status = 'running',
                        claimed_by = $2,
                        attempts = attempts + 1,
                        updated_at = now()
                    WHERE id = $1 AND status = 'pending'
                    RETURNING id, job_type, status, payload, attempts
                    """,
                    row["id"],
                    WORKER_ID,
                )
                if updated:
                    claimed.append(dict(updated))
            return claimed


async def _claim_sqlite(pool: Any, batch_size: int) -> list[dict[str, Any]]:
    """SQLite has no SKIP LOCKED / reliable UPDATE RETURNING via aiosqlite."""
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT id, job_type, status, payload, attempts
            FROM jobs
            WHERE status = 'pending'
            ORDER BY created_at
            LIMIT $1
            """,
            batch_size,
        )
        claimed: list[dict[str, Any]] = []
        for row in rows:
            await conn.execute(
                """
                UPDATE jobs
                SET status = 'running',
                    claimed_by = $2,
                    attempts = attempts + 1,
                    updated_at = now()
                WHERE id = $1 AND status = 'pending'
                """,
                row["id"],
                WORKER_ID,
            )
            claimed.append(dict(row))
        return claimed


async def claim_job_by_id(job_id: UUID) -> dict[str, Any] | None:
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT id, job_type, status, payload, attempts
            FROM jobs WHERE id = $1
            """,
            job_id,
        )
        if row is None or row["status"] != "pending":
            return None
        await conn.execute(
            """
            UPDATE jobs
            SET status = 'running',
                claimed_by = $2,
                attempts = attempts + 1,
                updated_at = now()
            WHERE id = $1 AND status = 'pending'
            """,
            job_id,
            WORKER_ID,
        )
        return dict(row)


async def mark_job_completed(job_id: UUID, result_ref: str | None = None) -> None:
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            """
            UPDATE jobs
            SET status = 'completed', result_ref = $2, updated_at = now(), error = NULL
            WHERE id = $1
            """,
            job_id,
            result_ref,
        )


async def mark_job_failed(job_id: UUID, error: str) -> None:
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            """
            UPDATE jobs
            SET status = 'failed', error = $2, updated_at = now()
            WHERE id = $1
            """,
            job_id,
            error[:2000],
        )


async def _run_chunk_tabular(payload: dict[str, Any], report_progress) -> dict[str, Any]:
    from api.core.blob_store import download_bytes
    from worker.job_handlers.chunk_tabular import chunk_tabular_csv

    file_bytes = await download_bytes(payload["blob_key"])
    return await chunk_tabular_csv(
        payload["session_id"],
        payload["blob_key"],
        file_bytes,
        chunking_method=payload.get("chunking_method", "sentence"),
        chunking_config=payload.get("chunking_config"),
        source_format=payload.get("source_format", "csv"),
        on_progress=report_progress,
    )


async def _run_embed_chunks(payload: dict[str, Any], report_progress) -> dict[str, Any]:
    from worker.job_handlers.embed_chunks import embed_draft_chunks

    return await embed_draft_chunks(
        payload["session_id"],
        source_format=payload.get("source_format", "csv"),
        on_progress=report_progress,
    )


async def _run_ingest_tabular(payload: dict[str, Any], report_progress) -> dict[str, Any]:
    from api.core.blob_store import download_bytes
    from worker.job_handlers.ingest_tabular import ingest_tabular_csv

    file_bytes = await download_bytes(payload["blob_key"])
    return await ingest_tabular_csv(
        payload["session_id"],
        payload["blob_key"],
        file_bytes,
        on_progress=report_progress,
        chunking_method=payload.get("chunking_method", "sentence"),
        chunking_config=payload.get("chunking_config"),
    )


async def _run_chunk_pdf(payload: dict[str, Any], report_progress) -> dict[str, Any]:
    from api.core.blob_store import download_bytes
    from worker.job_handlers.chunk_pdf import chunk_pdf

    file_bytes = await download_bytes(payload["blob_key"])
    return await chunk_pdf(
        payload["session_id"],
        payload["blob_key"],
        file_bytes,
        chunking_method=payload.get("chunking_method", "semantic"),
        chunking_config=payload.get("chunking_config"),
        on_progress=report_progress,
    )


async def _run_chunk_txt(payload: dict[str, Any], report_progress) -> dict[str, Any]:
    from api.core.blob_store import download_bytes
    from worker.job_handlers.chunk_txt import chunk_txt

    file_bytes = await download_bytes(payload["blob_key"])
    return await chunk_txt(
        payload["session_id"],
        payload["blob_key"],
        file_bytes,
        chunking_method=payload.get("chunking_method", "semantic"),
        chunking_config=payload.get("chunking_config"),
        on_progress=report_progress,
    )


async def _run_cleanup(payload: dict[str, Any], report_progress) -> dict[str, Any]:
    from worker.job_handlers.cleanup import cleanup_expired_sessions

    return await cleanup_expired_sessions(on_progress=report_progress)


async def _run_eval(payload: dict[str, Any], report_progress) -> dict[str, Any]:
    from worker.job_handlers.eval_benchmark import run_eval_benchmark

    return await run_eval_benchmark(payload, on_progress=report_progress)


HANDLERS: dict[str, Callable[..., Awaitable[dict[str, Any]]]] = {
    "chunk_tabular": _run_chunk_tabular,
    "chunk_pdf": _run_chunk_pdf,
    "chunk_txt": _run_chunk_txt,
    "embed_chunks": _run_embed_chunks,
    "ingest_tabular": _run_ingest_tabular,
    "eval_benchmark": _run_eval,
    "cleanup": _run_cleanup,
}


_INFLIGHT: set[str] = set()


async def fail_stale_jobs() -> None:
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            """
            UPDATE jobs
            SET status = 'failed', error = 'stale job cleared on worker start', updated_at = now()
            WHERE status IN ('pending', 'running')
            """
        )
    logger.info("stale_jobs_cleared")


async def dispatch_job(job: dict[str, Any]) -> None:
    job_id = job["id"]
    job_key = str(job_id)
    if job_key in _INFLIGHT:
        return
    _INFLIGHT.add(job_key)
    try:
        await _dispatch_job_inner(job)
    finally:
        _INFLIGHT.discard(job_key)


async def _dispatch_job_inner(job: dict[str, Any]) -> None:
    job_id = job["id"]
    job_type = job["job_type"]
    payload = job["payload"]
    if isinstance(payload, str):
        payload = json.loads(payload)

    logger.info("job_started", job_id=str(job_id), job_type=job_type, worker_id=WORKER_ID)

    async def report_progress(stage: str, progress_pct: int, message: str = "") -> None:
        await cache_job_status(
            str(job_id),
            {
                "id": str(job_id),
                "job_type": job_type,
                "status": "running",
                "stage": stage,
                "progress_pct": progress_pct,
                "message": message,
                "error": None,
            },
        )

    await cache_job_status(
        str(job_id),
        {
            "id": str(job_id),
            "job_type": job_type,
            "status": "running",
            "stage": "starting",
            "progress_pct": 0,
            "message": "Starting",
            "error": None,
        },
    )

    handler = HANDLERS.get(job_type)
    if handler is None:
        await mark_job_failed(UUID(str(job_id)), f"Unknown job type: {job_type}")
        logger.error("job_unknown_type", job_id=str(job_id), job_type=job_type)
        return

    try:
        result = await handler(payload, report_progress)
        result_ref = json.dumps(result)
        await mark_job_completed(UUID(str(job_id)), result_ref)
        await cache_job_status(
            str(job_id),
            {
                "id": str(job_id),
                "job_type": job_type,
                "status": "completed",
                "stage": "done",
                "progress_pct": 100,
                "message": "Complete",
                "error": None,
                "result_ref": result_ref,
            },
        )
        logger.info("job_completed", job_id=str(job_id), job_type=job_type)
    except Exception as exc:
        await mark_job_failed(UUID(str(job_id)), str(exc))
        await cache_job_status(
            str(job_id),
            {
                "id": str(job_id),
                "job_type": job_type,
                "status": "failed",
                "error": str(exc),
            },
        )
        logger.error("job_failed", job_id=str(job_id), job_type=job_type, error=str(exc))
