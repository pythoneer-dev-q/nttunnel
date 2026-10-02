# -*- coding: utf-8 -*-
"""Кабинет: профиль + текстовый fallback.

«Мой конфиг» (u:sub) и итог (u:done) обрабатываются в register.py.
Здесь остаётся профиль (u:cab) и уловка произвольного текста → меню.
"""
import logging

from aiogram import F, Router
from aiogram.types import CallbackQuery, Message

from ..context import app
from ..keyboards import back_menu_kb
from ..texts import esc
from ..utils import answer_or_alert, safe_edit

log = logging.getLogger(__name__)
router = Router(name="cabinet")


@router.callback_query(F.data == "u:cab")
async def cb_cabinet(cb: CallbackQuery, user: dict):
    """Личный кабинет: профиль."""
    if not cb.message:
        return await answer_or_alert(cb)
    text = (
        "👤 <b>Мой профиль</b>\n\n"
        f"<blockquote>🆔 ID: <code>{user.get('tg_id')}</code>\n"
        f"📝 Имя: <b>{esc(user.get('full_name'))}</b>\n"
        f"🔗 Username: {('@' + esc(user['username'])) if user.get('username') else '—'}\n"
        f"💎 Telegram Premium: {'да' if user.get('is_premium') else 'нет'}\n"
        f"🆕 В боте с: {__fmt(user.get('created_at'))}\n"
        f"👀 Последний онлайн: {__fmt(user.get('last_seen'))}</blockquote>"
    )
    await safe_edit(cb.message, text, back_menu_kb())
    await answer_or_alert(cb)


def __fmt(dt) -> str:
    try:
        return dt.strftime("%d.%m.%Y")
    except Exception:  # noqa: BLE001
        return "—"


@router.message(F.text & ~F.text.startswith("/"))
async def any_message_fallback(message: Message, user: dict | None = None):
    """Любой текст без команды → меню (листательный flow)."""
    if not message.from_user or message.from_user.is_bot:
        return
    from .common import show_menu
    await show_menu(message, user or {"tg_id": message.from_user.id}, edit=False)