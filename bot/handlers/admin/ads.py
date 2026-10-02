# -*- coding: utf-8 -*-
"""Админка: рекламные кнопки в меню подписки/кабинета."""
import logging

from aiogram import F, Router
from aiogram.filters import StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message

from ...context import app
from ...keyboards import adm_back_kb
from ...texts import esc
from ...utils import answer_or_alert, build_page_kb, extract_url, safe_edit

log = logging.getLogger(__name__)
router = Router(name="adm-ads")


class AdmAdStates(StatesGroup):
    wait_label = State()
    wait_url = State()


@router.callback_query(F.data == "adm:ads")
async def cb_ads(cb: CallbackQuery):
    if not cb.message:
        return await answer_or_alert(cb)
    ctx = app()
    ads = [a async for a in ctx.db.ads.find().sort("added_at", 1)]
    lines = [f"🎯 <b>{esc(a['title'])}</b> → {esc(a['url'])}" for a in ads]
    items = [(f"🗑 {a['title'][:30]}", f"adm:ads:del:{a['key']}")
             for a in ads]
    kb = build_page_kb("adm:ads", 0, 1, items)
    from aiogram.types import InlineKeyboardButton
    kb.inline_keyboard.insert(
        0, [InlineKeyboardButton(text="➕ Добавить кнопку",
                                 callback_data="adm:ads:add")])
    text = ("🎯 <b>Рекламные кнопки</b>\n\n"
            + ("\n".join(lines) if lines else "Пока пусто.")
            + "\n\n<i>Показываются в меню и кабинете пользователей. "
              "Нажмите на кнопку для удаления.</i>")
    await safe_edit(cb.message, text, kb)
    await answer_or_alert(cb)


@router.callback_query(F.data.startswith("adm:ads:del:"))
async def cb_ads_del(cb: CallbackQuery):
    if not cb.message:
        return await answer_or_alert(cb)
    key = cb.data.removeprefix("adm:ads:del:")
    ctx = app()
    await ctx.db.ads.delete_one({"key": key})
    ctx.gate.list_cache.pop("ads")
    await ctx.db.log_event(cb.from_user.id, "admin", f"ad removed {key}")
    await answer_or_alert(cb, "Удалено")
    await cb_ads(cb)


@router.callback_query(F.data == "adm:ads:add")
async def cb_ads_add(cb: CallbackQuery, state: FSMContext):
    await state.set_state(AdmAdStates.wait_label)
    if cb.message:
        try:
            await cb.message.edit_text(
                "➕ <b>Добавление рекламной кнопки</b>\n\n"
                "1️⃣ Пришлите текст кнопки (например, «🔥 Наш партнёр»)",
                reply_markup=adm_back_kb("adm"))
        except Exception:  # noqa: BLE001
            pass
    await answer_or_alert(cb)


@router.message(StateFilter(AdmAdStates.wait_label),
                F.text & ~F.text.startswith("/"))
async def h_ad_label(message: Message, state: FSMContext):
    label = (message.text or "").strip()[:60]
    if not label or label.startswith("/"):
        return
    await state.set_state(AdmAdStates.wait_url)
    await state.update_data(label=label)
    from aiogram.utils.keyboard import InlineKeyboardBuilder
    kb = InlineKeyboardBuilder()
    kb.button(text="❌ Отмена", callback_data="adm:ads")
    await message.answer(
        f"2️⃣ Текст: <b>{esc(label)}</b>\n\nТеперь пришлите ссылку "
        "(URL):", reply_markup=kb.as_markup())


@router.message(StateFilter(AdmAdStates.wait_url), F.text)
async def h_ad_url(message: Message, state: FSMContext):
    url = extract_url(message.text or "")
    data = await state.get_data()
    await state.clear()
    if not url:
        await message.answer("❌ Не вижу ссылки. Пришлите URL ещё раз или /cancel.")
        return
    import time as _t
    ctx = app()
    key = f"ad_{int(_t.time())}"
    await ctx.db.ads.insert_one({
        "key": key,
        "title": data["label"],
        "url": url,
        "added_by": message.from_user.id,
        "added_at": _t.time(),
    })
    ctx.gate.list_cache.pop("ads")
    await ctx.db.log_event(message.from_user.id, "admin", f"ad added {key}")
    await message.answer(f"✅ Кнопка «{data['label']}» добавлена в меню.")


@router.message(StateFilter(AdmAdStates.wait_label), F.text.startswith("/"))
@router.message(StateFilter(AdmAdStates.wait_url), F.text.startswith("/"))
async def h_ad_cancel_cmd(message: Message, state: FSMContext):
    await state.clear()
    await message.answer("❌ Добавление отменено.")
