# -*- coding: utf-8 -*-
"""Админка: настройки — регистрация, слоты, лимиты, соглашение, ссылки приложений."""
import logging

from aiogram import F, Router
from aiogram.filters import StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message

from ...context import app
from ...keyboards import adm_back_kb
from ...texts import esc
from ...utils import answer_or_alert, extract_url, safe_edit

log = logging.getLogger(__name__)
router = Router(name="adm-settings")


class AdmSetStates(StatesGroup):
    wait_int = State()      # слоты/лимиты/период
    wait_agreement = State()
    wait_app_links = State()


INT_FIELDS = {
    "slots": "slots_total",
    "gb": "default_total_gb",
    "dev": "default_max_devices",
    "reset": "reset_period_days",
}


def _reg_status(s: dict, ok: bool, left: int) -> str:
    if ok:
        return "🟢 открыта" + ("" if left == -1 else f" ({left} мест осталось)")
    return "🔴 закрыта (нет мест)"


@router.callback_query(F.data == "adm:set")
async def cb_settings(cb: CallbackQuery):
    if not cb.message:
        return await answer_or_alert(cb)
    ctx = app()
    s = await ctx.db.get_settings()
    ok, left = await ctx.db.slots_available(s)
    links_preview = "\n".join(
        f"  • {esc(l.get('label'))} → {esc(l.get('url')[:50])}"
        for l in s["app_links"]) or "  • пусто"
    agree = s["agreement_text"]
    text = (
        "⚙️ <b>Настройки</b>\n\n"
        f"🎟 Регистрация: {_reg_status(s, ok, left)}\n"
        f"• Регистрация включена: {'да' if s['registration_open'] else 'НЕТ'}\n"
        f"• Всего слотов: <b>{s['slots_total'] or '∞'}</b>\n"
        f"📦 Лимит трафика новых подписок: <b>{s['default_total_gb'] or '∞'} GB</b>\n"
        f"📱 Устройств на подписку: <b>{s['default_max_devices']}</b>\n"
        f"♻️ Авто-сброс трафика раз "
        f"<b>{s['reset_period_days'] or '—'}</b> дн.\n"
        f"📖 Соглашение: {len(agree)} символов\n"
        f"📥 Ссылки приложений:\n{links_preview}\n"
    )
    from aiogram.utils.keyboard import InlineKeyboardBuilder
    kb = InlineKeyboardBuilder()
    kb.button(text=("⛔️ Выключить регистрацию" if s["registration_open"]
                    else "✅ Включить регистрацию"),
              callback_data="adm:set:tgl")
    kb.button(text="🎯 Слотов всего", callback_data="adm:set:i:slots")
    kb.button(text="📦 Лимит GB", callback_data="adm:set:i:gb")
    kb.button(text="📱 Лимит устройств", callback_data="adm:set:i:dev")
    kb.button(text="♻️ Период сброса (дн.)", callback_data="adm:set:i:reset")
    kb.button(text="📖 Редактировать соглашение", callback_data="adm:set:agr")
    kb.button(text="📥 Изменить ссылки приложений", callback_data="adm:set:apps")
    kb.button(text="⬅️ В админку", callback_data="adm")
    kb.adjust(1)
    await safe_edit(cb.message, text, kb.as_markup())
    await answer_or_alert(cb)


@router.callback_query(F.data == "adm:set:tgl")
async def cb_toggle_reg(cb: CallbackQuery):
    ctx = app()
    s = await ctx.db.get_settings()
    new_val = not s["registration_open"]
    await ctx.db.save_settings({"registration_open": new_val})
    await ctx.db.log_event(cb.from_user.id, "admin",
                           f"registration {'on' if new_val else 'off'}")
    await answer_or_alert(cb, "Регистрация включена ✅" if new_val
                          else "Регистрация выключена ⛔️ (режим «нет мест»)")
    await cb_settings(cb)


@router.callback_query(F.data.startswith("adm:set:i:"))
async def cb_set_int(cb: CallbackQuery, state: FSMContext):
    field = cb.data.split(":")[-1]
    await state.set_state(AdmSetStates.wait_int)
    await state.update_data(field=field)
    prompts = {
        "slots": "🎯 Сколько всего слотов? (0 — без ограничения)",
        "gb": "📦 Лимит трафика для новых подписок в GB (0 — безлимит):",
        "dev": "📱 Сколько устройств на одну подписку?",
        "reset": "♻️ Через сколько дней автоматически сбрасывать счётчик трафика? (0 — никогда)",
    }
    if cb.message:
        from aiogram.utils.keyboard import InlineKeyboardBuilder
        kb = InlineKeyboardBuilder()
        kb.button(text="❌ Отмена", callback_data="adm:cancel-set")
        try:
            await cb.message.edit_text(prompts[field],
                                       reply_markup=kb.as_markup())
            await answer_or_alert(cb)
        except Exception:  # noqa: BLE001
            pass


@router.callback_query(F.data == "adm:cancel-set")
async def cb_cancel_set(cb: CallbackQuery, state: FSMContext):
    await state.clear()
    await cb_settings(cb)


@router.message(StateFilter(AdmSetStates.wait_int), F.text)
async def h_set_int(message: Message, state: FSMContext):
    data = await state.get_data()
    await state.clear()
    field = INT_FIELDS.get(data.get("field"))
    raw = (message.text or "").strip()
    if not raw.lstrip("-").isdigit():
        await message.answer("❌ Нужно целое число. Повторите через настройки.")
        return
    val = max(int(raw), 0)
    ctx = app()
    await ctx.db.save_settings({field: val})
    await ctx.db.log_event(message.from_user.id, "admin",
                           f"{field}={val}")
    await message.answer(f"✅ Сохранено: {field} = {val}")


@router.callback_query(F.data == "adm:set:agr")
async def cb_set_agreement(cb: CallbackQuery, state: FSMContext):
    await state.set_state(AdmSetStates.wait_agreement)
    if cb.message:
        ctx = app()
        s = await ctx.db.get_settings()
        cur = s["agreement_text"]
        try:
            await cb.message.edit_text(
                "📖 <b>Текущее соглашение:</b>\n\n"
                f"{cur[:2500]}\n\n"
                "⌨️ Пришлите новый текст соглашения (HTML разрешён, "
                "до 3500 символов):",
                reply_markup=adm_back_kb("adm"))
            await answer_or_alert(cb)
        except Exception:  # noqa: BLE001
            await answer_or_alert(cb, "Пришлите новый текст соглашения", True)


@router.message(StateFilter(AdmSetStates.wait_agreement), F.text)
async def h_set_agreement(message: Message, state: FSMContext):
    text = (message.text or "").strip()
    await state.clear()
    if len(text) < 20:
        await message.answer("❌ Текст слишком короткий.")
        return
    ctx = app()
    await ctx.db.save_settings({"agreement_text": text[:3500]})
    await ctx.db.log_event(message.from_user.id, "admin", "agreement updated")
    await message.answer("✅ Соглашение обновлено.")


@router.callback_query(F.data == "adm:set:apps")
async def cb_set_apps(cb: CallbackQuery, state: FSMContext):
    await state.set_state(AdmSetStates.wait_app_links)
    if cb.message:
        try:
            await cb.message.edit_text(
                "📥 <b>Ссылки приложений</b>\n\n"
                "⌨️ Пришлите список кнопок, каждая строка:\n"
                "<code>Метка | https://ссылка</code>\n\n"
                "Например:\n<code>🤖 Android — WDTT | https://github.com/ildarmaga/wdtt/releases</code>\n\n"
                "Новый список заменит текущий.",
                reply_markup=adm_back_kb("adm"))
            await answer_or_alert(cb)
        except Exception:  # noqa: BLE001
            pass


@router.message(StateFilter(AdmSetStates.wait_app_links), F.text)
async def h_set_apps(message: Message, state: FSMContext):
    lines = [l.strip() for l in (message.text or "").splitlines()
             if l.strip() and "|" in l]
    links = []
    for l in lines:
        label, _, url = l.partition("|")
        url = extract_url(url) or ""
        label = label.strip()[:60]
        if label and url:
            links.append({"label": label, "url": url})
    await state.clear()
    if not links:
        await message.answer("❌ Не удалось разобрать. Формат строки: "
                             "Метка | ссылка")
        return
    ctx = app()
    await ctx.db.save_settings({"app_links": links})
    await ctx.db.log_event(message.from_user.id, "admin",
                           f"app_links set ({len(links)})")
    await message.answer(f"✅ Сохранено кнопок приложений: {len(links)}")
