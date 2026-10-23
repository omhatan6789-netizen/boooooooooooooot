
import html
import os
import re

from aiogram import Router, F
from aiogram.types import Message
from db import get_pool
from user_registry import ensure_user_registered, find_registered_user

router = Router()

# المستوى الأعلى رقمه أكبر
RANKS = {
    "nawaf": ("Nawaf🎖️", 1000, True),
    "dev": ("Dev🎖️", 900, True),
    "dev2": ("Dev²🎖️", 800, True),
    "owner": ("المالك", 700, False),
    "creator": ("المنشئ", 600, False),
    "manager": ("المدير", 500, False),
    "admin": ("الادمن", 400, False),
    "distinguished": ("المميز", 300, False),
    "member": ("العضو", 100, False),
}

ALIASES = {
    "nawaf🎖️": "nawaf",
    "نواف": "nawaf",
    "dev🎖️": "dev",
    "dev": "dev",
    "dev²🎖️": "dev2",
    "dev2": "dev2",
    "dev 2": "dev2",
    "مالك": "owner",
    "المالك": "owner",
    "منشئ": "creator",
    "المنشئ": "creator",
    "مدير": "manager",
    "المدير": "manager",
    "ادمن": "admin",
    "الأدمن": "admin",
    "الادمن": "admin",
    "مميز": "distinguished",
    "المميز": "distinguished",
    "عضو": "member",
    "العضو": "member",
}


def mention(user_id: int, name: str | None) -> str:
    safe_name = html.escape(name or str(user_id))
    return f'<a href="tg://user?id={user_id}">{safe_name}</a>'


def normalize_rank(text: str) -> str | None:
    return ALIASES.get(text.strip().lower())


async def get_ranks(chat_id: int, user_id: int) -> list[str]:
    pool = get_pool()

    async with pool.acquire() as conn:
        local_rows = await conn.fetch(
            """
            SELECT rank_key
            FROM group_user_ranks
            WHERE chat_id = $1 AND user_id = $2
            """,
            chat_id, user_id,
        )

        global_rows = await conn.fetch(
            """
            SELECT rank_key
            FROM global_user_ranks
            WHERE user_id = $1
            """,
            user_id,
        )

    ranks = list(dict.fromkeys(
        [row["rank_key"] for row in local_rows]
        + [row["rank_key"] for row in global_rows]
    ))

    return [rank for rank in ranks if rank in RANKS]


async def highest_rank(chat_id: int, user_id: int) -> str:
    ranks = await get_ranks(chat_id, user_id)
    if not ranks:
        return "member"

    return max(ranks, key=lambda key: RANKS[key][1])


async def ensure_local_member(chat_id: int, user_id: int) -> None:
    pool = get_pool()

    async with pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO group_user_ranks (chat_id, user_id, rank_key)
            VALUES ($1, $2, 'member')
            ON CONFLICT DO NOTHING
            """,
            chat_id, user_id,
        )



async def resolve_target(
    message: Message, target_text: str
) -> tuple[int, str, str | None] | None:
    # إذا كان الأمر ردًا على رسالة، فالشخص الموجود في الرد له الأولوية
    replied = message.reply_to_message

    if replied and replied.from_user:
        user = replied.from_user

        await ensure_user_registered(user)
        await ensure_local_member(message.chat.id, user.id)

        return user.id, user.full_name, user.username

    target_text = target_text.strip()
    if not target_text:
        return None

    pool = get_pool()

    if target_text.isdigit():
        user_id = int(target_text)

        try:
            member = await message.bot.get_chat_member(
                message.chat.id, user_id
            )
            user = member.user

            await ensure_user_registered(user)
            await ensure_local_member(message.chat.id, user.id)

            return user.id, user.full_name, user.username
        except Exception:
            profile = await find_registered_user(user_id=user_id)

            if not profile:
                return None

            name = profile.get("first_name") or str(user_id)
            username = profile.get("username")

            await ensure_local_member(message.chat.id, user_id)
            return user_id, name, username

    if target_text.startswith("@"):
        profile = await find_registered_user(
            username=target_text.lstrip("@")
        )

        if profile:
            user_id = int(profile["user_id"])
            name = profile.get("first_name") or target_text
            username = profile.get("username")

            await ensure_local_member(message.chat.id, user_id)
            return user_id, name, username

    return None



def parse_rank_and_target(
    body: str,
) -> tuple[str, str] | None:
    body = body.strip()

    # نطابق أسماء الرتب الأطول أولًا
    for alias in sorted(ALIASES, key=len, reverse=True):
        if body.lower() == alias:
            return ALIASES[alias], ""

        if body.lower().startswith(alias + " "):
            target_text = body[len(alias):].strip()
            return ALIASES[alias], target_text

    return None


async def can_manage_rank(
    chat_id: int,
    actor_id: int,
    target_id: int,
    rank_key: str,
    action: str,
) -> bool:
    configured_nawaf = os.getenv("NAWAF_USER_ID", "").strip()
    is_nawaf = configured_nawaf.isdigit() and actor_id == int(configured_nawaf)

    if is_nawaf:
        return True

    actor_rank = await highest_rank(chat_id, actor_id)
    actor_level = RANKS[actor_rank][1]
    target_rank_level = RANKS[rank_key][1]

    # لا يستطيع الشخص منح رتبة مساوية لرتبته أو أعلى منها
    if action == "promote" and target_rank_level >= actor_level:
        return False

    # لا يستطيع تنزيل رتبة مساوية لرتبته أو أعلى منها
    if action == "demote" and target_rank_level >= actor_level:
        return False

    # رتبة نواف محصورة بمعرّف صاحب البوت المحدد في الإعدادات
    if rank_key == "nawaf":
        return False

    # لا يمكن تنزيل رتبة مالك المجموعة إلا بواسطة Dev أو Nawaf
    if action == "demote" and rank_key == "owner":
        pool = get_pool()
        async with pool.acquire() as conn:
            owner_id = await conn.fetchval(
                """
                SELECT user_id
                FROM group_user_ranks
                WHERE chat_id = $1 AND rank_key = 'owner'
                LIMIT 1
                """,
                chat_id,
            )

        if owner_id == target_id and actor_rank not in {"dev"}:
            return False

    # Dev أعلى من Dev²، وDev² لا يمكنه إدارة رتبة Dev
    if rank_key == "dev" and actor_rank != "dev":
        return False

    if rank_key == "dev2" and actor_rank not in {"dev"}:
        return False

    return True


async def save_rank(
    chat_id: int,
    user_id: int,
    rank_key: str,
    actor_id: int,
    remove: bool = False,
) -> None:
    pool = get_pool()
    is_global = RANKS[rank_key][2]

    table = "global_user_ranks" if is_global else "group_user_ranks"

    async with pool.acquire() as conn:
        if remove:
            if is_global:
                await conn.execute(
                    """
                    DELETE FROM global_user_ranks
                    WHERE user_id = $1 AND rank_key = $2
                    """,
                    user_id, rank_key,
                )
            else:
                await conn.execute(
                    """
                    DELETE FROM group_user_ranks
                    WHERE chat_id = $1 AND user_id = $2
                      AND rank_key = $3
                    """,
                    chat_id, user_id, rank_key,
                )
        else:
            if is_global:
                await conn.execute(
                    f"""
                    INSERT INTO {table}
                        (user_id, rank_key, assigned_by)
                    VALUES ($1, $2, $3)
                    ON CONFLICT (user_id, rank_key) DO NOTHING
                    """,
                    user_id, rank_key, actor_id,
                )
            else:
                await conn.execute(
                    f"""
                    INSERT INTO {table}
                        (chat_id, user_id, rank_key, assigned_by)
                    VALUES ($1, $2, $3, $4)
                    ON CONFLICT (chat_id, user_id, rank_key)
                    DO NOTHING
                    """,
                    chat_id, user_id, rank_key, actor_id,
                )


async def handle_rank_change(message: Message, action: str) -> None:
    if not message.from_user or not message.text:
        return

    if message.chat.type not in {"group", "supergroup"}:
        return

    prefix = "رفع " if action == "promote" else "تنزيل "
    body = message.text.strip()[len(prefix):].strip()

    parsed = parse_rank_and_target(body)
    if not parsed:
        return

    rank_key, target_text = parsed

    target = await resolve_target(message, target_text)
    if not target:
        await message.reply("• اعذرني بس مالقيت معلوماته.")
        return

    target_id, target_name, _ = target
    actor_id = message.from_user.id

    if not await can_manage_rank(
        message.chat.id, actor_id, target_id, rank_key, action
    ):
        await message.reply("• اعذرني بس ما عندك الصلاحية الكافية.")
        return

    # تأكد من تسجيل صاحب الأمر أيضًا
    await ensure_user_registered(message.from_user)
    await ensure_local_member(message.chat.id, actor_id)

    # لا تسمح بإعطاء رتبة Nawaf إلا للحساب المحدد في إعدادات Render
    if rank_key == "nawaf":
        configured = os.getenv("NAWAF_USER_ID", "").strip()
        if not configured.isdigit() or target_id != int(configured):
            await message.reply("• رتبة Nawaf🎖️ مخصصة لصاحب البوت فقط.")
            return

    await save_rank(
        message.chat.id,
        target_id,
        rank_key,
        actor_id,
        remove=(action == "demote"),
    )

    rank_name = RANKS[rank_key][0]
    short_name = rank_name

    if rank_key in {
        "owner", "creator", "manager", "admin", "distinguished", "member"
    }:
        short_name = {
            "owner": "مالك",
            "creator": "منشئ",
            "manager": "مدير",
            "admin": "ادمن",
            "distinguished": "مميز",
            "member": "عضو",
        }[rank_key]

    if action == "promote":
        text = (
            f"• تمام رفعته {html.escape(short_name)} .\n"
            f"• المستخدم ↤︎ {mention(target_id, target_name)}"
        )
    else:
        text = (
            f"• تمام نزلته من {html.escape(short_name)}\n"
            f"• المستخدم ↤︎ {mention(target_id, target_name)}"
        )

    await message.reply(text, parse_mode="HTML")


@router.message(F.text.regexp(re.compile(r"^\s*رفع\s+", re.I)))
async def promote_rank(message: Message) -> None:
    await handle_rank_change(message, "promote")


@router.message(F.text.regexp(re.compile(r"^\s*تنزيل\s+", re.I)))
async def demote_rank(message: Message) -> None:
    await handle_rank_change(message, "demote")


@router.message(F.text.func(lambda text: text and text.strip() == "رتبتي"))
async def my_rank(message: Message) -> None:
    if not message.from_user:
        return

    await ensure_user_registered(message.from_user)

    if message.chat.type in {"group", "supergroup"}:
        await ensure_local_member(message.chat.id, message.from_user.id)

    rank_key = await highest_rank(message.chat.id, message.from_user.id)
    await message.reply(f"• رتبتك هي ↤︎ ‎{RANKS[rank_key][0]}")


@router.message(F.text.func(lambda text: text and text.strip() == "رتبته"))
async def their_rank(message: Message) -> None:
    replied = message.reply_to_message

    if not replied or not replied.from_user:
        return

    user = replied.from_user
    await ensure_user_registered(user)

    if message.chat.type in {"group", "supergroup"}:
        await ensure_local_member(message.chat.id, user.id)

    rank_key = await highest_rank(message.chat.id, user.id)
    await message.reply(f"• رتبته هي ↤︎ ‎{RANKS[rank_key][0]}")
