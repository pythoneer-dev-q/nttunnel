# -*- coding: utf-8 -*-
"""Конструктор динамических разделов (админка).

Раздел — это именованный блок с текстом и набором кнопок.
Админ создаёт/редактирует/удаляет разделы, а пользователи открывают
их по ключу из меню. Позволяет добавить в меню произвольные разделы
без переписывания кода.

Формат секции в БД:
  key: уникальный идентификатор (slug)
  title: заголовок для меню
  text: текст раздела (HTML)
  buttons: [{label, url}] — опциональные кнопки
"""
import logging

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import CallbackQuery, Message

from ...context import app
from ...keyboards import adm_back_kb
from ...texts import esc
from ...utils import answer_or_alert, safe_edit

log = logging.getLogger(__name__)
router = Router(name="adm-sections")


async def _render_sections_list(cb: CallbackQuery):
    """Рисует список разделов (без answer — для переиспользования)."""
    from aiogram.utils.keyboard import InlineKeyboardBuilder

    ctx = app()
    sections = await ctx.db.list_sections()

    if not sections:
        await safe_edit(
            cb.message,
            "📂 <b>Конструктор разделов</b>\n\nПока пусто.",
            adm_back_kb("adm"),
        )
        return

    kb = InlineKeyboardBuilder()
    for s in sections:
        kb.button(text=f"🗑 {s['key']}",
                  callback_data=f"adm:sec:del:{s['key']}")
    kb.button(text="➕ Новый раздел", callback_data="adm:sec:add")
    kb.button(text="⬅️ В админку", callback_data="adm")
    kb.adjust(1)

    lines = [f"• <code>{s['key']}</code> — {esc(s.get('title', '')[:40])}"
             for s in sections]
    await safe_edit(
        cb.message,
        "📂 <b>Конструктор разделов</b>\n\n" + "\n".join(lines),
        kb.as_markup(),
    )


@router.callback_query(F.data == "adm:sec")
async def cb_sections_list(cb: CallbackQuery):
    if not cb.message:
        return await answer_or_alert(cb)
    await _render_sections_list(cb)
    await answer_or_alert(cb)


@router.callback_query(F.data.startswith("adm:sec:del:"))
async def cb_section_del(cb: CallbackQuery):
    """Удаление раздела прямо из списка."""
    if not cb.message:
        return await answer_or_alert(cb)
    key = cb.data.removeprefix("adm:sec:del:")
    ctx = app()
    await ctx.db.delete_section(key)
    ctx.gate.list_cache.pop("sections", None)
    await ctx.db.log_event(cb.from_user.id, "section_deleted", key)
    await _render_sections_list(cb)
    await answer_or_alert(cb, f"🗑 Раздел «{key}» удалён")


@router.callback_query(F.data == "adm:sec:add")
async def cb_section_add(cb: CallbackQuery):
    if not cb.message:
        return await answer_or_alert(cb)
    await safe_edit(
        cb.message,
        "➕ <b>Новый раздел</b>\n\n"
        "<blockquote>"
        "Пришли ключ раздела (латинница, подчёркивания, дефисы).\n"
        "Например: <code>faq</code>, <code>partners</code>"
        "</blockquote>",
        adm_back_kb("adm:sec"),
    )
    await answer_or_alert(cb, "Жду ключ раздела")


@router.message(Command("addsection"))
async def cmd_add_section(message: Message):
    """Быстрое создание раздела: /addsection key | title | text."""
    if not message.text:
        return
    # Убираем саму команду: "/addsection key | title | text" -> "key | ...".
    # Иначе parts[0] = "/addsection key" и валидация ключа всегда падала.
    raw = message.text.partition(" ")[2]
    parts = [p.strip() for p in raw.split("|")]
    if len(parts) < 3:
        return await message.answer(
            "Формат: <code>/addsection key | Заголовок | Текст раздела</code>")
    key, title, text = parts[0], parts[1], parts[2]
    if not key or not key.replace("_", "").replace("-", "").isalnum():
        return await message.answer("Ключ — только латиница, _, -")
    ctx = app()
    await ctx.db.save_section(key, {"title": title, "text": text, "buttons": []})
    ctx.gate.list_cache.pop("sections")
    await message.answer(f"✅ Раздел <code>{key}</code> создан.")
