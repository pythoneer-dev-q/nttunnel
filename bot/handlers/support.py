# -*- coding: utf-8 -*-
"""Поддержка: обращения пользователей."""
from __future__ import annotations

import logging

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message

from ..context import app
from ..keyboards import back_menu_kb, support_kb, markup, btn
from ..texts import esc
from ..utils import answer_or_alert, safe_edit

log = logging.getLogger(__name__)
router = Router(name="support")


class TicketStates(StatesGroup):
    wait_subject = State()
    wait_body = State()


HELP_TEXT = (
    "🆘 <b>Поддержка</b>\n\n"
    "Опиши проблему — ответ придёт в этот чат.\n\n"
    "Полезно указать: что делал, что ожидал, текст ошибки."
)


@router.message(Command("support"))
@router.callback_query(F.data == "u:support")
async def open_support(event, user: dict | None = None):
    kb = support_kb()

    if isinstance(event, Message):
        await event.answer(HELP_TEXT, reply_markup=kb)
        return

    if not event.message:
        return await answer_or_alert(event)

    await safe_edit(event.message, HELP_TEXT, kb)
    await answer_or_alert(event)


@router.callback_query(F.data == "u:ticket:new")
async def cb_ticket_start(cb: CallbackQuery, state: FSMContext):
    if not cb.message:
        return await answer_or_alert(cb)

    await state.set_state(TicketStates.wait_subject)
    await safe_edit(
        cb.message,
        "📝 <b>Новое обращение</b>\n\n"
        "Шаг 1/2 — коротко опиши тему.",
        back_menu_kb(),
    )
    await answer_or_alert(cb)


@router.message(TicketStates.wait_subject, F.text)
async def h_ticket_subject(message: Message, state: FSMContext):
    subject = (message.text or "").strip()[:120]
    if not subject:
        return

    await state.update_data(subject=subject)
    await state.set_state(TicketStates.wait_body)
    await message.answer(
        f"Тема: <b>{esc(subject)}</b>\n\nШаг 2/2 — опиши проблему подробнее.",
        reply_markup=back_menu_kb(),
    )


@router.message(TicketStates.wait_body, F.text)
async def h_ticket_body(message: Message, state: FSMContext):
    body = (message.text or "").strip()[:2000]
    if not body:
        return

    data = await state.get_data()
    subject = data.get("subject", "")
    ctx = app()
    try:
        tid = await ctx.db.create_ticket(message.from_user.id, subject, body)
    except Exception:
        log.exception("ticket creation failed")
        return await message.answer("Не удалось сохранить обращение. Попробуй отправить текст ещё раз.", reply_markup=back_menu_kb())
    await state.clear()

    delivered = 0
    for admin_id in set(ctx.cfg.admin_ids):
        try:
            await message.bot.send_message(
                admin_id,
                f"🎫 <b>Новое обращение</b> <code>{esc(tid)}</code>\n"
                f"От: <code>{message.from_user.id}</code>\n"
                f"Тема: <b>{esc(subject)}</b>\n\n"
                f"<blockquote>{esc(body)}</blockquote>",
                reply_markup=markup([btn("Открыть обращение", f"adm:tkt:v{tid}")]),
            )
            delivered += 1
        except Exception:
            log.warning("ticket notification failed for admin %s", admin_id, exc_info=True)

    await message.answer(
        f"✅ <b>Обращение создано</b>\n\n"
        f"Номер: <code>{tid}</code>\n"
        f"Тема: {esc(subject)}\n\n"
        + ("Ответ придёт сюда." if delivered else "Обращение сохранено в панели поддержки. Уведомить администратора сейчас не удалось."),
        reply_markup=back_menu_kb(),
    )


@router.callback_query(F.data == "u:ticket:list")
async def cb_ticket_list(cb: CallbackQuery):
    if not cb.message:
        return await answer_or_alert(cb)

    tickets = await app().db.user_active_tickets(cb.from_user.id)

    if not tickets:
        await safe_edit(
            cb.message,
            "📭 <b>Активных обращений нет</b>",
            back_menu_kb(),
        )
        return await answer_or_alert(cb)

    statuses = {
        "open": "🟡 открыт",
        "in_progress": "🔵 в работе",
        "closed": "🟢 закрыт",
    }
    lines = [
        f"• <code>{t['ticket_id']}</code> — {esc(t.get('subject'))} "
        f"[{statuses.get(t['status'], t['status'])}]"
        for t in tickets
    ]
    await safe_edit(
        cb.message,
        "📬 <b>Мои обращения</b>\n\n" + "\n".join(lines),
        back_menu_kb(),
    )
    await answer_or_alert(cb)
