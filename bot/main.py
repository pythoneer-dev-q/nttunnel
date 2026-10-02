# -*- coding: utf-8 -*-
"""Точка входа бота.

Запуск (любой из вариантов):
  python -m bot.main
  python run.py
  python bot/main.py   # файл сам перезапустится в контексте пакета
"""
import runpy
import sys

if not __package__:
    # Файл запущен напрямую ("python bot/main.py") — относительные импорты
    # не работают. Перезапускаем сами себя как модуль пакета bot.
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
from .scheduler import panel_sync_loop, run_scheduler
from .wdtt import WdttClient

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s")
# шибко болтливые библиотеки — приглушить
logging.getLogger("aiogram.event").setLevel(logging.WARNING)
logging.getLogger("pymongo").setLevel(logging.WARNING)
log = logging.getLogger("main")


async def main():
    if not config.bot_token:
        raise SystemExit(
            "BOT_TOKEN не задан! Добавьте строку 'BOT-TOKEN = ваш_токен' в "
            "creds.txt или пропишите BOT_TOKEN в .env (см. .env.example), "
            "и укажите ADMINS.")

    db = Database(config)
    await db.init()
    wdtt = WdttClient(config.panel_base, config.panel_username,
                      config.panel_password, config.ssl_insecure)
    wdtt.attach_store(db)          # зеркало пользователей панели в MongoDB
    gate = UserGate(db)
    init_ctx(config, db, wdtt, gate)

    bot = Bot(config.bot_token,
              default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    dp = Dispatcher(storage=MemoryStorage())
    dp["config"] = config          # для middleware (нужен admin_ids)
    dp["admin_ids"] = config.admin_ids

    # middleware гейта на все апдейты от пользователя
    dp.message.middleware(gate)
    dp.callback_query.middleware(gate)

    # порядок важен: сначала админ-роутер (свой IsAdmin-фильтр),
    # затем пользовательские; cabinet подключён последним, т.к. содержит
    # текстовый fallback
    dp.include_router(admin_router)
    dp.include_router(register_router)
    dp.include_router(support_router)
    dp.include_router(common_router)
    dp.include_router(cabinet_router)

    try:
        me = await bot.get_me()
        log.info("Бот @%s запущен", me.username)
    except Exception as e:  # noqa: BLE001
        log.warning(
            "Проверка токена не удалась (сеть?): %s — polling попробует снова", e
        )

    scheduler_task = asyncio.create_task(run_scheduler())
    sync_task = asyncio.create_task(panel_sync_loop())
    try:
        await bot.delete_webhook(drop_pending_updates=False)
        await dp.start_polling(bot)
    finally:
        scheduler_task.cancel()
        sync_task.cancel()
        await wdtt.close()
        await db.close()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        log.info("Остановлено пользователем")
