# -*- coding: utf-8 -*-
"""Создание доступа, экраны «Мой доступ» и «Подписка»."""
from __future__ import annotations

import logging
import time
import hashlib
from datetime import timedelta

from aiogram import F, Router
from aiogram.filters import StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message

from ..context import app
from ..db import utcnow
from ..keyboards import (
    access_kb,
    agreement_kb,
    config_missing_kb,
    no_config_kb,
    panel_down_kb,
    show_link_kb,
    sub_kb,
    markup, btn,
)
from ..services import (
    access_links,
    as_int,
    fetch_live,
    node_limit,
    refresh_snapshot,
    public_subscription_url,
    _by_tg,
)
from ..texts import (
    access_text,
    agree_text,
    config_missing_text,
    no_config_text,
    no_slots_text,
    node_link_text,
    panel_down_text,
    sub_text,
    esc,
)
from ..utils import answer_or_alert, yes_no_kb, extract_vk_hash
from ..wdtt import WdttError, online_flag

log = logging.getLogger(__name__)
router = Router(name="access")
MAX_HASHES = 4


class RegStates(StatesGroup):
    hashes = State()


def _hash_kb(hashes: list[str]):
    rows = []
    for value in hashes:
        key = hashlib.sha256(value.encode()).hexdigest()[:16]
        preview = value if len(value) <= 20 else value[:17] + "…"
        rows.append([btn(f"🔎 {preview}", f"u:hash:view:{key}"), btn("🗑", f"u:hash:rm:{key}")])
    if hashes:
        rows.append([btn("✅ Создать доступ", "u:hash:done", style="success")])
    if hashes:
        rows.append([btn("🗑 Очистить список", "u:hash:clear")])
    rows.append([btn("↩️ Отмена", "u:menu")])
    return markup(*rows)


def _hash_text(hashes: list[str]) -> str:
    return ("🔗 <b>VK-хеши звонков</b>\n\n"
            "Отправь хеш или ссылку приглашения VK: например, "
            "<code>https://vk.ru/call/join/...</code>. Можно отправить несколько "
            "значений по одному или через запятую.\n\n"
            f"Добавлено: <b>{len(hashes)}/{MAX_HASHES}</b>. "
            "Нужен хотя бы один хеш. После этого нажми «Создать доступ».")


async def _slots_ok() -> tuple[dict, bool]:
    ctx = app()
    settings = await ctx.db.get_settings()
    ok, _left = await ctx.db.slots_available(settings)
    return settings, ok


async def _nodes() -> list:
    try:
        return await app().wdtt.list_nodes()
    except Exception as e:
        log.debug("nodes unavailable: %s", e)
        return []


async def render_access(
    cb: CallbackQuery,
    user: dict,
    force: bool = True,
    fallback: dict | None = None,
):
    """Единый экран доступа: трафик + кнопки копирования нод.

    ``fallback`` — данные, полученные при создании доступа. Нужны, чтобы
    пользователь сразу увидел ключ, даже если повторный запрос к панели
    не удался.
    """
    if not cb.message:
        return

    user = dict(user or {})

    if not user.get("registered"):
        await cb.message.edit_text(no_config_text(), reply_markup=no_config_kb())
        return

    live, reason = await refresh_snapshot(user, force=force, timeout=12)

    if live is None and fallback:
        live = fallback
    elif live is None:
        if reason == "panel_down":
            await cb.message.edit_text(
                config_missing_text() if not user.get("panel_id")
                else panel_down_text(),
                reply_markup=panel_down_kb(),
            )
        elif reason in ("missing", "no_link"):
            await cb.message.edit_text(
                config_missing_text(), reply_markup=config_missing_kb()
            )
        else:
            await cb.message.edit_text(
                no_config_text(), reply_markup=no_config_kb()
            )
        return

    settings = await app().db.get_settings()
    shown = node_limit(settings)
    nodes = await _nodes()
    links = access_links(live, nodes, settings.get("include_main_node", False))
    cfg = app().cfg
    sub_url = public_subscription_url(live, user, cfg.sub_url, cfg.sub_path)
    live = {**live, "subscription_url": sub_url}

    text = access_text(user, live, links, shown)
    kb = access_kb(links, sub_url=sub_url, shown=shown, total_nodes=len(links))
    await cb.message.edit_text(text, reply_markup=kb)


@router.callback_query(F.data == "u:access")
async def cb_access(cb: CallbackQuery, user: dict | None = None):
    if not cb.message:
        return await answer_or_alert(cb)

    await render_access(cb, user or {}, force=True)
    await answer_or_alert(cb)


@router.callback_query(F.data == "u:sub")
async def cb_sub(cb: CallbackQuery, user: dict | None = None):
    if not cb.message:
        return await answer_or_alert(cb)

    user = dict(user or {})
    if not user.get("registered"):
        await cb.message.edit_text(no_config_text(), reply_markup=no_config_kb())
        return await answer_or_alert(cb)

    live, reason = await refresh_snapshot(user, force=True, timeout=12)

    if live is None:
        if reason == "missing":
            await cb.message.edit_text(
                config_missing_text(), reply_markup=config_missing_kb()
            )
        else:
            await cb.message.edit_text(
                panel_down_text(), reply_markup=panel_down_kb()
            )
        return await answer_or_alert(cb)

    settings = await app().db.get_settings()
    shown = node_limit(settings)
    nodes = await _nodes()
    links = access_links(live, nodes, settings.get("include_main_node", False))
    cfg = app().cfg
    sub_url = public_subscription_url(live, user, cfg.sub_url, cfg.sub_path)
    live = {**live, "subscription_url": sub_url}

    await cb.message.edit_text(
        sub_text(user, live, links),
        reply_markup=sub_kb(sub_url, links, shown),
    )
    await answer_or_alert(cb)


@router.callback_query(F.data.startswith("u:show:"))
async def cb_show_link(cb: CallbackQuery, user: dict | None = None):
    if not cb.message:
        return await answer_or_alert(cb)

    try:
        idx = int(cb.data.removeprefix("u:show:"))
    except ValueError:
        return await answer_or_alert(cb, "Ссылка не найдена", True)

    user = dict(user or {})
    live, reason = await refresh_snapshot(user, force=True, timeout=12)

    if live is None:
        return await answer_or_alert(cb, "Панель недоступна", True)

    settings = await app().db.get_settings()
    links = access_links(live, await _nodes(), settings.get("include_main_node", False))

    if idx < 0 or idx >= len(links):
        return await answer_or_alert(cb, "Ссылка не найдена", True)

    item = links[idx]
    await cb.message.edit_text(
        node_link_text(idx, item.get("link") or "", item.get("name") or ""),
        reply_markup=show_link_kb(),
    )
    await answer_or_alert(cb)


async def _clear_local_access(tg_id: int, user: dict) -> bool:
    result = await app().db.users.update_one(
        {"tg_id": tg_id, "registered": True,
         "panel_id": user.get("panel_id"), "creating": {"$ne": True}},
        {"$set": {"registered": False, "creating": False},
         "$unset": {key: "" for key in (
             "panel_id", "panel_password", "panel_link", "panel_snapshot_at",
             "panel_total_gb", "panel_traffic_used_bytes", "panel_expires_at",
             "panel_max_devices", "panel_devices_bound", "panel_online",
             "panel_active", "panel_status", "subscription_url", "sub_id",
             "sub_total_gb", "sub_max_devices", "sub_created_at", "sub_vk_hashes",
         )}},
    )
    return bool(result.modified_count)


@router.callback_query(F.data == "u:recreate")
async def cb_recreate(cb: CallbackQuery, user: dict | None = None):
    if not cb.message:
        return await answer_or_alert(cb)
    user = dict(user or {})
    if user.get("registered") and not await _clear_local_access(cb.from_user.id, user):
        return await answer_or_alert(cb, "Данные доступа изменились. Открой меню и попробуй снова.", True)
    await cb_reg_start(cb, {**user, "registered": False})


@router.callback_query(F.data == "u:reg")
async def cb_reg_start(cb: CallbackQuery, user: dict | None = None):
    if not cb.message:
        return await answer_or_alert(cb)

    user = dict(user or {})

    if user.get("registered"):
        # Сообщения с прежней клавиатурой отправляли этот экран в u:reg.
        if "Доступ не найден в панели" in (cb.message.text or ""):
            return await cb_recreate(cb, user)
        live, reason = await fetch_live(user, force=True, timeout=8)

        if reason == "ok":
            await render_access(cb, user, force=False)
            return await answer_or_alert(cb, "Доступ уже создан")

        if reason == "panel_down":
            return await answer_or_alert(
                cb, "Панель недоступна, попробуй позже", True
            )

        # Карточка точно отсутствует: освобождаем локальную запись и место.
        # При таймауте панели сюда не попадаем — отсутствие не подтверждено.
        if not await _clear_local_access(cb.from_user.id, user):
            return await answer_or_alert(cb, "Данные доступа изменились. Открой меню и попробуй снова.", True)

        settings, ok = await _slots_ok()
        if not ok:
            return await answer_or_alert(cb, "Свободных мест нет", True)

        await cb.message.edit_text(
            agree_text(settings), reply_markup=agreement_kb("u:agree")
        )
        return await answer_or_alert(cb)

    settings, ok = await _slots_ok()
    if not ok:
        await cb.message.edit_text(no_slots_text(), reply_markup=no_config_kb())
        return await answer_or_alert(cb)

    await cb.message.edit_text(
        agree_text(settings), reply_markup=agreement_kb("u:agree")
    )
    await answer_or_alert(cb)


async def _find_existing(tg_id: int) -> dict | None:
    """Если пользователь уже есть в панели — переиспользуем его."""
    return await _by_tg(tg_id)


@router.callback_query(F.data.in_({"u:agree", "u:agree:r"}))
async def cb_agree(cb: CallbackQuery, state: FSMContext, user: dict | None = None):
    if not cb.message:
        return await answer_or_alert(cb)
    await state.clear()
    await state.set_state(RegStates.hashes)
    await state.update_data(hashes=[], recreate=cb.data == "u:agree:r")
    await cb.message.edit_text(_hash_text([]), reply_markup=_hash_kb([]))
    await answer_or_alert(cb)


@router.message(StateFilter(RegStates.hashes), F.text)
async def collect_hashes(message: Message, state: FSMContext):
    raw = (message.text or "").strip()
    if raw.startswith("/"):
        return await message.answer("Отправь хеш или ссылку VK либо нажми «Отмена».")
    parts = [part.strip() for part in raw.replace("\n", ",").split(",") if part.strip()]
    try:
        parsed = [extract_vk_hash(part) for part in parts]
    except ValueError:
        parsed = []
    data = await state.get_data()
    hashes = list(data.get("hashes") or [])
    if not parsed or any(not item for item in parsed):
        return await message.answer("Не удалось распознать хеш. Отправь хеш или ссылку vk.com/call/… либо vk.ru/call/…", reply_markup=_hash_kb(hashes))
    for item in parsed:
        if item not in hashes:
            hashes.append(item)
    if len(hashes) > MAX_HASHES:
        return await message.answer("Можно добавить не более четырёх уникальных хешей.", reply_markup=_hash_kb(data.get("hashes") or []))
    await state.update_data(hashes=hashes)
    await message.answer(_hash_text(hashes), reply_markup=_hash_kb(hashes))


@router.callback_query(StateFilter(RegStates.hashes), F.data == "u:hash:clear")
async def clear_hashes(cb: CallbackQuery, state: FSMContext):
    await state.update_data(hashes=[])
    if cb.message:
        await cb.message.edit_text(_hash_text([]), reply_markup=_hash_kb([]))
    await answer_or_alert(cb)


@router.callback_query(StateFilter(RegStates.hashes), F.data.startswith("u:hash:view:"))
async def view_hash(cb: CallbackQuery, state: FSMContext):
    hashes = (await state.get_data()).get("hashes") or []
    key = cb.data.rsplit(":", 1)[-1]
    value = next((h for h in hashes if hashlib.sha256(h.encode()).hexdigest()[:16] == key), None)
    if value is None:
        return await answer_or_alert(cb, "Хеш больше не найден", True)
    if cb.message:
        await cb.message.edit_text(_hash_text(hashes) + f"\n\n<b>Выбранный хеш:</b>\n<code>{esc(value)}</code>", reply_markup=_hash_kb(hashes))
    await answer_or_alert(cb)


@router.callback_query(StateFilter(RegStates.hashes), F.data.startswith("u:hash:rm:"))
async def remove_hash(cb: CallbackQuery, state: FSMContext):
    hashes = (await state.get_data()).get("hashes") or []
    key = cb.data.rsplit(":", 1)[-1]
    remaining = [h for h in hashes if hashlib.sha256(h.encode()).hexdigest()[:16] != key]
    if len(remaining) == len(hashes):
        return await answer_or_alert(cb, "Хеш больше не найден", True)
    await state.update_data(hashes=remaining)
    if cb.message:
        await cb.message.edit_text(_hash_text(remaining), reply_markup=_hash_kb(remaining))
    await answer_or_alert(cb, "Хеш удалён")


@router.callback_query(StateFilter(RegStates.hashes), F.data == "u:hash:done")
async def cb_create_with_hashes(cb: CallbackQuery, state: FSMContext, user: dict | None = None):
    if not cb.message:
        return await answer_or_alert(cb)

    state_data = await state.get_data()
    hashes = state_data.get("hashes") or []
    if not 1 <= len(hashes) <= MAX_HASHES:
        return await answer_or_alert(cb, "Добавь от одного до четырёх хешей", True)
    ctx = app()
    tg_id = cb.from_user.id
    recreate = bool(state_data.get("recreate"))
    user_doc = dict(user or await ctx.db.get_user(tg_id) or {})

    if user_doc.get("registered") and not recreate:
        return await answer_or_alert(cb, "Доступ уже создан")

    settings, ok = await _slots_ok()
    if not ok:
        return await answer_or_alert(cb, "Свободных мест нет", True)

    if not await ctx.db.claim_creating(tg_id, allow_recreate=recreate):
        return await answer_or_alert(cb, "Доступ уже создаётся", True)

    gb = int(settings.get("default_total_gb") or 0)
    devices = int(settings.get("default_max_devices") or 1)
    days = int(settings.get("default_expires_days") or 0)
    expires_at = int(time.time()) + days * 86400 if days > 0 else 0

    panel_name = f"tg_{tg_id}"

    try:
        try:
            created = await ctx.wdtt.create_user(
                name=panel_name,
                comment=f"tg{tg_id}",
                total_gb=gb,
                expires_at=expires_at,
                max_devices=devices,
                vk_hash=",".join(hashes),
            )
        except WdttError as e:
            existing = await _find_existing(tg_id)
            if existing is None:
                raise e
            panel_id = str(existing.get("id") or "")
            if not panel_id:
                raise e
            created = await ctx.wdtt.add_vk_hashes(panel_id, hashes)
            created = {**existing, **created}

        panel_id = str(created.get("id") or panel_name)
        password = str(created.get("password") or "")
        sub_url = str(
            created.get("subscription_url") or created.get("sub_url") or ""
        )
        link = str(created.get("link") or "")

        await ctx.db.users.update_one(
            {"tg_id": tg_id},
            {
                "$set": {
                    "registered": True,
                    "creating": False,
                    "panel_id": panel_id,
                    "panel_password": password,
                    "panel_total_gb": gb,
                    "panel_traffic_used_bytes": 0,
                    "panel_expires_at": expires_at,
                    "panel_max_devices": devices,
                    "panel_devices_bound": as_int(
                        created.get("devices_bound")
                    ),
                    "panel_online": online_flag(created.get("online")),
                    "panel_active": True,
                    "panel_status": "active",
                    "panel_link": link,
                    "subscription_url": sub_url,
                    "sub_id": str(created.get("sub_id") or ""),
                    "sub_created_at": utcnow(),
                    "sub_total_gb": gb,
                    "sub_max_devices": devices,
                    "sub_vk_hashes": hashes,
                    "panel_snapshot_at": utcnow(),
                    "referral_credited": False,
                },
                "$unset": {"creating_at": ""},
            },
        )

        await ctx.db.log_event(
            tg_id, "access_created", f"gb={gb} dev={devices} days={days}"
        )
        await state.clear()

        user_doc = await ctx.db.get_user(tg_id) or user_doc
        fallback = dict(created) if isinstance(created, dict) else {}
        fallback.setdefault("id", panel_id)
        fallback.setdefault("password", password)
        fallback.setdefault("total_gb", gb)
        fallback.setdefault("traffic_used_bytes", 0)
        fallback.setdefault("expires_at", expires_at)
        fallback.setdefault("max_devices", devices)
        fallback.setdefault("subscription_url", sub_url)
        fallback.setdefault("link", link)
        await render_access(cb, user_doc, force=True, fallback=fallback)
        await answer_or_alert(cb, "✅ Доступ создан")

        inviter = _inviter(user_doc)
        if inviter and inviter != tg_id:
            await _credit_inviter(inviter, settings)

    except Exception as e:
        await ctx.db.release_creating(tg_id)
        await ctx.db.log_event(tg_id, "access_failed", str(e)[:150])
        log.exception("create access failed for %s", tg_id)

        await cb.message.edit_text(
            "❌ <b>Не удалось создать доступ</b>\n\n"
            f"<code>{str(e)[:250]}</code>\n\n"
            "Попробуй ещё раз через минуту.",
            reply_markup=no_config_kb(),
        )
        await answer_or_alert(cb, "Ошибка создания", True)


@router.callback_query(F.data == "u:devices")
async def cb_devices(cb: CallbackQuery, user: dict | None = None):
    if not cb.message:
        return await answer_or_alert(cb)
    live, reason = await refresh_snapshot(dict(user or {}), force=True, timeout=12)
    if live is None:
        return await answer_or_alert(cb, "Не удалось получить данные панели", True)
    devices = live.get("devices") or live.get("bound_devices")
    lines = ["📱 <b>Устройства</b>", "",
             f"Привязано: <b>{as_int(live.get('devices_bound'))}</b> из <b>{as_int(live.get('max_devices')) or '∞'}</b>."]
    if isinstance(devices, list) and devices:
        lines.append("")
        for item in devices[:30]:
            if isinstance(item, dict):
                label = item.get("name") or item.get("device_name") or item.get("id") or item.get("device_id") or "Устройство"
            else:
                label = item
            lines.append(f"• {esc(str(label)[:100])}")
    else:
        lines += ["", "Панель не предоставила список устройств."]
    lines += ["", "Чтобы сбросить привязки, можно удалить доступ и создать его заново. "
              "Старые ссылки перестанут работать; новую ссылку потребуется добавить на устройствах. "
              "Удаление доступно не чаще одного раза в 24 часа."]
    await cb.message.edit_text("\n".join(lines), reply_markup=markup(
        [btn("♻️ Сбросить через удаление доступа", "u:del1")],
        [btn("↩️ Мой доступ", "u:access")]))
    await answer_or_alert(cb)


@router.callback_query(F.data == "u:del1")
async def cb_del_confirm(cb: CallbackQuery):
    if not cb.message:
        return await answer_or_alert(cb)

    await cb.message.edit_text(
        "🗑 <b>Удалить доступ?</b>\n\n"
        "Пользователь, ключи и привязки будут удалены из панели. "
        "Старые ссылки перестанут работать. Затем создай доступ заново.\n\n"
        "Удалять доступ можно не чаще одного раза в 24 часа.",
        reply_markup=yes_no_kb(
            "", "u:del2", "u:access", "🗑 Удалить", "❌ Отмена"
        ),
    )
    await answer_or_alert(cb)


@router.callback_query(F.data == "u:del2")
async def cb_del_do(cb: CallbackQuery, user: dict | None = None):
    if not cb.message:
        return await answer_or_alert(cb)

    ctx = app()
    user = dict(user or {})
    panel_id = str(user.get("panel_id") or "")

    if not user.get("registered") or not panel_id:
        return await answer_or_alert(cb, "Доступ не найден", True)

    now = utcnow()
    now = now.replace(microsecond=(now.microsecond // 1000) * 1000)
    claimed = await ctx.db.users.find_one_and_update(
        {"tg_id": cb.from_user.id, "registered": True, "panel_id": panel_id,
         "$or": [{"last_access_delete": {"$exists": False}},
                 {"last_access_delete": {"$lte": now - timedelta(days=1)}}]},
        {"$set": {"last_access_delete": now}},
    )
    if not claimed:
        return await answer_or_alert(cb, "Удаление доступно раз в 24 часа", True)

    try:
        if panel_id:
            await ctx.wdtt.delete_user(panel_id)
    except WdttError as e:
        if e.status != 404:
            await ctx.db.users.update_one({"tg_id": cb.from_user.id, "last_access_delete": now}, {"$unset": {"last_access_delete": ""}})
            log.warning("self delete failed: %s", e)
            return await answer_or_alert(cb, "Не удалось удалить доступ в панели. Попробуй позже.", True)
    except Exception as e:
        await ctx.db.users.update_one({"tg_id": cb.from_user.id, "last_access_delete": now}, {"$unset": {"last_access_delete": ""}})
        log.warning("self delete failed: %s", e)
        return await answer_or_alert(cb, "Не удалось удалить доступ в панели. Попробуй позже.", True)

    await ctx.db.users.update_one(
        {"tg_id": cb.from_user.id},
        {
            "$set": {"registered": False},
            "$unset": {
                "panel_id": "", "panel_password": "", "panel_link": "",
                "panel_snapshot_at": "", "subscription_url": "", "sub_id": "",
                "sub_total_gb": "", "sub_max_devices": "", "sub_created_at": "",
            },
        },
    )
    await ctx.db.log_event(cb.from_user.id, "access_deleted", "self")

    await cb.message.edit_text(
        "🗑 Доступ удалён.\n\n" + no_config_text(),
        reply_markup=no_config_kb(),
    )
    await answer_or_alert(cb, "Удалено")


def _inviter(user_doc: dict) -> int | None:
    try:
        if user_doc.get("referral_of"):
            return int(user_doc["referral_of"])

        payload = str(user_doc.get("start_payload") or "")
        if payload.startswith("ref_"):
            return int(payload[4:].split("_")[0])
    except (ValueError, TypeError):
        return None
    return None


async def _credit_inviter(inviter_id: int, settings: dict):
    ctx = app()
    inv = await ctx.db.get_user(inviter_id)

    if not inv or not inv.get("registered"):
        return

    await ctx.db.users.update_one(
        {"tg_id": inviter_id}, {"$inc": {"referrals": 1}}
    )

    bonus = int(
        settings.get("referral_bonus_gb")
        or ctx.cfg.referral_bonus_gb
        or 0
    )
    panel_id = str(inv.get("panel_id") or "")
    if bonus <= 0 or not panel_id:
        return

    try:
        live = await ctx.wdtt.get_user(panel_id, force=True)
    except Exception:
        return

    current = int(live.get("total_gb") or 0)
    if current <= 0:
        return  # безлимит не трогаем

    try:
        await ctx.wdtt.update_user(panel_id, total_gb=current + bonus)
        await ctx.db.users.update_one(
            {"tg_id": inviter_id},
            {"$set": {"panel_total_gb": current + bonus,
                      "sub_total_gb": current + bonus}},
        )
        await ctx.db.log_event(
            inviter_id, "referral_bonus", f"+{bonus} GB"
        )
    except Exception as e:
        log.warning("referral bonus failed: %s", e)
