import io
import json
import uuid
from collections.abc import Awaitable, Callable
from typing import Any

import polars as pl

from api.core.db import get_pool
from api.core.logging import logger
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


def _read_tabular(file_bytes: bytes, source_format: str) -> pl.DataFrame:
    if source_format == "xlsx":
        return pl.read_excel(io.BytesIO(file_bytes), infer_schema_length=10000)
    try:
        return pl.read_csv(io.BytesIO(file_bytes), infer_schema_length=10000)
    except Exception:
        return pl.read_csv(io.BytesIO(file_bytes), infer_schema=False)


async def chunk_tabular_csv(
    session_id: str,
    blob_key: str,
    file_bytes: bytes,
    chunking_method: str = DEFAULT_CHUNKING_METHOD,
    chunking_config: dict | None = None,
    source_format: str = "csv",
    on_progress: ProgressCallback | None = None,
) -> dict[str, Any]:
    async def report(stage: str, progress_pct: int, message: str = "") -> None:
        if on_progress:
            await on_progress(stage, progress_pct, message)

    cfg = chunking_config or {}
    label = "Excel" if source_format == "xlsx" else "CSV"
    await report("chunking", 5, f"Parsing {label}")

    df = _read_tabular(file_bytes, source_format)
    rows = df.to_dicts()
    columns = df.columns
    sample = rows[: min(20, len(rows))]

    narrative_cols, categorical_cols, row_id_col = classify_columns(columns, sample)
    if not narrative_cols:
        raise ValueError(f"No narrative columns found in {label}; RAG ingestion requires free-text fields")

    await report("chunking", 15, f"Chunking with {chunking_method}")

    drafts: list[dict[str, Any]] = []
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
            embed_fn=embed_texts if chunking_method == "semantic" else None,
        )

        for sub_idx, chunk_text_value in enumerate(sub_chunks):
            drafts.append(
                {
                    "id": str(uuid.uuid4()),
                    "session_id": session_id,
                    "chunk_index": len(drafts),
                    "source_ref": source_ref if len(sub_chunks) == 1 else f"{source_ref}#chunk:{sub_idx + 1}",
                    "chunk_text": chunk_text_value,
                    "char_count": len(chunk_text_value),
                    "categorical_metadata": json.dumps(categorical_payload),
                }
            )

        if idx % max(1, total_rows // 10) == 0 or idx == total_rows:
            pct = 15 + int((idx / total_rows) * 80)
            await report("chunking", pct, f"Chunked {idx}/{total_rows} rows ({len(drafts)} chunks)")

    if not drafts:
        raise ValueError(f"No chunkable narrative content found in {label}")

    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute("DELETE FROM draft_chunks WHERE session_id = $1", uuid.UUID(session_id))
        for d in drafts:
            await conn.execute(
                """
                INSERT INTO draft_chunks
                  (id, session_id, chunk_index, source_ref, chunk_text, char_count, categorical_metadata)
                VALUES ($1, $2, $3, $4, $5, $6, $7)
                """,
                uuid.UUID(d["id"]),
                uuid.UUID(session_id),
                d["chunk_index"],
                d["source_ref"],
                d["chunk_text"],
                d["char_count"],
                d["categorical_metadata"],
            )
        await conn.execute(
            """
            UPDATE sessions
            SET chunk_count = $1,
                upload_status = 'chunked',
                chunking_method = $2,
                chunking_config = $3
            WHERE session_id = $4
            """,
            len(drafts),
            chunking_method,
            json.dumps(cfg),
            uuid.UUID(session_id),
        )

    await cache_session(
        session_id,
        {
            "session_id": session_id,
            "chunk_count": len(drafts),
            "upload_status": "chunked",
            "chunking_method": chunking_method,
        },
    )

    await report("chunking", 100, f"Ready to preview — {len(drafts)} chunks")
    logger.info(
        "chunk_tabular_completed",
        session_id=session_id,
        chunk_count=len(drafts),
        chunking_method=chunking_method,
    )
    return {
        "chunk_count": len(drafts),
        "rows": total_rows,
        "chunking_method": chunking_method,
    }
