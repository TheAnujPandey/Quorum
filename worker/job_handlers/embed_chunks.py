import json
import uuid
from collections.abc import Awaitable, Callable
from typing import Any

from qdrant_client.http import models as qmodels

from api.core.config import settings
from api.core.db import get_pool
from api.core.logging import logger
from api.core.qdrant_client import ensure_collection, get_qdrant
from api.core.redis_client import cache_session
from backend.embeddings.model import embed_texts

ProgressCallback = Callable[[str, int, str], Awaitable[None]]


async def embed_draft_chunks(
    session_id: str,
    source_format: str = "csv",
    on_progress: ProgressCallback | None = None,
) -> dict[str, Any]:
    async def report(stage: str, progress_pct: int, message: str = "") -> None:
        if on_progress:
            await on_progress(stage, progress_pct, message)

    await report("embedding", 5, "Loading draft chunks")

    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT id, source_ref, chunk_text, categorical_metadata
            FROM draft_chunks
            WHERE session_id = $1
            ORDER BY chunk_index
            """,
            uuid.UUID(session_id),
        )

    if not rows:
        raise ValueError("No draft chunks found — run chunking first")

    await report("embedding", 15, f"Embedding {len(rows)} chunks")

    points: list[qmodels.PointStruct] = []
    texts = [r["chunk_text"] for r in rows]
    batch_size = 32
    total_batches = max(1, (len(texts) + batch_size - 1) // batch_size)
    vectors: list[list[float]] = []

    for batch_idx, i in enumerate(range(0, len(texts), batch_size), start=1):
        batch = texts[i : i + batch_size]
        vectors.extend(embed_texts(batch))
        pct = 15 + int((batch_idx / total_batches) * 70)
        await report("embedding", pct, f"Embedded batch {batch_idx}/{total_batches}")

    for row, vector in zip(rows, vectors, strict=True):
        meta = row["categorical_metadata"]
        if isinstance(meta, str):
            meta = json.loads(meta) if meta else {}
        elif meta is None:
            meta = {}
        points.append(
            qmodels.PointStruct(
                id=str(row["id"]),
                vector=vector,
                payload={
                    "session_id": session_id,
                    "source_format": source_format,
                    "source_ref": row["source_ref"],
                    "chunk_text": row["chunk_text"],
                    "embedding_model_version": settings.embedding_model_version,
                    **meta,
                },
            )
        )

    await report("embedding", 90, "Indexing in Qdrant")
    await ensure_collection()
    client = await get_qdrant()
    for i in range(0, len(points), 64):
        await client.upsert(
            collection_name=settings.qdrant_collection,
            points=points[i : i + 64],
        )

    async with pool.acquire() as conn:
        await conn.execute(
            "UPDATE sessions SET upload_status = 'ingested', chunk_count = $1 WHERE session_id = $2",
            len(points),
            uuid.UUID(session_id),
        )

    await cache_session(
        session_id,
        {
            "session_id": session_id,
            "chunk_count": len(points),
            "upload_status": "ingested",
        },
    )

    await report("embedding", 100, "Ready for Q&A")
    logger.info("embed_chunks_completed", session_id=session_id, chunk_count=len(points))
    return {"chunk_count": len(points)}
