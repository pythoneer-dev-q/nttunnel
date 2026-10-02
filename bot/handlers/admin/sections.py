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


@router.callback_query(F.data == "adm:sec")
async def cb_sections_list(cb: CallbackQuery):
    if not cb.message:
        return await answer_or_alert(cb)
    ctx = app()
    sections = await ctx.db.list_sections()
    if not sections:
        await safe_edit(
            cb.message,
            "📂 <b>Конструктор разделов</b>\n\nПока пусто.",
            adm_back_kb("adm"),
        )
        return await answer_or_alert(cb)
    lines = [f"• <code>{s['key']}</code> — {esc(s.get('title', '')[:40])}"
             for s in sections]
    await safe_edit(
        cb.message,
        "📂 <b>Конструктор разделов</b>\n\n" + "\n".join(lines),
        adm_back_kb("adm"),
    )
    await answer_or_alert(cb)


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
    parts = [p.strip() for p in message.text.split("|")]
    if len(parts) < 3:
        return await message.answer(
            "Формат: <code>/addsection key | Заголовок | Текст раздела</code>")
    key, title, text = parts[0], parts[1], parts[2]
    if not key.replace("_", "").replace("-", "").isalnum():
        return await message.answer("Ключ — только латиница, _, -")
    ctx = app()
    await ctx.db.save_section(key, {"title": title, "text": text, "buttons": []})
    ctx.gate.list_cache.pop("sections")
    await message.answer(f"✅ Раздел <code>{key}</code> создан.")
