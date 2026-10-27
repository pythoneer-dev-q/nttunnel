# -*- coding: utf-8 -*-
"""Админка: пользователи панели — список, поиск, лимиты, блокировки."""
from __future__ import annotations

import logging
import time

from aiogram import F, Router
from aiogram.filters import StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message
from aiogram.utils.keyboard import InlineKeyboardBuilder

from ...context import app
from ...keyboards import adm_back_kb, copy_btn
from ...texts import esc
from ...utils import answer_or_alert, safe_edit, yes_no_kb
from ...wdtt import (
    expires_text,
    extract_node_links,
    human_bytes,
    panel_tg_id,
    traffic_bar,
    user_status,
)

log = logging.getLogger(__name__)
router = Router(name="adm-users")

PAGE_SIZE = 8


class AdmUserStates(StatesGroup):
    wait_input = State()
    search = State()


def _status_dot(user: dict) -> str:
    status, key = user_status(user)
    return {
        "active": "🟢",
        "blocked": "🚫",
        "expired": "⌛",
        "exceeded": "📵",
    }.get(key, "⚪")


def _pct(user: dict) -> int:
    try:
        total = float(user.get("total_gb") or 0) * 1024 ** 3
        used = float(user.get("traffic_used_bytes") or 0)
        return int(min(used / total * 100, 100)) if total > 0 else 0
    except (TypeError, ValueError):
        return 0


def _users_kb(page: int, pages: int, users: list):
    from aiogram.types import InlineKeyboardButton

    kb = InlineKeyboardBuilder()

    for user in users:
        user_id = str(user.get("id") or "")
        name = str(user.get("name") or user.get("comment") or user_id)[:28]
        traffic = human_bytes(user.get("traffic_used_bytes"))
        label = f"{_status_dot(user)} {name} · {traffic}"
        kb.button(text=label[:64], callback_data=f"adm:usr:v:{user_id}")

    kb.button(text="🔍 Поиск", callback_data="adm:usr:find")
    kb.button(text="⬅️ В админку", callback_data="adm")
    kb.adjust(1)

    nav: list[InlineKeyboardButton] = []
    if page > 0:
        nav.append(InlineKeyboardButton(
            text="⬅️", callback_data=f"adm:usr:p{page - 1}"))
    if pages > 1:
        nav.append(InlineKeyboardButton(
            text=f"{page + 1}/{pages}", callback_data="noop"))
    if page < pages - 1:
        nav.append(InlineKeyboardButton(
            text="➡️", callback_data=f"adm:usr:p{page + 1}"))
    if nav:
        kb.row(*nav)

    return kb.as_markup()


@router.callback_query(F.data == "adm:usr")
@router.callback_query(F.data.startswith("adm:usr:p"))
async def cb_users_list(cb: CallbackQuery, state: FSMContext | None = None):
    if state:
        await state.clear()
    if not cb.message:
        return await answer_or_alert(cb)

    rest = cb.data.removeprefix("adm:usr").removeprefix(":p")
    page = int(rest) if rest.isdigit() else 0

    try:
        data = await app().wdtt.list_users(
            limit=PAGE_SIZE, offset=page * PAGE_SIZE
        )
    except Exception as e:
        await safe_edit(
            cb.message,
            f"🔌 Не удалось загрузить пользователей:\n"
            f"<code>{esc(str(e)[:200])}</code>",
            adm_back_kb("adm"),
        )
        return await answer_or_alert(cb)

    total = int(data.get("total") or 0)
    users = [u for u in data.get("users") or [] if isinstance(u, dict)]
    pages = max((total + PAGE_SIZE - 1) // PAGE_SIZE, 1)
    page = min(max(page, 0), pages - 1)

    lines = []
    for user in users:
        name = esc(user.get("name") or user.get("comment") or user.get("id"))
        used = human_bytes(user.get("traffic_used_bytes"))
        total_gb = user.get("total_gb") or 0
        tail = f"/{float(total_gb):.0f} ГБ" if total_gb else "/∞"
        lines.append(f"{_status_dot(user)} <b>{name}</b> · {used}{tail}")

    text = (
        f"👥 <b>Пользователи панели</b> · {total}\n\n"
        + ("\n".join(lines) if lines else "Пусто.")
    )

    await safe_edit(cb.message, text, _users_kb(page, pages, users))
    await answer_or_alert(cb)


@router.callback_query(F.data == "adm:usr:find")
async def cb_users_find(cb: CallbackQuery, state: FSMContext):
    await state.set_state(AdmUserStates.search)
    if cb.message:
        await safe_edit(
            cb.message,
            "🔍 <b>Поиск</b>\n\n"
            "Пришли имя, комментарий, пароль или <code>tg_id</code>.",
            adm_back_kb("adm:usr"),
        )
    await answer_or_alert(cb, "Жду запрос")


async def _search(query: str) -> list:
    ctx = app()
    found: list = []
    seen: set[str] = set()

    queries = [query]
    if query.lstrip("-").isdigit():
        queries = [f"tg{query}", f"tg_{query}", query]

    for q in queries:
        try:
            data = await ctx.wdtt.list_users(q=q, limit=10)
        except Exception:
            continue

        for user in data.get("users") or []:
            if not isinstance(user, dict):
                continue
            user_id = str(user.get("id") or "")
            if user_id and user_id not in seen:
                seen.add(user_id)
                found.append(user)

    return found[:10]


@router.message(StateFilter(AdmUserStates.search), F.text)
async def h_users_search(message: Message, state: FSMContext):
    query = (message.text or "").strip()
    await state.clear()

    if not query or query.startswith("/"):
        return

    found = await _search(query)

    if not found:
        return await message.answer(
            f"❌ Ничего не найдено: <code>{esc(query)}</code>",
            reply_markup=adm_back_kb("adm:usr"),
        )

    if len(found) == 1:
        user_id = str(found[0].get("id") or "")
        text, kb = await profile_text(user_id)
        return await message.answer(text, reply_markup=kb)

    kb = InlineKeyboardBuilder()
    lines = []
    for user in found:
        user_id = str(user.get("id") or "")
        label = str(user.get("name") or user.get("comment") or user_id)[:30]
        used = human_bytes(user.get("traffic_used_bytes"))
        lines.append(f"{_status_dot(user)} <b>{esc(label)}</b> · {used}")
        kb.button(text=f"{_status_dot(user)} {label}"[:64],
                  callback_data=f"adm:usr:v:{user_id}")

    kb.button(text="⬅️ К списку", callback_data="adm:usr")
    kb.adjust(1)

    await message.answer(
        f"🔍 <b>Найдено: {len(found)}</b>\n\n" + "\n".join(lines),
        reply_markup=kb.as_markup(),
    )


@router.callback_query(F.data.startswith("adm:usr:v:"))
async def cb_user_profile(cb: CallbackQuery):
    if not cb.message:
        return await answer_or_alert(cb)

    user_id = cb.data.removeprefix("adm:usr:v:")
    text, kb = await profile_text(user_id)
    await safe_edit(cb.message, text, kb)
    await answer_or_alert(cb)


def _traffic_block(user: dict) -> str:
    bar, used, total, pct = traffic_bar(
        user.get("traffic_used_bytes"), user.get("total_gb")
    )
    if total == "∞":
        return f"📊 <b>{used}</b> · безлимит"
    return f"📊 <b>{used}</b> / {total} · <b>{pct}%</b>\n<code>{bar}</code>"


async def profile_text(user_id: str):
    ctx = app()

    try:
        user = await ctx.wdtt.get_user(user_id, force=True)
    except Exception as e:
        return (
            f"❌ Не удалось получить пользователя:\n"
            f"<code>{esc(str(e)[:200])}</code>",
            adm_back_kb("adm:usr"),
        )

    if not user:
        return f"❌ Пользователь {esc(user_id)} не найден.", adm_back_kb("adm:usr")

    status, _key = user_status(user)
    password = user.get("password") or "—"
    comment = user.get("comment") or "—"
    sub_url = user.get("subscription_url") or user.get("sub_url") or ""
    tg_id = panel_tg_id(user)

    settings = await ctx.db.get_settings()
    include_main = settings.get("include_main_node", False)
    try:
        links = extract_node_links(user, await ctx.wdtt.list_nodes(), include_main=include_main)
    except Exception:
        links = extract_node_links(user, include_main=include_main)

    lines = [
        f"👤 <b>{esc(user.get('name') or user_id)}</b>",
        "",
        f"ID: <code>{esc(user.get('id') or user_id)}</code>",
        f"Пароль: <code>{esc(password)}</code>",
        f"Комментарий: {esc(comment)}",
        "",
        _traffic_block(user),
        "",
        f"📅 {expires_text(user.get('expires_at'))} · "
        f"👥 {user.get('devices_bound') or 0}/{user.get('max_devices') or '?'}",
        f"Статус: <b>{status}</b>",
        f"🌍 Нод: <b>{len(links)}</b>",
    ]

    if tg_id:
        lines.append(f"💬 Telegram: <code>{tg_id}</code>")

    if sub_url:
        lines.append(f"\n<code>{esc(sub_url)}</code>")

    kb = InlineKeyboardBuilder()
    kb.row(copy_btn("📋 Пароль", password))
    kb.button(text="📈 Лимит ГБ", callback_data=f"adm:ua:{user_id}:gb")
    kb.button(text="📱 Устройства", callback_data=f"adm:ua:{user_id}:dev")
    kb.button(text="📅 Срок", callback_data=f"adm:ua:{user_id}:exp")
    kb.button(text="♻️ Сбросить трафик", callback_data=f"adm:ua:{user_id}:rst")

    if user.get("active") is False or user.get("is_deactivated"):
        kb.button(text="✅ Разблокировать", callback_data=f"adm:ua:{user_id}:ub")
    else:
        kb.button(text="🚫 Заблокировать", callback_data=f"adm:ua:{user_id}:b")

    if tg_id:
        kb.button(text="✉️ Написать", callback_data=f"adm:ua:{user_id}:msg")

    kb.button(text="🗑 Удалить", callback_data=f"adm:ua:{user_id}:del1")
    kb.button(text="🔄 Обновить", callback_data=f"adm:usr:v:{user_id}")
    kb.button(text="⬅️ К списку", callback_data="adm:usr")
    kb.adjust(1)

    return "\n".join(lines), kb.as_markup()


def _parse_action(data: str) -> tuple[str, str]:
    rest = data.removeprefix("adm:ua:")
    user_id, _, action = rest.rpartition(":")
    return user_id, action


PROMPTS = {
    "gb": "📈 <b>Лимит трафика</b>\n\n"
          "Пришли ГБ (0 — безлимит):",
    "dev": "📱 <b>Лимит устройств</b>\n\n"
           "Пришли число устройств:",
    "exp": "📅 <b>Срок действия</b>\n\n"
           "Пришли дней (0 — бессрочно):",
    "msg": "✉️ <b>Сообщение</b>\n\n"
           "Пришли текст — он уйдёт пользователю в Telegram.",
}


@router.callback_query(F.data.startswith("adm:ua:"))
async def cb_user_action(cb: CallbackQuery, state: FSMContext):
    if not cb.message:
        return await answer_or_alert(cb)

    user_id, action = _parse_action(cb.data)
    ctx = app()

    if action in PROMPTS:
        tg_id = None
        try:
            user = await ctx.wdtt.get_user(user_id, force=True)
            tg_id = panel_tg_id(user)
        except Exception:
            user = {}

        if action == "msg" and not tg_id:
            return await answer_or_alert(
                cb, "У пользователя нет Telegram ID в комментарии", True
            )

        await state.set_state(AdmUserStates.wait_input)
        await state.update_data(target=user_id, action=action, tg_id=tg_id)

        kb = InlineKeyboardBuilder()
        kb.button(text="❌ Отмена", callback_data=f"adm:usr:v:{user_id}")
        await safe_edit(cb.message, PROMPTS[action], kb.as_markup())
        return await answer_or_alert(cb, "Жду ввод")

    if action in ("b", "ub"):
        blocking = action == "b"
        try:
            if blocking:
                await ctx.wdtt.block_user(user_id)
            else:
                await ctx.wdtt.activate_user(user_id)
            await ctx.db.log_event(
                cb.from_user.id, "admin",
                f"{'block' if blocking else 'unblock'} {user_id}",
            )
            await answer_or_alert(
                cb, "🚫 Заблокирован" if blocking else "✅ Разблокирован"
            )
        except Exception as e:
            await answer_or_alert(cb, f"Ошибка: {str(e)[:150]}", True)

        text, kb = await profile_text(user_id)
        await safe_edit(cb.message, text, kb)
        return

    if action == "rst":
        try:
            await ctx.wdtt.reset_traffic(user_id)
            await ctx.db.log_event(
                cb.from_user.id, "admin", f"traffic reset {user_id}"
            )
            await answer_or_alert(cb, "♻️ Трафик сброшен")
        except Exception as e:
            return await answer_or_alert(cb, f"Ошибка: {str(e)[:150]}", True)

        text, kb = await profile_text(user_id)
        await safe_edit(cb.message, text, kb)
        return

    if action == "del1":
        await safe_edit(
            cb.message,
            f"🗑 <b>Удалить пользователя</b>\n\n<code>{esc(user_id)}</code>\n\n"
            "Удаление безвозвратное.",
            yes_no_kb(
                "", f"adm:ua:{user_id}:del2", f"adm:usr:v:{user_id}",
                "🗑 Удалить", "❌ Отмена",
            ),
        )
        return await answer_or_alert(cb)

    if action == "del2":
        try:
            await ctx.wdtt.delete_user(user_id)
            await ctx.db.users.update_one(
                {"panel_id": user_id},
                {
                    "$set": {"registered": False},
                    "$unset": {"panel_id": "", "panel_password": "",
                               "panel_link": "", "panel_snapshot_at": ""},
                },
            )
            await ctx.db.log_event(
                cb.from_user.id, "admin", f"user deleted {user_id}"
            )
            await answer_or_alert(cb, "🗑 Удалено")
        except Exception as e:
            await answer_or_alert(cb, f"Ошибка: {str(e)[:150]}", True)

        try:
            data = await ctx.wdtt.list_users(limit=PAGE_SIZE)
            users = data.get("users") or []
        except Exception:
            users = []

        await safe_edit(
            cb.message,
            "🗑 Пользователь удалён.",
            _users_kb(0, 1, users),
        )
        return

    await answer_or_alert(cb, "Неизвестное действие")


@router.callback_query(F.data == "adm:cancel")
async def cb_cancel_input(cb: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    await state.clear()

    user_id = data.get("target")
    if user_id:
        text, kb = await profile_text(user_id)
    else:
        text, kb = "🛠 <b>Админка</b>", adm_back_kb("adm")

    if cb.message:
        await safe_edit(cb.message, text, kb)
    await answer_or_alert(cb, "Отменено")


@router.message(StateFilter(AdmUserStates.wait_input), F.text)
async def h_wait_input(message: Message, state: FSMContext):
    data = await state.get_data()
    target = data.get("target")
    action = data.get("action")
    tg_id = data.get("tg_id")
    raw = (message.text or "").strip()
    await state.clear()

    if not target or not action:
        return

    ctx = app()

    if action == "msg":
        if not tg_id:
            return await message.answer("❌ Нет Telegram ID.")
        try:
            await message.bot.send_message(tg_id, raw)
            await ctx.db.log_event(tg_id, "admin_dm", raw[:80])
            await message.answer("✅ Сообщение отправлено.")
        except Exception as e:
            await message.answer(f"❌ Не удалось отправить: {str(e)[:150]}")
        return

    if not raw.lstrip("-").isdigit():
        return await message.answer("❌ Нужно целое число.")

    value = max(0, int(raw))

    try:
        if action == "gb":
            await ctx.wdtt.update_user(target, total_gb=value)
            await ctx.db.log_event(target, "limit_gb_changed", str(value))
            text = f"✅ Лимит трафика: {value or '∞'} ГБ"

        elif action == "dev":
            await ctx.wdtt.update_user(target, max_devices=max(1, value))
            await ctx.db.log_event(target, "limit_devices_changed", str(value))
            text = f"✅ Устройств: {max(1, value)}"

        elif action == "exp":
            expires_at = int(time.time()) + value * 86400 if value > 0 else 0
            await ctx.wdtt.update_user(target, expires_at=expires_at)
            await ctx.db.log_event(target, "expires_changed", str(value))
            text = f"✅ Срок: {value} дн." if value else "✅ Срок: бессрочно"

        else:
            text = "✅ Сохранено"

        await message.answer(text)
    except Exception as e:
        await message.answer(f"❌ Ошибка панели: {str(e)[:200]}")
