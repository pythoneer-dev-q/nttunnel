# -*- coding: utf-8 -*-
"""Общие утилиты."""

import logging
import re
import time
from typing import Optional

from aiogram.exceptions import TelegramBadRequest
from aiogram.types import CallbackQuery, InlineKeyboardMarkup

log = logging.getLogger(__name__)


# ------------------------------------------------------------------ Telegram


async def safe_edit(
    msg,
    text: str,
    kb: Optional[InlineKeyboardMarkup] = None,
) -> bool:
    """Безопасно редактирует сообщение.

    Возвращает True, если сообщение успешно изменено
    или Telegram сообщил, что оно уже содержит эти данные.
    """
    try:
        # Не делаем лишний API-запрос, если текст и клавиатура уже совпадают.
        if msg.text == text and msg.reply_markup == kb:
            return True

        await msg.edit_text(
            text=text,
            reply_markup=kb,
        )
        return True

    except TelegramBadRequest as e:
        error = str(e).lower()

        if "message is not modified" in error or "not modified" in error:
            return True

        log.debug("safe_edit failed: %s", e)
        return False


async def answer_or_alert(
    cb: CallbackQuery,
    text: str = "",
    alert: bool = False,
):
    """Безопасно отвечает на callback query."""
    try:
        await cb.answer(
            text=text or None,
            show_alert=alert,
        )
    except TelegramBadRequest:
        pass


def back_line(
    title: str = "⬅️ Назад",
) -> InlineKeyboardMarkup:
    """Однокнопочная заглушка/кнопка назад."""
    from aiogram.utils.keyboard import InlineKeyboardBuilder

    kb = InlineKeyboardBuilder()
    kb.button(
        text=title,
        callback_data="noop",
    )

    return kb.as_markup()


# ------------------------------------------------------------------ Пагинация


def build_page_kb(
    prefix: str,
    page: int,
    pages: int,
    items: list[tuple[str, str]],
) -> InlineKeyboardMarkup:
    """Кнопки списка + компактная пагинация."""

    from aiogram.types import InlineKeyboardButton
    from aiogram.utils.keyboard import InlineKeyboardBuilder

    kb = InlineKeyboardBuilder()

    for label, callback_data in items:
        kb.button(
            text=label[:64],
            callback_data=callback_data,
        )

    nav: list[InlineKeyboardButton] = []

    if page > 0:
        nav.append(
            InlineKeyboardButton(
                text="⬅️",
                callback_data=f"{prefix}:p{page - 1}",
            )
        )

    if pages > 1:
        nav.append(
            InlineKeyboardButton(
                text=f"{page + 1}/{pages}",
                callback_data="noop",
            )
        )

    if page < pages - 1:
        nav.append(
            InlineKeyboardButton(
                text="➡️",
                callback_data=f"{prefix}:p{page + 1}",
            )
        )

    if nav:
        kb.row(*nav)

    return kb.as_markup()


def yes_no_kb(
    prefix: str,
    yes_cb: str,
    no_cb: str,
    yes_label: str = "✅ Да",
    no_label: str = "❌ Нет",
) -> InlineKeyboardMarkup:
    """Компактная пара Да/Нет.

    prefix оставлен в сигнатуре для совместимости со старым кодом.
    """
    from aiogram.utils.keyboard import InlineKeyboardBuilder

    kb = InlineKeyboardBuilder()

    kb.button(
        text=yes_label,
        callback_data=yes_cb,
    )
    kb.button(
        text=no_label,
        callback_data=no_cb,
    )

    return kb.adjust(1).as_markup()


def page_slice(
    items: list,
    page: int,
    size: int = 8,
):
    """Возвращает (элементы страницы, всего страниц, текущая страница)."""

    if size <= 0:
        size = 8

    total_pages = max(
        (len(items) + size - 1) // size,
        1,
    )

    page = max(
        min(page, total_pages - 1),
        0,
    )

    start = page * size
    end = start + size

    return (
        items[start:end],
        total_pages,
        page,
    )


# ------------------------------------------------------------------ Форматирование


def fmt_dt(dt) -> str:
    """Форматирует datetime в компактный вид."""

    if not dt:
        return "—"

    try:
        return dt.strftime("%d.%m.%Y %H:%M")
    except Exception:  # noqa: BLE001
        return str(dt)


def strip_tags(s: str) -> str:
    """Удаляет Telegram/HTML-теги из строки."""
    return re.sub(
        r"<[^>]+>",
        "",
        s or "",
    )


def blockquote(text: str) -> str:
    """Оборачивает текст в Telegram HTML blockquote."""

    if not text:
        return ""

    return f"<blockquote>{text}</blockquote>"


# ------------------------------------------------------------------ URL


URL_RE = re.compile(
    r"https?://\S+",
    re.IGNORECASE,
)


def extract_url(s: str) -> Optional[str]:
    """Извлекает первый HTTP/HTTPS URL."""

    if not s:
        return None

    match = URL_RE.search(s)

    if not match:
        return None

    url = match.group(0).rstrip(")>,.;")

    if "://" not in url:
        return None

    return url[:255]


# ------------------------------------------------------------------ VK hash


VK_HASH_RE = re.compile(
    r"/join[/:]\s*([A-Za-z0-9_-]+)",
    re.IGNORECASE,
)

VK_BARE_HASH_RE = re.compile(
    r"^\s*([A-Za-z0-9_-]{6,64})\s*$",
)


def extract_vk_hash(s: str) -> Optional[str]:
    """Достаёт VK-хеш звонка.

    Поддерживает:

        https://vk.com/call/join/XXXXXXXXXX
        vk.com/call/join/XXXXXXXXXX
        /join/XXXXXXXXXX
        /join:XXXXXXXXXX
        XXXXXXXXXX
    """

    if not s:
        return None

    s = s.strip()

    # Полная/частичная ссылка:
    match = VK_HASH_RE.search(s)

    if match:
        value = match.group(1)

        if 6 <= len(value) <= 64:
            return value

        return None

    # Голый хеш.
    # Не принимаем строки, похожие на URL.
    if (
        "http" not in s.lower()
        and "/" not in s
        and "." not in s
        and " " not in s
    ):
        match = VK_BARE_HASH_RE.fullmatch(s)

        if match:
            return match.group(1)

    return None


# ------------------------------------------------------------------ TTL cache


class TTLCache:
    """Простой in-memory TTL-кэш."""

    __slots__ = (
        "ttl",
        "_data",
    )

    def __init__(
        self,
        ttl_seconds: float = 90.0,
    ):
        self.ttl = float(ttl_seconds)
        self._data: dict = {}

    def get(self, key):
        """Возвращает значение или None при отсутствии/истечении TTL."""

        item = self._data.get(key)

        if item is None:
            return None

        value, timestamp = item

        if time.time() - timestamp > self.ttl:
            self._data.pop(key, None)
            return None

        return value

    def set(
        self,
        key,
        value,
    ):
        """Сохраняет значение."""

        self._data[key] = (
            value,
            time.time(),
        )

    def pop(self, key, default=None):
        """Удаляет значение из кэша."""

        return self._data.pop(
            key,
            None,
        )

    def clear(self):
        """Полностью очищает кэш."""
        self._data.clear()