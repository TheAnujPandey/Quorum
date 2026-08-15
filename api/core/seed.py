import json
from pathlib import Path
from uuid import UUID

from api.core.db import get_pool
from api.core.logging import logger

SEED_PATH = Path(__file__).resolve().parents[2] / "db" / "seed" / "labeled_qa.json"


async def seed_labeled_qa_for_session(session_id: UUID) -> int:
    if not SEED_PATH.exists():
        return 0

    items = json.loads(SEED_PATH.read_text(encoding="utf-8"))
    pool = await get_pool()
    async with pool.acquire() as conn:
        existing = await conn.fetchval(
            "SELECT COUNT(*) FROM labeled_qa WHERE session_id = $1::uuid",
            session_id,
        )
        if existing and int(existing) > 0:
            return 0

        for item in items:
            await conn.execute(
                """
                INSERT INTO labeled_qa (session_id, question, expected_answer, expected_source_ref)
                VALUES ($1::uuid, $2, $3, $4)
                """,
                session_id,
                item["question"],
                item["expected_answer"],
                item.get("expected_source_ref"),
            )

    logger.info("labeled_qa_seeded", session_id=str(session_id), count=len(items))
    return len(items)
