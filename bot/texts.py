# -*- coding: utf-8 -*-
"""Все тексты пользовательских экранов (HTML)."""

import html
import bot.config as config

def esc(s) -> str:
    if not s:
        return ""
    return (
        str(s)
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )


def quote(text: str) -> str:
    """Оборачивает длинный текст в Telegram HTML blockquote."""
    if not text:
        return ""
    return f"<blockquote>{text}</blockquote>"


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
        "label": "💻 Desktop — PWDTT",
        "url": "https://github.com/ildarmaga/pwdtt-client/releases",
    },
]


DEFAULT_AGREEMENT = (
    "<b>📜 Пользовательское соглашение</b>\n\n"
    "Это <b>тестовая технология</b>. Она предоставляется «как есть» (AS IS) "
    "без каких-либо гарантий работоспособности, стабильности и отсутствия "
    "сбоев. Используя сервис, ты соглашаешься с тем, что:\n\n"
    "• трафик шифруется (DTLS 1.2), логи подключений не ведутся;\n"
    "• доступ работает через TURN-серверы VK Звонков и зависит от их доступности;\n"
    "• администрация может временно приостановить доступ без объяснения причин;\n"
    "• ты не используешь сервис для противоправных действий.\n\n"
    "Нажимая «Да, продолжить», ты подтверждаешь согласие с условиями."
)


def hello_text(user: dict) -> str:
    name = user.get("full_name") or f"id{user.get('tg_id', '')}"
    return f"👋 Привет, <b>{esc(name)}</b>!"


def app_caption(app: str) -> str:
    return {
        "WDTT": "WDTT (Android+iOS)",
        "qWDTT": "qWDTT (Android)",
    }.get(app, app)


# ------------------------------------------------------------ меню

def menu_text(user: dict, limit_gb: int = 175) -> str:
    text = (
        "👋 <b>NTTunnel</b>\n\n"
        "WireGuard через TURN-серверы VK Звонков.\n"
        "Трафик шифруется DTLS 1.2 — работает там, где заблокирован обычный VPN.\n\n"
        "<blockquote><b>Возможности:</b>\n"
        "• 1 устройство\n"
        f"• {limit_gb} ГБ трафика в месяц\n"
        "• +5 ГБ за каждого приглашённого\n\n</blockquote>"
        "Нужны активные ссылки на VK Звонок."
    )
    return text


def no_config_text() -> str:
    text = (
        "<b>Что нужно:</b>\n"
        "Активная ссылка на VK Звонок — она нужна для получения TURN credentials.\n\n"
        "<b>Как получить:</b>\n"
        "ВК → Мессенджер → Звонки → Создать → Скопировать ссылку\n"
        "⚠️ Не нажимай «Завершить для всех»"
    )
    return (
        "🔑 <b>У тебя пока нет конфига.</b>\n\n"
        f"{quote(text)}"
    )


def no_slots_text() -> str:
    return (
        "🚷 <b>Нет мест</b>\n\n"
        "Регистрация временно закрыта. Попробуй позже."
    )


def panel_down_text() -> str:
    """Панель недоступна — конфиг на месте, просто не удалось прочитать."""
    return (
        "🔌 <b>Панель временно недоступна</b>\n\n"
        "<blockquote>Не удалось получить данные подписки из панели WDTT.\n\n"
        "Твой конфиг никуда не пропал — это сбой связи. "
        "Подожди минуту и нажми «Обновить».</blockquote>"
    )


def config_missing_text() -> str:
    """Бот считает, что подписка есть, а панель её не отдаёт."""
    return (
        "🔑 <b>Конфиг не найден в панели</b>\n\n"
        "<blockquote>В боте подписка числится, но панель WDTT не отдаёт "
        "по ней данные.\n\n"
        "Обычно так бывает, если конфиг удалили в панели или сбросили её "
        "базу.\n\n"
        "Нажми «Пересоздать конфиг» — старая запись будет заменена новой."
        "</blockquote>"
    )


# ------------------------------------------------------ флоу регистрации

STEP_APP = (
    "🔑 <b>У тебя пока нет конфига.</b>\n\n"
    "<blockquote>"
    "<b>Что нужно:</b>\n"
    "Активная ссылка на VK Звонок — она нужна для получения TURN credentials.\n\n"
    "<b>Как получить:</b>\n"
    "ВК → Мессенджер → Звонки → Создать → Скопировать ссылку\n"
    "⚠️ Не нажимай «Завершить для всех»"
    "</blockquote>\n\n"
    "—— <b>Шаг 1 из 3 — приложение</b> ——\n\n"
    "Выбери приложение, в котором будешь использовать конфиг:\n\n"
    "• <b>qWDTT</b> — рекомендуемый вариант для Android.\n"
    "• <b>WDTT</b> — подходит для Android и iPhone."
)


AGREEMENT_HEAD = "📜 <b>Соглашение</b>\n\n"


HASH_HELP = (
    "🔗 <b>VK-хеш звонка</b>\n\n"
    "<blockquote>"
    "VK-хеш — часть ссылки на звонок вида:\n"
    "<code>https://vk.com/call/join/XXXXXXXXXX</code>\n"
    "или просто <code>XXXXXXXXXX</code> после /join/.\n\n"
    "<b>Как взять:</b>\n"
    "1️⃣ VK → Мессенджер → Звонки → «+» → «Создать звонок»\n"
    "2️⃣ Скопируй ссылку (или хеш после /join/)"
    "</blockquote>"
)


def hash_intro(app_name: str = "WDTT") -> str:
    return (
        "—— <b>Шаг 2 из 3 — VK-хеши</b> ——\n\n"
        f"✅ <b>Выбрано приложение:</b> {esc(app_name)}\n\n"
        "🔗 <b>Добавь VK-хеш звонка</b>\n\n"
        "<blockquote>"
        "VK-хеш — это часть ссылки на звонок. Он нужен приложению для "
        "подключения через серверы VK.\n\n"
        "Пришли полную ссылку или только хеш после <code>/join/</code>:\n"
        "• <code>https://vk.com/call/join/XXXXXXXXXX</code>\n"
        "• <code>XXXXXXXXXX</code>\n\n"
        "Одного хеша достаточно. Дополнительные хеши могут повысить "
        "стабильность и скорость. Можно добавить до четырёх."
        "</blockquote>"
    )


def hash_added_text(hashes: list, max_h: int = 4) -> str:
    n = len(hashes)
    left = max(max_h - n, 0)

    tail = ", ".join(h[-4:] for h in hashes) or "—"

    if n >= max_h:
        return (
            "—— <b>Шаг 2 из 3 — VK-хеши</b> ——\n\n"
            f"✅ <b>Добавлено {n}/{max_h} — максимум.</b>"
        )

    return (
        "—— <b>Шаг 2 из 3 — VK-хеши</b> ——\n\n"
        f"✅ <b>Хеш добавлен ({n}/{max_h}).</b>\n\n"
        f"<blockquote>"
        "Одного хеша достаточно. Можно добавить ещё "
        f"<b>{left}</b> для повышения стабильности и скорости.\n"
        f"Добавленные (последние 4 симв.): "
        f"<code>{esc(tail)}</code>"
        f"</blockquote>"
    )


# ------------------------------------------------------ готовый конфиг

def done_text(
    password: str,
    limit_gb: int,
    dev: int,
    app: str,
    hashes: list,
    sub_url: str = "",
    wdtt_link: str = "",
    ios_link: str = "",
    android_link: str = "",
) -> str:
    """Финальный экран «Шаг 3 — готово».

    Сразу показывает WDTT-ссылки для iOS и Android (не «ссылку из словаря»).
    """
    lines = [
        "—— <b>Шаг 3 из 3 — готово</b> ——\n",
        "✅ <b>Доступ создан!</b>\n",
        f"🔐 Пароль: <code>{esc(password)}</code>",
        f"📊 Лимит: <b>{limit_gb or '∞'} ГБ</b>/мес",
        "👥 За каждого друга: +5 ГБ",
        f"📱 Формат: <b>{esc(app_caption(app))}</b>",
        "",
        f"📌 VK хеши ({len(hashes)}):",
    ]

    for i, h in enumerate(hashes, 1):
        lines.append(f"{i}. <code>{esc(h)}</code>")

    lines += [
        "",
        f"⚠️ Только для {max(dev, 1)} устройства.",
    ]

    # Сразу выводим WDTT-ссылки iOS + Android (не «ссылку из словаря»).
    if android_link:
        lines += [
            "",
            "🤖 <b>WDTT — Android</b>",
            f"<code>{esc(android_link)}</code>",
        ]

    if ios_link:
        lines += [
            "",
            "🍏 <b>WDTT — iOS</b>",
            f"<code>{esc(ios_link)}</code>",
        ]

    lines += [
        "",
        "Нажми «Показать ссылку» и открой её в выбранном приложении.",
    ]

    return "\n".join(lines)


# ------------------------------------------------------ трафик

def _fmt_size(b) -> str:
    try:
        b = float(b or 0)
    except (TypeError, ValueError):
        return "0 Б"

    if b < 1024:
        return f"{int(b)} Б"

    for unit in ("КБ", "МБ", "ГБ"):
        b /= 1024
        if b < 1024 or unit == "ГБ":
            return f"{b:.1f} {unit}"

    return f"{b:.1f} ГБ"


def traffic_bar(used_bytes, total_gb) -> tuple[str, str, int]:
    try:
        total_b = float(total_gb or 0) * 1024 ** 3
        used_b = float(used_bytes or 0)
    except (TypeError, ValueError):
        total_b, used_b = 0.0, 0.0

    pct = (
        int(min(used_b / total_b * 100, 100))
        if total_b
        else 0
    )

    filled = max(min(pct // 10, 10), 0)
    bar = "[" + "█" * filled + "░" * (10 - filled) + "]"

    return bar, _fmt_size(used_b), pct


# ------------------------------------------------------ конфиг

def wdtt_configs(
    live: dict,
    hashes: list,
    host: str = "",
) -> dict:
    """Возвращает WDTT-конфиги для iOS и Android (порт клиента разный).

    Форматы (как в панели):
      iOS — VK Turn Proxy:  wdtt://IP:dtls:wg:0:pwd:hash
      Android — WDTT:       wdtt://IP:dtls:wg:lp:pwd:hash

    host — хост панели (без порта и пути). Если не передан, берётся
    из live["server_host"], иначе пустой.
    """
    if not host:
        host = live.get("server_host") or live.get("server_ip") or ""
    dtls = live.get("dtls_port") or 0
    wg = live.get("wg_port") or 0
    lp = live.get("client_port") or 0
    pwd = live.get("password_key") or ""
    vk = ",".join(h for h in (hashes or []) if h) or "VK_HASH"

    ios = f"wdtt://{host}:{dtls}:{wg}:0:{pwd}:{vk}"
    android = f"wdtt://{host}:{dtls}:{wg}:{lp}:{pwd}:{vk}"

    return {
        "ios": ios,
        "android": android,
    }


def config_text(
    live: dict,
    hashes: list,
    app: str = "WDTT",
    created_at=None,
    include_links: bool = True,
    host: str = "",
) -> str:
    pwd = live.get("password_key") or live.get("password") or "—"
    total_gb = live.get("total_gb") or 0
    sub_url = live.get("sub_url") or ""

    bar, used_s, pct = traffic_bar(
        live.get("traffic_used"),
        total_gb,
    )

    total_s = f"{float(total_gb):.2f} ГБ" if total_gb else "∞"
    vk = (
        hashes[0] + ("…" if len(hashes) > 1 else "")
        if hashes
        else "—"
    )

    lines = [
        "🔑 <b>Твой конфиг</b>\n",
        "<blockquote>",
        f"📱 Формат: <b>{esc(app_caption(app))}</b>",
        f"🔐 Пароль: <code>{esc(pwd)}</code>",
        f"🔗 VK Хеш: <code>{esc(vk)}</code>",
        "📅 Истекает: ♾️ бессрочный",
        "",
        f"📊 Трафик: {esc(used_s)} / {esc(total_s)} "
        f"{bar} {pct}%",
        "</blockquote>",
    ]

    if include_links:
        cfg = wdtt_configs(live, hashes, host=host)

        if sub_url:
            lines += [
                "",
                "🌐 <b>Подписка (ссылкa):</b>",
                f"<code>{esc(sub_url)}</code>",
            ]

        lines += [
            "",
            "📱 <b>WDTT — Android</b>",
            f"<code>{esc(cfg['android'])}</code>",
            "",
            "🍏 <b>WDTT — iOS</b>",
            f"<code>{esc(cfg['ios'])}</code>",
        ]

    return "\n".join(lines)


# ------------------------------------------------------ подписка

def sub_text(
    live: dict,
    hashes: list,
    app: str = "WDTT",
) -> str:
    sub_url = live.get("sub_url") or ""
    sub_id = live.get("sub_id") or "—"

    total_gb = live.get("total_gb") or 0

    bar, used_s, pct = traffic_bar(
        live.get("traffic_used"),
        total_gb,
    )

    total_s = f"{float(total_gb):.2f} ГБ" if total_gb else "∞"

    status = ("🟢 активна" if live.get("active", True)
              else "⏸ приостановлена")
    online = "🟢 в сети" if live.get("online") else "⚪ не в сети"
    expires = live.get("expires") or "бессрочно"

    lines = [
        "📄 <b>Информация о подписке</b>\n",
        f"🆔 ID подписки: <code>{esc(sub_id)}</code>",
        f"Статус: <b>{status}</b>",
        f"📡 Онлайн: <b>{online}</b>",
        f"📊 Использовано: {esc(used_s)}",
        f"💾 Общий лимит: {esc(total_s)}",
        f"⏰ Срок действия: {esc(expires)}",
        "",
    ]

    if sub_url:
        lines += [
            "🌐 <b>Подписка URL</b>",
            f"<code>{esc(sub_url)}</code>",
            "",
        ]

    return "\n".join(lines)