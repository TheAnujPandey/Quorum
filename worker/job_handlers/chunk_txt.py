"""Chunk a plain-text file into draft_chunks for preview and embedding.

Text is semantic-chunked directly. Each chunk gets source_ref = "chunk:<n>".
"""

import json
import uuid
from collections.abc import Awaitable, Callable
from typing import Any

from api.core.db import get_pool
from api.core.logging import logger
from api.core.redis_client import cache_session
from backend.embeddings.model import embed_texts
from backend.ingestion.chunk_strategies import chunk_text

ProgressCallback = Callable[[str, int, str], Awaitable[None]]


async def chunk_txt(
    session_id: str,
    blob_key: str,
    file_bytes: bytes,
    chunking_method: str = "semantic",
    chunking_config: dict | None = None,
    on_progress: ProgressCallback | None = None,
) -> dict[str, Any]:
    async def report(stage: str, pct: int, msg: str = "") -> None:
        if on_progress:
            await on_progress(stage, pct, msg)

    await report("chunking", 5, "Reading text file")

    for encoding in ("utf-8", "latin-1"):
        try:
            text = file_bytes.decode(encoding)
            break
        except UnicodeDecodeError:
            continue
    else:
        text = file_bytes.decode("utf-8", errors="replace")

    text = text.strip()
    if not text:
        raise ValueError("Text file is empty")

    await report("chunking", 15, "Chunking text")

    cfg = chunking_config or {}
    chunks = chunk_text(
        text,
        method=chunking_method,
        config=cfg,
        embed_fn=embed_texts if chunking_method == "semantic" else None,
    )
    if not chunks:
        raise ValueError("No chunkable content found in text file")

    drafts: list[dict[str, Any]] = []
    for idx, chunk_value in enumerate(chunks, start=1):
        drafts.append({
            "id": str(uuid.uuid4()),
            "session_id": session_id,
            "chunk_index": idx - 1,
            "source_ref": f"chunk:{idx}",
            "chunk_text": chunk_value,
            "char_count": len(chunk_value),
            "categorical_metadata": json.dumps({}),
        })

    await report("chunking", 80, f"Saving {len(drafts)} chunks")

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
            SET chunk_count = $1, upload_status = 'chunked',
                chunking_method = $3, chunking_config = $4
            WHERE session_id = $2
            """,
            len(drafts),
            uuid.UUID(session_id),
            chunking_method,
            json.dumps(cfg),
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
    logger.info("chunk_txt_completed", session_id=session_id, chunk_count=len(drafts), method=chunking_method)
    return {"chunk_count": len(drafts), "chunking_method": chunking_method}
