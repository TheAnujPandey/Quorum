import re
import uuid
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path
from typing import Any

import asyncpg

from api.core.config import settings

_pool: asyncpg.Pool | None = None
_sqlite_db: "SqliteDatabase | None" = None


def _use_sqlite() -> bool:
    return settings.effective_database_url.startswith("sqlite:")


def _sqlite_path() -> Path:
    raw = settings.effective_database_url.removeprefix("sqlite:///")
    return Path(raw)


class SqliteConnection:
    def __init__(self, db: "SqliteDatabase") -> None:
        self._db = db

    @asynccontextmanager
    async def transaction(self):
        yield self

    async def execute(self, sql: str, *args: Any) -> None:
        await self._db.execute(sql, *args)

    async def fetchrow(self, sql: str, *args: Any) -> dict[str, Any] | None:
        return await self._db.fetchrow(sql, *args)

    async def fetch(self, sql: str, *args: Any) -> list[dict[str, Any]]:
        return await self._db.fetch(sql, *args)

    async def fetchval(self, sql: str, *args: Any) -> Any:
        row = await self.fetchrow(sql, *args)
        if row is None:
            return None
        return next(iter(row.values()))


class SqliteDatabase:
    def __init__(self, path: Path) -> None:
        self.path = path
        self._conn = None

    async def connect(self) -> None:
        import aiosqlite

        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = await aiosqlite.connect(self.path)
        self._conn.row_factory = aiosqlite.Row
        await self._conn.execute("PRAGMA journal_mode=WAL")
        await self._conn.execute("PRAGMA foreign_keys=ON")

    async def close(self) -> None:
        if self._conn is not None:
            await self._conn.close()
            self._conn = None

    def _convert_sql(self, sql: str, args: tuple[Any, ...] = ()) -> tuple[str, tuple[Any, ...]]:
        sql = sql.replace("::jsonb", "")
        sql = sql.replace("now()", "datetime('now')")
        sql = re.sub(r"\bFOR UPDATE SKIP LOCKED\b", "", sql, flags=re.IGNORECASE)
        sql = re.sub(r"::uuid\b", "", sql, flags=re.IGNORECASE)
        bound = self._bind_args(args)
        params: list[Any] = []

        def _repl(match: re.Match[str]) -> str:
            idx = int(match.group(1)) - 1
            params.append(bound[idx] if idx < len(bound) else None)
            return "?"

        sql = re.sub(r"\$(\d+)", _repl, sql)
        return sql, tuple(params)

    def _bind_args(self, args: tuple[Any, ...]) -> tuple[Any, ...]:
        bound: list[Any] = []
        for a in args:
            if isinstance(a, uuid.UUID):
                bound.append(str(a))
            elif isinstance(a, datetime):
                bound.append(a.isoformat())
            else:
                bound.append(a)
        return tuple(bound)

    async def execute(self, sql: str, *args: Any) -> None:
        assert self._conn is not None
        converted, params = self._convert_sql(sql, args)
        await self._conn.execute(converted, params)
        await self._conn.commit()

    async def fetchrow(self, sql: str, *args: Any) -> dict[str, Any] | None:
        assert self._conn is not None
        converted, params = self._convert_sql(sql, args)
        cursor = await self._conn.execute(converted, params)
        row = await cursor.fetchone()
        if re.match(r"^\s*(INSERT|UPDATE|DELETE)\b", sql, flags=re.IGNORECASE):
            await self._conn.commit()
        if row is None:
            return None
        return dict(row)

    async def fetch(self, sql: str, *args: Any) -> list[dict[str, Any]]:
        assert self._conn is not None
        converted, params = self._convert_sql(sql, args)
        cursor = await self._conn.execute(converted, params)
        rows = await cursor.fetchall()
        return [dict(r) for r in rows]

    @asynccontextmanager
    async def acquire(self):
        yield SqliteConnection(self)

    @asynccontextmanager
    async def transaction(self):
        yield SqliteConnection(self)


async def get_pool() -> Any:
    global _pool, _sqlite_db
    if _use_sqlite():
        if _sqlite_db is None:
            _sqlite_db = SqliteDatabase(_sqlite_path())
            await _sqlite_db.connect()
        return _sqlite_db
    if _pool is None:
        _pool = await asyncpg.create_pool(settings.postgres_url, min_size=2, max_size=10)
    return _pool


async def close_pool() -> None:
    global _pool, _sqlite_db
    if _pool is not None:
        await _pool.close()
        _pool = None
    if _sqlite_db is not None:
        await _sqlite_db.close()
        _sqlite_db = None


async def run_migrations() -> None:
    if _use_sqlite():
        await _run_sqlite_migrations()
        return

    pool = await get_pool()
    migrations_dir = Path(__file__).resolve().parents[2] / "db" / "migrations"
    for name in ("001_initial.sql", "002_draft_chunks.sql"):
        migration_path = migrations_dir / name
        if not migration_path.exists():
            continue
        sql = migration_path.read_text(encoding="utf-8")
        async with pool.acquire() as conn:
            await conn.execute(sql)


async def _run_sqlite_migrations() -> None:
    db = await get_pool()
    migrations_dir = Path(__file__).resolve().parents[2] / "db" / "migrations"
    for name in ("001_initial_sqlite.sql", "002_draft_chunks_sqlite.sql"):
        migration_path = migrations_dir / name
        if not migration_path.exists():
            continue
        sql = migration_path.read_text(encoding="utf-8")
        for statement in sql.split(";"):
            stmt = statement.strip()
            if stmt:
                await db.execute(stmt)

    # Additive columns for existing SQLite DBs
    for col_sql in (
        "ALTER TABLE sessions ADD COLUMN chunking_method TEXT",
        "ALTER TABLE sessions ADD COLUMN chunking_config TEXT",
    ):
        try:
            await db.execute(col_sql)
        except Exception:
            pass
