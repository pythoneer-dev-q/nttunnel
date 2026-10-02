# -*- coding: utf-8 -*-
"""Админка: управление тикетами поддержки."""
import logging

from aiogram import F, Router
from aiogram.filters import StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message

from ...context import app
from ...keyboards import adm_back_kb
from ...texts import esc
from ...utils import answer_or_alert, build_page_kb, page_slice, safe_edit

log = logging.getLogger(__name__)
router = Router(name="adm-tickets")

PAGE_SIZE = 8


class AdmTicketStates(StatesGroup):
    reply = State()


def ticket_text(t: dict) -> str:
    status = {"open": "🟡 открыт", "in_progress": "🔵 в работе",
              "closed": "🟢 закрыт"}.get(t["status"], t["status"])
    msgs = t.get("messages", []) or []
    history = ""
    for m in msgs[-5:]:
        who = "👤" if m["author"] == "user" else "🛠"
        history += f"\n{who} {esc(m['text'][:200])}"
    return (
        "🎫 <b>Тикет</b> <code>{tid}</code> [{status}]\n"
        "От: <code>{tg_id}</code> · {subject}\n"
        "<blockquote>{body}</blockquote>\n"
        "<b>Переписка:</b>{history}"
    ).format(tid=t["ticket_id"], status=status, tg_id=t["tg_id"],
             subject=esc(t.get("subject", "")), body=esc(t.get("body", "")),
             history=history or " —")


@router.callback_query(F.data == "adm:tkt")
@router.callback_query(F.data.startswith("adm:tkt:p"))
async def cb_tickets_list(cb: CallbackQuery):
    if not cb.message:
        return await answer_or_alert(cb)
    ctx = app()
    tickets = await ctx.db.list_tickets(limit=100)
    chunk, pages, page = page_slice(
        tickets, int(cb.data.removeprefix("adm:tkt:p") or 0), PAGE_SIZE)
    items = [(f"🎫 {t['ticket_id']} · {esc(t.get('subject', '')[:25])}",
              f"adm:tkt:v{t['ticket_id']}") for t in chunk]
    text = (f"🎫 <b>Обращения</b> — всего {len(tickets)}\n\n"
            + (f"Стр. {page + 1}/{pages}" if pages > 1 else ""))
    await safe_edit(cb.message, text, build_page_kb("adm:tkt", page, pages, items))
    await answer_or_alert(cb)


@router.callback_query(F.data.startswith("adm:tkt:v"))
async def cb_ticket_view(cb: CallbackQuery):
    if not cb.message:
        return await answer_or_alert(cb)
    tid = cb.data.removeprefix("adm:tkt:v")
    ctx = app()
    t = await ctx.db.get_ticket(tid)
    if not t:
        return await answer_or_alert(cb, "Тикет не найден", True)
    status = t["status"]
    buttons = []
    if status != "closed":
        buttons.append(("💬 Ответить", f"adm:tkt:reply:{tid}"))
        if status == "open":
            buttons.append(("🔵 Взять в работу", f"adm:tkt:prog:{tid}"))
        buttons.append(("✅ Закрыть", f"adm:tkt:close:{tid}"))
    buttons.append(("⬅️ К списку", "adm:tkt"))
    from aiogram.utils.keyboard import InlineKeyboardBuilder
    kb = InlineKeyboardBuilder()
    for label, cbd in buttons:
        kb.button(text=label, callback_data=cbd)
    kb.adjust(1)
    await safe_edit(cb.message, ticket_text(t), kb.as_markup())
    await answer_or_alert(cb)


@router.callback_query(F.data.startswith("adm:tkt:reply:"))
async def cb_ticket_reply_start(cb: CallbackQuery, state: FSMContext):
    if not cb.message:
        return await answer_or_alert(cb)
    tid = cb.data.removeprefix("adm:tkt:reply:")
    await state.set_state(AdmTicketStates.reply)
    await state.update_data(ticket_id=tid)
    await safe_edit(
        cb.message,
        f"💬 <b>Ответ в тикет</b> <code>{tid}</code>\n\n"
        "Напиши ответ — он уйдёт пользователю:",
        adm_back_kb("adm:tkt"),
    )
    await answer_or_alert(cb)


@router.message(StateFilter(AdmTicketStates.reply), F.text)
async def h_ticket_reply(message: Message, state: FSMContext):
    data = await state.get_data()
    tid = data.get("ticket_id")
    await state.clear()
    if not tid:
        return
    ctx = app()
    t = await ctx.db.get_ticket(tid)
    if not t:
        return await message.answer("Тикет не найден.")
    await ctx.db.append_ticket_message(tid, "admin", message.text or "")
    if t.get("status") == "open":
        await ctx.db.set_ticket_status(tid, "in_progress")
    # уведомляем юзера
    try:
        await message.bot.send_message(
            t["tg_id"],
            f"🛠 <b>Ответ в обращение</b> <code>{tid}</code>:\n\n"
            f"{message.text[:2000]}",
        )
    except Exception as e:  # noqa: BLE001
        log.warning("notify user %s failed: %s", t["tg_id"], e)
    await message.answer(f"✅ Ответ отправлен в тикет <code>{tid}</code>.")


@router.callback_query(F.data.startswith("adm:tkt:close:"))
async def cb_ticket_close(cb: CallbackQuery):
    if not cb.message:
        return await answer_or_alert(cb)
    tid = cb.data.removeprefix("adm:tkt:close:")
    ctx = app()
    await ctx.db.set_ticket_status(tid, "closed")
    t = await ctx.db.get_ticket(tid)
    if t:
        try:
            await cb.bot.send_message(
                t["tg_id"],
                f"✅ <b>Обращение</b> <code>{tid}</code> закрыто.\n"
                "Если вопрос остался — создай новое: /support",
            )
        except Exception:  # noqa: BLE001
            pass
    await answer_or_alert(cb, f"✅ Тикет {tid} закрыт")


@router.callback_query(F.data.startswith("adm:tkt:prog:"))
async def cb_ticket_progress(cb: CallbackQuery):
    tid = cb.data.removeprefix("adm:tkt:prog:")
    await app().db.set_ticket_status(tid, "in_progress")
    await answer_or_alert(cb, "🔵 Взято в работу")
