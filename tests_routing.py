# -*- coding: utf-8 -*-
"""Интеграционный тест роутинга: /start и текст доходят до хендлеров
(через настоящий Dispatcher + замоканный Telegram API).

Тест воспроизводит баг: раньше fallback-хендлер кабинета перехватывал
команды и бот «молчал» на /start.
"""
import asyncio
import os

os.environ.setdefault("BOT_TOKEN", "111:TEST")
os.environ.setdefault("ADMINS", "1")


async def main():
    os.environ["MONGO_DB"] = "nttunnel_test"
    from unittest.mock import AsyncMock, MagicMock

    from aiogram import Bot, Dispatcher
    from aiogram.fsm.storage.memory import MemoryStorage
    from aiogram.types import CallbackQuery, Chat, Message, Update, User

    from bot.config import load_config
    from bot.context import init_ctx
    from bot.db import Database
    from bot.handlers.admin import router as admin_router
    from bot.handlers.cabinet import router as cabinet_router
    from bot.handlers.common import router as common_router
    from bot.handlers.register import router as register_router
    from bot.middlewares.check_sub import UserGate
    from bot.wdtt import WdttClient

    cfg = load_config()
    db = Database(cfg)
    await db.init()
    wdtt = WdttClient(cfg.panel_base, cfg.panel_username,
                      cfg.panel_password)
    gate = UserGate(db)
    init_ctx(cfg, db, wdtt, gate)

    bot = Bot(cfg.bot_token)
    # В aiogram 3 запросы идут через `await bot.session(bot, method, ...)`
    bot.session = AsyncMock(return_value=True)

    dp = Dispatcher(storage=MemoryStorage())
    dp["config"] = cfg
    dp["admin_ids"] = cfg.admin_ids
    dp.message.middleware(gate)
    dp.callback_query.middleware(gate)
    # тот же порядок, что в main.py
    dp.include_router(admin_router)
    dp.include_router(register_router)
    dp.include_router(common_router)
    dp.include_router(cabinet_router)

    async def send(text):
        u = User(id=901_001, is_bot=False, first_name="Tester",
                 username="tester001")
        m = Message(message_id=10,
                    date=__import__("datetime").datetime.now(),
                    chat=Chat(id=901_001, type="private"),
                    from_user=u, text=text)
        await db.users.delete_many({"tg_id": 901_001})
        upd = Update(update_id=hash(text) % 100000, message=m)
        await dp.feed_update(bot, upd)

    async def sent_methods():
        calls = []
        for c in bot.session.call_args_list:
            # session(bot, method, timeout=...) — method на позиции 1
            args = c.args
            if len(args) >= 2:
                calls.append(getattr(args[1], "__api_method__",
                                     str(args[1])))
        bot.session.reset_mock(side_effect=None)
        return calls

    # 1) /start должен ответить сообщением (меню)
    await send("/start")
    assert "sendMessage" in await sent_methods(), \
        "/start не был обработан — снова молчит!"

    # 2) обычный текст тоже отвечает меню
    await send("привет бот")
    assert "sendMessage" in await sent_methods(), "текст не обработан"

    # 3) /menu отвечает
    await send("/menu")
    assert "sendMessage" in await sent_methods(), "/menu не обработан"

    # 4) пользователя записало в БД со счётчиком (пересоздаётся в send())
    doc = await db.get_user(901_001)
    assert doc and doc["messages_count"] >= 1

    # ---- флоу регистрации (колбэки) — проверяем маршрутизацию шагов
    from datetime import datetime as _dt
    TG2 = 901_999
    await db.users.delete_many({"tg_id": TG2})
    await db.events.delete_many({"tg_id": TG2})
    # создаём юзера как незарегистрированного
    class FU2:
        id = TG2; username = "regflow"; first_name = "R"; last_name = None
        full_name = "R"; language_code = "ru"; is_premium = False
    await db.sync_user(FU2())

    def make_cb(data, mid):
        u = User(id=TG2, is_bot=False, first_name="R", username="regflow")
        chat = Chat(id=TG2, type="private")
        m = Message(message_id=mid, date=_dt.now(), chat=chat,
                    from_user=u, text="menu")
        return CallbackQuery(id=f"q{mid}", from_user=u,
                             chat_instance="c", data=data, message=m), u

    async def feed_cb(data, mid):
        bot.session.reset_mock(side_effect=None)
        cb, fu = make_cb(data, mid)
        await dp.feed_update(bot, Update(update_id=mid, callback_query=cb))

    # меню → «Создать подписку» → Шаг 1 приложение
    await feed_cb("u:reg", 7001)
    assert "editMessageText" in await sent_methods(), "шаг 1 не открылся"
    # выбор приложения → соглашение
    await feed_cb("u:app:WDTT", 7002)
    assert "editMessageText" in await sent_methods(), "соглашение не открылось"
    # согласие → шаг 2 (ввод VK-хеша) + FSM-состояние
    await feed_cb("u:agree:ok", 7003)
    assert "editMessageText" in await sent_methods(), "шаг 2 не открылся"
    from aiogram.fsm.storage.base import StorageKey
    key = StorageKey(bot_id=bot.id, chat_id=TG2, user_id=TG2)
    st = await dp.storage.get_state(key)
    assert st == "RegStates:hash", f"FSM не переведён на шаг 2: {st}"

    # ввод VK-хеша — проверяем парсер (полноценный message-шаг покрыт unit)
    from bot.utils import extract_vk_hash
    assert extract_vk_hash("https://vk.com/call/join/abc123XYZ") == "abc123XYZ"

    await db.client.drop_database("nttunnel_test")
    print("ROUTING_TEST_OK")


if __name__ == "__main__":
    asyncio.run(main())
