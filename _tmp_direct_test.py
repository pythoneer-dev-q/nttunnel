# -*- coding: utf-8 -*-
"""Временная проверка: создание/мутации конфига без парсинга списка панели."""
import asyncio
import os
import time

os.environ.setdefault("BOT_TOKEN", "1:x")
os.environ.setdefault("ADMINS", "1")

from bot import context  # noqa: E402
from bot.handlers import register  # noqa: E402
from bot.wdtt import WdttClient, WdttError  # noqa: E402


class FakeStore:
    """Фейковое зеркало: считает операции, хранит в dict."""

    def __init__(self):
        self.users: dict = {}
        self.upserts = 0

    def _key(self, u):
        return str(u.get("password_key") or u.get("password") or "")

    async def upsert_panel_user(self, user):
        self.upserts += 1
        self.users[self._key(user)] = dict(user)

    async def drop_panel_user(self, key):
        self.users.pop(key, None)

    async def get_panel_inbound(self):
        return {"dtls_port": 56000, "wg_port": 56001, "client_port": 9000}

    async def get_panel_user(self, key):
        return self.users.get(key)


class CountingClient(WdttClient):
    """Клиент: панель отвечает успешно, считаем запросы списка."""

    def __init__(self):
        self.panel_calls = 0
        self._users_cache = None
        self._users_cached_at = 0.0
        self._users_index = {}
        self._users_comment_index = {}
        self._users_lock = asyncio.Lock()
        self._store = FakeStore()

    async def _request(self, method, path, payload=None, retries=2,
                       timeout=None):
        if path == "/panel/api/users":
            self.panel_calls += 1
            return {"users": []}
        return {}  # add/update/delete/reset


class FakeCtx:
    def __init__(self, wdtt):
        self.wdtt = wdtt


async def main():
    c = CountingClient()
    context._app = FakeCtx(c)

    # 1) note_user_created: запись в кэш+зеркало, порты из inbound, 0 запросов
    live = await c.note_user_created("newpwd", comment="tg42",
                                     total_gb=175, max_devices=1)
    assert c.panel_calls == 0, "создание не должно парсить список!"
    assert live["dtls_port"] == 56000 and live["wg_port"] == 56001
    assert live["client_port"] == 9000
    assert c._store.upserts == 1 and "newpwd" in c._store.users
    assert c.cache_ready

    # 2) find_user по паролю и по comment — мгновенно, из кэша
    assert await c.find_user("newpwd")
    assert await c.find_user("tg42")
    assert c.panel_calls == 0

    # 3) _resolve_live → ok без единого запроса к панели
    live2, reason = await register._resolve_live(
        {"tg_id": 42, "wdtt_password": "newpwd"})
    assert reason == "ok" and live2["password"] == "newpwd"
    assert c.panel_calls == 0

    # 4) update_user: точечный patch, кэш НЕ сносится, 0 парсингов
    await c.update_user("newpwd", total_gb=300, max_devices=2)
    assert c.cache_ready, "кэш не должен инвалидироваться!"
    u = await c.find_user("newpwd")
    assert u["total_gb"] == 300 and u["max_devices"] == 2, u
    assert c.panel_calls == 0

    # 5) reset_traffic: счётчики обнулены точечно
    u["_store_mark"] = True
    await c._upsert_cached({"password_key": "newpwd", "traffic_used": 999})
    await c.reset_traffic("newpwd")
    u = await c.find_user("newpwd")
    assert u["traffic_used"] == 0 and u["traffic_used_fmt"] == "0.0 KB", u
    assert c.cache_ready and c.panel_calls == 0

    # 6) delete_user: одна запись убрана из кэша и зеркала
    await c.note_user_created("otherpwd", comment="tg77")
    assert c._store.upserts >= 2
    await c.delete_user("newpwd")
    assert await c.find_user("newpwd") is None
    assert await c.find_user("otherpwd"), "сосед не должен пострадать"
    assert "newpwd" not in c._store.users
    assert "otherpwd" in c._store.users
    assert c.cache_ready and c.panel_calls == 0

    # 7) inbound берётся и из store, если кэш пуст
    c2 = CountingClient()
    c2._users_cache = None
    context._app = FakeCtx(c2)
    live3 = await c2.note_user_created("p1", comment="tg1")
    assert live3["dtls_port"] == 56000, live3
    assert c2.panel_calls == 0

    # 8) двойное создание с тем же comment не плодит дубликаты
    await c.note_user_created("duppwd", comment="tg42")  # comment уже есть
    n = len(c._users_cache["users"])
    await c.note_user_created("duppwd2", comment="tg42")
    assert len(c._users_cache["users"]) == n, "дубль по comment!"

    print("DIRECT_CACHE_OK")


asyncio.run(main())
