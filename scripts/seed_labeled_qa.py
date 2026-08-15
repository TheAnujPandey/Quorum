"""Seed labeled Q&A pairs for eval benchmark.

Usage:
    python scripts/seed_labeled_qa.py --session-id <uuid>
"""

import argparse
import asyncio
import json
import sys
from pathlib import Path
from uuid import UUID

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from api.core.db import close_pool, get_pool, run_migrations  # noqa: E402


async def seed(session_id: str) -> None:
    await get_pool()
    await run_migrations()

    seed_path = ROOT / "db" / "seed" / "labeled_qa.json"
    items = json.loads(seed_path.read_text(encoding="utf-8"))

    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute("DELETE FROM labeled_qa WHERE session_id = $1::uuid", UUID(session_id))
        for item in items:
            await conn.execute(
                """
                INSERT INTO labeled_qa (session_id, question, expected_answer, expected_source_ref)
                VALUES ($1::uuid, $2, $3, $4)
                """,
                UUID(session_id),
                item["question"],
                item["expected_answer"],
                item.get("expected_source_ref"),
            )

    print(f"Seeded {len(items)} labeled Q&A pairs for session {session_id}")
    await close_pool()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--session-id", required=True, help="Session UUID from upload")
    args = parser.parse_args()
    asyncio.run(seed(args.session_id))


if __name__ == "__main__":
    main()
