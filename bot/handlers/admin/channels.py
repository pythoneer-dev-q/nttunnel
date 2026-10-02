# -*- coding: utf-8 -*-
"""Админка: каналы обязательной подписки."""
import logging
from datetime import datetime

from aiogram import F, Router
from aiogram.filters import StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message

from ...context import app
from ...keyboards import adm_back_kb
from ...texts import esc
from ...utils import answer_or_alert, build_page_kb, fmt_dt, safe_edit

log = logging.getLogger(__name__)
router = Router(name="adm-channels")


class AdmChStates(StatesGroup):
    wait_channel = State()


@router.callback_query(F.data == "adm:chn")
async def cb_channels(cb: CallbackQuery):
    if not cb.message:
        return await answer_or_alert(cb)
    ctx = app()
    chans = [c async for c in ctx.db.channels.find().sort("added_at", -1)]
    lines, items = [], []
    for ch in chans:
        t = (ch.get("title") or ch.get("username") or str(ch["channel_id"]))[:30]
        lines.append(f"📺 <b>{esc(t)}</b> · {ch['channel_id']}")
        items.append((f"🗑 {t} · {ch['channel_id']}",
                      f"adm:chn:del:{ch['channel_id']}"))
    kb = build_page_kb("adm:chn", 0, 1, items)
    from aiogram.utils.keyboard import InlineKeyboardBuilder
    b = InlineKeyboardBuilder()
    if not lines:
        await safe_edit(
            cb.message,
            "📺 <b>Каналы обязательной подписки</b>\n\nПока не добавлены.",
            adm_back_kb("adm"))
        return await answer_or_alert(cb)
    b.button(text="➕ Добавить канал", callback_data="adm:chn:add")
    text = ("📺 <b>Каналы обязательной подписки</b>\n\n"
            + "\n".join(lines)
            + "\n\n<i>Нажмите на канал для удаления.</i>")
    kb.inline_keyboard.insert(0, [from_aiogram_button("➕ Добавить канал",
                                                      "adm:chn:add")])
    await safe_edit(cb.message, text, kb)
    await answer_or_alert(cb)


def from_aiogram_button(text, cbd):
    from aiogram.types import InlineKeyboardButton
    return InlineKeyboardButton(text=text[:64], callback_data=cbd)


@router.callback_query(F.data == "adm:chn:add")
async def cb_channel_add(cb: CallbackQuery, state: FSMContext):
    await state.set_state(AdmChStates.wait_channel)
    if cb.message:
        try:
            await cb.message.edit_text(
                "➕ <b>Добавление канала</b>\n\n"
                "Отправьте одно из:\n"
                "• @username публичного канала\n"
                "• ссылку https://t.me/имя_канала\n"
                "• числовой ID приватного канала (-100...)\n\n"
                "Бот должен быть администратором канала с правом чтения участников!",
                reply_markup=adm_back_kb("adm"))
        except Exception:  # noqa: BLE001
            pass
    await answer_or_alert(cb)


@router.callback_query(F.data.startswith("adm:chn:del:"))
async def cb_channel_del(cb: CallbackQuery):
    if not cb.message:
        return await answer_or_alert(cb)
    ch_id = int(cb.data.removeprefix("adm:chn:del:"))
    ctx = app()
    await ctx.db.channels.delete_one({"channel_id": ch_id})
    ctx.gate.list_cache.pop("channels")
    await ctx.db.log_event(cb.from_user.id, "admin", f"channel removed {ch_id}")
    await cb_channels(cb)


@router.message(StateFilter(AdmChStates.wait_channel), F.text)
async def h_channel_input(message: Message, state: FSMContext):
    raw = (message.text or "").strip()
    await state.clear()
    ch_ref = None
    if raw.lstrip("-").isdigit():
        ch_ref = int(raw)
    else:
        raw2 = raw.removeprefix("@")
        if "t.me/" in raw2:
            raw2 = raw2.split("t.me/")[-1].lstrip("/")
        raw2 = raw2.split("?")[0].strip("/")
        if raw2 and "/" not in raw2 and not raw2.startswith("+"):
            ch_ref = f"@{raw2}"
    if ch_ref is None:
        await message.answer(
            "❌ Не понял ссылку. Пришлите @username, ссылку t.me или ID канала.")
        return
    try:
        chat = await message.bot.get_chat(ch_ref)
    except Exception as e:  # noqa: BLE001
        await message.answer(f"❌ Не удалось найти канал ({str(e)[:150]}).\n"
                             "Для приватных каналов пришлите числовой ID.")
        return
    ctx = app()
    doc = {
        "channel_id": chat.id,
        "title": chat.title or chat.username or str(chat.id),
        "username": chat.username,
        "url": (f"https://t.me/{chat.username}" if chat.username else None),
        "type": str(chat.type),
        "added_at": fmt_dt(datetime.now()),
        "_ts_added": datetime.now(),
    }
    await ctx.db.channels.update_one({"channel_id": chat.id},
                                     {"$setOnInsert": doc}, upsert=True)
    ctx.gate.list_cache.pop("channels")
    await ctx.db.log_event(message.from_user.id, "admin",
                           f"channel added {chat.id}")
    await message.answer(f"✅ Канал <b>{esc(doc['title'])}</b> добавлен как "
                         "обязательный.")
