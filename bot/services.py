# -*- coding: utf-8 -*-
"""Общие операции с панелью: чтение доступа, снимок трафика, ссылки нод."""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from urllib.parse import quote, urlsplit

from .context import app
from .wdtt import (
    WdttError,
    extract_node_links,
    online_flag,
    panel_tg_id,
    subscription_url,
    to_int,
)

log = logging.getLogger(__name__)

SNAPSHOT_TTL_SEC = 60

# Публичный алиас: им пользуются хендлеры и тесты.
as_int = to_int


def public_subscription_url(live: dict, user: dict, base: str, path: str) -> str:
    """Build the public subscription URL from configured base and panel sub ID."""
    raw = subscription_url(live) or subscription_url(user)
    if not base:
        return raw
    sub_id = str(live.get("sub_id") or user.get("sub_id") or "").strip()
    if not sub_id and raw:
        parts = urlsplit(raw).path.rstrip("/").split("/")
        if len(parts) >= 3:
            from urllib.parse import unquote
            sub_id = unquote(parts[-1])
    if not sub_id:
        return ""
    base = base.rstrip("/")
    path = path.strip("/")
    if path and not urlsplit(base).path.rstrip("/").endswith("/" + path):
        base += "/" + path
    return base + "/" + quote(sub_id, safe="")


def _now() -> datetime:
    return datetime.now(timezone.utc)


def snapshot_is_fresh(user: dict) -> bool:
    ts = user.get("panel_snapshot_at")
    if not ts:
        return False

    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)

    return (_now() - ts).total_seconds() < SNAPSHOT_TTL_SEC


async def _by_tg(tg_id: int) -> dict | None:
    """Резервный поиск, если в профиле бота нет panel_id."""
    ctx = app()
    for query in (f"tg{tg_id}", f"tg_{tg_id}", str(tg_id)):
        data = await ctx.wdtt.list_users(q=query, limit=50)
        for found in data.get("users", []):
            if panel_tg_id(found) == tg_id:
                return found
    return None


async def fetch_live(user: dict, force: bool = False,
                     timeout: float = 10) -> tuple[dict | None, str]:
    """Возвращает (данные панели, причина).

    Причины: ``ok``, ``missing`` (404), ``panel_down``, ``no_link``.
    """
    ctx = app()
    panel_id = str(user.get("panel_id") or "").strip()

    try:
        if panel_id:
            live = await asyncio.wait_for(
                ctx.wdtt.get_user(panel_id, force=force), timeout=timeout
            )
        else:
            live = await asyncio.wait_for(
                _by_tg(int(user.get("tg_id") or 0)), timeout=timeout
            )
    except asyncio.TimeoutError:
        return None, "panel_down"
    except WdttError as e:
        if e.status == 404:
            return None, "missing"
        log.warning("panel get_user failed: %s", e)
        return None, "panel_down"
    except Exception as e:
        log.warning("panel get_user failed: %s", e)
        return None, "panel_down"

    if not live:
        return None, "no_link"

    return live, "ok"


async def update_snapshot(tg_id: int, live: dict) -> None:
    ctx = app()
    patch = {
        "panel_id": str(live.get("id") or ""),
        "panel_password": str(live.get("password") or ""),
        "panel_total_gb": as_int(live.get("total_gb")),
        "panel_traffic_used_bytes": as_int(live.get("traffic_used_bytes")),
        "panel_expires_at": as_int(live.get("expires_at")),
        "panel_max_devices": as_int(live.get("max_devices")),
        "panel_devices_bound": as_int(live.get("devices_bound")),
        "panel_online": online_flag(live.get("online")),
        "panel_active": online_flag(live.get("active", True)),
        "panel_status": str(live.get("status") or "active"),
        "panel_link": str(live.get("link") or ""),
        "subscription_url": subscription_url(live),
        "sub_id": str(live.get("sub_id") or ""),
        "panel_snapshot_at": _now(),
    }

    if not patch["panel_id"]:
        patch.pop("panel_id")

    await ctx.db.users.update_one({"tg_id": tg_id}, {"$set": patch})


async def refresh_snapshot(user: dict, force: bool = False,
                           timeout: float = 10) -> tuple[dict | None, str]:
    live, reason = await fetch_live(user, force=force, timeout=timeout)

    if live is not None:
        try:
            await update_snapshot(int(user.get("tg_id") or 0), live)
        except Exception as e:
            log.warning("snapshot update failed: %s", e)

    return live, reason


def access_links(live: dict, nodes: list | None = None,
                 include_main: bool = False) -> list[dict]:
    return extract_node_links(live, nodes, include_main=include_main)


def node_limit(settings: dict | None = None) -> int:
    cfg = app().cfg
    if settings:
        try:
            return max(1, int(settings.get("nodes_copy_limit") or 0))
        except (TypeError, ValueError):
            pass
    return max(1, int(cfg.nodes_copy_limit or 5))
