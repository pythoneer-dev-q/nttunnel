# -*- coding: utf-8 -*-
"""Интеграционный тест MongoDB-слоя (нужен локальный mongod)."""
import asyncio

os_environ = {"BOT_TOKEN": "123:test", "ADMINS": "1"}


async def main():
    import os
    for k, v in os_environ.items():
        os.environ.setdefault(k, v)
    from bot.config import load_config
    from bot.db import Database
    cfg = load_config()
    db = Database(cfg)
    await db.init()

    # чистим с прошлого прогона (иначе залипший creating срывает клейм)
    await db.users.delete_many({"tg_id": 424242})
    await db.events.delete_many({"tg_id": 424242})

    # настройки: дефолты слиты с БД, app_links — непустой список {label, url}
    s = await db.get_settings()
    assert s["registration_open"] is True and "agreement_text" in s
    assert isinstance(s["app_links"], list) and s["app_links"], s["app_links"]
    assert all("label" in l and "url" in l for l in s["app_links"])
    ok, left = await db.slots_available(s)
    assert ok and left == -1

    # пользователь из фейкового tg_user (duck-typing достаточно)
    class FakeUser:
        id = 424242
        username = "tester"
        first_name = "Тест"
        last_name = None
        full_name = "Тест"
        language_code = "ru"
        is_premium = False

    doc = await db.sync_user(FakeUser())
    assert doc["tg_id"] == 424242 and doc["messages_count"] >= 1
    doc2 = await db.sync_user(FakeUser())
    assert doc2["messages_count"] > doc["messages_count"], (
        doc["messages_count"], doc2["messages_count"])

    # заявка на создание подписки (клейм)
    claimed = await db.users.find_one_and_update(
        {"tg_id": 424242, "registered": {"$ne": True},
         "creating": {"$ne": True}},
        {"$set": {"creating": True}})
    assert claimed
    await db.log_event(424242, "test", "meta")
    ev = await db.events.find_one({"tg_id": 424242})
    assert ev["kind"] == "test"

    # счётчик зарегистрированных: юзер без подписки (клейм) НЕ считается
    usr = await db.get_user(424242)
    assert usr and not usr.get("registered"), usr
    base_reg = await db.registered_count()
    # притворимся, что тестовый юзер зарегистрирован -> count увеличится на 1
    await db.users.update_one({"tg_id": 424242}, {"$set": {"registered": True}})
    assert await db.registered_count() == base_reg + 1
    assert await db.registered_count() >= 0

    # прибираем за собой всегда (иначе creating=True залипает)
    await db.users.delete_many({"tg_id": FakeUser.id})
    await db.events.delete_many({"tg_id": FakeUser.id})
    print("DB_TEST_OK")


if __name__ == "__main__":
    asyncio.run(main())
