# -*- coding: utf-8 -*-
"""Точка входа бота."""
import runpy
import sys

if not __package__:
    import os

    _ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    if _ROOT not in sys.path:
        sys.path.insert(0, _ROOT)
    runpy.run_module("bot.main", run_name="__main__")
    raise SystemExit(0)

import asyncio
import logging

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.fsm.storage.memory import MemoryStorage

from .config import config
from .context import init_ctx
from .db import Database
from .handlers.admin import router as admin_router
from .handlers.cabinet import router as cabinet_router
from .handlers.common import router as common_router
from .handlers.register import router as register_router
from .handlers.support import router as support_router
from .middlewares.check_sub import UserGate
from .scheduler import run_scheduler
from .wdtt import WdttClient

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logging.getLogger("aiogram.event").setLevel(logging.WARNING)
logging.getLogger("pymongo").setLevel(logging.WARNING)
log = logging.getLogger("main")


async def main():
    if not config.bot_token:
        raise SystemExit(
            "BOT_TOKEN не задан. Заполни .env (см. .env.example)."
        )

    db = Database(config)
    await db.init()

    wdtt = WdttClient(
        base_url=config.panel_base,
        api_key=config.panel_api_key,
        username=config.panel_username,
        password=config.panel_password,
        ssl_insecure=config.ssl_insecure,
        timeout=config.panel_timeout,
    )

    gate = UserGate(db)
    init_ctx(config, db, wdtt, gate)

    bot = Bot(
        config.bot_token,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    dp = Dispatcher(storage=MemoryStorage())
    dp["config"] = config
    dp["admin_ids"] = config.admin_ids

    dp.message.middleware(gate)
    dp.callback_query.middleware(gate)

    dp.include_router(admin_router)
    dp.include_router(register_router)
    dp.include_router(support_router)
    dp.include_router(common_router)
    dp.include_router(cabinet_router)

    try:
        me = await bot.get_me()
        log.info("Бот @%s запущен", me.username)
    except Exception as e:
        log.warning("Проверка токена не удалась: %s", e)

    scheduler_task = asyncio.create_task(run_scheduler())

    try:
        await bot.delete_webhook(drop_pending_updates=False)
        await dp.start_polling(bot)
    finally:
        scheduler_task.cancel()
        await wdtt.close()
        await db.close()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        log.info("Остановлено пользователем")
