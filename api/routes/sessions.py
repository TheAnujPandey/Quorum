import json
from datetime import datetime
from typing import Any
from uuid import UUID

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from api.core.db import get_pool
from api.core.jobs import enqueue_job
from api.core.logging import logger
from api.core.redis_client import cache_session
from api.core.seed import seed_labeled_qa_for_session

router = APIRouter(prefix="/sessions", tags=["sessions"])


class ChunkRequest(BaseModel):
    chunking_method: str = "sentence"
    chunking_config: dict[str, Any] = Field(default_factory=dict)


class EmbedRequest(BaseModel):
    pass


class SessionResponse(BaseModel):
    session_id: UUID
    source_format: str
    blob_key: str
    upload_status: str
    chunk_count: int | None = None
    chunking_method: str | None = None
    chunking_config: dict[str, Any] | None = None
    created_at: datetime | None = None


class ChunkSample(BaseModel):
    chunk_index: int
    source_ref: str
    chunk_text: str
    char_count: int


class ChunkPreviewResponse(BaseModel):
    total: int
    avg_chars: float
    min_chars: int
    max_chars: int
    method: str | None
    config: dict[str, Any]
    sample: list[ChunkSample]


@router.get("/{session_id}", response_model=SessionResponse)
async def get_session(session_id: UUID) -> SessionResponse:
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT session_id, source_format, blob_key, upload_status, chunk_count,
                   chunking_method, chunking_config, created_at
            FROM sessions WHERE session_id = $1
            """,
            session_id,
        )
    if row is None:
        raise HTTPException(status_code=404, detail="Session not found")

    cfg = row.get("chunking_config")
    if isinstance(cfg, str):
        cfg = json.loads(cfg) if cfg else {}
    created = row["created_at"]
    if isinstance(created, str):
        created = datetime.fromisoformat(created)

    return SessionResponse(
        session_id=UUID(str(row["session_id"])),
        source_format=row["source_format"],
        blob_key=row["blob_key"],
        upload_status=row["upload_status"],
        chunk_count=row["chunk_count"],
        chunking_method=row.get("chunking_method"),
        chunking_config=cfg or {},
        created_at=created,
    )


@router.post("/{session_id}/chunk")
async def start_chunking(session_id: UUID, body: ChunkRequest) -> dict:
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT session_id, blob_key, upload_status, source_format FROM sessions WHERE session_id = $1",
            session_id,
        )
    if row is None:
        raise HTTPException(status_code=404, detail="Session not found")
    if row["upload_status"] not in ("uploaded", "chunked", "ingested"):
        raise HTTPException(status_code=400, detail=f"Cannot chunk from status: {row['upload_status']}")

    async with pool.acquire() as conn:
        await conn.execute(
            "UPDATE sessions SET upload_status = 'chunking' WHERE session_id = $1",
            session_id,
        )

    fmt = row["source_format"]
    JOB_TYPE_MAP = {"csv": "chunk_tabular", "xlsx": "chunk_tabular", "pdf": "chunk_pdf", "txt": "chunk_txt"}
    job_type = JOB_TYPE_MAP.get(fmt, "chunk_tabular")

    payload: dict[str, Any] = {
        "session_id": str(session_id),
        "blob_key": row["blob_key"],
        "chunking_method": body.chunking_method,
        "chunking_config": body.chunking_config,
    }
    if job_type == "chunk_tabular":
        payload["source_format"] = fmt

    job_id = await enqueue_job(job_type, payload)
    logger.info("chunk_job_enqueued", session_id=str(session_id), job_id=str(job_id), job_type=job_type)
    return {"job_id": str(job_id)}


@router.get("/{session_id}/chunks", response_model=ChunkPreviewResponse)
async def get_chunk_preview(session_id: UUID, sample_size: int = 20) -> ChunkPreviewResponse:
    pool = await get_pool()
    async with pool.acquire() as conn:
        session = await conn.fetchrow(
            "SELECT chunking_method, chunking_config, upload_status FROM sessions WHERE session_id = $1",
            session_id,
        )
        if session is None:
            raise HTTPException(status_code=404, detail="Session not found")

        stats = await conn.fetchrow(
            """
            SELECT COUNT(*) AS total,
                   AVG(char_count) AS avg_chars,
                   MIN(char_count) AS min_chars,
                   MAX(char_count) AS max_chars
            FROM draft_chunks WHERE session_id = $1
            """,
            session_id,
        )
        samples = await conn.fetch(
            """
            SELECT chunk_index, source_ref, chunk_text, char_count
            FROM draft_chunks
            WHERE session_id = $1
            ORDER BY chunk_index
            LIMIT $2
            """,
            session_id,
            sample_size,
        )

    cfg = session.get("chunking_config")
    if isinstance(cfg, str):
        cfg = json.loads(cfg) if cfg else {}

    total = int(stats["total"] or 0) if stats else 0
    return ChunkPreviewResponse(
        total=total,
        avg_chars=float(stats["avg_chars"] or 0),
        min_chars=int(stats["min_chars"] or 0),
        max_chars=int(stats["max_chars"] or 0),
        method=session.get("chunking_method"),
        config=cfg or {},
        sample=[
            ChunkSample(
                chunk_index=s["chunk_index"],
                source_ref=s["source_ref"],
                chunk_text=s["chunk_text"][:500],
                char_count=s["char_count"],
            )
            for s in samples
        ],
    )


@router.post("/{session_id}/embed")
async def start_embedding(session_id: UUID) -> dict:
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT upload_status, source_format FROM sessions WHERE session_id = $1",
            session_id,
        )
        count = await conn.fetchval(
            "SELECT COUNT(*) FROM draft_chunks WHERE session_id = $1",
            session_id,
        )
    if row is None:
        raise HTTPException(status_code=404, detail="Session not found")
    if row["upload_status"] != "chunked" and not count:
        raise HTTPException(status_code=400, detail="Chunk data first before embedding")

    async with pool.acquire() as conn:
        await conn.execute(
            "UPDATE sessions SET upload_status = 'embedding' WHERE session_id = $1",
            session_id,
        )

    await seed_labeled_qa_for_session(session_id)
    job_id = await enqueue_job(
        "embed_chunks",
        {"session_id": str(session_id), "source_format": row["source_format"]},
    )
    logger.info("embed_job_enqueued", session_id=str(session_id), job_id=str(job_id))
    return {"job_id": str(job_id)}


@router.delete("/{session_id}")
async def clear_session(session_id: UUID) -> dict:
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute("DELETE FROM draft_chunks WHERE session_id = $1", session_id)
        await conn.execute("DELETE FROM labeled_qa WHERE session_id = $1", session_id)
        await conn.execute("DELETE FROM sessions WHERE session_id = $1", session_id)
    await cache_session(str(session_id), {"upload_status": "cleared"})
    return {"ok": True}
