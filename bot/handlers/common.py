# -*- coding: utf-8 -*-
"""Пользовательские экраны: /start, меню, инструкция, рефералка, разделы."""
from __future__ import annotations

import logging

from aiogram import F, Router
from aiogram.filters import Command, CommandObject, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from ..context import app
from ..db import utcnow
from ..keyboards import apps_kb, menu_back_kb, menu_kb, referral_kb
from ..services import refresh_snapshot, snapshot_is_fresh
from ..texts import esc, help_text, menu_text
from ..utils import answer_or_alert, safe_edit

log = logging.getLogger(__name__)
router = Router(name="common")


async def show_menu(target: Message, user_doc: dict, edit: bool = False):
    ctx = app()

    user_doc = dict(user_doc or {})
    live = None

    if user_doc.get("registered") and not snapshot_is_fresh(user_doc):
        live, _reason = await refresh_snapshot(
            user_doc, force=True, timeout=5
        )

    try:
        ads = await ctx.gate.get_ads()
        sections = await ctx.gate.get_sections()
    except Exception as e:
        log.warning("menu data failed: %s", e)
        ads, sections = [], []

    text = menu_text(user_doc, live)
    kb = menu_kb(bool(user_doc.get("registered")), ads, sections)

    if edit:
        await safe_edit(target, text, kb)
        return

    try:
        await target.answer(text, reply_markup=kb)
    except Exception as e:
        log.warning("menu send failed: %s", e)


@router.message(CommandStart())
async def cmd_start(
    message: Message,
    command: CommandObject | None = None,
    user: dict | None = None,
):
    ctx = app()
    payload = ((command.args or "").strip() if command else "")[:64]
    user_doc = dict(user or {})

    if payload and payload != user_doc.get("start_payload"):
        tg_id = message.from_user.id if message.from_user else user_doc.get("tg_id")
        patch = {"start_payload": payload, "source_set_at": utcnow()}

        if payload.startswith("ref_"):
            try:
                patch["referral_of"] = int(payload[4:].split("_")[0])
            except (ValueError, IndexError):
                pass

        await ctx.db.users.update_one({"tg_id": tg_id}, {"$set": patch})
        user_doc.update(patch)
        await ctx.db.log_event(tg_id, "start_payload", payload)

    await show_menu(message, user_doc, edit=False)


@router.message(Command("menu"))
async def cmd_menu(message: Message, user: dict | None = None):
    await show_menu(message, user or {}, edit=False)


@router.message(Command("help"))
async def cmd_help(message: Message):
    await message.answer(help_text())


@router.callback_query(F.data == "u:menu")
async def cb_menu(
    cb: CallbackQuery,
    user: dict | None = None,
    state: FSMContext | None = None,
):
    if state:
        await state.clear()

    if not cb.message:
        return await answer_or_alert(cb)

    await answer_or_alert(cb)
    await show_menu(cb.message, user or {}, edit=True)


@router.callback_query(F.data == "u:apps")
async def cb_instruction(cb: CallbackQuery):
    if not cb.message:
        return await answer_or_alert(cb)

    settings = await app().db.get_settings()
    await safe_edit(
        cb.message,
        help_text(),
        apps_kb(settings.get("app_links") or []),
    )
    await answer_or_alert(cb)


@router.callback_query(F.data.startswith("u:sec:"))
async def cb_section(cb: CallbackQuery):
    if not cb.message:
        return await answer_or_alert(cb)

    key = cb.data.removeprefix("u:sec:")
    sec = await app().db.get_section(key)

    if not sec:
        return await answer_or_alert(cb, "Раздел не найден", True)

    await answer_or_alert(cb)
    sections = await app().gate.get_sections()
    text = f"<b>{esc(sec.get('title') or key)}</b>\n\n{sec.get('text') or ''}"
    await safe_edit(cb.message, text, menu_back_kb(sections))


@router.callback_query(F.data == "u:ref")
async def cb_referral(cb: CallbackQuery, user: dict | None = None):
    if not cb.message:
        return await answer_or_alert(cb)

    u = dict(user or {})
    if not u.get("registered"):
        return await answer_or_alert(
            cb, "Рефералка станет доступна после создания доступа", True
        )

    await answer_or_alert(cb)

    try:
        me = await cb.bot.get_me()
        username = me.username or "bot"
    except Exception:
        username = "bot"

    settings = await app().db.get_settings()
    bonus = int(
        settings.get("referral_bonus_gb")
        or app().cfg.referral_bonus_gb
        or 0
    )

    refs = int(u.get("referrals") or 0)
    link = f"https://t.me/{username}?start=ref_{u.get('tg_id')}"

    text = (
        "🚀 <b>Рефералка</b>\n\n"
        f"+{bonus} ГБ за каждого друга.\n\n"
        f"<code>{link}</code>\n\n"
        f"Приглашено: <b>{refs}</b> · бонус: <b>+{refs * bonus} ГБ</b>"
    )
    await safe_edit(cb.message, text, referral_kb())


@router.callback_query(F.data == "noop")
async def cb_noop(cb: CallbackQuery):
    await answer_or_alert(cb)
