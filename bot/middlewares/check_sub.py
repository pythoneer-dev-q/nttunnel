# -*- coding: utf-8 -*-
"""Middleware: пользователь, блокировка, обязательные подписки."""
from __future__ import annotations

import logging

from aiogram import BaseMiddleware
from aiogram.types import CallbackQuery, Message, TelegramObject

from ..db import Database
from ..keyboards import subscribe_kb
from ..utils import TTLCache, answer_or_alert, safe_edit

log = logging.getLogger(__name__)

SUB_SCREEN_TEXT = (
    "📺 <b>Подпишись на каналы</b>\n\n"
    "После подписки нажми «Проверить подписку»."
)

ALLOWED_CB = {"chk:r", "noop"}


class UserGate(BaseMiddleware):
    def __init__(self, db: Database):
        self.db = db
        self.list_cache = TTLCache(30)
        self.member_cache = TTLCache(90)

    # ------------------------------------------------------------- helpers

    async def get_channels(self) -> list:
        cached = self.list_cache.get("channels")
        if cached is not None:
            return cached

        channels = [
            c async for c in self.db.channels.find().sort("_ts_added", 1)
        ]
        self.list_cache.set("channels", channels)
        return channels

    async def get_ads(self) -> list:
        cached = self.list_cache.get("ads")
        if cached is not None:
            return cached

        ads = [a async for a in self.db.ads.find().sort("added_at", 1)]
        self.list_cache.set("ads", ads)
        return ads

    async def get_sections(self) -> list:
        cached = self.list_cache.get("sections")
        if cached is not None:
            return cached

        sections = [s async for s in self.db.sections.find().sort("key", 1)]
        self.list_cache.set("sections", sections)
        return sections

    async def check_membership(
        self, bot, tg_id: int, channel: dict, force: bool = False
    ) -> bool:
        key = f"m:{tg_id}:{channel['channel_id']}"

        if not force:
            cached = self.member_cache.get(key)
            if cached is not None:
                return cached

        try:
            member = await bot.get_chat_member(
                channel["channel_id"], tg_id
            )
            ok = member.status not in ("left", "kicked")
        except Exception as e:
            log.warning(
                "membership check failed ch=%s: %s",
                channel.get("channel_id"), e,
            )
            ok = True  # ошибка бота не блокирует пользователя

        if ok:
            self.member_cache.set(key, True)
        else:
            self.member_cache.pop(key)

        return ok

    async def all_subscribed(
        self, bot, tg_id: int, channels: list, force: bool = False
    ) -> bool:
        for channel in channels:
            if not await self.check_membership(
                bot, tg_id, channel, force=force
            ):
                return False
        return True

    async def send_subscribe_screen(self, message: Message):
        try:
            await message.answer(
                SUB_SCREEN_TEXT,
                reply_markup=subscribe_kb(await self.get_channels()),
            )
        except Exception as e:
            log.warning("subscribe screen failed: %s", e)

    # ------------------------------------------------------------ entrypoint

    async def __call__(self, handler, event: TelegramObject, data: dict):
        from_user = data.get("event_from_user")
        if from_user is None or from_user.is_bot:
            return await handler(event, data)

        bot = data["bot"]
        tg_id = from_user.id
        is_admin = tg_id in set(data.get("admin_ids", []) or [])

        try:
            user_doc = await self.db.sync_user(
                from_user, source=data.get("start_payload")
            )
        except Exception as e:
            log.error("sync_user failed: %s", e)
            user_doc = {"tg_id": tg_id}

        data["user"] = user_doc

        cb = event if isinstance(event, CallbackQuery) else None
        msg = event if isinstance(event, Message) else None

        if user_doc.get("blocked") and not is_admin:
            await self.db.log_event(tg_id, "blocked_attempt")
            if cb:
                await answer_or_alert(cb, "🚫 Доступ заблокирован", True)
            return

        if cb and cb.data == "chk:r":
            channels = [] if is_admin else await self.get_channels()
            missing = []
            for channel in channels:
                if not await self.check_membership(
                    bot, tg_id, channel, force=True
                ):
                    missing.append(channel)

            if not missing:
                from ..handlers.common import show_menu

                if cb.message:
                    await show_menu(cb.message, user_doc, edit=True)
                await answer_or_alert(cb, "✅ Подписка подтверждена")
            else:
                if cb.message:
                    await safe_edit(
                        cb.message,
                        SUB_SCREEN_TEXT + "\n\n❌ Не все каналы подписаны.",
                        subscribe_kb(missing),
                    )
                await answer_or_alert(cb, "Подпишись на каналы 📺")
            return

        if is_admin:
            return await handler(event, data)

        if cb and cb.data in ALLOWED_CB:
            await answer_or_alert(cb)
            return

        channels = await self.get_channels()
        if channels and not await self.all_subscribed(bot, tg_id, channels):
            if cb:
                await self.db.bump_callback(tg_id)
                if cb.message:
                    await safe_edit(
                        cb.message,
                        SUB_SCREEN_TEXT,
                        subscribe_kb(channels),
                    )
                await answer_or_alert(cb, "⚠️ Сначала подпишись", True)
                return

            if msg:
                await self.send_subscribe_screen(msg)
                return

        return await handler(event, data)
