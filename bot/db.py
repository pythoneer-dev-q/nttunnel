# -*- coding: utf-8 -*-
"""MongoDB-слой проекта (motor).

Коллекции:
  users     — профили бота, привязка к пользователю панели
  channels  — обязательные каналы
  ads       — рекламные кнопки
  settings  — глобальные настройки
  events    — журнал событий
  tickets   — обращения в поддержку
  sections  — динамические разделы меню
"""
from __future__ import annotations

import logging
import random
import string
import time
from datetime import datetime, timezone

from motor.motor_asyncio import AsyncIOMotorClient, AsyncIOMotorDatabase
from pymongo import ReturnDocument

from .config import Config

log = logging.getLogger(__name__)

TICKET_STATUSES = ("open", "in_progress", "closed")


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


DEFAULT_SETTINGS: dict = {
    "registration_open": True,       # False = режим «нет мест»
    "slots_total": 0,                # 0 = без лимита
    "default_total_gb": 175,         # 0 = безлимит
    "default_max_devices": 2,
    "default_expires_days": 0,       # 0 = бессрочно
    "reset_period_days": 0,          # авто-сброс трафика, 0 = выкл.
    "referral_bonus_gb": 5,
    "nodes_copy_limit": 5,           # нод кнопками, остальные — в подписке
    "include_main_node": False,
    "agreement_text": "",            # seed из texts.DEFAULT_AGREEMENT
    "app_links": [],                 # [{label, url}]
    "support_chat_id": "",
}


class Database:
    """Обёртка над MongoDB."""

    def __init__(self, cfg: Config):
        self.client: AsyncIOMotorClient = AsyncIOMotorClient(cfg.mongo_uri)
        self.db: AsyncIOMotorDatabase = self.client[cfg.mongo_db]

        self.users = self.db["users"]
        self.channels = self.db["channels"]
        self.ads = self.db["ads"]
        self.events = self.db["events"]
        self.settings_col = self.db["settings"]
        self.tickets = self.db["tickets"]
        self.sections = self.db["sections"]

        self._settings_ttl = 20.0
        self._settings_cache: dict | None = None
        self._settings_cached_at = 0.0

    # ------------------------------------------------------------ lifecycle

    async def init(self):
        await self.users.create_index("tg_id", unique=True)
        await self.users.create_index("registered")
        await self.users.create_index("created_at")
        await self.users.create_index("blocked")
        await self.users.create_index("username")
        await self.users.create_index("full_name")
        await self.users.create_index("first_name")
        await self.users.create_index("panel_id")
        await self.channels.create_index("channel_id", unique=True)
        await self.channels.create_index("_ts_added")
        await self.ads.create_index("key", unique=True)
        await self.events.create_index("tg_id")
        await self.events.create_index("ts")
        await self.tickets.create_index("ticket_id", unique=True)
        await self.tickets.create_index("tg_id")
        await self.sections.create_index("key", unique=True)

        from .texts import DEFAULT_AGREEMENT, DEFAULT_APP_LINKS

        await self.settings_col.update_one(
            {"_id": "main"},
            {"$setOnInsert": {
                **DEFAULT_SETTINGS,
                "agreement_text": DEFAULT_AGREEMENT,
                "app_links": DEFAULT_APP_LINKS,
            }},
            upsert=True,
        )

    async def close(self):
        self.client.close()

    # ------------------------------------------------------------ settings

    async def get_settings(self) -> dict:
        now = time.monotonic()

        if (
            self._settings_cache is not None
            and now - self._settings_cached_at < self._settings_ttl
        ):
            return dict(self._settings_cache)

        doc = await self.settings_col.find_one({"_id": "main"})
        merged = {**DEFAULT_SETTINGS, **(doc or {})}
        merged.pop("_id", None)

        self._settings_cache = merged
        self._settings_cached_at = time.monotonic()
        return dict(merged)

    async def save_settings(self, patch: dict):
        await self.settings_col.update_one(
            {"_id": "main"}, {"$set": patch}, upsert=True
        )
        self._settings_cache = None
        self._settings_cached_at = 0.0

    # --------------------------------------------------------------- users

    async def sync_user(self, tg_user, source: str | None = None) -> dict:
        now = utcnow()
        update = {
            "$set": {
                "username": tg_user.username,
                "first_name": tg_user.first_name or "",
                "last_name": tg_user.last_name or "",
                "full_name": tg_user.full_name or "",
                "language_code": tg_user.language_code,
                "is_premium": bool(tg_user.is_premium),
                "last_seen": now,
            },
            "$setOnInsert": {
                "tg_id": tg_user.id,
                "created_at": now,
                "blocked": False,
                "registered": False,
                "creating": False,
                "is_admin": False,
                "referrals": 0,
                "callbacks_count": 0,
                "start_payload": source or "",
                "source_set_at": now if source else None,
            },
            "$inc": {"messages_count": 1},
        }
        return await self.users.find_one_and_update(
            {"tg_id": tg_user.id},
            update,
            upsert=True,
            return_document=ReturnDocument.AFTER,
        )

    async def get_user(self, tg_id: int) -> dict | None:
        return await self.users.find_one({"tg_id": tg_id})

    async def get_user_by_panel_id(self, panel_id: str) -> dict | None:
        return await self.users.find_one({"panel_id": str(panel_id)})

    async def bump_callback(self, tg_id: int):
        await self.users.update_one(
            {"tg_id": tg_id}, {"$inc": {"callbacks_count": 1}}
        )

    async def log_event(self, tg_id: int, kind: str, meta: str = ""):
        try:
            await self.events.insert_one({
                "tg_id": tg_id,
                "kind": kind,
                "meta": (meta or "")[:300],
                "ts": utcnow(),
            })
        except Exception:
            log.warning("log_event failed", exc_info=True)

    async def registered_count(self) -> int:
        return await self.users.count_documents({"registered": True})

    async def slots_available(self, settings: dict) -> tuple[bool, int]:
        if not settings.get("registration_open", True):
            return False, 0

        total = int(settings.get("slots_total") or 0)
        if not total:
            return True, -1

        used = await self.registered_count()
        left = max(total - used, 0)
        return left > 0, left

    # ------------------------------------------------------------- tickets

    async def create_ticket(self, tg_id: int, subject: str, body: str) -> str:
        for _ in range(10):
            tid = "".join(
                random.choices(string.ascii_uppercase + string.digits, k=6)
            )
            if not await self.tickets.find_one({"ticket_id": tid}):
                now = utcnow()
                await self.tickets.insert_one({
                    "ticket_id": tid,
                    "tg_id": tg_id,
                    "subject": subject[:120],
                    "body": body[:2000],
                    "status": "open",
                    "created_at": now,
                    "updated_at": now,
                    "messages": [],
                })
                return tid
        raise RuntimeError("could not generate unique ticket id")

    async def get_ticket(self, ticket_id: str) -> dict | None:
        return await self.tickets.find_one({"ticket_id": ticket_id})

    async def append_ticket_message(self, ticket_id: str, author: str, text: str):
        await self.tickets.update_one(
            {"ticket_id": ticket_id},
            {
                "$push": {
                    "messages": {
                        "author": author,
                        "text": text[:2000],
                        "ts": utcnow(),
                    }
                },
                "$set": {"updated_at": utcnow()},
            },
        )

    async def set_ticket_status(self, ticket_id: str, status: str):
        await self.tickets.update_one(
            {"ticket_id": ticket_id},
            {"$set": {"status": status, "updated_at": utcnow()}},
        )

    async def list_tickets(self, status: str | None = None,
                           limit: int = 50) -> list:
        query = {} if status is None else {"status": status}
        return [t async for t in self.tickets.find(query)
                .sort("updated_at", -1).limit(limit)]

    async def user_active_tickets(self, tg_id: int) -> list:
        return [t async for t in self.tickets.find(
            {"tg_id": tg_id, "status": {"$in": ["open", "in_progress"]}}
        ).sort("updated_at", -1)]

    # ------------------------------------------------------------- sections

    async def get_section(self, key: str) -> dict | None:
        return await self.sections.find_one({"key": key})

    async def save_section(self, key: str, data: dict):
        data["key"] = key
        data["updated_at"] = utcnow()
        await self.sections.update_one(
            {"key": key}, {"$set": data}, upsert=True
        )

    async def delete_section(self, key: str):
        await self.sections.delete_one({"key": key})

    async def list_sections(self) -> list:
        return [s async for s in self.sections.find().sort("key", 1)]

    # ---------------------------------------------------------- registration

    async def claim_creating(
        self,
        tg_id: int,
        allow_recreate: bool = False,
        timeout_sec: int = 90,
    ) -> bool:
        now = utcnow()
        timeout_dt = datetime.fromtimestamp(
            now.timestamp() - timeout_sec, tz=timezone.utc
        )
        query: dict = {
            "tg_id": tg_id,
            "$or": [
                {"creating": {"$ne": True}},
                {"creating_at": {"$lt": timeout_dt}},
            ],
        }
        if not allow_recreate:
            query["registered"] = {"$ne": True}

        res = await self.users.find_one_and_update(
            query,
            {"$set": {"creating": True, "creating_at": now}},
            return_document=ReturnDocument.AFTER,
        )
        return res is not None

    async def release_creating(self, tg_id: int):
        await self.users.update_one(
            {"tg_id": tg_id},
            {"$set": {"creating": False}, "$unset": {"creating_at": ""}},
        )
