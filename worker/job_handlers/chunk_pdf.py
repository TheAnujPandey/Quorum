"""Chunk a PDF into draft_chunks for preview and embedding.

Prose is semantic-chunked per page. Tables are kept as whole chunks
(never split across rows/headers). Each chunk gets source_ref = "page:<n>".
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
from backend.ingestion.pdf_parser import parse_pdf

ProgressCallback = Callable[[str, int, str], Awaitable[None]]


async def chunk_pdf(
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

    await report("chunking", 5, "Parsing PDF")

    pages = parse_pdf(file_bytes)
    if not pages:
        raise ValueError("No extractable content found in PDF")

    await report("chunking", 20, f"Parsed {len(pages)} pages")

    drafts: list[dict[str, Any]] = []
    total_pages = len(pages)
    cfg = chunking_config or {}
    effective_method = chunking_method

    for idx, page in enumerate(pages):
        source_ref = f"page:{page.page_number}"

        if effective_method == "page":
            parts = []
            if page.prose:
                parts.append(page.prose)
            for table_md in page.tables:
                parts.append(table_md)
            if parts:
                full_text = "\n\n".join(parts)
                drafts.append({
                    "id": str(uuid.uuid4()),
                    "session_id": session_id,
                    "chunk_index": len(drafts),
                    "source_ref": source_ref,
                    "chunk_text": full_text,
                    "char_count": len(full_text),
                    "categorical_metadata": json.dumps({}),
                })
        else:
            if page.prose:
                prose_chunks = chunk_text(
                    page.prose,
                    method=effective_method,
                    config=cfg,
                    embed_fn=embed_texts if effective_method == "semantic" else None,
                )
                for sub_idx, text in enumerate(prose_chunks):
                    ref = source_ref if len(prose_chunks) == 1 else f"{source_ref}#chunk:{sub_idx + 1}"
                    drafts.append({
                        "id": str(uuid.uuid4()),
                        "session_id": session_id,
                        "chunk_index": len(drafts),
                        "source_ref": ref,
                        "chunk_text": text,
                        "char_count": len(text),
                        "categorical_metadata": json.dumps({}),
                    })

            for tbl_idx, table_md in enumerate(page.tables):
                ref = f"{source_ref}#table:{tbl_idx + 1}" if len(page.tables) > 1 else f"{source_ref}#table"
                drafts.append({
                    "id": str(uuid.uuid4()),
                    "session_id": session_id,
                    "chunk_index": len(drafts),
                    "source_ref": ref,
                    "chunk_text": table_md,
                    "char_count": len(table_md),
                    "categorical_metadata": json.dumps({}),
                })

        pct = 20 + int(((idx + 1) / total_pages) * 75)
        await report("chunking", pct, f"Chunked page {idx + 1}/{total_pages}")

    if not drafts:
        raise ValueError("No chunkable content found in PDF")

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
    logger.info("chunk_pdf_completed", session_id=session_id, chunk_count=len(drafts), method=chunking_method)
    return {"chunk_count": len(drafts), "pages": total_pages, "chunking_method": chunking_method}
