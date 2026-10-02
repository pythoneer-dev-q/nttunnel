# -*- coding: utf-8 -*-
"""Админка: рассылка всем пользователям с прогрессом."""
import asyncio
import logging
from datetime import datetime

from aiogram import Bot, F, Router
from aiogram.filters import StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message

from ...context import app
from ...keyboards import adm_back_kb
from ...utils import answer_or_alert, fmt_dt, safe_edit

log = logging.getLogger(__name__)
router = Router(name="adm-broadcast")


class AdmBcStates(StatesGroup):
    wait_text = State()
    confirm = State()


@router.callback_query(F.data == "adm:bc")
async def cb_broadcast_root(cb: CallbackQuery):
    if not cb.message:
        return await answer_or_alert(cb)
    ctx = app()
    total = await ctx.db.users.count_documents({"blocked": {"$ne": True}})
    await safe_edit(
        cb.message,
        "📤 <b>Рассылка</b>\n\n"
        f"Получателей (не заблокированных): <b>{total}</b>\n\n"
        "Нажмите «Начать» и отправьте сообщение для рассылки — текст, фото, "
        "видео или любой другой контент.\n\n"
        "⚠️ Используйте разумно; частые рассылки могут привести к жалобам.",
        _bc_start_kb())
    await answer_or_alert(cb)


def _bc_start_kb():
    from aiogram.utils.keyboard import InlineKeyboardBuilder
    kb = InlineKeyboardBuilder()
    kb.button(text="📝 Начать", callback_data="adm:bc:start")
    kb.button(text="⬅️ В админку", callback_data="adm")
    return kb.adjust(1).as_markup()


@router.callback_query(F.data == "adm:bc:start")
async def cb_broadcast_start(cb: CallbackQuery, state: FSMContext):
    await state.set_state(AdmBcStates.wait_text)
    if cb.message:
        try:
            await cb.message.edit_text("⌨️ <b>Отправьте сообщение для рассылки</b>",
                                       reply_markup=adm_back_kb("adm"))
            from aiogram.utils.keyboard import InlineKeyboardBuilder
        except Exception:  # noqa: BLE001
            pass
    await answer_or_alert(cb)


@router.message(StateFilter(AdmBcStates.wait_text))
async def h_broadcast_content(message: Message, state: FSMContext,
                              bot: Bot):
    if message.text and message.text.startswith("/"):
        return
    await state.set_state(AdmBcStates.confirm)
    await state.update_data(src_chat=message.chat.id,
                            src_msg=message.message_id)

    kb_msg = None
    try:
        kb_msg = await message.copy_to(message.chat.id)  # превью
    except Exception as e:  # noqa: BLE001
        log.warning("preview copy failed: %s", e)

    from ...utils import yes_no_kb
    await message.answer(
        "📤 <b>Отправить эту рассылку?</b>",
        reply_markup=yes_no_kb(None, "adm:bc:go", "adm:bc:no",
                               "📤 Отправить", "❌ Отмена"))


@router.callback_query(F.data == "adm:bc:no", StateFilter(AdmBcStates.confirm))
async def cb_bc_cancel(cb: CallbackQuery, state: FSMContext):
    await state.clear()
    await answer_or_alert(cb, "Отменено")


@router.callback_query(F.data == "adm:bc:go", StateFilter(AdmBcStates.confirm))
async def cb_broadcast_run(cb: CallbackQuery, state: FSMContext):
    if not cb.message:
        return await answer_or_alert(cb)
    ctx = app()
    data = await state.get_data()
    await state.clear()
    src_chat, src_msg = data["src_chat"], data["src_msg"]

    total = await ctx.db.users.count_documents({"blocked": {"$ne": True}})
    cursor = ctx.db.users.find({"blocked": {"$ne": True}},
                               {"tg_id": 1})
    bot = cb.bot

    ok = fail = 0
    i = 0
    status_line = f"📤 Рассылка… 0/{total}"
    await safe_edit(cb.message, status_line, adm_back_kb("adm"))
    async for doc in cursor:
        i += 1
        uid = doc["tg_id"]
        try:
            await bot.copy_message(uid, src_chat, src_msg)
            ok += 1
        except Exception as e:  # noqa: BLE001
            fail += 1
            log.debug("broadcast to %s failed: %s", uid, e)
        if i % 25 == 0:
            await safe_edit(cb.message,
                            f"📤 Рассылка… {i}/{total} (ok={ok}, "
                            f"fail={fail})", adm_back_kb("adm"))
            await asyncio.sleep(0.5)  # мягкий rate-limit
        else:
            await asyncio.sleep(0.05)
    await safe_edit(
        cb.message,
        f"✅ <b>Рассылка завершена</b>\n\n"
        f"• Доставлено: <b>{ok}</b>\n"
        f"• Не доставлено: <b>{fail}</b>\n"
        f"• Дата: {fmt_dt(datetime.now())}",
        adm_back_kb("adm"))
    await answer_or_alert(cb, "Готово!")
