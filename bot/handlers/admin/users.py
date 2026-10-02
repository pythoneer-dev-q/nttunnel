# -*- coding: utf-8 -*-
"""Админка: пользователи — список, профили, блокировка, лимиты, сброс трафика."""
import logging

from aiogram import F, Router
from aiogram.filters import StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message

from ...context import app
from ...keyboards import adm_back_kb
from ...texts import esc
from ...utils import (answer_or_alert, build_page_kb, fmt_dt,
                      safe_edit)

log = logging.getLogger(__name__)
router = Router(name="adm-users")

PAGE_SIZE = 8


class AdmUserStates(StatesGroup):
    wait_input = State()


def ua_cb(tg_id: int, act: str) -> str:
    return f"adm:ua:{tg_id}:{act}"


def parse_ua(data: str) -> tuple[int, str]:
    rest = data.removeprefix("adm:ua:")
    tg_id_s, act = rest.split(":", 1)
    return int(tg_id_s), act


@router.callback_query(F.data == "adm:usr")
@router.callback_query(F.data.startswith("adm:usr:p"))
async def cb_users_list(cb: CallbackQuery):
    if not cb.message:
        return await answer_or_alert(cb)
    ctx = app()

    rest = cb.data.removeprefix("adm:usr").removeprefix(":p")
    page = int(rest) if rest.isdigit() else 0

    # Пагинация на стороне MongoDB: не тянем всех пользователей в память.
    total = await ctx.db.users.count_documents({})
    pages = max((total + PAGE_SIZE - 1) // PAGE_SIZE, 1)
    page = min(max(page, 0), pages - 1)

    docs = [d async for d in ctx.db.users.find(
        {},
        {"tg_id": 1, "username": 1, "first_name": 1,
         "blocked": 1, "registered": 1},
    ).sort("created_at", -1).skip(page * PAGE_SIZE).limit(PAGE_SIZE)]

    lines = []
    items = []
    for u in docs:
        marks = ("🚫" if u.get("blocked") else "") + \
                ("🔐" if u.get("registered") else "")
        label = (u.get("username") or u.get("first_name") or
                 f"id{u['tg_id']}")[:30]
        lines.append(f"{marks} <b>{esc(label)}</b> · {u['tg_id']}")
        items.append((f"👤 {label} · {u['tg_id']}", f"adm:usr:v{u['tg_id']}"))
    text = (f"👥 <b>Пользователи</b> — всего {total}\n\n"
            + ("\n".join(lines) if lines else "Пусто."))
    await safe_edit(cb.message, text,
                    build_page_kb("adm:usr", page, pages, items))
    await answer_or_alert(cb)


@router.callback_query(F.data.startswith("adm:usr:v"))
async def cb_user_profile(cb: CallbackQuery):
    if not cb.message:
        return await answer_or_alert(cb)
    tg_id = int(cb.data.removeprefix("adm:usr:v"))
    text, kb = await profile_text(tg_id)
    await safe_edit(cb.message, text, kb)
    await answer_or_alert(cb)


async def profile_text(tg_id: int):
    ctx = app()
    u = await ctx.db.get_user(tg_id)
    if not u:
        return f"❌ Пользователь {tg_id} не найден.", adm_back_kb("adm:usr")

    live = None
    pwd = u.get("wdtt_password")
    if u.get("registered") and pwd:
        live = await ctx.wdtt.find_user(pwd, force=True)

    name = u.get("full_name") or ""
    username = "@" + u["username"] if u.get("username") else "—"
    line = (
        "👤 <b>Профиль пользователя</b>\n\n"
        f"🆔 ID: <code>{u['tg_id']}</code>\n"
        f"📝 Имя: <b>{esc(name)}</b>\n"
        f"🔗 Username: <b>{username}</b>\n"
        f"🌐 Язык: {u.get('language_code') or '—'} · "
        f"Premium: {'💎' if u.get('is_premium') else '—'}\n"
        f"📅 В боте с: {fmt_dt(u.get('created_at'))}\n"
        f"👀 Активность: {fmt_dt(u.get('last_seen'))}\n"
        f"💬 Сообщений: {u.get('messages_count', 0)} · "
        f"нажатий: {u.get('callbacks_count', 0)}\n"
        f"🔗 Источник /start: <code>{esc(u.get('start_payload') or '—')}</code>\n"
    )
    status = []
    if u.get("blocked"):
        status.append("🚫 заблокирован в боте")
    if not u.get("registered"):
        status.append("❌ подписка не создана")
    if live is not None and not live.get("active", True):
        status.append("🔴 подписка деактивирована в панели")
    if status:
        line += "\n⚠️ " + "; ".join(status) + "\n"

    if u.get("registered"):
        used = (live or {}).get("traffic_used_fmt", "?")
        gb = (live or {}).get("total_gb", u.get("sub_total_gb", 0))
        dev = (live or {}).get("devices_bound", "?")
        maxd = (live or {}).get("max_devices", u.get("sub_max_devices", "?"))
        line += (
            "\n🔌 <b>Подключение WDTT</b>\n"
            f"🔑 Пароль/ID: <code>{esc(pwd)}</code>\n"
            f"📊 Трафик: <b>{used}</b> из <b>{gb if gb else '∞'}</b>\n"
            f"📱 Устройств: <b>{dev}</b>/<b>{maxd}</b>\n"
            f"🟢 Онлайн: {'да' if (live or {}).get('online') else 'нет'}\n"
            f"🔑 Ключ: <code>{esc((live or {}).get('link') or u.get('wdtt_link', ''))}</code>\n"
        )

    from aiogram.utils.keyboard import InlineKeyboardBuilder
    kb = InlineKeyboardBuilder()
    if u.get("registered"):
        kb.button(text="📈 Лимит трафика (GB)", callback_data=ua_cb(tg_id, "gb"))
        kb.button(text="📱 Лимит устройств", callback_data=ua_cb(tg_id, "dev"))
        kb.button(text="♻️ Сбросить трафик", callback_data=ua_cb(tg_id, "rst"))
        kb.button(text="🗑 Удалить подписку", callback_data=ua_cb(tg_id, "del1"))
    block_act, block_lbl = (("ub", "✅ Разблокировать") if u.get("blocked")
                            else ("b", "🚫 Заблокировать"))
    kb.button(text=block_lbl, callback_data=ua_cb(tg_id, block_act))
    kb.button(text="✉️ Написать пользователю", callback_data=ua_cb(tg_id, "msg"))
    kb.button(text="🔄 Обновить", callback_data=f"adm:usr:v{tg_id}")
    kb.button(text="⬅️ К списку", callback_data="adm:usr")
    kb.adjust(1)
    return line, kb.as_markup()


@router.callback_query(F.data.startswith("adm:ua:"))
async def cb_user_action(cb: CallbackQuery, state: FSMContext):
    if not cb.message:
        return await answer_or_alert(cb)
    ctx = app()
    tg_id, act = parse_ua(cb.data)
    u = await ctx.db.get_user(tg_id) or {}

    # ---- ввод через FSM (лимиты, сообщение)
    if act in ("gb", "dev", "msg"):
        prompts = {
            "gb": f"📈 Введите лимит трафика для <b>{tg_id}</b> в GB (0 — безлимит):",
            "dev": f"📱 Введите лимит устройств для <b>{tg_id}</b> (число):",
            "msg": f"✉️ Введите текст сообщения для <b>{esc(u.get('full_name') or tg_id)}</b>:",
        }
        await state.set_state(AdmUserStates.wait_input)
        await state.update_data(target=tg_id, action=act)
        from aiogram.utils.keyboard import InlineKeyboardBuilder
        kb = InlineKeyboardBuilder()
        kb.button(text="❌ Отмена", callback_data="adm:cancel")
        try:
            await cb.message.edit_text(prompts[act], reply_markup=kb.as_markup())
            await answer_or_alert(cb, "Жду ввод ⌨️")
        except Exception:  # noqa: BLE001
            await answer_or_alert(
                cb, prompts[act].replace("<b>", "").replace("</b>", ""), True)
        return

    # ---- блокировка / разблокировка
    if act in ("b", "ub"):
        blocking = act == "b"
        try:
            if u.get("registered") and u.get("wdtt_password"):
                await ctx.wdtt.update_user(u["wdtt_password"],
                                           active=not blocking)
        except Exception as e:  # noqa: BLE001
            log.warning("wdtt active toggle failed: %s", e)
        await ctx.db.users.update_one({"tg_id": tg_id},
                                      {"$set": {"blocked": blocking}})
        await ctx.db.log_event(tg_id,
                               "blocked" if blocking else "unblocked",
                               "by admin")
        text, kb = await profile_text(tg_id)
        await safe_edit(cb.message, text, kb)
        await answer_or_alert(
            cb, "🚫 Заблокирован" if blocking else "✅ Разблокирован")
        return

    # ---- сброс трафика
    if act == "rst":
        try:
            await ctx.wdtt.reset_traffic(u["wdtt_password"])
            await ctx.db.log_event(tg_id, "traffic_reset", "by admin")
            await answer_or_alert(cb, "♻️ Трафик сброшен")
        except Exception as e:  # noqa: BLE001
            await answer_or_alert(cb, f"Ошибка: {str(e)[:150]}", True)
            return
        text, kb = await profile_text(tg_id)
        await safe_edit(cb.message, text, kb)
        return

    # ---- удаление подписки (два шага)
    if act == "del1":
        from ...utils import yes_no_kb
        await safe_edit(
            cb.message,
            f"🗑 <b>Удалить подписку</b> пользователя {tg_id}?\n\n"
            "Пользователь будет удалён из панели WDTT безвозвратно.",
            yes_no_kb(None, ua_cb(tg_id, "del2"), f"adm:usr:v{tg_id}",
                      "🗑 Да, удалить", "❌ Отмена"))
        await answer_or_alert(cb)
        return

    if act == "del2":
        try:
            if u.get("wdtt_password"):
                await ctx.wdtt.delete_user(u["wdtt_password"])
        except Exception as e:  # noqa: BLE001
            log.warning("delete wdtt user: %s", e)
        await ctx.db.users.update_one(
            {"tg_id": tg_id},
            {"$set": {"registered": False},
             "$unset": {"wdtt_password": "", "wdtt_link": "",
                        "sub_total_gb": "", "sub_max_devices": ""}})
        await ctx.db.log_event(tg_id, "subscription_deleted", "by admin")
        text, kb = await profile_text(tg_id)
        await safe_edit(cb.message, text, kb)
        await answer_or_alert(cb, "🗑 Удалено")
        return

    await answer_or_alert(cb, "Неизвестное действие")


@router.callback_query(F.data == "adm:cancel")
async def cb_cancel_input(cb: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    await state.clear()
    tg_id = data.get("target")
    if tg_id:
        text, kb = await profile_text(tg_id)
    else:
        text, kb = "🛠 <b>Админ-панель</b>", adm_root_kb()
    if cb.message:
        await safe_edit(cb.message, text, kb)
    await answer_or_alert(cb, "Отменено")


@router.message(StateFilter(AdmUserStates.wait_input), F.text)
async def h_wait_input(message: Message, state: FSMContext):
    data = await state.get_data()
    target, action = data.get("target"), data.get("action")
    raw = (message.text or "").strip()
    await state.clear()

    if action == "msg":
        try:
            await message.bot.send_message(target, raw)
            await message.answer("✅ Сообщение отправлено.")
            await app().db.log_event(target, "admin_dm", raw[:80])
        except Exception as e:  # noqa: BLE001
            await message.answer(f"❌ Не удалось отправить: {str(e)[:150]}")
        return

    if not raw.lstrip("-").isdigit():
        await message.answer("❌ Нужны цифры. Попробуйте снова через профиль.")
        return
    val = int(raw)
    ctx = app()
    u = await ctx.db.get_user(target) or {}
    try:
        if action == "gb":
            await ctx.wdtt.update_user(u["wdtt_password"], total_gb=val)
            await ctx.db.users.update_one({"tg_id": target},
                                          {"$set": {"sub_total_gb": val}})
            await ctx.db.log_event(target, "limit_gb_changed", str(val))
            await message.answer(f"✅ Лимит трафика {target} → {val} GB")
        elif action == "dev":
            await ctx.wdtt.update_user(u["wdtt_password"], max_devices=val)
            await ctx.db.users.update_one({"tg_id": target},
                                          {"$set": {"sub_max_devices": val}})
            await ctx.db.log_event(target, "limit_devices_changed", str(val))
            await message.answer(f"✅ Лимит устройств {target} → {val}")
    except Exception as e:  # noqa: BLE001
        await message.answer(f"❌ Ошибка панели: {str(e)[:200]}")


