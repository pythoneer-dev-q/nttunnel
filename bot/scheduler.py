# -*- coding: utf-8 -*-
"""Фоновая задача: авто-сброс трафика подписок (бесконечные подписки с квотой).

Согласно creds.txt: подписки бессрочные, лимит держим через total_gb,
счётчик трафика сбрасываем сами раз в N дней (настройка в админке).
"""
import asyncio
import logging
from datetime import datetime, timezone

from .context import app

log = logging.getLogger(__name__)

CHECK_EVERY_SEC = 600  # проверяем каждые 10 минут

DEFAULT_SYNC_SEC = 45  # интервал зеркалирования пользователей панели


async def _panel_sync_once():
    """Один проход: список пользователей панели → in-memory + зеркало Mongo.

    ``get_users(force=True)`` сам сохраняет снапшот в зеркало (WdttClient
    вызывает ``store.sync_panel_users``), поэтому панель не опрашивается
    на действия пользователей.
    """
    ctx = app()
    data = await ctx.wdtt.get_users(force=True)
    log.debug("panel sync: %s users",
              len((data or {}).get("users") or []))


async def panel_sync_loop():
    """Фоновая синхронизация зеркала пользователей панели."""
    interval = DEFAULT_SYNC_SEC

    try:
        interval = max(10, int(app().cfg.panel_sync_sec or DEFAULT_SYNC_SEC))
    except Exception:  # noqa: BLE001 — контекст ещё не готов
        pass

    while True:
        try:
            await _panel_sync_once()
        except Exception as e:  # noqa: BLE001 — не роняем задачу
            log.warning("panel sync failed: %s", e)

        await asyncio.sleep(interval)


async def _reset_once():
    ctx = app()
    s = await ctx.db.get_settings()
    period = int(s.get("reset_period_days") or 0)
    if period <= 0:
        return
    now = datetime.now(timezone.utc)
    cursor = ctx.db.users.find({"registered": True},
                               {"tg_id": 1, "wdtt_password": 1,
                                "last_traffic_reset": 1})
    async for u in cursor:
        pwd = u.get("wdtt_password")
        if not pwd:
            continue  # без пароля запрос к панели бессмысленен
        last = u.get("last_traffic_reset")
        if last is not None and last.tzinfo is None:
            last = last.replace(tzinfo=timezone.utc)  # naive -> UTC
        due = (last is None or (now - last).total_seconds() >= period * 86400)
        if not due:
            continue
        try:
            await ctx.wdtt.reset_traffic(pwd)
            await ctx.db.users.update_one(
                {"tg_id": u["tg_id"]}, {"$set": {"last_traffic_reset": now}})
            log.info("traffic reset for %s", u["tg_id"])
        except Exception as e:  # noqa: BLE001
            log.warning("traffic reset failed for %s: %s", u["tg_id"], e)


async def run_scheduler():
    while True:
        try:
            await _reset_once()
        except Exception as e:  # noqa: BLE001
            log.error("scheduler iteration failed: %s", e)
        await asyncio.sleep(CHECK_EVERY_SEC)
