# -*- coding: utf-8 -*-
"""Фоновый авто-сброс трафика (если включён в настройках)."""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone

from .context import app

log = logging.getLogger(__name__)

CHECK_EVERY_SEC = 600


async def _reset_once():
    ctx = app()
    settings = await ctx.db.get_settings()
    period = int(settings.get("reset_period_days") or 0)

    if period <= 0:
        return

    now = datetime.now(timezone.utc)
    cursor = ctx.db.users.find(
        {"registered": True, "panel_id": {"$exists": True, "$ne": ""}},
        {"tg_id": 1, "panel_id": 1, "last_traffic_reset": 1},
    )

    async for user in cursor:
        last = user.get("last_traffic_reset")
        if last is not None and last.tzinfo is None:
            last = last.replace(tzinfo=timezone.utc)

        due = (
            last is None
            or (now - last).total_seconds() >= period * 86400
        )
        if not due:
            continue

        try:
            await ctx.wdtt.reset_traffic(user["panel_id"])
            await ctx.db.users.update_one(
                {"tg_id": user["tg_id"]},
                {
                    "$set": {
                        "last_traffic_reset": now,
                        "panel_traffic_used_bytes": 0,
                    }
                },
            )
            log.info("traffic reset for %s", user["tg_id"])
        except Exception as e:
            log.warning("traffic reset failed for %s: %s", user["tg_id"], e)


async def run_scheduler():
    while True:
        try:
            await _reset_once()
        except Exception as e:
            log.error("scheduler iteration failed: %s", e)
        await asyncio.sleep(CHECK_EVERY_SEC)
