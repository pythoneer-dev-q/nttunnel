# -*- coding: utf-8 -*-
"""Админка: каналы обязательной подписки."""
import logging
import re
from datetime import datetime, timezone

from aiogram import F, Router
from aiogram.filters import StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message

from ...context import app
from ...keyboards import adm_back_kb
from ...texts import esc
from ...utils import answer_or_alert, fmt_dt, safe_edit

log = logging.getLogger(__name__)
router = Router(name="adm-channels")

PAGE_SIZE = 8


class AdmChStates(StatesGroup):
    wait_channel = State()


def _channels_kb(page: int, pages: int, items: list, extra: list):
    """Клавиатура списка каналов: удаление + действия + пагинация."""
    from aiogram.types import InlineKeyboardButton
    from aiogram.utils.keyboard import InlineKeyboardBuilder

    kb = InlineKeyboardBuilder()

    for label, cbd in items:
        kb.button(text=label[:64], callback_data=cbd)

    for label, cbd in extra:
        kb.button(text=label[:64], callback_data=cbd)

    kb.adjust(1)

    nav: list = []
    if page > 0:
        nav.append(InlineKeyboardButton(
            text="⬅️", callback_data=f"adm:chn:p{page - 1}"))
    if pages > 1:
        nav.append(InlineKeyboardButton(
            text=f"{page + 1}/{pages}", callback_data="noop"))
    if page < pages - 1:
        nav.append(InlineKeyboardButton(
            text="➡️", callback_data=f"adm:chn:p{page + 1}"))
    if nav:
        kb.row(*nav)

    return kb.as_markup()


@router.callback_query(F.data == "adm:chn")
@router.callback_query(F.data.startswith("adm:chn:p"))
async def cb_channels(cb: CallbackQuery):
    if not cb.message:
        return await answer_or_alert(cb)
    ctx = app()

    rest = cb.data.removeprefix("adm:chn").removeprefix(":p")
    page = int(rest) if rest.isdigit() else 0

    # Пагинация на стороне MongoDB + сортировка по datetime (а не по строке).
    total = await ctx.db.channels.count_documents({})
    pages = max((total + PAGE_SIZE - 1) // PAGE_SIZE, 1)
    page = min(max(page, 0), pages - 1)

    chans = [c async for c in ctx.db.channels.find().sort(
        [("_ts_added", -1), ("channel_id", 1)],
    ).skip(page * PAGE_SIZE).limit(PAGE_SIZE)]

    lines, items = [], []
    for ch in chans:
        t = (ch.get("title") or ch.get("username") or str(ch["channel_id"]))[:30]
        lines.append(f"📺 <b>{esc(t)}</b> · <code>{ch['channel_id']}</code>")
        items.append((f"🗑 {t} · {ch['channel_id']}",
                      f"adm:chn:del:{ch['channel_id']}"))

    if lines:
        text = ("📺 <b>Каналы обязательной подписки</b>\n\n"
                + "\n".join(lines)
                + "\n\n<i>Нажмите на канал для удаления.</i>")
    else:
        text = ("📺 <b>Каналы обязательной подписки</b>\n\n"
                "Пока не добавлены.")

    kb = _channels_kb(page, pages, items, [
        ("➕ Добавить канал", "adm:chn:add"),
        ("⬅️ В админку", "adm"),
    ])
    await safe_edit(cb.message, text, kb)
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


@router.callback_query(F.data == "adm:chn:add")
async def cb_channel_add(cb: CallbackQuery, state: FSMContext):
    await state.set_state(AdmChStates.wait_channel)
    if cb.message:
        try:
            await cb.message.edit_text(
                "➕ <b>Добавление канала</b>\n\n"
                "Отправьте одно из:\n"
                "• <code>@username</code> публичного канала\n"
                "• ссылку <code>https://t.me/username</code>\n"
                "• ссылку <code>https://t.me/c/1234567890</code> (приватный)\n"
                "• числовой ID приватного канала <code>-100…</code>\n\n"
                "Бот должен быть администратором канала с правом чтения "
                "участников!",
                reply_markup=adm_back_kb("adm:chn"))
        except Exception:  # noqa: BLE001
            pass
    await answer_or_alert(cb, "Жду ссылку или ID ⌨️")


_TME_RE = re.compile(r"^(?:https?://)?t\.me/(.+)$", re.I)


def _parse_channel_ref(raw: str):
    """Разбирает ввод админа в int ID канала или '@username'.

    Поддерживает: числовой ID, @username, t.me/username, t.me/username/123
    (пост-ссылка), t.me/c/<id> (приватный). Возвращает None, если не понял.
    """
    raw = (raw or "").strip()
    if not raw:
        return None

    # числовой ID: -100… или обычный
    if raw.lstrip("-").isdigit():
        return int(raw)

    m = _TME_RE.match(raw)
    if m:
        tail = m.group(1).split("?")[0].strip("/")

        # приватный канал: t.me/c/1234567890 -> -1001234567890
        if tail.lower().startswith("c/"):
            digits = re.sub(r"\D", "", tail[2:].split("/")[0])
            return int(f"-100{digits}") if digits else None

        # инвайт-ссылка t.me/+hash — нужен числовой ID
        if tail.startswith("+"):
            return None

        # t.me/username или t.me/username/123 -> username
        name = tail.split("/")[0]
        return f"@{name}" if name else None

    # @username или просто username
    name = raw.lstrip("@").split("/")[0].split("?")[0].strip()
    if name and name.replace("_", "").isalnum():
        return f"@{name}"
    return None


@router.message(StateFilter(AdmChStates.wait_channel), F.text)
async def h_channel_input(message: Message, state: FSMContext):
    raw = (message.text or "").strip()
    ch_ref = _parse_channel_ref(raw)

    if ch_ref is None:
        await message.answer(
            "❌ Не понял ссылку. Пришлите <code>@username</code>, ссылку "
            "<code>t.me/…</code> или ID канала <code>-100…</code>.")
        return

    await state.clear()

    try:
        chat = await message.bot.get_chat(ch_ref)
    except Exception as e:  # noqa: BLE001
        await message.answer(
            f"❌ Не удалось найти канал: <code>{esc(str(e)[:150])}</code>\n\n"
            "• публичный — @username или ссылку <code>t.me/…</code>;\n"
            "• приватный — числовой ID <code>-100…</code>;\n"
            "• бот должен быть админом канала с правом чтения участников.")
        return

    if str(chat.type) not in ("channel", "supergroup", "group"):
        await message.answer(
            "❌ Это не канал и не группа. Пришлите канал, "
            "а не пользователя или бота.")
        return

    ctx = app()
    doc = {
        "channel_id": chat.id,
        "title": chat.title or chat.username or str(chat.id),
        "username": chat.username,
        "url": (f"https://t.me/{chat.username}" if chat.username
                else f"https://t.me/c/{str(chat.id).replace('-100', '')}"),
        "type": str(chat.type),
        "added_at": fmt_dt(datetime.now()),
        "_ts_added": datetime.now(timezone.utc),
    }

    res = await ctx.db.channels.update_one(
        {"channel_id": chat.id}, {"$setOnInsert": doc}, upsert=True)
    ctx.gate.list_cache.pop("channels")

    if res.upserted_id is None:
        await message.answer(
            f"ℹ️ Канал <b>{esc(doc['title'])}</b> уже в списке обязательных.")
        return

    await ctx.db.log_event(message.from_user.id, "admin",
                           f"channel added {chat.id}")
    await message.answer(
        f"✅ Канал <b>{esc(doc['title'])}</b> добавлен как обязательный.")
