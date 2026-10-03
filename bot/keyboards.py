# -*- coding: utf-8 -*-
"""Все inline-клавиатуры."""

from aiogram.types import CopyTextButton, InlineKeyboardButton, InlineKeyboardMarkup


def btn(
    text: str,
    cb: str | None = None,
    url: str | None = None,
    style: str | None = None,
) -> InlineKeyboardButton:
    kwargs = {"text": text[:64]}

    if url:
        kwargs["url"] = url
    else:
        kwargs["callback_data"] = cb or "noop"

    if style:
        kwargs["style"] = style

    try:
        return InlineKeyboardButton(**kwargs)
    except Exception:
        kwargs.pop("style", None)
        return InlineKeyboardButton(**kwargs)


def copy_btn(text: str, value: str):
    return InlineKeyboardButton(text=text, copy_text=CopyTextButton(text=value))



def markup(*rows: list[InlineKeyboardButton]) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[row for row in rows if row]
    )


# --------------------------------------------------------------- меню

def menu_kb(registered: bool, ads: list,
            sections: list | None = None) -> InlineKeyboardMarkup:
    rows = []

    if registered:
        rows.append([
            btn("📱 Трафик", "u:traffic"),
            btn("🆘 Поддержка", "u:support"),
        ])
        rows.append([
            btn("🚀 Рефералка", "u:ref", style="success"),
            btn("👤 Кабинет", "u:cab"),
        ])
    else:
        rows.append([
            btn("💾 Создать подписку", "u:reg", style="success")
        ])

    # динамические разделы (конструктор из админки) — по 2 в ряд
    for i in range(0, len(sections or []), 2):
        pair = sections[i:i + 2]
        rows.append([btn(f"📂 {s.get('title') or s['key']}",
                         f"u:sec:{s['key']}") for s in pair])

    rows.append([
        btn("🏳️ Инструкция", "u:apps"),
    ])

    rows.extend(
        [btn(str(ad.get("title", "Реклама")), url=ad["url"])]
        for ad in ads
        if ad.get("url")
    )

    return markup(*rows)


def back_menu_kb() -> InlineKeyboardMarkup:
    return markup([
        btn("↩️ В меню", "u:menu"),
    ])


def support_kb() -> InlineKeyboardMarkup:
    return markup(
        [btn("📝 Написать обращение", "u:ticket:new", style="primary")],
        [btn("📬 Мои обращения", "u:ticket:list")],
        [btn("↩️ В меню", "u:menu")],
    )


# ------------------------------------------------------ нет конфига

def no_config_kb() -> InlineKeyboardMarkup:
    return markup([
        btn("💾 Создать конфиг", "u:reg", style="success"),
        btn("↩️ Назад", "u:menu"),
    ])


def panel_down_kb() -> InlineKeyboardMarkup:
    """Панель недоступна: только обновление/выход, без создания конфига."""
    return markup(
        [btn("🔄 Обновить", "u:traffic", style="primary")],
        [
            btn("↩️ В меню", "u:menu"),
        ],
    )


def config_missing_kb() -> InlineKeyboardMarkup:
    """Подписка в боте есть, а в панели нет — разрешаем пересоздать."""
    return markup(
        [btn("♻️ Пересоздать конфиг", "u:reg", style="success")],
        [
            btn("🔄 Обновить", "u:traffic"),
            btn("↩️ В меню", "u:menu"),
        ],
    )


# ------------------------------------------------------ флоу регистрации

def step_app_kb() -> InlineKeyboardMarkup:
    return markup(
        [btn("📱 Android / iPhone — WDTT", "u:app:WDTT", style="primary")],
        [btn("↩️ Отменить создание", "u:menu", style="danger")],
    )


def agreement_kb() -> InlineKeyboardMarkup:
    return markup(
        [btn("✅ Да, продолжить", "u:agree:ok", style="success")],
        [btn("↩️ Отменить создание", "u:menu", style="danger")],
    )


def hash_prompt_kb() -> InlineKeyboardMarkup:
    return markup([
        btn("📖 Где взять ссылку?", "u:hash:help"),
        btn("↩️ Отменить", "u:menu", style="danger"),
    ])


def hash_added_kb(hashes: list, max_h: int = 4) -> InlineKeyboardMarkup:
    rows = []

    hash_buttons = [
        btn(f"❌ …{h[-4:]}", f"u:hash:rm:{h}", style="danger")
        for h in hashes
    ]

    for i in range(0, len(hash_buttons), 2):
        rows.append(hash_buttons[i:i + 2])

    if len(hashes) < max_h:
        rows.append([
            btn("➕ Добавить ещё", "u:hash:add"),
        ])

    rows.append([
        btn(
            "✅ Продолжить с одним" if len(hashes) == 1 else "✅ Продолжить",
            "u:hash:done",
            style="success",
        ),
    ])

    rows.append([
        btn("📖 Где взять ссылку?", "u:hash:help"),
        btn("↩️ Отменить", "u:menu", style="danger"),
    ])

    return markup(*rows)


def hash_help_kb() -> InlineKeyboardMarkup:
    return markup([
        btn("🔙 К хешам", "u:hash:add"),
        btn("↩️ Отменить", "u:menu", style="danger"),
    ])


def done_kb(
    ios_link: str = "",
    android_link: str = "",
) -> InlineKeyboardMarkup:
    rows = []

    if ios_link:
        rows.append([copy_btn("🍏 Скопировать iOS WDTT", ios_link)])

    if android_link:
        rows.append([copy_btn("🤖 Скопировать Android WDTT", android_link)])

    rows.append([
        btn("↗️ Подписка", "u:sub", style="primary"),
        btn("↩️ В меню", "u:menu"),
    ])

    return markup(*rows)


def show_link_kb() -> InlineKeyboardMarkup:
    return markup([
        btn("🔙 Мой конфиг", "u:traffic"),
        btn("↩️ В меню", "u:menu"),
    ])


# ------------------------------------------------------------- конфиг

def config_kb(
    sub_url: str = "",
    ios_link: str = "",
    android_link: str = "",
) -> InlineKeyboardMarkup:
    rows = []

    if sub_url:
        rows.append([
            btn("🌐 Подписка", url=sub_url, style="primary"),
            btn("🗑 Удалить", "u:del1", style="danger"),
        ])
    else:
        rows.append([
            btn("🗑 Удалить", "u:del1", style="danger"),
        ])

    if ios_link and android_link:
        rows.append([
            copy_btn("🍏 iOS — WDTT", ios_link),
        ])
        rows.append([
            copy_btn("🤖 Android — WDTT", android_link),
        ])

    rows.append([
        btn("↩️ В меню", "u:menu"),
    ])

    return markup(*rows)


def sub_kb(sub_url: str = "") -> InlineKeyboardMarkup:
    rows = []

    if sub_url:
        rows.append([
            btn("🌐 Открыть подписку", url=sub_url, style="primary"),
        ])

    rows.append([
        btn("📱 Трафик", "u:traffic"),
        btn("↩️ В меню", "u:menu"),
    ])

    return markup(*rows)


def referral_kb() -> InlineKeyboardMarkup:
    return markup([
        btn("↩️ В меню", "u:menu"),
    ])


def menu_back_kb(sections: list | None = None) -> InlineKeyboardMarkup:
    """Кнопка возврата в меню (+ соседние разделы для листания)."""
    rows = []
    for i in range(0, len(sections or []), 2):
        pair = sections[i:i + 2]
        rows.append([btn(f"📂 {s.get('title') or s['key']}",
                         f"u:sec:{s['key']}") for s in pair])
    rows.append([btn("↩️ В меню", "u:menu")])
    return markup(*rows)


def apps_kb(links: list) -> InlineKeyboardMarkup:
    rows = [
        [btn(str(link.get("label", "Открыть")), url=link["url"])]
        for link in links
        if link.get("url")
    ]

    rows.append([
        btn("↩️ В меню", "u:menu"),
    ])

    return markup(*rows)


# ------------------------------------------------------------- каналы

def subscribe_kb(channels: list) -> InlineKeyboardMarkup:
    rows = []

    for ch in channels:
        username = ch.get("username")
        channel_id = ch.get("channel_id")
        url = ch.get("url")

        if not url and username:
            url = f"https://t.me/{username.lstrip('@')}"

        if not url and channel_id:
            url = f"https://t.me/c/{str(channel_id).replace('-100', '')}"

        if not url:
            continue

        title = ch.get("title") or username or str(channel_id)

        rows.append([
            btn(f"📺 {title}", url=url),
        ])

    rows.append([
        btn("🔄 Я подписался — проверить", "chk:r", style="success"),
    ])

    return markup(*rows)


# ---------------------------------------------------------------- админка

def adm_root_kb() -> InlineKeyboardMarkup:
    return markup(
        [
            btn("📊 Статистика", "adm:stat"),
            btn("👥 Пользователи", "adm:usr"),
        ],
        [
            btn("📤 Рассылка", "adm:bc"),
            btn("📺 Каналы", "adm:chn"),
        ],
        [
            btn("🎯 Реклама", "adm:ads"),
            btn("⚙️ Настройки", "adm:set"),
        ],
        [
            btn("🔌 Сервер / подключения", "adm:srv", style="primary"),
        ],
    )


def adm_back_kb(target: str = "adm") -> InlineKeyboardMarkup:
    return markup([
        btn("⬅️ В админку", target),
    ])


def srv_kb() -> InlineKeyboardMarkup:
    return markup(
        [
            btn("♻️ Рестарт WDTT", "adm:srv:rw", style="warn"),
            btn("♻️ Рестарт Xray", "adm:srv:rx", style="warn"),
        ],
        [
            btn("🔄 Обновить", "adm:srv"),
            btn("⬅️ В админку", "adm"),
        ],
    )


def profile_kb() -> InlineKeyboardMarkup:
    return markup(
        [
            btn(
                "🚀 Реферальная программа",
                "u:ref",
                style="success",
            ),
        ],
        [
            btn("↩️ В меню", "u:menu"),
        ],
    )