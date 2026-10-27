# -*- coding: utf-8 -*-
"""Тексты экранов бота (HTML).

Стиль: коротко, по делу, трафик — на видном месте.
"""
from __future__ import annotations

from .wdtt import (
    expires_text,
    human_bytes,
    traffic_bar,
    user_status,
)


def esc(value) -> str:
    if value is None:
        return ""
    return (
        str(value)
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )


def quote(text: str) -> str:
    return f"<blockquote>{text}</blockquote>" if text else ""


DEFAULT_APP_LINKS = [
    {
        "label": "🤖 Android — qWDTT",
        "url": "https://github.com/ildarmaga/qwdtt/releases",
    },
    {
        "label": "📱 Android/iPhone — WDTT",
        "url": "https://github.com/ildarmaga/wdtt/releases",
    },
    {
        "label": "🍏 iOS — VK Turn Proxy",
        "url": "https://apps.apple.com/app/vk-turn-proxy/id6477145458",
    },
    {
        "label": "💻 Windows/Linux — PWDTT",
        "url": "https://github.com/ildarmaga/pwdtt-client/releases",
    },
]

DEFAULT_AGREEMENT = (
    "Сервис работает по технологии WDTT: трафик идёт через медиарелеи ВК "
    "и шифруется DTLS 1.2.\n\n"
    "• технология предоставляется «как есть», возможны перебои;\n"
    "• логи подключений не ведутся;\n"
    "• доступ зависит от доступности серверов ВК;\n"
    "• запрещено использовать сервис для противоправных действий.\n\n"
    "Продолжая, вы принимаете эти условия."
)


# ------------------------------------------------------------ трафик


def traffic_line(user: dict) -> str:
    total_gb = user.get("total_gb")
    used = user.get("traffic_used_bytes")

    bar, used_s, total_s, pct = traffic_bar(used, total_gb)

    if total_s == "∞":
        return f"📊 <b>{used_s}</b> · безлимит"

    return f"📊 <b>{used_s}</b> / {total_s} · <b>{pct}%</b>\n<code>{bar}</code>"


def _snapshot(user: dict) -> dict:
    """Данные панели, сохранённые в профиле бота."""
    return {
        "total_gb": user.get("panel_total_gb", user.get("sub_total_gb", 0)),
        "traffic_used_bytes": user.get(
            "panel_traffic_used_bytes", user.get("sub_traffic_used_bytes", 0)
        ),
        "expires_at": user.get(
            "panel_expires_at", user.get("sub_expires_at", 0)
        ),
        "max_devices": user.get(
            "panel_max_devices", user.get("sub_max_devices", 1)
        ),
        "devices_bound": user.get("panel_devices_bound", 0),
        "online": user.get("panel_online", False),
        "active": user.get("panel_active", True),
        "status": user.get("panel_status", "active"),
        "subscription_url": user.get("subscription_url", ""),
        "link": user.get("panel_link", user.get("wdtt_link", "")),
    }


def status_line(user: dict) -> str:
    status, _ = user_status(user)
    expires = expires_text(user.get("expires_at"))
    devices = f"{user.get('devices_bound') or 0}/{user.get('max_devices') or '?'}"
    return f"📅 {expires} · 👥 {devices} · {status}"


# ------------------------------------------------------------ меню


def _name(user: dict) -> str:
    return esc(
        user.get("full_name")
        or user.get("first_name")
        or (f"@{user['username']}" if user.get("username") else "")
        or user.get("tg_id")
        or "друг"
    )


def menu_text(user: dict, live: dict | None = None) -> str:
    return (f"👋 <b>Привет, {_name(user)}!</b>\n\n"
            "Это сервис подключения через WDTT. Здесь можно получить доступ, "
            "настроить приложение и управлять подключёнными устройствами.\n\n"
            "Открой «Мой доступ», чтобы найти подписку и проверить её состояние. "
            "В профиле находится реферальная программа, а в инструкции — шаги подключения."
            if user.get("registered") else
            f"👋 <b>Привет, {_name(user)}!</b>\n\n"
            "Это сервис подключения через WDTT. Создай доступ, затем установи "
            "приложение и добавь в него ссылку подписки. Инструкция поможет начать, "
            "а поддержка ответит на вопросы.")


def no_config_text() -> str:
    return "🔑 <b>Доступ не создан</b>\n\nНажми «Создать доступ» — это займёт пару секунд."


def no_slots_text() -> str:
    return "🚷 <b>Свободных мест нет</b>\n\nРегистрация временно закрыта. Попробуй позже."


def panel_down_text() -> str:
    return (
        "🔌 <b>Панель недоступна</b>\n\n"
        "Данные не удалось обновить. Доступ не потерян — попробуй ещё раз через минуту."
    )


def config_missing_text() -> str:
    return (
        "⚠️ <b>Доступ не найден в панели</b>\n\n"
        "Скорее всего, его удалили вручную. Можно создать новый."
    )


# ------------------------------------------------------------ доступ


def access_text(
    user: dict,
    live: dict,
    links: list | None = None,
    shown: int = 5,
) -> str:
    links = links or []
    total_nodes = len(links)
    password = (
        live.get("password")
        or user.get("panel_password")
        or live.get("id")
        or "—"
    )

    lines = [
        "📱 <b>Мой доступ</b>",
        "",
        f"🔐 <code>{esc(password)}</code>",
        traffic_line(live),
        status_line(live),
    ]

    sub_url = live.get("subscription_url") or user.get("subscription_url") or ""
    if sub_url:
        lines += ["", "📦 <b>Ссылка подписки</b>", f"<code>{esc(sub_url)}</code>"]
    else:
        lines += ["", "📦 Панель пока не предоставила ссылку подписки."]
    lines += ["", "Добавь ссылку подписки в приложение и обновляй её при изменении серверов. "
              "В разделе «Устройства» можно проверить привязки."]

    return "\n".join(lines)


def sub_text(user: dict, live: dict, links: list | None = None) -> str:
    sub_url = live.get("subscription_url") or user.get("subscription_url") or ""
    sub_id = live.get("sub_id") or user.get("sub_id") or "—"

    lines = [
        "📦 <b>Подписка</b>",
        "",
        f"🆔 <code>{esc(sub_id)}</code>",
        traffic_line(live),
        status_line(live),
    ]

    if links:
        lines.append(f"🌍 Нод в подписке: <b>{len(links)}</b>")

    if sub_url:
        lines += ["", f"<code>{esc(sub_url)}</code>"]

    lines += ["", "Добавь ссылку подписки в поддерживающее её приложение. "
              "При изменении списка серверов обнови подписку в приложении."]

    return "\n".join(lines)


def node_link_text(index: int, link: str, name: str = "") -> str:
    title = f" · {esc(name)}" if name else ""
    return (
        f"🔗 <b>Ссылка{title}</b>\n\n"
        f"<code>{esc(link)}</code>\n\n"
        "Нажми на ссылку, чтобы скопировать."
    )


def agree_text(settings: dict) -> str:
    return (
        "📜 <b>Соглашение</b>\n\n"
        + quote(settings.get("agreement_text") or DEFAULT_AGREEMENT)
        + "\n\nНажми «Принимаю», чтобы создать доступ."
    )


def done_text(
    password: str,
    limit_gb: int,
    dev: int,
    app: str = "WDTT",
    hashes: list | None = None,
    sub_url: str = "",
    wdtt_link: str = "",
    ios_link: str = "",
    android_link: str = "",
) -> str:
    """Совместимость со старым флоу."""
    lines = [
        "✅ <b>Доступ создан</b>",
        "",
        f"🔐 <code>{esc(password)}</code>",
        f"📊 <b>{limit_gb or '∞'} ГБ</b> · 👥 {dev}",
    ]

    if android_link:
        lines += ["", "🤖 Android", f"<code>{esc(android_link)}</code>"]
    elif wdtt_link:
        lines += ["", f"<code>{esc(wdtt_link)}</code>"]

    if ios_link:
        lines += ["", "🍏 iOS", f"<code>{esc(ios_link)}</code>"]

    if sub_url:
        lines += ["", "📦 Подписка", f"<code>{esc(sub_url)}</code>"]

    return "\n".join(lines)


# ------------------------------------------------------------ кабинет


def profile_text(user: dict) -> str:
    username = f"@{esc(user['username'])}" if user.get("username") else "—"
    lines = [
        "👤 <b>Профиль</b>",
        "",
        f"ID: <code>{user.get('tg_id')}</code>",
        f"Имя: <b>{_name(user)}</b>",
        f"Username: {username}",
        f"Регистрация: {'есть' if user.get('registered') else 'нет'}",
        f"Приглашено: <b>{int(user.get('referrals') or 0)}</b>",
    ]

    if user.get("registered"):
        data = _snapshot(user)
        if data.get("total_gb") or data.get("traffic_used_bytes"):
            lines += ["", traffic_line(data)]

    return "\n".join(lines)


# ------------------------------------------------------------ инструкция


def help_text() -> str:
    return (
        "🏳️ <b>Подключение</b>\n\n"
        "1. Установи приложение для своей платформы.\n"
        "2. Открой «Мой доступ» и скопируй ссылку подписки.\n"
        "3. Добавь подписку в приложение и подключись.\n\n"
        "Если приложение поддерживает подписки, добавь ссылку из раздела «Подписка»: "
        "так будет проще обновлять список серверов.\n\n"
        "Если подключиться не получается, проверь доступный трафик и срок действия, "
        "попробуй другую ноду и обратись в поддержку с текстом ошибки."
    )


# ------------------------------------------------------------ совместимость


def wdtt_configs(live: dict, hashes: list | None = None, host: str = "") -> dict:
    """Старый формат ссылок. Нужен только как fallback."""
    if not host:
        host = live.get("server_host") or live.get("server_ip") or ""
    dtls = live.get("dtls_port") or 0
    wg = live.get("wg_port") or 0
    lp = live.get("client_port") or 0
    pwd = live.get("password_key") or live.get("password") or ""
    vk = ",".join(h for h in (hashes or []) if h) or "VK_HASH"

    return {
        "ios": f"wdtt://{host}:{dtls}:{wg}:0:{pwd}:{vk}",
        "android": f"wdtt://{host}:{dtls}:{wg}:{lp}:{pwd}:{vk}",
    }


def config_text(
    live: dict,
    hashes: list | None = None,
    app: str = "WDTT",
    created_at=None,
    include_links: bool = True,
    host: str = "",
) -> str:
    """Совместимость: карточка доступа из данных панели."""
    password = live.get("password") or live.get("password_key") or "—"
    lines = [
        "📱 <b>Мой доступ</b>",
        "",
        f"🔐 <code>{esc(password)}</code>",
        traffic_line(live),
        status_line(live),
    ]

    if include_links:
        link = live.get("link") or live.get("subscription_url") or ""
        if link:
            lines += ["", f"<code>{esc(link)}</code>"]

    return "\n".join(lines)


def sub_text_legacy(
    live: dict,
    hashes: list | None = None,
    app: str = "WDTT",
) -> str:
    return sub_text({}, live, [])


def hash_intro(app_name: str = "WDTT") -> str:
    return agree_text({})


def hash_added_text(hashes: list | None = None, max_h: int = 4) -> str:
    return "✅ VK-хеши больше не нужны — панель выдаёт готовую ссылку."


HASH_HELP = "🔗 Ссылки выдаёт панель автоматически."
STEP_APP = "📱 Нажми «Продолжить», чтобы создать доступ."
AGREEMENT_HEAD = "📜 <b>Соглашение</b>\n\n"


# Для удобства внешних вызовов
__all__ = [
    "esc", "quote", "DEFAULT_APP_LINKS", "DEFAULT_AGREEMENT",
    "traffic_line", "menu_text", "no_config_text", "no_slots_text",
    "panel_down_text", "config_missing_text", "access_text", "sub_text",
    "node_link_text", "agree_text", "done_text", "profile_text",
    "help_text", "wdtt_configs", "config_text", "sub_text_legacy",
    "hash_intro", "hash_added_text", "HASH_HELP", "STEP_APP",
    "AGREEMENT_HEAD", "human_bytes",
]
