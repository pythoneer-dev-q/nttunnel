# -*- coding: utf-8 -*-
"""Админка: корень, статистика, сервер/подключения."""
import logging
from datetime import datetime, timezone

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import CallbackQuery, Message

from ...context import app
from ...keyboards import adm_back_kb, adm_root_kb, srv_kb
from ...utils import answer_or_alert, safe_edit

log = logging.getLogger(__name__)
router = Router(name="adm-dashboard")


def fmt_bool(b) -> str:
    return "🟢" if b else "🔴"


def admin_root_text() -> str:
    return (
        "🛠 <b>Админ-панель NTTunnel</b>\n\n"
        "Выберите раздел:\n"
        "• 📊 Статистика — бото+панель\n"
        "• 👥 Пользователи — профили, блокировки, лимиты\n"
        "• 📤 Рассылка — сообщение всем пользователям\n"
        "• 📺 Каналы — обязательные подписки\n"
        "• 🎯 Реклама — кнопки в меню и кабинете\n"
        "• ⚙️ Настройки — регистрация, слоты, лимиты, тексты\n"
        "• 🔌 Сервер — inbound, сервисы WDTT"
    )


@router.message(Command("godmode"))
async def cmd_godmode(message: Message):
    """Вход в админку: /godmode (только для админов из .env)."""
    await message.answer(
        admin_root_text(),
        reply_markup=adm_root_kb(),
    )


@router.callback_query(F.data == "adm")
async def cb_admin_root(cb: CallbackQuery):
    if not cb.message:
        return await answer_or_alert(cb)
    await safe_edit(cb.message, admin_root_text(), adm_root_kb())
    await answer_or_alert(cb)


@router.callback_query(F.data == "adm:stat")
async def cb_stats(cb: CallbackQuery):
    if not cb.message:
        return await answer_or_alert(cb)
    ctx = app()
    db = ctx.db
    total = await db.users.count_documents({})
    registered = await db.registered_count()
    blocked = await db.users.count_documents({"blocked": True})
    today_start = datetime.now(timezone.utc).replace(hour=0, minute=0,
                                                     second=0, microsecond=0)
    new_today = await db.users.count_documents({"created_at": {"$gte": today_start}})
    msgs = [d async for d in db.users.aggregate([
        {"$group": {"_id": None,
                    "m": {"$sum": "$messages_count"},
                    "c": {"$sum": "$callbacks_count"}}}])]
    m = msgs[0] if msgs else {}
    settings = await db.get_settings()

    panel_line = ""
    try:
        st = await ctx.wdtt.status()
        ib = st.get("stats", {}) or {}
        panel_line = (
            f"\n🔌 <b>Панель WDTT:</b>\n"
            f"• wdtt.service: {fmt_bool(st.get('wdtt_active'))}   "
            f"xray: {fmt_bool(st.get('xray_active'))}\n"
            f"• IP: <code>{st.get('server_ip', '?')}</code>  "
            f"wdtt0: <code>{st.get('wdtt_iface', '?')}</code>\n"
            f"• Пользователей в панели: {st.get('users_count', '?')}"
        )
    except Exception as e:  # noqa: BLE001
        panel_line = f"\n🔌 Панель WDTT: <b>недоступна</b> ({str(e)[:80]})"

    ok, left = await db.slots_available(settings)
    slots_s = "∞" if left == -1 else f"{left} свободно"

    text = (
        "📊 <b>Статистика</b>\n\n"
        f"👥 Всего пользователей бота: <b>{total}</b>\n"
        f"🆕 Новых за сегодня: <b>{new_today}</b>\n"
        f"🔐 С подпиской: <b>{registered}</b>\n"
        f"🚫 Заблокировано: <b>{blocked}</b>\n"
        f"💬 Сообщений/нажатий: <b>{m.get('m', 0)}</b>/<b>{m.get('c', 0)}</b>\n"
        f"🎟 Регистрация: {'открыта' if ok else 'закрыта («нет мест»)'} "
        f"({slots_s})\n"
        f"{panel_line}"
    )
    kb = adm_root_kb()
    await safe_edit(cb.message, text, kb)
    await answer_or_alert(cb)


@router.callback_query(F.data == "adm:srv")
async def cb_server(cb: CallbackQuery):
    if not cb.message:
        return await answer_or_alert(cb)
    ctx = app()
    try:
        ib = await ctx.wdtt.get_inbound()
    except Exception as e:  # noqa: BLE001
        await safe_edit(
            cb.message,
            f"🔌 Панель недоступна: <code>{str(e)[:200]}</code>",
            adm_back_kb("adm"))
        # Без answer кружок загрузки на кнопке Telegram крутится вечно.
        await answer_or_alert(cb)
        return
    text = (
        "🔌 <b>Подключения / сервер</b>\n\n"
        f"🏷 Tag: <b>{ib.get('tag')}</b> · remark: {ib.get('remark')}\n"
        f"🌐 Host: <code>{ib.get('server_host') or ib.get('listen_host')}</code>\n"
        f"🎧 DTLS порт: <b>{ib.get('dtls_port')}</b> | WG: <b>{ib.get('wg_port')}</b>"
        f" | Client: <b>{ib.get('client_port')}</b>\n"
        f"📡 DNS: <code>{ib.get('dns')}</code>\n"
        f"👥 max_users: <b>{ib.get('max_users')}</b> | active: "
        f"<b>{ib.get('active_users', '?')}</b> | online: <b>{ib.get('online_users', '?')}</b>\n"
        f"⚙️ Сервис: {fmt_bool(ib.get('service_active'))} · iface: "
        f"{fmt_bool(ib.get('iface_up'))} · DTLS listening: "
        f"{fmt_bool(ib.get('dtls_listening'))}"
    )
    await safe_edit(cb.message, text, srv_kb())
    await answer_or_alert(cb)


@router.callback_query(F.data == "adm:srv:rw")
async def cb_restart_wdtt(cb: CallbackQuery):
    ctx = app()
    try:
        await ctx.wdtt.restart_wdtt()
        await answer_or_alert(cb, "♻️ WDTT перезапущен")
    except Exception as e:  # noqa: BLE001
        await answer_or_alert(cb, f"Ошибка: {str(e)[:150]}", True)


@router.callback_query(F.data == "adm:srv:rx")
async def cb_restart_xray(cb: CallbackQuery):
    ctx = app()
    try:
        await ctx.wdtt.restart_xray()
        await answer_or_alert(cb, "♻️ Xray перезапущен")
    except Exception as e:  # noqa: BLE001
        await answer_or_alert(cb, f"Ошибка: {str(e)[:150]}", True)

