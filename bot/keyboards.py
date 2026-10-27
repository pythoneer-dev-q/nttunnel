# -*- coding: utf-8 -*-
"""Inline-клавиатуры бота.

Дизайн лаконичный: одна-две кнопки в ряд, без визуального шума.
Ссылки на ноды копируются кнопками ``CopyTextButton``.
"""
from __future__ import annotations

from aiogram.types import CopyTextButton, InlineKeyboardButton, InlineKeyboardMarkup

COPY_TEXT_LIMIT = 256


def btn(
    text: str,
    cb: str | None = None,
    url: str | None = None,
    style: str | None = None,
) -> InlineKeyboardButton:
    kwargs: dict = {"text": text[:64]}

    if url:
        kwargs["url"] = url
    else:
        kwargs["callback_data"] = (cb or "noop")[:64]

    if style:
        kwargs["style"] = style

    try:
        return InlineKeyboardButton(**kwargs)
    except Exception:
        kwargs.pop("style", None)
        return InlineKeyboardButton(**kwargs)


def copy_btn(text: str, value: str, cb: str = "noop") -> InlineKeyboardButton:
    """Кнопка «скопировать». Длинную ссылку показываем по callback."""
    value = (value or "").strip()
    if value and len(value.encode("utf-8")) <= COPY_TEXT_LIMIT:
        return InlineKeyboardButton(
            text=text[:64],
            copy_text=CopyTextButton(text=value),
        )
    return btn(text, cb=cb)


def markup(*rows: list[InlineKeyboardButton]) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[row for row in rows if row])


# --------------------------------------------------------------- меню


def menu_kb(
    registered: bool,
    ads: list | None = None,
    sections: list | None = None,
) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []

    if registered:
        rows.append([btn("📱 Мой доступ", "u:access", style="primary")])
        rows.append([
            btn("🆘 Поддержка", "u:support"),
            btn("👤 Профиль", "u:cab"),
        ])
    else:
        rows.append([btn("🔑 Создать доступ", "u:reg", style="success")])
        rows.append([btn("🆘 Поддержка", "u:support"), btn("👤 Профиль", "u:cab")])

    for i in range(0, len(sections or []), 2):
        pair = sections[i:i + 2]
        rows.append([
            btn(f"📂 {s.get('title') or s.get('key')}", f"u:sec:{s.get('key')}")
            for s in pair
        ])

    for ad in ads or []:
        if ad.get("url"):
            rows.append([btn(str(ad.get("title") or "Реклама"), url=ad["url"])])

    rows.append([btn("🏳️ Инструкция", "u:apps")])
    return markup(*rows)


def back_menu_kb() -> InlineKeyboardMarkup:
    return markup([btn("↩️ В меню", "u:menu")])


def menu_back_kb(sections: list | None = None) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []

    for i in range(0, len(sections or []), 2):
        pair = sections[i:i + 2]
        rows.append([
            btn(f"📂 {s.get('title') or s.get('key')}", f"u:sec:{s.get('key')}")
            for s in pair
        ])

    rows.append([btn("↩️ В меню", "u:menu")])
    return markup(*rows)


def support_kb() -> InlineKeyboardMarkup:
    return markup(
        [btn("📝 Новое обращение", "u:ticket:new", style="primary")],
        [btn("📬 Мои обращения", "u:ticket:list")],
        [btn("↩️ В меню", "u:menu")],
    )


# ------------------------------------------------------ доступ / подписка


def no_config_kb() -> InlineKeyboardMarkup:
    return markup(
        [btn("🔑 Создать доступ", "u:reg", style="success")],
        [btn("↩️ В меню", "u:menu")],
    )


def panel_down_kb() -> InlineKeyboardMarkup:
    return markup(
        [btn("🔄 Повторить", "u:access", style="primary")],
        [btn("↩️ В меню", "u:menu")],
    )


def config_missing_kb() -> InlineKeyboardMarkup:
    return markup(
        [btn("♻️ Пересоздать доступ", "u:recreate", style="success")],
        [btn("🔄 Повторить", "u:access"), btn("↩️ В меню", "u:menu")],
    )


def access_kb(
    links: list | None = None,
    sub_url: str = "",
    shown: int = 5,
    total_nodes: int | None = None,
) -> InlineKeyboardMarkup:
    """Открытие подписки, управление устройствами и навигация."""
    rows: list[list[InlineKeyboardButton]] = []

    if sub_url:
        rows.append([btn("🌐 Открыть подписку", url=sub_url, style="primary")])

    rows.append([
        btn("🔄 Обновить", "u:access"),
        btn("↩️ В меню", "u:menu"),
    ])
    rows.insert(-1, [btn("📱 Устройства", "u:devices")])
    return markup(*rows)


def show_link_kb() -> InlineKeyboardMarkup:
    return markup(
        [btn("🔙 Мой доступ", "u:access")],
        [btn("↩️ В меню", "u:menu")],
    )


def sub_kb(sub_url: str = "", links: list | None = None,
           shown: int = 5) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []

    if sub_url:
        rows.append([btn("🌐 Открыть подписку", url=sub_url, style="primary")])

    rows.append([
        btn("📱 Мой доступ", "u:access"),
        btn("↩️ В меню", "u:menu"),
    ])
    return markup(*rows)


def config_kb(
    sub_url: str = "",
    ios_link: str = "",
    android_link: str = "",
) -> InlineKeyboardMarkup:
    """Совместимость со старыми вызовами."""
    links = []
    if android_link:
        links.append({"name": "Android", "link": android_link})
    if ios_link:
        links.append({"name": "iOS", "link": ios_link})
    return access_kb(links, sub_url=sub_url, shown=len(links) or 5)


def done_kb(ios_link: str = "", android_link: str = "") -> InlineKeyboardMarkup:
    links = []
    if android_link:
        links.append({"name": "Android", "link": android_link})
    if ios_link:
        links.append({"name": "iOS", "link": ios_link})
    return access_kb(links, shown=len(links) or 5)


# ------------------------------------------------------ регистрация


def step_app_kb() -> InlineKeyboardMarkup:
    """Совместимость: выбор приложения больше не нужен."""
    return markup(
        [btn("✅ Продолжить", "u:agree", style="success")],
        [btn("↩️ Отменить", "u:menu", style="danger")],
    )


def agreement_kb(cb: str = "u:agree") -> InlineKeyboardMarkup:
    return markup(
        [btn("✅ Принимаю", cb, style="success")],
        [btn("↩️ Отмена", "u:menu", style="danger")],
    )


def hash_prompt_kb() -> InlineKeyboardMarkup:
    return markup([btn("↩️ Отмена", "u:menu", style="danger")])


def hash_added_kb(hashes: list | None = None, max_h: int = 4) -> InlineKeyboardMarkup:
    """Совместимость со старым сценарием сбора хешей."""
    return markup(
        [btn("✅ Продолжить", "u:hash:done", style="success")],
        [btn("↩️ Отмена", "u:menu", style="danger")],
    )


def hash_help_kb() -> InlineKeyboardMarkup:
    return markup([btn("↩️ Назад", "u:menu")])


def referral_kb() -> InlineKeyboardMarkup:
    return markup([btn("↩️ В профиль", "u:cab")], [btn("↩️ В меню", "u:menu")])


# ------------------------------------------------------ приложения


def apps_kb(links: list | None = None) -> InlineKeyboardMarkup:
    rows = [
        [btn(str(link.get("label") or "Открыть"), url=link["url"])]
        for link in (links or [])
        if link.get("url")
    ]
    rows.append([btn("↩️ В меню", "u:menu")])
    return markup(*rows)


# ------------------------------------------------------ каналы


def subscribe_kb(channels: list | None = None) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []

    for ch in channels or []:
        username = ch.get("username")
        channel_id = ch.get("channel_id")
        url = ch.get("url")

        if not url and username:
            url = f"https://t.me/{str(username).lstrip('@')}"
        if not url and channel_id:
            url = f"https://t.me/c/{str(channel_id).replace('-100', '')}"
        if not url:
            continue

        title = ch.get("title") or username or str(channel_id)
        rows.append([btn(f"📺 {title}", url=url)])

    rows.append([btn("🔄 Проверить подписку", "chk:r", style="success")])
    return markup(*rows)


# ------------------------------------------------------ админка


def adm_root_kb() -> InlineKeyboardMarkup:
    return markup(
        [btn("📊 Статистика", "adm:stat"), btn("👥 Пользователи", "adm:usr")],
        [btn("🌍 Ноды", "adm:nodes", style="primary"), btn("⚙️ Настройки", "adm:set")],
        [btn("📤 Рассылка", "adm:bc"), btn("🎯 Реклама", "adm:ads")],
        [btn("📺 Каналы", "adm:chn"), btn("🎫 Тикеты", "adm:tkt")],
        [btn("🧩 Разделы", "adm:sec")],
    )


def adm_back_kb(target: str = "adm") -> InlineKeyboardMarkup:
    return markup([btn("⬅️ Назад", target)])


def srv_kb() -> InlineKeyboardMarkup:
    return markup(
        [btn("♻️ Перезапустить WDTT", "adm:srv:rw", style="danger")],
        [btn("🔄 Обновить", "adm:srv"), btn("⬅️ В админку", "adm")],
    )


def nodes_kb(nodes: list, page: int = 0, pages: int = 1) -> InlineKeyboardMarkup:
    from aiogram.types import InlineKeyboardButton as IKB

    from .wdtt import node_online

    rows: list[list[IKB]] = []

    for node in nodes:
        node_id = str(node.get("id") or node.get("name") or "")
        name = str(node.get("name") or node.get("host") or node_id or "Нода")
        online = "🟢" if node_online(node) else "⚪"
        rows.append([
            btn(f"{online} {name}"[:64], cb=f"adm:nodes:v:{node_id}"),
            btn("📡", cb=f"adm:nodes:ping:{node_id}"),
            btn("🗑", cb=f"adm:nodes:del1:{node_id}", style="danger"),
        ])

    rows.append([btn("➕ Добавить ноду", "adm:nodes:add", style="success")])

    nav = []
    if page > 0:
        nav.append(IKB(text="⬅️", callback_data=f"adm:nodes:p{page - 1}"))
    if pages > 1:
        nav.append(IKB(text=f"{page + 1}/{pages}", callback_data="noop"))
    if page < pages - 1:
        nav.append(IKB(text="➡️", callback_data=f"adm:nodes:p{page + 1}"))
    if nav:
        rows.append(nav)

    rows.append([btn("🔄 Обновить", "adm:nodes"), btn("⬅️ В админку", "adm")])
    return markup(*rows)


def profile_kb() -> InlineKeyboardMarkup:
    return markup([btn("↩️ В меню", "u:menu")])
