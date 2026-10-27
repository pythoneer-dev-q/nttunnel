# -*- coding: utf-8 -*-
"""Админ-роутер (/godmode): агрегирует под-модули."""
from aiogram import BaseMiddleware, Router
from aiogram.filters import BaseFilter
from aiogram.types import TelegramObject

from ...context import app


class IsAdmin(BaseFilter):
    async def __call__(self, event: TelegramObject) -> bool:
        if not event.from_user:
            return False
        return event.from_user.id in set(app().cfg.admin_ids)


router = Router(name="admin")
router.message.filter(IsAdmin())
router.callback_query.filter(IsAdmin())


class ClearAdminStateOnBack(BaseMiddleware):
    async def __call__(self, handler, event, data):
        action = event.data or ""
        navigation = {"adm", "adm:stat", "adm:srv", "adm:nodes", "adm:usr", "adm:tkt", "adm:bc", "adm:chn", "adm:ads", "adm:sec", "adm:set"}
        if action in navigation or action.startswith(("adm:usr:v:", "adm:usr:p", "adm:tkt:v", "adm:tkt:p", "adm:nodes:p")):
            state = data.get("state")
            if state and str(await state.get_state() or "").startswith("Adm"):
                await state.clear()
        return await handler(event, data)


router.callback_query.outer_middleware(ClearAdminStateOnBack())

from . import (ads, broadcast, channels, dashboard, sections, settings_admin,
                 tickets, users)  # noqa: E402

router.include_router(dashboard.router)
router.include_router(users.router)
router.include_router(tickets.router)
router.include_router(broadcast.router)
router.include_router(channels.router)
router.include_router(ads.router)
router.include_router(sections.router)
router.include_router(settings_admin.router)
