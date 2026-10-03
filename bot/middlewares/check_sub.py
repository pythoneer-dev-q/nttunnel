# -*- coding: utf-8 -*-
"""Middleware: синхронизация пользователя, блокировка, проверка подписок на каналы.

Пропускает дальше только подписанных на все обязательные каналы.
Админы проходят всегда. Всё — листательным flow (edit по кнопкам).
"""
import logging
import time

from aiogram import BaseMiddleware
from aiogram.types import CallbackQuery, Message, TelegramObject

from ..db import Database
from ..keyboards import menu_kb, subscribe_kb
from ..texts import hello_text
from ..utils import TTLCache, answer_or_alert, safe_edit

log = logging.getLogger(__name__)

SUB_SCREEN_TEXT = (
    "📺 <b>Для доступа к боту подпишитесь на каналы:</b>\n\n"
    "Нажмите на кнопки-каналы ниже и подпишитесь, затем нажмите "
    "«🔄 Я подписался — проверить»."
)

# колбэки, обрабатываемые до основной проверки подписок
ALLOWED_CB = {"chk:r", "noop"}


class UserGate(BaseMiddleware):
    def __init__(self, db: Database):
        self.db = db
        self.list_cache = TTLCache(30)     # каналы/реклама
        self.member_cache = TTLCache(90)   # membership user:channel

    # ------------------------------------------------------------- helpers
    async def get_channels(self) -> list:
        cached = self.list_cache.get("channels")
        if cached is not None:
            return cached
        chans = [c async for c in self.db.channels.find().sort("added_at", 1)]
        self.list_cache.set("channels", chans)
        return chans

    async def get_ads(self) -> list:
        cached = self.list_cache.get("ads")
        if cached is not None:
            return cached
        ads = [a async for a in self.db.ads.find().sort("added_at", 1)]
        self.list_cache.set("ads", ads)
        return ads

    async def get_sections(self) -> list:
        """Динамические разделы меню (кэш, сброс в админке)."""
        cached = self.list_cache.get("sections")
        if cached is not None:
            return cached
        sections = [s async for s in self.db.sections.find().sort("key", 1)]
        self.list_cache.set("sections", sections)
        return sections

    async def check_membership(self, bot, tg_id: int, ch: dict, force: bool = False) -> bool:
        key = f"m:{tg_id}:{ch['channel_id']}"
        if not force:
            cached = self.member_cache.get(key)
            if cached is not None:
                return cached
        try:
            member = await bot.get_chat_member(ch["channel_id"], tg_id)
            ok = member.status not in ("left", "kicked")
        except Exception as e:  # noqa: BLE001 — бот без прав / канал удалён
            log.warning("membership check fail ch=%s: %s",
                        ch.get("channel_id"), e)
            ok = True  # ошибка бота не должна блокировать пользователя

        if ok:
            self.member_cache.set(key, True)
        else:
            self.member_cache.pop(key)
        return ok

    async def all_subscribed(self, bot, tg_id: int, channels: list, force: bool = False) -> bool:
        for ch in channels:
            if not await self.check_membership(bot, tg_id, ch, force=force):
                return False
        return True

    async def send_subscribe_screen(self, target_msg: Message, text_add: str = ""):
        try:
            await target_msg.answer(
                SUB_SCREEN_TEXT + text_add,
                reply_markup=subscribe_kb(await self.get_channels()))
        except Exception as e:  # noqa: BLE001
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
            user_doc = await self.db.sync_user(from_user,
                                               source=data.get("start_payload"))
        except Exception as e:  # noqa: BLE001
            log.error("sync_user failed: %s", e)
            user_doc = {"tg_id": tg_id}
        data["user"] = user_doc

        cb: CallbackQuery | None = event if isinstance(event, CallbackQuery) else None
        msg: Message | None = event if isinstance(event, Message) else None

        # ---- блокировка пользователя
        if user_doc.get("blocked") and not is_admin:
            await self.db.log_event(tg_id, "blocked_attempt")
            if cb:
                await answer_or_alert(cb, "🚫 Ваш доступ заблокирован.", True)
            return  # глушим все хендлеры

        if is_admin:
            return await handler(event, data)

        # ---- refresh экрана подписки («я подписался»)
        if cb and cb.data == "chk:r":
            channels = await self.get_channels()
            missing = []
            for ch in channels:
                ok = await self.check_membership(bot, tg_id, ch, force=True)
                if not ok:
                    missing.append(ch)
            registered = bool(user_doc.get("registered"))
            ads = await self.get_ads()
            if cb.message:
                if not missing:
                    await safe_edit(cb.message,
                                    hello_text(user_doc),
                                    menu_kb(registered, ads))
                    await answer_or_alert(cb, "✅ Проверка пройдена!")
                else:
                    extra = "\n\n❌ Вы ещё не подписались на все каналы."
                    kb = subscribe_kb(missing)
                    await safe_edit(cb.message, SUB_SCREEN_TEXT + extra, kb)
                    await answer_or_alert(cb, "Подпишитесь на отмеченные 📺")
            return

        if cb and cb.data in ALLOWED_CB:
            await answer_or_alert(cb)
            return

        # ---- основная проверка подписок
        channels = await self.get_channels()
        if channels and not await self.all_subscribed(bot, tg_id, channels):
            if cb:
                await self.db.bump_callback(tg_id)
            else:
                await self.db.log_event(tg_id, "sub_gate_msg")
            text_add = "\n\n" + hello_text(user_doc)
            if cb:
                edited = False
                if cb.message:
                    channels = await self.get_channels()
                    edited = await safe_edit(cb.message,
                                             SUB_SCREEN_TEXT + text_add,
                                             subscribe_kb(channels))
                await answer_or_alert(cb, "⚠️ Сначала подпишитесь!" if edited
                                      else "⚠️ Сначала подпишитесь!", True)
                return
            if msg:
                await self.send_subscribe_screen(msg, text_add)
                return

        return await handler(event, data)

