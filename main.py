import asyncio
import os

from aiohttp import web
from aiogram import Bot, Dispatcher
from aiogram.filters import CommandStart
from aiogram.types import Message

from rank_system import router as rank_router

from db import close_db, init_db
from user_registry import ensure_user_registered

BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()
PORT = int(os.getenv("PORT", "10000"))

if not BOT_TOKEN:
    raise RuntimeError("Please set BOT_TOKEN in Render Environment Variables")

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()
dp.include_router(rank_router)


@dp.message(CommandStart())
async def start_command(message: Message) -> None:
    # Register the sender once. Future commands can use the same helper.
    if message.from_user:
        await ensure_user_registered(message.from_user)
    await message.answer("حياك بالبوت 🤍")


async def home(request: web.Request) -> web.Response:
    # Render needs the Web Service to listen on PORT; no /health route is added.
    return web.Response(text="Bot is running")


async def main() -> None:
    app = web.Application()
    app.router.add_get("/", home)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", PORT)
    await site.start()

    try:
        await init_db()
        await dp.start_polling(bot)
    finally:
        await close_db()
        await runner.cleanup()
        await bot.session.close()


if __name__ == "__main__":
    asyncio.run(main())
