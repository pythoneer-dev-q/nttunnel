# -*- coding: utf-8 -*-
"""Админка: статистика, сервер, кластерные ноды."""
from __future__ import annotations

import logging
from datetime import datetime, timezone

from aiogram import F, Router
from aiogram.filters import Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message

from ...context import app
from ...keyboards import adm_back_kb, adm_root_kb, nodes_kb, srv_kb
from ...texts import esc
from ...utils import answer_or_alert, safe_edit, yes_no_kb
from ...wdtt import human_bytes, node_online

log = logging.getLogger(__name__)
router = Router(name="adm-dashboard")

NODES_PAGE_SIZE = 6


class AdmNodeStates(StatesGroup):
    wait_node = State()


def _truthy(value) -> bool:
    """Приводит «строковые» булевы значения панели к bool."""
    if isinstance(value, bool):
        return value
    if value is None:
        return False
    if isinstance(value, (int, float)):
        return value != 0
    if isinstance(value, str):
        return value.strip().lower() not in (
            "", "0", "false", "no", "off", "none", "null", "inactive",
            "disabled", "stopped", "down",
        )
    if isinstance(value, dict):
        for key in ("active", "enabled", "online", "running", "ok", "status"):
            if key in value:
                return _truthy(value[key])
    return bool(value)


def _dot(flag) -> str:
    return "🟢" if _truthy(flag) else "⚪"


def admin_root_text() -> str:
    return (
        "🛠 <b>Админка</b>\n\n"
        "• 👥 Пользователи — трафик, лимиты, блокировки\n"
        "• 🌍 Ноды — кластер, добавление и проверка\n"
        "• 📊 Статистика — бот и панель\n"
        "• ⚙️ Настройки — лимиты, соглашение, рефералка"
    )


def _deep_get(data, *names, default=None):
    """Ищет значение по ключам на любом уровне вложенности."""
    if isinstance(data, dict):
        for name in names:
            if name in data and data[name] not in (None, ""):
                return data[name]
        for value in data.values():
            found = _deep_get(value, *names, default=None)
            if found is not None:
                return found
    elif isinstance(data, list):
        for item in data:
            found = _deep_get(item, *names, default=None)
            if found is not None:
                return found
    return default


def _status_traffic(status: dict) -> int:
    for key in (
        "traffic_total_bytes", "total_traffic_bytes", "traffic_bytes",
        "total_bytes", "traffic_total", "total_traffic",
    ):
        value = _deep_get(status, key)
        if isinstance(value, (int, float)):
            return int(value)

    traffic = _deep_get(status, "traffic")
    if isinstance(traffic, (int, float)):
        return int(traffic)
    if isinstance(traffic, dict):
        up = _deep_get(traffic, "up", "up_bytes", "upload") or 0
        down = _deep_get(traffic, "down", "down_bytes", "download") or 0
        try:
            return int(up) + int(down)
        except (TypeError, ValueError):
            pass
    return 0


def _panel_status_text(status: dict) -> str:
    if not status:
        return "🔌 Панель: <b>недоступна</b>"

    version = _deep_get(status, "version", "panel_version") or "?"
    uptime = _deep_get(status, "uptime", "uptime_seconds", "uptime_str") or "?"
    memory = _deep_get(status, "memory", "memory_usage", "ram", "mem")
    traffic = _status_traffic(status)

    services = []
    for label, keys in (
        ("dtls", ("dtls_active", "dtls", "wdtt_active")),
        ("raw", ("raw_active", "raw_udp", "raw")),
        ("xray", ("xray_active", "xray")),
    ):
        value = _deep_get(status, *keys)
        if value is not None:
            services.append(f"{label} {_dot(value)}")

    lines = [
        f"🔌 <b>Панель</b> · v{esc(version)}",
        f"⏱ Аптайм: {esc(uptime)}",
    ]
    if memory:
        lines.append(f"💾 RAM: {esc(memory)}")
    if services:
        lines.append(" ⚙️ " + " · ".join(services))
    if traffic:
        lines.append(f"📊 Трафик: <b>{human_bytes(traffic)}</b>")

    return "\n".join(lines)


@router.message(Command("godmode"))
async def cmd_godmode(message: Message):
    await message.answer(admin_root_text(), reply_markup=adm_root_kb())


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
    today = datetime.now(timezone.utc).replace(
        hour=0, minute=0, second=0, microsecond=0
    )
    new_today = await db.users.count_documents({"created_at": {"$gte": today}})

    settings = await db.get_settings()
    ok, left = await db.slots_available(settings)
    slots = "∞" if left == -1 else str(left)

    panel_line = "🔌 Панель: <b>недоступна</b>"
    nodes_line = ""
    panel_users = "?"

    try:
        status = await ctx.wdtt.status()
        panel_line = _panel_status_text(status)
    except Exception as e:
        panel_line = f"🔌 Панель: <b>недоступна</b>\n<code>{esc(str(e)[:120])}</code>"

    try:
        nodes = await ctx.wdtt.list_nodes(force=True)
        online = sum(1 for n in nodes if node_online(n))
        nodes_line = f"\n🌍 Ноды: <b>{online}/{len(nodes)}</b> онлайн"
    except Exception:
        nodes_line = "\n🌍 Ноды: <b>недоступны</b>"

    try:
        data = await ctx.wdtt.list_users(limit=1)
        panel_users = str(data.get("total", "?"))
    except Exception:
        pass

    text = (
        "📊 <b>Статистика</b>\n\n"
        f"👥 Бот: <b>{total}</b> · доступов: <b>{registered}</b>\n"
        f"🆕 Сегодня: <b>{new_today}</b> · 🚫 блок: <b>{blocked}</b>\n"
        f"🎟 Места: {'открыто' if ok else 'закрыто'} ({slots})\n"
        f"👤 Пользователей в панели: <b>{panel_users}</b>\n"
        f"{nodes_line}\n\n"
        f"{panel_line}"
    )

    await safe_edit(cb.message, text, adm_root_kb())
    await answer_or_alert(cb)


# ------------------------------------------------------------------ server


@router.callback_query(F.data == "adm:srv")
async def cb_server(cb: CallbackQuery):
    if not cb.message:
        return await answer_or_alert(cb)

    try:
        status = await app().wdtt.status()
        text = "🖥 <b>Сервер</b>\n\n" + _panel_status_text(status)
    except Exception as e:
        text = f"🔌 <b>Панель недоступна</b>\n\n<code>{esc(str(e)[:200])}</code>"

    await safe_edit(cb.message, text, srv_kb())
    await answer_or_alert(cb)


@router.callback_query(F.data == "adm:srv:rw")
async def cb_restart(cb: CallbackQuery):
    try:
        await app().wdtt.restart()
        await answer_or_alert(cb, "♻️ Служба перезапущена")
    except Exception as e:
        await answer_or_alert(cb, f"Ошибка: {str(e)[:150]}", True)


# ------------------------------------------------------------------- nodes


def _node_id(node: dict) -> str:
    return str(node.get("id") or node.get("name") or node.get("host") or "")


def _node_text(nodes: list) -> str:
    if not nodes:
        return "🌍 <b>Ноды</b>\n\nПока не добавлены."

    online = sum(1 for n in nodes if node_online(n))
    lines = [f"🌍 <b>Ноды</b> · {online}/{len(nodes)} онлайн", ""]

    for node in nodes:
        if not isinstance(node, dict):
            continue

        name = esc(node.get("name") or node.get("host") or "Нода")
        host = esc(node.get("host") or "—")
        dtls = node.get("dtls_port") or "?"
        wg = node.get("wg_port") or "?"
        flag = "🟢" if node_online(node) else "⚪"

        lines.append(f"{flag} <b>{name}</b>")
        lines.append(f"   <code>{host}</code> · {dtls}/{wg}")

    return "\n".join(lines)


async def _render_nodes(cb: CallbackQuery, page: int = 0):
    try:
        nodes = await app().wdtt.list_nodes(force=True)
    except Exception as e:
        await safe_edit(
            cb.message,
            f"🔌 Не удалось получить ноды:\n<code>{esc(str(e)[:200])}</code>",
            adm_back_kb("adm"),
        )
        return

    pages = max((len(nodes) + NODES_PAGE_SIZE - 1) // NODES_PAGE_SIZE, 1)
    page = min(max(page, 0), pages - 1)
    chunk = nodes[page * NODES_PAGE_SIZE:(page + 1) * NODES_PAGE_SIZE]

    header = _node_text(nodes).split("\n\n", 1)[0]
    body = _node_text(chunk).split("\n\n", 1)[-1]

    text = header + "\n\n" + (body if chunk else "Пусто.")
    await safe_edit(cb.message, text, nodes_kb(chunk, page, pages))


@router.callback_query(F.data == "adm:nodes")
@router.callback_query(F.data.startswith("adm:nodes:p"))
async def cb_nodes(cb: CallbackQuery, state: FSMContext | None = None):
    if state:
        await state.clear()
    if not cb.message:
        return await answer_or_alert(cb)

    rest = cb.data.removeprefix("adm:nodes").removeprefix(":p")
    page = int(rest) if rest.isdigit() else 0

    await _render_nodes(cb, page)
    await answer_or_alert(cb)


@router.callback_query(F.data.startswith("adm:nodes:v:"))
async def cb_node_view(cb: CallbackQuery):
    if not cb.message:
        return await answer_or_alert(cb)

    node_id = cb.data.removeprefix("adm:nodes:v:")

    try:
        nodes = await app().wdtt.list_nodes(force=True)
    except Exception as e:
        return await answer_or_alert(cb, f"Ошибка: {str(e)[:150]}", True)

    node = next((n for n in nodes if _node_id(n) == node_id), None)
    if not node:
        return await answer_or_alert(cb, "Нода не найдена", True)

    lines = [
        f"🌍 <b>{esc(node.get('name') or node.get('host') or node_id)}</b>",
        "",
        f"Host: <code>{esc(node.get('host') or '—')}</code>",
        f"DTLS: <b>{node.get('dtls_port') or '?'}</b> · "
        f"WG: <b>{node.get('wg_port') or '?'}</b> · "
        f"RAW: <b>{node.get('raw_port') or '?'}</b>",
        f"Статус: {'🟢 онлайн' if node_online(node) else '⚪ офлайн'}",
    ]

    if node.get("last_seen") or node.get("last_heartbeat"):
        lines.append(
            f"Heartbeat: {esc(node.get('last_seen') or node.get('last_heartbeat'))}"
        )
    if node.get("users") is not None:
        lines.append(f"Пользователей: <b>{node.get('users')}</b>")

    from aiogram.utils.keyboard import InlineKeyboardBuilder

    kb = InlineKeyboardBuilder()
    kb.button(text="📡 Проверить адрес", callback_data=f"adm:nodes:ping:{node_id}")
    kb.button(text="🗑 Удалить ноду", callback_data=f"adm:nodes:del1:{node_id}")
    kb.button(text="⬅️ К нодам", callback_data="adm:nodes")
    kb.adjust(1)

    await safe_edit(cb.message, "\n".join(lines), kb.as_markup())
    await answer_or_alert(cb)


@router.callback_query(F.data.startswith("adm:nodes:ping:"))
async def cb_node_ping(cb: CallbackQuery):
    node_id = cb.data.removeprefix("adm:nodes:ping:")

    try:
        result = await app().wdtt.ping_node(node_id)
        resolved = result.get("resolved")
        if resolved is True:
            text = "✅ Адрес разрешается"
        elif resolved is False:
            text = "❌ Адрес не разрешается"
        else:
            text = f"📡 {esc(str(result)[:120])}"
        await answer_or_alert(cb, text, True)
    except Exception as e:
        await answer_or_alert(cb, f"Ошибка: {str(e)[:150]}", True)


@router.callback_query(F.data.startswith("adm:nodes:del1:"))
async def cb_node_del_confirm(cb: CallbackQuery):
    if not cb.message:
        return await answer_or_alert(cb)

    node_id = cb.data.removeprefix("adm:nodes:del1:")

    await safe_edit(
        cb.message,
        f"🗑 <b>Удалить ноду</b>\n\n<code>{esc(node_id)}</code>\n\n"
        "Пользователи потеряют ссылки на эту ноду.",
        yes_no_kb(
            "", f"adm:nodes:del2:{node_id}", f"adm:nodes:v:{node_id}",
            "🗑 Удалить", "❌ Отмена",
        ),
    )
    await answer_or_alert(cb)


@router.callback_query(F.data.startswith("adm:nodes:del2:"))
async def cb_node_del(cb: CallbackQuery):
    if not cb.message:
        return await answer_or_alert(cb)

    node_id = cb.data.removeprefix("adm:nodes:del2:")

    try:
        await app().wdtt.delete_node(node_id)
        await app().db.log_event(cb.from_user.id, "admin", f"node deleted {node_id}")
        await answer_or_alert(cb, "🗑 Нода удалена")
    except Exception as e:
        await answer_or_alert(cb, f"Ошибка: {str(e)[:150]}", True)

    await _render_nodes(cb, 0)


@router.callback_query(F.data == "adm:nodes:add")
async def cb_node_add(cb: CallbackQuery, state: FSMContext):
    if not cb.message:
        return await answer_or_alert(cb)

    await state.set_state(AdmNodeStates.wait_node)
    await safe_edit(
        cb.message,
        "➕ <b>Новая нода</b>\n\n"
        "Пришли одной строкой:\n"
        "<code>Имя | host | dtls | wg | raw | main_password</code>\n\n"
        "Обязательны только первые два поля. Порты по умолчанию: "
        "56000 / 56001 / 56003. Пароль — из <code>VPN_PASSWORD</code>.\n\n"
        "Пример:\n"
        "<code>Helsinki-01 | fi.example.com</code>",
        reply_markup=adm_back_kb("adm:nodes"),
    )
    await answer_or_alert(cb, "Жду данные ноды")


@router.message(StateFilter(AdmNodeStates.wait_node), F.text)
async def h_node_add(message: Message, state: FSMContext):
    raw = (message.text or "").strip()
    await state.clear()

    parts = [p.strip() for p in raw.split("|")]
    if len(parts) < 2 or not parts[0] or not parts[1]:
        return await message.answer(
            "❌ Формат: <code>Имя | host | dtls | wg | raw | password</code>",
            reply_markup=adm_back_kb("adm:nodes"),
        )

    def _port(value: str, default: int) -> int:
        return int(value) if value.isdigit() else default

    cfg = app().cfg
    payload = {
        "name": parts[0][:60],
        "host": parts[1][:120],
        "dtls_port": _port(parts[2], 56000) if len(parts) > 2 else 56000,
        "wg_port": _port(parts[3], 56001) if len(parts) > 3 else 56001,
        "raw_port": _port(parts[4], 56003) if len(parts) > 4 else 56003,
        "main_password": (
            parts[5] if len(parts) > 5 and parts[5] else cfg.vpn_password
        ),
        "enabled": True,
    }

    try:
        await app().wdtt.add_node(payload)
        await app().db.log_event(message.from_user.id, "admin",
                                 f"node added {payload['name']}")
        await message.answer(
            f"✅ Нода <b>{esc(payload['name'])}</b> добавлена.",
            reply_markup=adm_back_kb("adm:nodes"),
        )
    except Exception as e:
        await message.answer(
            f"❌ Не удалось добавить:\n<code>{esc(str(e)[:250])}</code>",
            reply_markup=adm_back_kb("adm:nodes"),
        )
