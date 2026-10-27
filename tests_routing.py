# -*- coding: utf-8 -*-
"""Интеграционный тест роутинга через настоящий Dispatcher (нужен MongoDB)."""
import asyncio
import os

os.environ.setdefault("BOT_TOKEN", "111:TEST")
os.environ.setdefault("ADMINS", "1")


async def main():
    os.environ["MONGO_DB"] = "nttunnel_test"

    from unittest.mock import AsyncMock

    from aiogram import Bot, Dispatcher
    from aiogram.fsm.storage.memory import MemoryStorage
    from aiogram.types import CallbackQuery, Chat, Message, Update, User

    from bot.config import load_config
    from bot.context import app, init_ctx
    from bot.db import Database
    from bot.handlers.admin import router as admin_router
    from bot.handlers.cabinet import router as cabinet_router
    from bot.handlers.common import router as common_router
    from bot.handlers.register import router as register_router
    from bot.handlers.support import router as support_router
    from bot.middlewares.check_sub import UserGate
    from bot.wdtt import WdttClient

    cfg = load_config()
    db = Database(cfg)
    await db.init()

    wdtt = WdttClient(
        base_url=cfg.panel_base,
        api_key=cfg.panel_api_key,
        username=cfg.panel_username,
        password=cfg.panel_password,
        ssl_insecure=cfg.ssl_insecure,
    )
    gate = UserGate(db)
    init_ctx(cfg, db, wdtt, gate)

    bot = Bot(cfg.bot_token)
    bot.session = AsyncMock(return_value=True)

    dp = Dispatcher(storage=MemoryStorage())
    dp["config"] = cfg
    dp["admin_ids"] = cfg.admin_ids

    dp.message.middleware(gate)
    dp.callback_query.middleware(gate)

    dp.include_router(admin_router)
    dp.include_router(register_router)
    dp.include_router(support_router)
    dp.include_router(common_router)
    dp.include_router(cabinet_router)

    async def send(text):
        tg_id = 901_001
        user = User(
            id=tg_id, is_bot=False, first_name="Tester", username="tester001"
        )
        message = Message(
            message_id=10,
            date=__import__("datetime").datetime.now(),
            chat=Chat(id=tg_id, type="private"),
            from_user=user,
            text=text,
        )
        await db.users.delete_many({"tg_id": tg_id})
        await dp.feed_update(
            bot, Update(update_id=hash(text) % 100000, message=message)
        )

    async def sent_methods():
        calls = []
        for call in bot.session.call_args_list:
            if len(call.args) >= 2:
                calls.append(
                    getattr(call.args[1], "__api_method__", str(call.args[1]))
                )
        bot.session.reset_mock(side_effect=None)
        return calls

    await send("/start")
    assert "sendMessage" in await sent_methods(), "/start не ответил"

    await send("привет бот")
    assert "sendMessage" in await sent_methods(), "текст не обработан"

    await send("/menu")
    assert "sendMessage" in await sent_methods(), "/menu не обработан"

    doc = await db.get_user(901_001)
    assert doc and doc["messages_count"] >= 1

    from datetime import datetime as dt

    TG2 = 901_999
    await db.users.delete_many({"tg_id": TG2})
    await db.events.delete_many({"tg_id": TG2})

    class FakeUser:
        id = TG2
        username = "regflow"
        first_name = "R"
        last_name = None
        full_name = "R"
        language_code = "ru"
        is_premium = False

    await db.sync_user(FakeUser())

    def make_cb(data, mid):
        user = User(
            id=TG2, is_bot=False, first_name="R", username="regflow"
        )
        chat = Chat(id=TG2, type="private")
        message = Message(
            message_id=mid, date=dt.now(), chat=chat,
            from_user=user, text="menu",
        )
        return CallbackQuery(
            id=f"q{mid}", from_user=user, chat_instance="c",
            data=data, message=message,
        )

    async def feed_cb(data, mid):
        bot.session.reset_mock(side_effect=None)
        cb = make_cb(data, mid)
        await dp.feed_update(
            bot, Update(update_id=mid, callback_query=cb)
        )

    # «Создать доступ» → соглашение
    await feed_cb("u:reg", 7001)
    assert "editMessageText" in await sent_methods(), "соглашение не открылось"

    # «Мой доступ» без регистрации → экран «нет доступа»
    await feed_cb("u:access", 7002)
    assert "editMessageText" in await sent_methods(), "экран доступа не открылся"

    # текстовый fallback → меню
    await feed_cb("u:menu", 7003)
    assert "editMessageText" in await sent_methods(), "меню не открылось"

    # Кнопка проверки возвращает в меню и пользователя, и администратора.
    await feed_cb("chk:r", 7004)
    assert "editMessageText" in await sent_methods(), "проверка подписки не открыла меню"
    dp["admin_ids"] = [TG2]
    await feed_cb("chk:r", 7005)
    assert "editMessageText" in await sent_methods(), "проверка подписки админа не открыла меню"
    dp["admin_ids"] = cfg.admin_ids

    # «Назад» из админского ввода очищает состояние и открывает раздел.
    original_admins = cfg.admin_ids
    cfg.admin_ids = [TG2]
    dp["admin_ids"] = [TG2]
    fsm = dp.fsm.get_context(bot=bot, chat_id=TG2, user_id=TG2)
    await feed_cb("adm:set:agr", 7006)
    assert await fsm.get_state() == "AdmSetStates:wait_agreement"
    await feed_cb("adm:set", 7007)
    assert await fsm.get_state() is None
    cfg.admin_ids = original_admins
    dp["admin_ids"] = original_admins

    # ------------------------------------------------ панель недоступна / нет юзера
    import bot.services as services

    ctx = app()

    def last_edit_text() -> str:
        for call in reversed(bot.session.call_args_list):
            if len(call.args) >= 2 and type(call.args[1]).__name__ == "EditMessageText":
                return call.args[1].text or ""
        return ""

    orig_fetch = services.fetch_live

    async def fake_down(user, force: bool = False, timeout: float = 10):
        return None, "panel_down"

    async def fake_missing(user, force: bool = False, timeout: float = 10):
        return None, "missing"

    await db.users.update_one(
        {"tg_id": TG2}, {"$set": {"registered": True, "panel_id": "tg_x"}}
    )

    services.fetch_live = fake_down
    await feed_cb("u:access", 7101)
    text = last_edit_text()
    assert "недоступна" in text.lower(), text
    down_edit = next(c.args[1] for c in reversed(bot.session.call_args_list) if len(c.args) > 1 and type(c.args[1]).__name__ == "EditMessageText")
    assert any(b.callback_data == "u:recreate" for row in down_edit.reply_markup.inline_keyboard for b in row)
    await feed_cb("u:access", 7109)
    assert "недоступна" in last_edit_text().lower()

    services.fetch_live = fake_missing
    await feed_cb("u:access", 7102)
    text = last_edit_text()
    assert "не найден" in text.lower(), text

    # Пересоздание очищает локальную запись без повторного обращения к панели.
    import bot.handlers.register as registration
    original_registration_fetch = registration.fetch_live
    registration.fetch_live = AsyncMock(side_effect=asyncio.TimeoutError())
    await feed_cb("u:recreate", 7108)
    assert "Соглашение" in last_edit_text(), last_edit_text()
    registration.fetch_live.assert_not_awaited()
    registration.fetch_live = original_registration_fetch
    doc = await db.get_user(TG2)
    assert not doc.get("registered") and not doc.get("panel_id"), doc

    # ------------------------- создание доступа при недоступной панели (fallback)
    services.fetch_live = fake_down
    ctx.wdtt.create_user = AsyncMock(return_value={
        "id": "tg_901999",
        "password": "SECRET123",
        "subscription_url": "https://sub.example/x",
        "link": "wdtt://secret",
    })
    ctx.wdtt.list_nodes = AsyncMock(return_value=[])

    await feed_cb("u:agree", 7103)
    text = last_edit_text()
    assert "VK-хеши" in text and not ctx.wdtt.create_user.called, text

    tg_user = User(id=TG2, is_bot=False, first_name="R", username="regflow")
    async def feed_hash(text, mid):
        message = Message(message_id=mid, date=dt.now(), chat=Chat(id=TG2, type="private"), from_user=tg_user, text=text)
        await dp.feed_update(bot, Update(update_id=mid, message=message))

    await feed_hash("https://evil.example/call/join/hash1", 7104)
    await feed_hash("hash1, https://vk.ru/call/join/hash2, hash1", 7105)
    import hashlib
    key = hashlib.sha256(b"hash2").hexdigest()[:16]
    await feed_cb(f"u:hash:view:{key}", 7120)
    assert "<code>hash2</code>" in last_edit_text()
    await feed_cb(f"u:hash:rm:{key}", 7121)
    assert "1/4" in last_edit_text()
    await feed_hash("hash2", 7122)
    await feed_hash("hash3,hash4,hash5", 7106)
    await feed_cb("u:hash:done", 7107)
    ctx.wdtt.create_user.assert_awaited_once()
    ctx.wdtt.list_nodes.assert_not_awaited()
    assert ctx.wdtt.create_user.await_args.kwargs["vk_hash"] == "hash1,hash2"
    text = last_edit_text()
    assert "SECRET123" in text, text

    doc = await db.get_user(TG2)
    assert doc and doc.get("registered") is True, doc
    assert doc.get("panel_id") == "tg_901999", doc

    # Тикет сохраняется и отправляется каждому настроенному администратору.
    cfg.admin_ids = [123456]
    dp["admin_ids"] = cfg.admin_ids
    await feed_cb("u:ticket:new", 7130)
    await feed_hash("Проблема <тест>", 7131)
    bot.session.reset_mock(side_effect=None)
    await feed_hash("Ошибка <подключения>", 7132)
    notifications = [c.args[1] for c in bot.session.call_args_list if len(c.args) > 1 and getattr(c.args[1], "chat_id", None) == 123456]
    assert len(notifications) == 1 and "&lt;подключения&gt;" in notifications[0].text
    assert notifications[0].reply_markup.inline_keyboard[0][0].callback_data.startswith("adm:tkt:v")
    cfg.admin_ids = original_admins
    dp["admin_ids"] = original_admins

    # Повтор после уже созданного пользователя добавляет хеши через API.
    from bot.wdtt import WdttError
    await db.users.update_one({"tg_id": TG2}, {"$set": {"registered": False}, "$unset": {"panel_id": ""}})
    ctx.wdtt.create_user = AsyncMock(side_effect=WdttError("already exists", status=400))
    ctx.wdtt.list_users = AsyncMock(return_value={"users": [{"id": "existing-id", "name": f"tg_{TG2}"}]})
    ctx.wdtt.add_vk_hashes = AsyncMock(return_value={"id": "existing-id", "vk_hash": "hash1"})
    await feed_cb("u:agree", 7110)
    await feed_hash("hash1", 7111)
    await feed_cb("u:hash:done", 7112)
    ctx.wdtt.add_vk_hashes.assert_awaited_once_with("existing-id", ["hash1"])
    assert (await db.get_user(TG2))["registered"] is True

    services.fetch_live = orig_fetch

    await db.client.drop_database("nttunnel_test")
    print("ROUTING_TEST_OK")


if __name__ == "__main__":
    asyncio.run(main())
