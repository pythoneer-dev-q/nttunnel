# -*- coding: utf-8 -*-
"""Личный кабинет и текстовый fallback."""
from __future__ import annotations

import logging

from aiogram import F, Router
from aiogram.types import CallbackQuery, Message

from ..keyboards import back_menu_kb
from ..texts import profile_text
from ..utils import answer_or_alert, safe_edit

log = logging.getLogger(__name__)
router = Router(name="cabinet")


@router.callback_query(F.data == "u:cab")
async def cb_cabinet(cb: CallbackQuery, user: dict | None = None):
    if not cb.message:
        return await answer_or_alert(cb)

    await safe_edit(cb.message, profile_text(dict(user or {})), back_menu_kb())
    await answer_or_alert(cb)


@router.message(F.text & ~F.text.startswith("/"))
async def any_message_fallback(message: Message, user: dict | None = None):
    """Любой текст без команды → меню."""
    if not message.from_user or message.from_user.is_bot:
        return

    from .common import show_menu

    await show_menu(
        message, user or {"tg_id": message.from_user.id}, edit=False
    )
