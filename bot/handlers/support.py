# -*- coding: utf-8 -*-
"""Поддержка: пользовательские тикеты."""
import logging

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message

from ..context import app
from ..keyboards import back_menu_kb
from ..texts import esc
from ..utils import answer_or_alert, safe_edit

log = logging.getLogger(__name__)
router = Router(name="support")


class TicketStates(StatesGroup):
    wait_subject = State()
    wait_body = State()


HELP_TEXT = (
    "🆘 <b>Поддержка</b>\n\n"
    "<blockquote>"
    "Опиши проблему — оператор ответит в этом чате.\n"
    "Для быстрой диагностики укажи:\n"
    "• что делал;\n"
    "• что ожидал;\n"
    "• что получилось (скриншот/текст ошибки).\n"
    "</blockquote>"
)


@router.message(Command("support"))
@router.callback_query(F.data == "u:support")
async def open_support(event, user: dict):
    """Открывает меню поддержки."""
    if not getattr(event, "message", None):
        return await answer_or_alert(event)
    text = HELP_TEXT
    kb = back_menu_kb()
    if isinstance(event, Message):
        await event.answer(text, reply_markup=kb)
    else:
        await safe_edit(event.message, text, kb)
        await answer_or_alert(event)


@router.callback_query(F.data == "u:ticket:new")
async def cb_ticket_start(cb: CallbackQuery, state: FSMContext):
    """Начало создания тикета."""
    if not cb.message:
        return await answer_or_alert(cb)
    await state.set_state(TicketStates.wait_subject)
    await safe_edit(
        cb.message,
        "📝 <b>Новый обращение</b>\n\n"
        "<blockquote>Шаг 1 из 2 — кратко опиши тему (до 120 символов):</blockquote>",
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
        f"✅ Тема: <b>{esc(subject)}</b>\n\n"
        "<blockquote>Шаг 2 из 2 — подробно опиши проблему:</blockquote>",
        reply_markup=back_menu_kb(),
    )


@router.message(TicketStates.wait_body, F.text)
async def h_ticket_body(message: Message, state: FSMContext):
    body = (message.text or "").strip()[:2000]
    if not body:
        return
    data = await state.get_data()
    subject = data.get("subject", "")
    await state.clear()

    ctx = app()
    tid = await ctx.db.create_ticket(message.from_user.id, subject, body)

    await message.answer(
        f"✅ <b>Обращение создано!</b>\n\n"
        f"Номер: <code>{tid}</code>\n"
        f"Тема: <b>{esc(subject)}</b>\n\n"
        "Оператор ответит здесь же. Ожидай 🔔",
        reply_markup=back_menu_kb(),
    )


@router.callback_query(F.data == "u:ticket:list")
async def cb_ticket_list(cb: CallbackQuery, user: dict):
    """Список активных тикетов пользователя."""
    if not cb.message:
        return await answer_or_alert(cb)
    ctx = app()
    tickets = await ctx.db.user_active_tickets(cb.from_user.id)
    if not tickets:
        await safe_edit(
            cb.message,
            "📭 <b>У тебя нет активных обращений.</b>",
            back_menu_kb(),
        )
        return await answer_or_alert(cb)
    lines = []
    for t in tickets:
        status = {"open": "🟡 открыт", "in_progress": "🔵 в работе",
                  "closed": "🟢 закрыт"}.get(t["status"], t["status"])
        lines.append(f"• <code>{t['ticket_id']}</code> — {esc(t['subject'])} [{status}]")
    await safe_edit(
        cb.message,
        "📬 <b>Твои обращения:</b>\n\n" + "\n".join(lines),
        back_menu_kb(),
    )
    await answer_or_alert(cb)
