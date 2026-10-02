# -*- coding: utf-8 -*-
"""Пользовательские хендлеры: /start, меню, рефералка, инструкция."""

import logging

from aiogram import F, Router
from aiogram.filters import Command, CommandObject, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from ..context import app
from ..db import utcnow
from ..keyboards import apps_kb, menu_kb, referral_kb
from ..texts import esc, menu_text
from ..utils import answer_or_alert


log = logging.getLogger(__name__)
router = Router(name="common")


async def _limit_gb() -> int:
    try:
        settings = await app().db.get_settings()
        return int(settings.get("default_total_gb") or 175)
    except Exception:
        return 175


async def show_menu(
    target: Message,
    user_doc: dict,
    edit: bool = False,
):
    ctx = app()

    ads = await ctx.gate.get_ads()
    limit_gb = await _limit_gb()
    sections = await ctx.gate.get_sections()

    text = menu_text(user_doc, limit_gb)
    kb = menu_kb(
        bool(user_doc.get("registered")),
        ads,
        sections,
    )

    if edit:
        try:
            await target.edit_text(
                text,
                reply_markup=kb,
            )
            return
        except Exception as e:
            log.debug("menu edit failed: %s", e)
            return

    try:
        await target.answer(
            text,
            reply_markup=kb,
        )
    except Exception as e:
        log.warning("menu send failed: %s", e)


@router.message(CommandStart())
async def cmd_start(
    message: Message,
    command: CommandObject | None = None,
    user: dict | None = None,
):
    ctx = app()

    payload = (
        (command.args or "").strip()
        if command
        else ""
    )

    if payload and len(payload) <= 64 and user:
        if user.get("start_payload") != payload:
            tg_id = message.from_user.id

            await ctx.db.users.update_one(
                {"tg_id": tg_id},
                {
                    "$set": {
                        "start_payload": payload,
                        "source_set_at": utcnow(),
                    }
                },
            )

            await ctx.db.log_event(
                tg_id,
                "start_payload",
                payload,
            )

            user["start_payload"] = payload

    await show_menu(
        message,
        user or {},
        edit=False,
    )


@router.message(Command("menu"))
async def cmd_menu(
    message: Message,
    user: dict | None = None,
):
    await show_menu(
        message,
        user or {},
        edit=False,
    )


@router.callback_query(F.data == "u:menu")
async def cb_menu(
    cb: CallbackQuery,
    user: dict | None = None,
    state: FSMContext = None,
):
    if state:
        await state.clear()

    if not cb.message:
        await answer_or_alert(cb)
        return

    await answer_or_alert(cb)

    await show_menu(
        cb.message,
        user or {},
        edit=True,
    )


@router.callback_query(F.data.startswith("u:sec:"))
async def cb_section(
    cb: CallbackQuery,
    user: dict | None = None,
):
    """Динамический раздел из конструктора (админка → sections)."""
    if not cb.message:
        await answer_or_alert(cb)
        return

    key = cb.data.removeprefix("u:sec:")
    sec = await app().db.get_section(key)
    if not sec:
        await answer_or_alert(cb, "Раздел не найден", True)
        return

    await answer_or_alert(cb)

    all_secs = await app().gate.get_sections()
    from ..keyboards import menu_back_kb
    text = f"<b>{esc(sec.get('title') or key)}</b>\n\n{sec.get('text') or ''}"
    try:
        await cb.message.edit_text(
            text,
            reply_markup=menu_back_kb(all_secs),
            disable_web_page_preview=True,
        )
    except Exception as e:
        log.debug("section edit failed: %s", e)


@router.callback_query(F.data == "noop")
async def cb_noop(cb: CallbackQuery):
    await answer_or_alert(cb)


@router.callback_query(F.data == "u:apps")
async def cb_instruction(
    cb: CallbackQuery,
    user: dict | None = None,
):
    """Инструкция: приложения и порядок подключения."""

    if not cb.message:
        await answer_or_alert(cb)
        return

    await answer_or_alert(cb)

    settings = await app().db.get_settings()

    text = (
        "🏳️ <b>Инструкция</b>\n\n"
        "<blockquote>"
        "1️⃣ Установи подходящее приложение.\n"
        "2️⃣ Создай конфиг в боте (нужен VK-хеш звонка).\n"
        "3️⃣ «Показать ссылку» → открой её в приложении.\n"
        "4️⃣ Подключение — готово."
        "</blockquote>\n\n"
        "Скачать приложения:"
    )

    try:
        await cb.message.edit_text(
            text,
            reply_markup=apps_kb(
                settings.get("app_links", [])
            ),
        )
    except Exception as e:
        log.debug("instruction edit failed: %s", e)


@router.callback_query(F.data == "u:ref")
async def cb_referral(
    cb: CallbackQuery,
    user: dict | None = None,
):
    """Реферальная программа."""

    if not cb.message:
        await answer_or_alert(cb)
        return

    u = user or {}

    if not u.get("registered"):
        await answer_or_alert(
            cb,
            "Данный раздел станет доступен после создания подключения",
            True,
        )
        return

    await answer_or_alert(cb)

    try:
        me = await cb.bot.get_me()
        username = me.username or "bot"
    except Exception:
        username = "bot"

    tg_id = u.get("tg_id")
    link = f"https://t.me/{username}?start=ref_{tg_id}"

    refs = int(u.get("referrals") or 0)
    bonus = refs * 5

    text = (
        "🚀 <b>Реферальная программа</b>\n\n"
        "+5 ГБ трафика за каждого приглашённого друга.\n\n"
        "Твоя ссылка:\n"
        f"<blockquote><code>{link}</code></blockquote>\n"
        f"Приглашено: <b>{refs}</b> · "
        f"бонус: <b>+{bonus} ГБ</b>"
    )

    try:
        await cb.message.edit_text(
            text,
            reply_markup=referral_kb(),
        )
    except Exception as e:
        log.debug("referral edit failed: %s", e)