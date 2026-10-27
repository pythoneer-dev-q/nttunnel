# -*- coding: utf-8 -*-
"""Админка: настройки бота и лимитов."""
from __future__ import annotations

import logging

from aiogram import F, Router
from aiogram.filters import StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message
from aiogram.utils.keyboard import InlineKeyboardBuilder

from ...context import app
from ...texts import esc
from ...utils import answer_or_alert, extract_url, safe_edit

log = logging.getLogger(__name__)
router = Router(name="adm-settings")


class AdmSetStates(StatesGroup):
    wait_int = State()
    wait_agreement = State()
    wait_app_links = State()


INT_FIELDS = {
    "slots": ("slots_total", 0),
    "gb": ("default_total_gb", 0),
    "dev": ("default_max_devices", 1),
    "exp": ("default_expires_days", 0),
    "reset": ("reset_period_days", 0),
    "bonus": ("referral_bonus_gb", 0),
    "nodes": ("nodes_copy_limit", 1),
}

PROMPTS = {
    "slots": "🎟 Всего мест (0 — без лимита):",
    "gb": "📦 Трафик новым доступам, ГБ (0 — безлимит):",
    "dev": "📱 Устройств на доступ:",
    "exp": "📅 Срок доступа, дней (0 — бессрочно):",
    "reset": "♻️ Авто-сброс трафика, дней (0 — выключен):",
    "bonus": "🚀 Реферальный бонус, ГБ (0 — выключен):",
    "nodes": "🌍 Нод кнопками копирования (остальные — в подписке):",
}


@router.callback_query(F.data == "adm:set")
async def cb_settings(cb: CallbackQuery):
    if not cb.message:
        return await answer_or_alert(cb)

    ctx = app()
    s = await ctx.db.get_settings()
    ok, left = await ctx.db.slots_available(s)

    reg = "🟢 открыта" if ok else "🔴 закрыта"
    if ok and left != -1:
        reg += f" · {left} мест"

    links = s.get("app_links") or []
    links_preview = "\n".join(
        f"   • {esc(l.get('label'))}" for l in links[:5]
    ) or "   • пусто"

    text = (
        "⚙️ <b>Настройки</b>\n\n"
        f"Регистрация: <b>{reg}</b>\n"
        f"Мест: <b>{s.get('slots_total') or '∞'}</b>\n"
        f"Трафик: <b>{s.get('default_total_gb') or '∞'} ГБ</b>\n"
        f"Устройств: <b>{s.get('default_max_devices')}</b>\n"
        f"Срок: <b>{s.get('default_expires_days') or '∞'} дн.</b>\n"
        f"Сброс трафика: <b>{s.get('reset_period_days') or '—'} дн.</b>\n"
        f"Рефералка: <b>+{s.get('referral_bonus_gb') or 0} ГБ</b>\n"
        f"Нод кнопками: <b>{s.get('nodes_copy_limit') or 5}</b>\n"
        f"Основная нода в прямых ссылках бота: <b>{'включена' if s.get('include_main_node') else 'выключена'}</b>\n"
        "Состав подписки задаётся в панели.\n"
        f"Соглашение: <b>{len(s.get('agreement_text') or '')}</b> симв.\n"
        f"Приложения:\n{links_preview}"
    )

    kb = InlineKeyboardBuilder()
    kb.button(
        text="⛔️ Закрыть регистрацию" if s.get("registration_open")
        else "✅ Открыть регистрацию",
        callback_data="adm:set:tgl",
    )
    kb.button(text="🎟 Места", callback_data="adm:set:i:slots")
    kb.button(text="📦 Трафик", callback_data="adm:set:i:gb")
    kb.button(text="📱 Устройства", callback_data="adm:set:i:dev")
    kb.button(text="📅 Срок", callback_data="adm:set:i:exp")
    kb.button(text="♻️ Сброс трафика", callback_data="adm:set:i:reset")
    kb.button(text="🚀 Реферальный бонус", callback_data="adm:set:i:bonus")
    kb.button(text="🌍 Нод кнопками", callback_data="adm:set:i:nodes")
    kb.button(text="🖥 Основная нода: " + ("вкл." if s.get("include_main_node") else "выкл."), callback_data="adm:set:mainnode")
    kb.button(text="📖 Соглашение", callback_data="adm:set:agr")
    kb.button(text="📥 Приложения", callback_data="adm:set:apps")
    kb.button(text="⬅️ В админку", callback_data="adm")
    kb.adjust(1, 1, 2, 2, 2, 1, 1, 1)

    await safe_edit(cb.message, text, kb.as_markup())
    await answer_or_alert(cb)


@router.callback_query(F.data == "adm:set:mainnode")
async def cb_toggle_main_node(cb: CallbackQuery):
    ctx = app()
    settings = await ctx.db.get_settings()
    enabled = not settings.get("include_main_node", False)
    await ctx.db.save_settings({"include_main_node": enabled})
    await ctx.db.log_event(cb.from_user.id, "admin", f"include_main_node={enabled}")
    await cb_settings(cb)


@router.callback_query(F.data == "adm:set:tgl")
async def cb_toggle_reg(cb: CallbackQuery):
    ctx = app()
    s = await ctx.db.get_settings()
    new_value = not s.get("registration_open", True)

    await ctx.db.save_settings({"registration_open": new_value})
    await ctx.db.log_event(
        cb.from_user.id, "admin",
        f"registration {'on' if new_value else 'off'}",
    )
    await answer_or_alert(
        cb, "Регистрация открыта ✅" if new_value
        else "Регистрация закрыта ⛔️"
    )
    await cb_settings(cb)


@router.callback_query(F.data.startswith("adm:set:i:"))
async def cb_set_int(cb: CallbackQuery, state: FSMContext):
    field = cb.data.split(":")[-1]

    if field not in PROMPTS:
        return await answer_or_alert(cb, "Неизвестное поле", True)

    await state.set_state(AdmSetStates.wait_int)
    await state.update_data(field=field)

    if cb.message:
        kb = InlineKeyboardBuilder()
        kb.button(text="❌ Отмена", callback_data="adm:cancel-set")
        await safe_edit(cb.message, PROMPTS[field], kb.as_markup())

    await answer_or_alert(cb)


@router.callback_query(F.data == "adm:cancel-set")
async def cb_cancel_set(cb: CallbackQuery, state: FSMContext):
    await state.clear()
    await cb_settings(cb)


@router.message(StateFilter(AdmSetStates.wait_int), F.text)
async def h_set_int(message: Message, state: FSMContext):
    data = await state.get_data()
    await state.clear()

    field = data.get("field")
    mapping = INT_FIELDS.get(field)
    raw = (message.text or "").strip()

    if not mapping or not raw.isdigit():
        return await message.answer(
            "❌ Нужно целое число. Открой настройки ещё раз."
        )

    key, minimum = mapping
    value = max(minimum, int(raw))

    await app().db.save_settings({key: value})
    await app().db.log_event(
        message.from_user.id, "admin", f"{key}={value}"
    )
    await message.answer(f"✅ Сохранено: <b>{key}</b> = {value}")


@router.callback_query(F.data == "adm:set:agr")
async def cb_set_agreement(cb: CallbackQuery, state: FSMContext):
    await state.set_state(AdmSetStates.wait_agreement)

    if cb.message:
        s = await app().db.get_settings()
        await safe_edit(
            cb.message,
            "📖 <b>Соглашение</b>\n\n"
            f"{esc((s.get('agreement_text') or '')[:2000])}\n\n"
            "Пришли новый текст (HTML разрешён, до 3500 символов).",
            None,
        )
    await answer_or_alert(cb, "Жду текст")


@router.message(StateFilter(AdmSetStates.wait_agreement), F.text)
async def h_set_agreement(message: Message, state: FSMContext):
    text = (message.text or "").strip()
    await state.clear()

    if len(text) < 20:
        return await message.answer("❌ Слишком коротко.")

    await app().db.save_settings({"agreement_text": text[:3500]})
    await app().db.log_event(
        message.from_user.id, "admin", "agreement updated"
    )
    await message.answer("✅ Соглашение обновлено.")


@router.callback_query(F.data == "adm:set:apps")
async def cb_set_apps(cb: CallbackQuery, state: FSMContext):
    await state.set_state(AdmSetStates.wait_app_links)

    if cb.message:
        await safe_edit(
            cb.message,
            "📥 <b>Ссылки приложений</b>\n\n"
            "Каждая строка:\n"
            "<code>Метка | https://ссылка</code>\n\n"
            "Новый список заменит текущий.",
            None,
        )
    await answer_or_alert(cb, "Жду список")


@router.message(StateFilter(AdmSetStates.wait_app_links), F.text)
async def h_set_apps(message: Message, state: FSMContext):
    lines = [
        line.strip() for line in (message.text or "").splitlines()
        if line.strip() and "|" in line
    ]
    links = []

    for line in lines:
        label, _, url = line.partition("|")
        url = extract_url(url) or ""
        label = label.strip()[:60]
        if label and url:
            links.append({"label": label, "url": url})

    await state.clear()

    if not links:
        return await message.answer(
            "❌ Не удалось разобрать. Формат: <code>Метка | ссылка</code>"
        )

    await app().db.save_settings({"app_links": links})
    await app().db.log_event(
        message.from_user.id, "admin", f"app_links set ({len(links)})"
    )
    await message.answer(f"✅ Сохранено кнопок: {len(links)}")
