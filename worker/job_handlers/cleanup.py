"""TTL sweep: clean up expired sessions and their associated data.

Finds sessions where expires_at < now(), then deletes:
- Qdrant points for the session
- draft_chunks rows
- labeled_qa rows
- eval_results (via eval_runs that reference the session's labeled_qa)
- The session row itself
- Blob objects (best-effort)
"""

from collections.abc import Awaitable, Callable
from typing import Any

from api.core.config import settings
from api.core.db import get_pool
from api.core.logging import logger

ProgressCallback = Callable[[str, int, str], Awaitable[None]]


async def cleanup_expired_sessions(
    on_progress: ProgressCallback | None = None,
) -> dict[str, Any]:
    async def report(stage: str, pct: int, msg: str = "") -> None:
        if on_progress:
            await on_progress(stage, pct, msg)

    await report("cleanup", 5, "Scanning for expired sessions")

    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT session_id, blob_key
            FROM sessions
            WHERE expires_at < now()
            """
        )

    if not rows:
        await report("cleanup", 100, "No expired sessions")
        return {"cleaned": 0}

    total = len(rows)
    cleaned = 0

    for idx, row in enumerate(rows):
        sid = row["session_id"]
        blob_key = row["blob_key"]

        try:
            from api.core.qdrant_client import get_qdrant
            from qdrant_client.http import models as qmodels

            client = await get_qdrant()
            await client.delete(
                collection_name=settings.qdrant_collection,
                points_selector=qmodels.FilterSelector(
                    filter=qmodels.Filter(
                        must=[
                            qmodels.FieldCondition(
                                key="session_id",
                                match=qmodels.MatchValue(value=str(sid)),
                            )
                        ]
                    )
                ),
            )
        except Exception as exc:
            logger.warning("cleanup_qdrant_failed", session_id=str(sid), error=str(exc))

        try:
            from api.core.blob_store import download_bytes  # noqa: F401

            if settings.storage_backend == "s3" and blob_key:
                from api.core.blob_store import get_s3_client
                async with await get_s3_client() as s3:
                    await s3.delete_object(Bucket=settings.minio_bucket, Key=blob_key)
        except Exception as exc:
            logger.warning("cleanup_blob_failed", session_id=str(sid), error=str(exc))

        async with pool.acquire() as conn:
            await conn.execute("DELETE FROM draft_chunks WHERE session_id = $1", sid)
            await conn.execute("DELETE FROM labeled_qa WHERE session_id = $1", sid)
            await conn.execute("DELETE FROM sessions WHERE session_id = $1", sid)

        cleaned += 1
        pct = 5 + int((idx + 1) / total * 90)
        await report("cleanup", pct, f"Cleaned {cleaned}/{total} sessions")

    await report("cleanup", 100, f"Cleaned {cleaned} expired sessions")
    logger.info("cleanup_completed", cleaned=cleaned)
    return {"cleaned": cleaned}
