# -*- coding: utf-8 -*-
"""Админка: динамические разделы меню."""
from __future__ import annotations

import logging

from aiogram import F, Router
from aiogram.filters import Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message
from aiogram.utils.keyboard import InlineKeyboardBuilder

from ...context import app
from ...texts import esc
from ...utils import answer_or_alert, safe_edit

log = logging.getLogger(__name__)
router = Router(name="adm-sections")


class AdmSectionStates(StatesGroup):
    wait_key = State()
    wait_title = State()
    wait_text = State()


async def _render(cb: CallbackQuery):
    ctx = app()
    sections = await ctx.db.list_sections()

    kb = InlineKeyboardBuilder()
    for section in sections:
        kb.button(
            text=f"🗑 {section['key']}",
            callback_data=f"adm:sec:del:{section['key']}",
        )
    kb.button(text="➕ Новый раздел", callback_data="adm:sec:add")
    kb.button(text="⬅️ В админку", callback_data="adm")
    kb.adjust(1)

    lines = [
        f"• <code>{esc(s['key'])}</code> — {esc((s.get('title') or '')[:40])}"
        for s in sections
    ]

    await safe_edit(
        cb.message,
        "🧩 <b>Разделы меню</b>\n\n"
        + ("\n".join(lines) if lines else "Пока пусто."),
        kb.as_markup(),
    )


@router.callback_query(F.data == "adm:sec")
async def cb_sections_list(cb: CallbackQuery):
    if not cb.message:
        return await answer_or_alert(cb)
    await _render(cb)
    await answer_or_alert(cb)


@router.callback_query(F.data.startswith("adm:sec:del:"))
async def cb_section_del(cb: CallbackQuery):
    if not cb.message:
        return await answer_or_alert(cb)

    key = cb.data.removeprefix("adm:sec:del:")
    ctx = app()
    await ctx.db.delete_section(key)
    ctx.gate.list_cache.pop("sections")
    await ctx.db.log_event(cb.from_user.id, "section_deleted", key)
    await _render(cb)
    await answer_or_alert(cb, f"🗑 Раздел «{key}» удалён")


@router.callback_query(F.data == "adm:sec:add")
async def cb_section_add(cb: CallbackQuery, state: FSMContext):
    if not cb.message:
        return await answer_or_alert(cb)

    await state.set_state(AdmSectionStates.wait_key)
    await safe_edit(
        cb.message,
        "➕ <b>Новый раздел</b>\n\n"
        "Шаг 1/3 — ключ (латиница, цифры, _, -).\n"
        "Например: <code>faq</code>",
        None,
    )
    await answer_or_alert(cb, "Жду ключ")


@router.message(StateFilter(AdmSectionStates.wait_key), F.text)
async def h_section_key(message: Message, state: FSMContext):
    key = (message.text or "").strip().lower()

    if not key or not key.replace("_", "").replace("-", "").isalnum():
        return await message.answer("❌ Ключ — только латиница, цифры, _ и -.")

    if await app().db.get_section(key):
        return await message.answer("❌ Такой раздел уже есть.")

    await state.update_data(key=key)
    await state.set_state(AdmSectionStates.wait_title)
    await message.answer("Шаг 2/3 — заголовок для кнопки:")


@router.message(StateFilter(AdmSectionStates.wait_title), F.text)
async def h_section_title(message: Message, state: FSMContext):
    title = (message.text or "").strip()[:60]
    if not title:
        return

    await state.update_data(title=title)
    await state.set_state(AdmSectionStates.wait_text)
    await message.answer(
        f"Заголовок: <b>{esc(title)}</b>\n\n"
        "Шаг 3/3 — текст раздела (HTML разрешён):"
    )


@router.message(StateFilter(AdmSectionStates.wait_text), F.text)
async def h_section_text(message: Message, state: FSMContext):
    text = (message.text or "").strip()
    if not text:
        return

    data = await state.get_data()
    await state.clear()

    key = data.get("key")
    if not key:
        return

    ctx = app()
    await ctx.db.save_section(
        key, {"title": data.get("title") or key, "text": text, "buttons": []}
    )
    ctx.gate.list_cache.pop("sections")
    await ctx.db.log_event(message.from_user.id, "section_created", key)
    await message.answer(
        f"✅ Раздел <code>{esc(key)}</code> создан.",
        reply_markup=None,
    )


@router.message(Command("addsection"))
async def cmd_add_section(message: Message):
    if not message.text:
        return

    raw = message.text.partition(" ")[2]
    parts = [p.strip() for p in raw.split("|")]

    if len(parts) < 3:
        return await message.answer(
            "Формат: <code>/addsection key | Заголовок | Текст</code>"
        )

    key, title, text = parts[0].lower(), parts[1], parts[2]

    if not key or not key.replace("_", "").replace("-", "").isalnum():
        return await message.answer("Ключ — только латиница, _, -")

    ctx = app()
    await ctx.db.save_section(
        key, {"title": title, "text": text, "buttons": []}
    )
    ctx.gate.list_cache.pop("sections")
    await message.answer(f"✅ Раздел <code>{key}</code> создан.")
