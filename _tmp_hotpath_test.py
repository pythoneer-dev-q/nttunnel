# -*- coding: utf-8 -*-
"""Временная проверка: чтения не ходят в панель, панель — только по force/старту."""
import asyncio
import os
import time

os.environ.setdefault("BOT_TOKEN", "1:x")
os.environ.setdefault("ADMINS", "1")

from bot import context  # noqa: E402
from bot.handlers import register  # noqa: E402
from bot.wdtt import WdttClient, WdttError  # noqa: E402


class CountingClient(WdttClient):
    """Клиент без сети: считает панельные запросы."""

    def __init__(self, panel_up=True):
        # не вызываем super().__init__ — нужен только кэш/индекс
        self.panel_up = panel_up
        self.panel_calls = 0
        self._users_cache = None
        self._users_cached_at = 0.0
        self._users_index = {}
        self._users_comment_index = {}
        self._users_lock = asyncio.Lock()
        self._store = None

    async def _request(self, method, path, payload=None, retries=2,
                       timeout=None):
        self.panel_calls += 1
        if not self.panel_up:
            raise WdttError("panel down")
        data = {"users": [{"password": "pwd1", "comment": "tg1"},
                          {"password": "pwd2", "comment": "tg2"}]}
        self._users_cache = data
        self._users_cached_at = time.monotonic()
        self._users_index, self._users_comment_index = self._index_users(data)
        return data


class FakeCtx:
    def __init__(self, wdtt):
        self.wdtt = wdtt


async def main():
    # 1) cold start: первое чтение делает ровно ОДИН запрос
    c = CountingClient()
    context._app = FakeCtx(c)
    assert not c.cache_ready
    live = await c.find_user("pwd1")
    assert live and c.panel_calls == 1, (live, c.panel_calls)

    # 2) warm: повторные чтения — 0 запросов (TTL не участвует)
    for _ in range(20):
        assert await c.find_user("pwd1")
        assert await c.find_user("tg2")
        assert await c.find_user("nope") is None
    assert c.panel_calls == 1, c.panel_calls

    # 3) get_users() без force тоже без сети
    await c.get_users()
    assert c.panel_calls == 1, c.panel_calls

    # 4) force (мутация/фоновый sync) — запрос, если кэш «старый»;
    #    немедленный повтор отсекается барьером <2с
    c._users_cached_at = 0.0
    await c.get_users(force=True)
    calls_after = c.panel_calls
    assert calls_after == 2, calls_after
    await c.get_users(force=True)  # сразу за ним — барьер
    assert c.panel_calls == calls_after, c.panel_calls

    # 5) invalidate (после add_user) + force → новый запрос (барьер сброшен)
    c.invalidate_users()
    await c.get_users(force=True)
    assert c.panel_calls == calls_after + 1, c.panel_calls

    # 6) _resolve_live: warm мисс → missing БЕЗ запросов к панели
    context._app = FakeCtx(c)
    before = c.panel_calls
    live, reason = await register._resolve_live(
        {"tg_id": 999, "wdtt_password": "pwdX"})
    assert reason == "missing" and live is None, reason
    assert c.panel_calls == before, "чтение не должно дёргать панель!"

    # 7) _resolve_live: warm хит — ok, 0 запросов
    live, reason = await register._resolve_live(
        {"tg_id": 1, "wdtt_password": "pwd1"})
    assert reason == "ok" and live, reason
    assert c.panel_calls == before

    # 8) холодный старт + панель лежит → panel_down
    c2 = CountingClient(panel_up=False)
    context._app = FakeCtx(c2)
    live, reason = await register._resolve_live(
        {"tg_id": 1, "wdtt_password": "pwd1"})
    assert reason == "panel_down" and live is None, reason
    assert c2.panel_calls <= 3, c2.panel_calls  # не копим попытки

    # 9) холодный старт + панель жива → ok, ровно один запрос
    c3 = CountingClient()
    context._app = FakeCtx(c3)
    live, reason = await register._resolve_live(
        {"tg_id": 1, "wdtt_password": "pwd1"})
    assert reason == "ok" and live, reason
    assert c3.panel_calls == 1, c3.panel_calls

    print("NO_HOT_PANEL_OK")


asyncio.run(main())
