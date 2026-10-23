
from typing import Optional

from aiogram.types import User
from db import get_pool

_registered_user_ids: set[int] = set()


async def ensure_user_registered(user: User) -> None:
    if user.id in _registered_user_ids:
        return

    pool = get_pool()

    async with pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO telegram_users
                (user_id, username, first_name, last_name)
            VALUES ($1, $2, $3, $4)
            ON CONFLICT (user_id) DO NOTHING
            """,
            user.id,
            user.username,
            user.first_name or "",
            user.last_name,
        )

    _registered_user_ids.add(user.id)


async def find_registered_user(
    *, user_id: Optional[int] = None,
    username: Optional[str] = None
) -> Optional[dict]:
    pool = get_pool()

    async with pool.acquire() as conn:
        if user_id is not None:
            row = await conn.fetchrow(
                """
                SELECT user_id, username, first_name, last_name
                FROM telegram_users
                WHERE user_id = $1
                """,
                user_id,
            )
        elif username:
            row = await conn.fetchrow(
                """
                SELECT user_id, username, first_name, last_name
                FROM telegram_users
                WHERE LOWER(username) = LOWER($1)
                LIMIT 1
                """,
                username.lstrip("@").strip(),
            )
        else:
            return None

    return dict(row) if row else None
