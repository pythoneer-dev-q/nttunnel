
# -*- coding: utf-8 -*-
"""Флоу регистрации: приложение → соглашение → VK-хеши → готово (подписка).

Листательный flow: бот-сообщение редактируется по кнопкам;
ввод VK-хешей — новыми сообщениями в состоянии (FSM).
"""

import logging

from aiogram import F, Router
from aiogram.filters import StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message

from ..context import app
from ..db import utcnow
from ..keyboards import (
    agreement_kb,
    config_missing_kb,
    done_kb,
    hash_added_kb,
    hash_help_kb,
    hash_prompt_kb,
    no_config_kb,
    panel_down_kb,
    show_link_kb,
    step_app_kb,
    config_kb,
    sub_kb,
)
from ..texts import (
    AGREEMENT_HEAD,
    HASH_HELP,
    STEP_APP,
    config_missing_text,
    config_text,
    done_text,
    hash_added_text,
    hash_intro,
    no_config_text,
    no_slots_text,
    panel_down_text,
    sub_text,
    wdtt_configs,
)
from ..utils import answer_or_alert, extract_vk_hash, safe_edit
from ..wdtt import WdttError


log = logging.getLogger(__name__)
router = Router(name="register")

MAX_HASHES = 4


class RegStates(StatesGroup):
    hash = State()


async def _settings_and_slots():
    ctx = app()
    settings = await ctx.db.get_settings()
    ok, _left = await ctx.db.slots_available(settings)
    return settings, ok


async def _edit_loading(cb: CallbackQuery, step: int = 0):
    """Анимирует «загрузку» на редактируемом сообщении перед запросом к серверу."""
    if not cb.message:
        return
    frames = ["⏳", "🔄", "⏳"]
    emoji = frames[step % len(frames)]
    try:
        await cb.message.edit_text(
            f"{emoji} <b>Загружаю…</b>\n\n"
            "Подожди, подключаюсь к серверу…"
        )
    except Exception:
        pass


async def _show_no_config(cb: CallbackQuery):
    """Экран «нет конфига» — для незарегистрированных."""
    if cb.message:
        await safe_edit(
            cb.message,
            no_config_text(),
            no_config_kb(),
        )

    await answer_or_alert(cb)


async def _resolve_live(user: dict):
    """Ищет конфиг пользователя в панели.

    Возвращает ``(live|None, reason)``:
      • ``'ok'``         — конфиг найден;
      • ``'panel_down'`` — панель недоступна (это НЕ «нет конфига»);
      • ``'missing'``    — панель отвечает, но конфига у пользователя нет.

    Сначала быстрый путь (кэш/зеркало, без запроса к панели), и только при
    промахе — прямой **строгий** запрос, чтобы отличить сбой связи от
    реального отсутствия конфига.
    """
    ctx = app()
    tg_id = user.get("tg_id")
    pwd = user.get("wdtt_password") or ""

    if pwd:
        live = await ctx.wdtt.find_user(pwd)

        if live:
            return live, "ok"

    # Запасной ключ: панель хранит комментарий как "tg<id>" (см. регистрацию).
    candidates = [c for c in (pwd, f"tg{tg_id}" if tg_id else "") if c]

    for key in candidates:
        try:
            live = await ctx.wdtt.find_user(key, force=True, strict=True)
        except WdttError:
            return None, "panel_down"

        if live:
            return live, "ok"

    return None, "missing"


async def _show_live_problem(cb: CallbackQuery, reason: str):
    """Корректный экран, когда конфиг не удалось получить."""
    if not cb.message:
        return await answer_or_alert(cb)

    if reason == "panel_down":
        await safe_edit(cb.message, panel_down_text(), panel_down_kb())
        return await answer_or_alert(
            cb, "🔌 Панель недоступна, попробуй позже", True)

    await safe_edit(
        cb.message, config_missing_text(), config_missing_kb())
    return await answer_or_alert(cb, "Конфиг не найден в панели", True)


@router.callback_query(F.data == "u:traffic")
async def cb_traffic(cb: CallbackQuery, user: dict):
    """Трафик: зарегистрированным — конфиг + ссылки для копирования.

    Кнопка «Трафик» в меню показывает:
      • инфо о конфиге (пароль, VK, трафик);
      • ссылку подписки;
      • WDTT-конфиги для копирования (iOS и Android).
    """
    if not cb.message:
        return await answer_or_alert(cb)

    if not user.get("registered"):
        return await _show_no_config(cb)

    # Анимация загрузки перед запросом к серверу.
    await _edit_loading(cb, step=1)

    live, reason = await _resolve_live(user)

    if live is None:
        return await _show_live_problem(cb, reason)

    hashes = user.get("sub_vk_hashes") or (
        [live["vk_hash"]]
        if live.get("vk_hash")
        else []
    )

    app_name = user.get("sub_app") or "WDTT"

    cfg = wdtt_configs(live, hashes, host=app().cfg.host)

    text = config_text(
        live,
        hashes,
        app_name,
        host=app().cfg.host,
    )
    kb = config_kb(
        sub_url=live.get("sub_url") or "",
        ios_link=cfg["ios"],
        android_link=cfg["android"],
    )

    await safe_edit(cb.message, text, kb)
    await answer_or_alert(cb)


@router.callback_query(F.data == "u:sub")
async def cb_sub(cb: CallbackQuery, user: dict):
    """Экран «Подписка»: инфо о подписке + все форматы ссылок."""
    if not cb.message:
        return await answer_or_alert(cb)

    if not user.get("registered"):
        return await _show_no_config(cb)

    # Анимация загрузки перед запросом к серверу.
    await _edit_loading(cb, step=2)

    live, reason = await _resolve_live(user)

    if live is None:
        return await _show_live_problem(cb, reason)

    hashes = user.get("sub_vk_hashes") or (
        [live["vk_hash"]]
        if live.get("vk_hash")
        else []
    )

    app_name = user.get("sub_app") or "WDTT"

    text = sub_text(
        live,
        hashes,
        app_name,
    )
    kb = sub_kb(
        live.get("sub_url") or ""
    )

    await safe_edit(cb.message, text, kb)
    await answer_or_alert(cb)


@router.callback_query(F.data == "u:reg")
async def cb_reg_start(
    cb: CallbackQuery,
    user: dict,
    state: FSMContext,
):
    if not cb.message:
        return await answer_or_alert(cb)

    recreate = False

    if user.get("registered"):
        # Пересоздание разрешаем ТОЛЬКО если в панели конфига реально нет.
        # Иначе получался тупик: «нет конфига» ↔ «у тебя уже есть конфиг».
        _live, reason = await _resolve_live(user)

        if reason == "ok":
            return await answer_or_alert(
                cb,
                "У тебя уже есть конфиг",
            )

        if reason == "panel_down":
            return await answer_or_alert(
                cb,
                "🔌 Панель недоступна, попробуй позже",
                True,
            )

        # reason == "missing" — подписки в панели нет, создаём заново.
        recreate = True

    settings, ok = await _settings_and_slots()

    if not ok:
        await app().db.log_event(
            cb.from_user.id,
            "reg_denied_no_slots",
        )

        await safe_edit(
            cb.message,
            no_slots_text(),
            no_config_kb(),
        )

        return await answer_or_alert(cb)

    await state.clear()

    await state.update_data(
        app="WDTT",
        hashes=[],
        recreate=recreate,
    )

    await safe_edit(
        cb.message,
        STEP_APP,
        step_app_kb(),
    )

    await answer_or_alert(cb)


@router.callback_query(F.data.startswith("u:app:"))
async def cb_pick_app(
    cb: CallbackQuery,
    state: FSMContext,
):
    if not cb.message:
        return await answer_or_alert(cb)

    chosen = cb.data.removeprefix("u:app:")

    data = await state.get_data()

    # В режиме пересоздания (панель потеряла конфиг) не блокируем.
    if not data.get("recreate"):
        u = await app().db.get_user(
            cb.from_user.id
        ) or {}

        if u.get("registered"):
            return await answer_or_alert(
                cb,
                "У тебя уже есть конфиг",
            )

    await state.update_data(app=chosen)

    settings, _ = await _settings_and_slots()

    text = (
        AGREEMENT_HEAD
        + (settings.get("agreement_text") or "")
    )

    await safe_edit(
        cb.message,
        text,
        agreement_kb(),
    )

    await answer_or_alert(cb)


@router.callback_query(F.data == "u:agree:ok")
async def cb_agree_ok(
    cb: CallbackQuery,
    state: FSMContext,
):
    if not cb.message:
        return await answer_or_alert(cb)

    data = await state.get_data()
    app_name = data.get("app") or "WDTT"

    await state.update_data(
        hashes=[],
    )

    await state.set_state(RegStates.hash)

    await safe_edit(
        cb.message,
        hash_intro(app_name),
        hash_prompt_kb(),
    )

    await answer_or_alert(cb)


@router.message(StateFilter(RegStates.hash), F.text)
async def h_hash_input(
    message: Message,
    state: FSMContext,
):
    """
    Принимаем VK-хеш обычным сообщением.

    ВАЖНО:
    сообщение пользователя не редактируется;
    старое сообщение бота тоже не редактируется.

    Каждый успешно добавленный хеш приводит к отправке
    нового сообщения бота со свежим списком.
    """
    ctx = app()

    data = await state.get_data()
    hashes = list(data.get("hashes") or [])

    raw = (message.text or "").strip()
    hash_ = extract_vk_hash(raw)

    # Невалидный хеш — просто новое сообщение бота.
    if not hash_:
        try:
            await message.answer(
                "⚠️ Не получилось распознать хеш.\n\n"
                "<blockquote>"
                "Пришли полную ссылку на звонок:\n"
                "<code>https://vk.ru/call/join/XXXXXXXXXX</code>\n"
                "или только хеш после <code>/join/</code>."
                "</blockquote>"
            )
        except Exception:
            pass

        await ctx.db.log_event(
            message.from_user.id,
            "hash_invalid",
            raw[:60],
        )
        return

    # Дубликат — тоже новое сообщение.
    if hash_ in hashes:
        try:
            await message.answer(
                "⚠️ Этот хеш уже добавлен.\n\n"
                "Пришли другой.",
                reply_markup=hash_added_kb(
                    hashes,
                    MAX_HASHES,
                ),
            )
        except Exception:
            pass

        return

    # Добавляем новый хеш.
    hashes.append(hash_)

    await state.update_data(
        hashes=hashes,
    )

    # КЛЮЧЕВОЕ ИЗМЕНЕНИЕ:
    # здесь НЕТ safe_edit / edit_message_text.
    # Всегда создаём новое сообщение.
    try:
        await message.answer(
            hash_added_text(
                hashes,
                MAX_HASHES,
            ),
            reply_markup=hash_added_kb(
                hashes,
                MAX_HASHES,
            ),
        )
    except Exception as e:
        log.warning(
            "failed to send hash status: %s",
            e,
        )

    await ctx.db.log_event(
        message.from_user.id,
        "vk_hash_added",
        hash_,
    )


@router.callback_query(F.data.startswith("u:hash:rm:"))
async def cb_hash_remove(
    cb: CallbackQuery,
    state: FSMContext,
):
    """Удаление хеша по кнопке."""
    if not cb.message:
        return await answer_or_alert(cb)

    data = await state.get_data()

    target = cb.data.removeprefix(
        "u:hash:rm:"
    )

    hashes = [
        h
        for h in (data.get("hashes") or [])
        if h != target
    ]

    await state.update_data(
        hashes=hashes,
    )

    if not hashes:
        app_name = data.get("app") or "WDTT"

        await state.set_state(
            RegStates.hash
        )

        # Это нажатие кнопки → редактирование уместно.
        await safe_edit(
            cb.message,
            hash_intro(app_name),
            hash_prompt_kb(),
        )
    else:
        # Это нажатие кнопки → редактирование уместно.
        await safe_edit(
            cb.message,
            hash_added_text(
                hashes,
                MAX_HASHES,
            ),
            hash_added_kb(
                hashes,
                MAX_HASHES,
            ),
        )

    await answer_or_alert(
        cb,
        "Хеш удалён",
    )


@router.callback_query(F.data == "u:hash:add")
async def cb_hash_add(
    cb: CallbackQuery,
    state: FSMContext,
):
    if not cb.message:
        return await answer_or_alert(cb)

    data = await state.get_data()
    app_name = data.get("app") or "WDTT"

    await state.set_state(
        RegStates.hash
    )

    # Кнопка → редактируем текущее сообщение.
    await safe_edit(
        cb.message,
        hash_intro(app_name),
        hash_prompt_kb(),
    )

    await answer_or_alert(cb)


@router.callback_query(F.data == "u:hash:help")
async def cb_hash_help(cb: CallbackQuery):
    if not cb.message:
        return await answer_or_alert(cb)

    # Кнопка → редактируем текущее сообщение.
    await safe_edit(
        cb.message,
        HASH_HELP,
        hash_help_kb(),
    )

    await answer_or_alert(cb)


@router.callback_query(F.data == "u:hash:done")
async def cb_hash_done(
    cb: CallbackQuery,
    state: FSMContext,
):
    """Создание подписки в панели WDTT + выдача подписки."""
    if not cb.message:
        return await answer_or_alert(cb)

    data = await state.get_data()

    app_name = data.get("app") or "WDTT"
    hashes = list(data.get("hashes") or [])
    tg_id = cb.from_user.id

    ctx = app()

    u = await ctx.db.get_user(tg_id) or {}

    if u.get("registered"):
        await state.clear()

        return await answer_or_alert(
            cb,
            "У тебя уже есть конфиг",
            True,
        )

    settings, ok = await _settings_and_slots()

    if not ok:
        return await answer_or_alert(
            cb,
            "Свободных мест нет 😔",
            True,
        )

    if u.get("creating"):
        return await answer_or_alert(
            cb,
            "Подписка уже создаётся",
            True,
        )

    gb = int(
        settings.get("default_total_gb") or 175
    )

    dev = int(
        settings.get("default_max_devices") or 1
    )

    inviter = await _self_inviter(tg_id)

    await ctx.db.users.update_one(
        {"tg_id": tg_id},
        {"$set": {"creating": True}},
    )

    try:
        log.info(
            "[reg] create start tg=%s app=%s gb=%s dev=%s hashes=%s",
            tg_id,
            app_name,
            gb,
            dev,
            len(hashes),
        )

        # Анимация загрузки перед запросами к панели.
        await _edit_loading(cb, step=0)

        password = await ctx.wdtt.add_user(
            comment=f"tg{tg_id}",
            total_gb=gb,
            max_devices=dev,
        )

        log.info(
            "[reg] panel add_user OK tg=%s",
            tg_id,
        )

        # VK-хеши → панель.
        if hashes:
            try:
                await ctx.wdtt.update_user(
                    password,
                    vk_hash=",".join(hashes),
                )
            except Exception as e:
                log.warning(
                    "[reg] set vk_hash failed: %s",
                    e,
                )

        # Получаем актуальные данные.
        live = (
            await ctx.wdtt.find_user(password, force=True)
            or {}
        )

        sub_id = live.get("sub_id") or ""
        sub_url = live.get("sub_url") or ""
        wdtt_link = live.get("link") or ""

        # WDTT-ссылки iOS + Android (из живых данных, не из «словаря»).
        cfg = wdtt_configs(live, hashes, host=app().cfg.host)

        log.info(
            "[reg] sub ready tg=%s sub_id=%s link_len=%s",
            tg_id,
            sub_id,
            len(wdtt_link),
        )

        await ctx.db.users.update_one(
            {"tg_id": tg_id},
            {
                "$set": {
                    "registered": True,
                    "creating": False,
                    "wdtt_password": password,
                    "wdtt_link": wdtt_link,
                    "sub_id": sub_id,
                    "sub_url": sub_url,
                    "sub_created_at": utcnow(),
                    "sub_total_gb": gb,
                    "sub_max_devices": dev,
                    "sub_app": app_name,
                    "sub_vk_hashes": hashes,
                    "referral_of": inviter,
                }
            },
        )

        await ctx.db.log_event(
            tg_id,
            "subscription_created",
            f"gb={gb} dev={dev} hashes={len(hashes)}",
        )

        text = done_text(
            password,
            gb,
            dev,
            app_name,
            hashes,
            sub_url=sub_url,
            wdtt_link=wdtt_link,
            ios_link=cfg["ios"],
            android_link=cfg["android"],
        )

        await state.clear()

        # Завершение flow по кнопке → редактируем
        # текущее сообщение.
        await safe_edit(
            cb.message,
            text,
            done_kb(
                cfg["ios"],
                cfg["android"],
            ),
        )

        await answer_or_alert(
            cb,
            "🎉 Доступ создан!",
        )

        if inviter:
            await _credit_inviter(inviter)

        log.info(
            "created subscription for %s",
            tg_id,
        )

    except Exception as e:
        await ctx.db.users.update_one(
            {"tg_id": tg_id},
            {"$set": {"creating": False}},
        )

        await ctx.db.log_event(
            tg_id,
            "subscription_failed",
            str(e)[:150],
        )

        log.exception(
            "create failed for %s",
            tg_id,
        )

        err = (
            "<b>Не удалось создать доступ</b>\n\n"
            f"<code>{str(e)[:300]}</code>\n\n"
            "Сервер панели недоступен. "
            "Попробуй чуть позже."
        )

        # Ошибка возникла после нажатия кнопки,
        # поэтому редактирование здесь нормально.
        await safe_edit(
            cb.message,
            err,
            hash_prompt_kb(),
        )

        await answer_or_alert(
            cb,
            "Ошибка создания",
            True,
        )


@router.callback_query(F.data == "u:show")
async def cb_show_link(
    cb: CallbackQuery,
    user: dict,
):
    """«Показать ссылку» — ссылка подписки для копирования."""
    if not cb.message:
        return await answer_or_alert(cb)

    u = user or {}

    link = (
        u.get("wdtt_link")
        or u.get("sub_url")
    )

    if not link:
        return await answer_or_alert(
            cb,
            "Ссылка ещё не создана",
            True,
        )

    text = (
        f"🔗 <b>Твоя ссылка:</b>\n\n"
        f"<code>{link}</code>\n\n"
        "Открой её в выбранном приложении."
    )

    await safe_edit(
        cb.message,
        text,
        show_link_kb(),
    )

    await answer_or_alert(cb)


@router.callback_query(F.data == "u:del1")
async def cb_del_confirm(
    cb: CallbackQuery,
    user: dict,
):
    """Подтверждение удаления подписки."""
    if not cb.message:
        return await answer_or_alert(cb)

    from ..utils import yes_no_kb

    await safe_edit(
        cb.message,
        "🗑 <b>Удалить подписку?</b>\n\n"
        "<blockquote>"
        "Конфиг будет удалён из панели безвозвратно. "
        "Создать новый можно будет позже."
        "</blockquote>",
        yes_no_kb(
            None,
            "u:del2",
            "u:traffic",
            "🗑 Да, удалить",
            "❌ Отмена",
        ),
    )

    await answer_or_alert(cb)


@router.callback_query(F.data == "u:del2")
async def cb_del_do(
    cb: CallbackQuery,
    user: dict,
):
    if not cb.message:
        return await answer_or_alert(cb)

    ctx = app()
    pwd = user.get("wdtt_password")

    try:
        if pwd:
            await ctx.wdtt.delete_user(pwd)
    except Exception as e:
        log.warning(
            "self-delete failed: %s",
            e,
        )

    await ctx.db.users.update_one(
        {"tg_id": cb.from_user.id},
        {
            "$set": {
                "registered": False,
            },
            "$unset": {
                "wdtt_password": "",
                "wdtt_link": "",
                "sub_id": "",
                "sub_url": "",
                "sub_total_gb": "",
                "sub_max_devices": "",
                "sub_app": "",
                "sub_vk_hashes": "",
            },
        },
    )

    await ctx.db.log_event(
        cb.from_user.id,
        "subscription_deleted",
        "self",
    )

    await safe_edit(
        cb.message,
        "🗑 Подписка удалена.\n\n"
        + no_config_text(),
        no_config_kb(),
    )

    await answer_or_alert(
        cb,
        "🗑 Удалено",
    )


async def _self_inviter(tg_id: int):
    """Определяет, кто пригласил пользователя."""
    try:
        u = await app().db.get_user(tg_id) or {}
        payload = u.get("start_payload") or ""

        if payload.startswith("ref_"):
            return int(
                payload[4:].split("_")[0]
            )

    except (ValueError, TypeError):
        return None

    return None


async def _credit_inviter(inviter_id: int):
    """+5 ГБ пригласившему."""
    try:
        ctx = app()

        inv = (
            await ctx.db.get_user(inviter_id)
            or {}
        )

        if not inv.get("registered"):
            return

        await ctx.db.users.update_one(
            {"tg_id": inviter_id},
            {"$inc": {"referrals": 1}},
        )

        inv = (
            await ctx.db.get_user(inviter_id)
            or {}
        )

        base = int(
            inv.get("sub_total_gb") or 0
        )

        bonus = (
            int(inv.get("referrals") or 0)
            * 5
        )

        pwd = inv.get(
            "wdtt_password",
            "",
        )

        if pwd:
            await ctx.wdtt.update_user(
                pwd,
                total_gb=base + bonus,
            )

    except Exception as e:
        log.warning(
            "inviter credit failed: %s",
            e,
        )
