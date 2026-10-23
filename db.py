"""Small async PostgreSQL connection pool for Supabase."""
import os
from typing import Optional

import asyncpg

_pool: Optional[asyncpg.Pool] = None


async def init_db() -> None:
    """Open the pool and ensure the base user table exists."""
    global _pool
    dsn = os.getenv("DATABASE_URL", "").strip()
    if not dsn:
        raise RuntimeError(
            "Please set DATABASE_URL to your Supabase PostgreSQL connection string"
        )

    _pool = await asyncpg.create_pool(
        dsn=dsn,
        min_size=1,
        max_size=5,
        command_timeout=10,
        ssl="require",
    )

    async with _pool.acquire() as conn:
        await conn.execute(
            """
            CREATE TABLE IF NOT EXISTS telegram_users (
                user_id BIGINT PRIMARY KEY,
                username TEXT,
                first_name TEXT NOT NULL DEFAULT '',
                last_name TEXT,
                first_seen_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            )
            """
        )
        await conn.execute(
            "CREATE INDEX IF NOT EXISTS telegram_users_username_idx "
            "ON telegram_users (LOWER(username)) WHERE username IS NOT NULL"
        )

        await conn.execute("""
            CREATE TABLE IF NOT EXISTS group_user_ranks (
                chat_id BIGINT NOT NULL,
                user_id BIGINT NOT NULL,
                rank_key TEXT NOT NULL,
                assigned_by BIGINT,
                assigned_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                PRIMARY KEY (chat_id, user_id, rank_key)
            )
        """)

        await conn.execute("""
            CREATE TABLE IF NOT EXISTS global_user_ranks (
                user_id BIGINT NOT NULL,
                rank_key TEXT NOT NULL,
                assigned_by BIGINT,
                assigned_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                PRIMARY KEY (user_id, rank_key)
            )
        """)


async def close_db() -> None:
    global _pool
    if _pool is not None:
        await _pool.close()
        _pool = None


def get_pool() -> asyncpg.Pool:
    if _pool is None:
        raise RuntimeError("Database pool is not initialized")
    return _pool
