import io
import uuid
from collections.abc import Awaitable, Callable
from typing import Any

import polars as pl
from qdrant_client.http import models as qmodels

from api.core.config import settings
from api.core.db import get_pool
from api.core.logging import logger
from api.core.qdrant_client import ensure_collection, get_qdrant
from api.core.redis_client import cache_session
from backend.embeddings.model import embed_texts
from backend.ingestion.chunk_strategies import DEFAULT_CHUNKING_METHOD, chunk_text
from backend.ingestion.tabular_split import (
    build_categorical_payload,
    build_row_narrative,
    classify_columns,
    row_source_ref,
)

ProgressCallback = Callable[[str, int, str], Awaitable[None]]


async def ingest_tabular_csv(
    session_id: str,
    blob_key: str,
    file_bytes: bytes,
    on_progress: ProgressCallback | None = None,
    chunking_method: str = DEFAULT_CHUNKING_METHOD,
    chunking_config: dict | None = None,
) -> dict[str, Any]:
    async def report(stage: str, progress_pct: int, message: str = "") -> None:
        if on_progress:
            await on_progress(stage, progress_pct, message)

    cfg = chunking_config or {}
    use_embed = chunking_method == "semantic"

    await report("chunking", 5, "Parsing CSV")

    try:
        df = pl.read_csv(io.BytesIO(file_bytes), infer_schema_length=10000)
    except Exception:
        df = pl.read_csv(io.BytesIO(file_bytes), infer_schema=False)
    rows = df.to_dicts()
    columns = df.columns
    sample = rows[: min(20, len(rows))]

    narrative_cols, categorical_cols, row_id_col = classify_columns(columns, sample)
    if not narrative_cols:
        raise ValueError("No narrative columns found in CSV; RAG ingestion requires free-text fields")

    await report("chunking", 15, f"Classifying columns (method: {chunking_method})")

    points: list[qmodels.PointStruct] = []
    chunk_count = 0
    total_rows = len(rows)

    for idx, row in enumerate(rows, start=1):
        narrative = build_row_narrative(row, narrative_cols)
        if not narrative.strip():
            continue

        categorical_payload = build_categorical_payload(row, categorical_cols)
        source_ref = row_source_ref(row, row_id_col, idx)
        sub_chunks = chunk_text(
            narrative,
            method=chunking_method,
            config=cfg,
            embed_fn=embed_texts if use_embed else None,
        )

        for sub_idx, chunk_text_value in enumerate(sub_chunks):
            chunk_count += 1
            point_id = str(uuid.uuid4())
            payload = {
                "session_id": session_id,
                "source_format": "csv",
                "source_ref": source_ref if len(sub_chunks) == 1 else f"{source_ref}#chunk:{sub_idx + 1}",
                "chunk_text": chunk_text_value,
                "embedding_model_version": settings.embedding_model_version,
                **categorical_payload,
            }
            points.append(
                qmodels.PointStruct(
                    id=point_id,
                    vector=[0.0] * 384,
                    payload=payload,
                )
            )

        if idx % max(1, total_rows // 10) == 0 or idx == total_rows:
            pct = 15 + int((idx / total_rows) * 35)
            await report("chunking", pct, f"Chunked {idx}/{total_rows} rows ({chunk_count} chunks)")

    if not points:
        raise ValueError("No embeddable narrative content found in CSV")

    await report("chunking", 50, f"Chunking complete — {chunk_count} chunks")

    texts = [p.payload["chunk_text"] for p in points]
    batch_size = 32
    total_batches = max(1, (len(texts) + batch_size - 1) // batch_size)

    await report("embedding", 55, "Embedding chunks")

    for batch_idx, i in enumerate(range(0, len(texts), batch_size), start=1):
        batch_texts = texts[i : i + batch_size]
        batch_vectors = embed_texts(batch_texts)
        for point, vector in zip(points[i : i + batch_size], batch_vectors, strict=True):
            point.vector = vector
        pct = 55 + int((batch_idx / total_batches) * 35)
        await report("embedding", pct, f"Embedded batch {batch_idx}/{total_batches}")

    await report("embedding", 92, "Indexing in Qdrant")

    await ensure_collection()
    client = await get_qdrant()
    qdrant_batch = 64
    for i in range(0, len(points), qdrant_batch):
        await client.upsert(
            collection_name=settings.qdrant_collection,
            points=points[i : i + qdrant_batch],
        )

    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            "UPDATE sessions SET chunk_count = $1, upload_status = 'ingested' WHERE session_id = $2::uuid",
            chunk_count,
            uuid.UUID(session_id),
        )

    await cache_session(
        session_id,
        {
            "session_id": session_id,
            "chunk_count": chunk_count,
            "upload_status": "ingested",
        },
    )

    await report("embedding", 100, "Ready for Q&A")

    logger.info(
        "ingest_tabular_completed",
        session_id=session_id,
        chunk_count=chunk_count,
        rows=len(rows),
        chunking_method=chunking_method,
    )
    return {"chunk_count": chunk_count, "rows": len(rows), "chunking_method": chunking_method}
