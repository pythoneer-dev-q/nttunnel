# -*- coding: utf-8 -*-
"""Асинхронный клиент WDTT REST API v2 (Remnawave-style).

Аутентификация:
  - ``X-API-Key`` (рекомендуется);
  - ``Authorization: Bearer <JWT>`` через ``POST /api/auth/token``.

Все ответы панели обёрнуты в ``{"success": true, "data": ...}``. Клиент
возвращает уже развёрнутый ``data``.
"""
from __future__ import annotations

import asyncio
import json as jsonlib
import logging
import ssl as ssl_mod
import time
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Any

import aiohttp

log = logging.getLogger(__name__)

USER_CACHE_TTL = 5.0
NODES_CACHE_TTL = 30.0

_NODE_LIST_KEYS = (
    "nodes", "connections", "node_links", "nodeLinks",
    "configs", "configurations", "links",
)


class WdttError(Exception):
    """Ошибка клиента WDTT API."""

    def __init__(self, message: str, code: int | None = None,
                 status: int | None = None):
        super().__init__(message)
        self.code = code
        self.status = status


# ------------------------------------------------------------------ helpers


def human_bytes(value: Any) -> str:
    """Байты в компактный человекочитаемый вид."""
    try:
        num = float(value or 0)
    except (TypeError, ValueError):
        num = 0.0

    if num < 1024:
        return f"{int(num)} Б"

    for unit in ("КБ", "МБ", "ГБ", "ТБ"):
        num /= 1024
        if num < 1024 or unit == "ТБ":
            return f"{num:.1f} {unit}"

    return f"{num:.1f} ТБ"


def traffic_bar(used_bytes: Any, total_gb: Any, width: int = 10) -> tuple[str, str, str, int]:
    """Возвращает (полоса, использовано, всего, процент)."""
    try:
        total_b = float(total_gb or 0) * 1024 ** 3
        used_b = float(used_bytes or 0)
    except (TypeError, ValueError):
        total_b, used_b = 0.0, 0.0

    used_s = human_bytes(used_b)

    if total_b <= 0:
        return "∞", used_s, "∞", 0

    pct = int(min(used_b / total_b * 100, 100))
    if used_b > 0 and pct == 0:
        pct = 1

    filled = max(0, min(width, round(pct / 100 * width)))
    if used_b > 0 and filled == 0:
        filled = 1

    bar = "█" * filled + "░" * (width - filled)
    return bar, used_s, f"{float(total_gb):.0f} ГБ", pct


def expires_text(expires_at: Any) -> str:
    try:
        ts = int(expires_at or 0)
    except (TypeError, ValueError):
        ts = 0

    if ts <= 0:
        return "бессрочно"

    try:
        return datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%d.%m.%Y")
    except (OSError, ValueError, OverflowError):
        return "—"


def user_status(user: dict) -> tuple[str, str]:
    """(emoji + текст, ключ статуса)."""
    status = str(user.get("status") or "").lower()

    if status == "expired" or online_flag(user.get("is_expired")):
        return "⌛ истёк", "expired"
    if status == "exceeded" or online_flag(user.get("traffic_exceeded")):
        return "📵 лимит исчерпан", "exceeded"
    if (
        status == "blocked"
        or online_flag(user.get("is_deactivated"))
        or ("active" in user and not online_flag(user.get("active")))
    ):
        return "🚫 заблокирован", "blocked"
    if online_flag(user.get("online")):
        return "🟢 онлайн", "active"
    return "🟢 активен", "active"


def _first(obj: dict, *keys: str) -> Any:
    for key in keys:
        value = obj.get(key)
        if value not in (None, ""):
            return value
    return None


def _link_from(obj: Any) -> str:
    """Достаёт ссылку подключения из вложенной структуры."""
    if isinstance(obj, str):
        s = obj.strip()
        if s.startswith(("wdtt://", "qwdtt://", "http://", "https://")):
            return s
        return ""

    if isinstance(obj, dict):
        for key in ("link", "wdtt", "wdtt_link", "url", "value",
                    "config", "connection", "subscription_url"):
            found = _link_from(obj.get(key))
            if found:
                return found

        for value in obj.values():
            found = _link_from(value)
            if found:
                return found

    if isinstance(obj, list):
        for item in obj:
            found = _link_from(item)
            if found:
                return found

    return ""


def _node_name(obj: dict, fallback: str = "") -> str:
    node = obj.get("node") if isinstance(obj.get("node"), dict) else {}
    return str(
        _first(obj, "name", "node_name", "nodeName", "title", "host", "id")
        or _first(node, "name", "host", "id")
        or fallback
        or "Нода"
    )


def extract_node_links(detail: dict, nodes: list | None = None,
                       include_main: bool = False) -> list[dict]:
    """Возвращает список ``[{"name": ..., "link": ...}]`` для всех нод.

    Панель может отдавать конфигурации в разных полях и форматах, поэтому
    разбор намеренно гибкий. Дубликаты ссылок убираются.
    """
    detail = detail or {}
    result: list[dict] = []
    seen: set[str] = set()
    master = str(_first(detail, "link", "wdtt_link", "url") or "").strip()

    def is_main(item: dict) -> bool:
        return any(online_flag(item.get(k)) for k in ("is_main", "is_master", "is_primary")) or str(item.get("role") or "").lower() in ("main", "master", "primary")

    def add(name: str, link: str) -> None:
        link = (link or "").strip()
        if not link or link in seen or (not include_main and master and link == master):
            return
        seen.add(link)
        result.append({"name": (name or "Нода")[:40], "link": link})

    # Список нод из /api/nodes — для имён по id/host.
    nodes_by_id: dict[str, dict] = {}
    nodes_by_host: dict[str, dict] = {}
    for node in nodes or []:
        if not isinstance(node, dict):
            continue
        for key in ("id", "name", "host"):
            if node.get(key):
                nodes_by_id[str(node[key])] = node
        if node.get("host"):
            nodes_by_host[str(node["host"])] = node

    for key in _NODE_LIST_KEYS:
        container = detail.get(key)
        if not container:
            continue

        if isinstance(container, dict):
            items = list(container.items())
        elif isinstance(container, list):
            items = list(enumerate(container))
        else:
            continue

        for idx, item in items:
            if isinstance(item, str):
                name = str(idx)
                node = nodes_by_id.get(name) or nodes_by_host.get(name)
                if node:
                    if not include_main and is_main(node):
                        continue
                    name = _node_name(node, name)
                add(name, item)
                continue

            if not isinstance(item, dict):
                continue

            if not include_main and (is_main(item) or (isinstance(item.get("node"), dict) and is_main(item["node"]))):
                continue

            link = _link_from(item)
            if not link:
                continue

            name = _node_name(item, str(idx) if isinstance(idx, int) else str(idx))
            node = (
                nodes_by_id.get(str(item.get("id") or ""))
                or nodes_by_id.get(str(item.get("node_id") or ""))
                or nodes_by_host.get(str(item.get("host") or ""))
            )
            if node:
                if not include_main and is_main(node):
                    continue
                name = _node_name(node, name)
            add(name, link)

    # Отдельная ссылка пользователя (мастер-нода).
    if master and include_main:
        add("Основная нода", str(master))

    # Если панель отдала список нод, но без ссылок — хотя бы подпишем их.
    if not result and nodes:
        for node in nodes:
            if not isinstance(node, dict):
                continue
            if not include_main and is_main(node):
                continue
            link = _link_from(node)
            if link:
                add(_node_name(node), link)

    return result


def subscription_url(user: dict) -> str:
    return str(
        _first(user, "subscription_url", "sub_url", "subscriptionUrl") or ""
    )


def online_flag(value: Any) -> bool:
    """Приводит «строковые» булевы значения из панели к bool."""
    if isinstance(value, bool):
        return value
    if value is None:
        return False
    if isinstance(value, (int, float)):
        return value != 0
    if isinstance(value, str):
        return value.strip().lower() not in (
            "", "0", "false", "no", "off", "none", "null",
            "inactive", "disabled", "stopped", "down", "offline",
        )
    if isinstance(value, dict):
        for key in ("online", "active", "enabled", "running", "ok", "status"):
            if key in value:
                return online_flag(value[key])
    return bool(value)


def node_online(node: dict) -> bool:
    if not isinstance(node, dict):
        return False

    for key in ("online", "is_online", "status"):
        if key in node:
            return online_flag(node[key])
    return False


def to_int(value: Any, default: int = 0) -> int:
    """Аккуратно приводит число из панели к int."""
    if isinstance(value, bool):
        return int(value)
    try:
        return int(float(str(value).strip().replace(",", ".")))
    except (TypeError, ValueError):
        return default


def _password(raw: dict) -> str:
    """Панель маскирует ``password``, реальный ключ лежит в ``password_key``."""
    masked = str(raw.get("password") or "")
    key = str(raw.get("password_key") or "")

    if key and ("*" in masked or not masked):
        return key
    return masked or key


def normalize_user(raw: Any) -> dict:
    """Приводит карточку пользователя панели к единому виду.

    Панель отдаёт разные наборы полей: ``traffic_used`` вместо
    ``traffic_used_bytes``, ``sub_url`` вместо ``subscription_url``,
    идентификатор — ``sub_id``/``password_key``. Бот работает с
    каноническими именами.
    """
    if not isinstance(raw, dict):
        return {}

    user = dict(raw)
    nested = user.get("user")
    if isinstance(nested, dict):
        user = {**user, **nested}
        user.pop("user", None)

    used = user.get("traffic_used_bytes")
    if used is None:
        used = user.get("traffic_used")
    if used is None:
        used = user.get("total_bytes")
    if used is None:
        used = to_int(user.get("up_bytes")) + to_int(user.get("down_bytes"))

    user["traffic_used_bytes"] = to_int(used)
    user["total_gb"] = to_int(user.get("total_gb"))
    user["expires_at"] = to_int(user.get("expires_at"))
    user["max_devices"] = to_int(user.get("max_devices"))
    user["devices_bound"] = to_int(user.get("devices_bound"))
    user["online"] = online_flag(user.get("online"))
    user["password"] = _password(user)
    user["subscription_url"] = subscription_url(user)
    user["sub_id"] = str(user.get("sub_id") or "")

    if "active" not in user and "is_deactivated" in user:
        user["active"] = not online_flag(user["is_deactivated"])
    else:
        user["active"] = online_flag(user.get("active", True))

    user["id"] = str(
        user.get("id")
        or user.get("sub_id")
        or user.get("password_key")
        or user.get("name")
        or ""
    )

    if not user.get("links") and isinstance(user.get("node_links"), list):
        user["links"] = user["node_links"]

    return user


def normalize_node(raw: Any) -> dict:
    if not isinstance(raw, dict):
        return {}

    node = dict(raw)
    node["online"] = node_online(node)
    node["id"] = str(
        node.get("id") or node.get("node_id") or node.get("name") or ""
    )
    return node


def panel_tg_id(user: dict) -> int | None:
    """Извлекает Telegram ID из name/comment пользователя панели."""
    import re

    for key in ("comment", "name", "description"):
        raw = str(user.get(key) or "")
        match = re.search(r"tg[_\s:-]*(-?\d{1,})", raw, re.IGNORECASE)
        if match:
            try:
                return int(match.group(1))
            except ValueError:
                pass
    return None


class WdttClient:
    """Клиент WDTT REST API v2."""

    def __init__(
        self,
        base_url: str,
        api_key: str = "",
        username: str = "",
        password: str = "",
        ssl_insecure: bool = True,
        timeout: int = 30,
        api_url: str = "",
    ):
        self.base = (base_url or "").rstrip("/")
        from urllib.parse import urlsplit
        parsed = urlsplit(self.base)
        self.api_base = (api_url or f"{parsed.scheme}://{parsed.netloc}/api").rstrip("/")
        self.api_key = (api_key or "").strip()
        self.username = username or ""
        self.password = password or ""
        self.ssl_insecure = ssl_insecure
        self.timeout = timeout

        self._session: aiohttp.ClientSession | None = None
        self._token = ""
        self._token_expires_at = 0.0
        self._lock = asyncio.Lock()

        self._user_cache: dict[str, tuple[float, dict]] = {}
        self._nodes_cache: list | None = None
        self._nodes_cached_at = 0.0

    # ------------------------------------------------------------ session

    async def _get_session(self) -> aiohttp.ClientSession:
        if self._session is not None and not self._session.closed:
            return self._session

        connector: aiohttp.TCPConnector
        if self.api_base.startswith("https://"):
            ctx = ssl_mod.create_default_context()
            if self.ssl_insecure:
                ctx.check_hostname = False
                ctx.verify_mode = ssl_mod.CERT_NONE
            connector = aiohttp.TCPConnector(
                ssl=ctx, limit=50, limit_per_host=25,
                ttl_dns_cache=300, enable_cleanup_closed=True,
            )
        else:
            connector = aiohttp.TCPConnector(
                limit=50, limit_per_host=25,
                ttl_dns_cache=300, enable_cleanup_closed=True,
            )

        self._session = aiohttp.ClientSession(
            timeout=aiohttp.ClientTimeout(
                total=self.timeout,
                connect=min(10, self.timeout),
                sock_connect=min(10, self.timeout),
                sock_read=self.timeout,
            ),
            connector=connector,
        )
        return self._session

    async def close(self) -> None:
        if self._session and not self._session.closed:
            await self._session.close()

    @asynccontextmanager
    async def _session_ctx(self):
        """Даёт общую сессию, не закрывая её после запроса."""
        yield await self._get_session()

    # --------------------------------------------------------------- auth

    def _auth_headers(self) -> dict:
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["X-API-Key"] = self.api_key
        elif self._token:
            headers["Authorization"] = f"Bearer {self._token}"
        return headers

    async def _ensure_token(self, force: bool = False) -> None:
        if self.api_key:
            return

        now = time.time()
        if not force and self._token and now < self._token_expires_at - 60:
            return

        await self._login()

    async def _login(self) -> None:
        async with self._lock:
            url = f"{self.api_base}/auth/token"
            payload = {"username": self.username, "password": self.password}

            async with self._session_ctx() as sess:
                async with sess.post(url, json=payload) as resp:
                    try:
                        body = await resp.json(content_type=None)
                    except Exception:
                        body = {}

                    if resp.status >= 400 or not body.get("success", False):
                        raise WdttError(
                            str(body.get("error") or f"auth failed ({resp.status})"),
                            code=body.get("code"),
                            status=resp.status,
                        )

                    data = body.get("data") or {}
                    self._token = str(data.get("token") or "")
                    self._token_expires_at = float(
                        data.get("expires_at") or (time.time() + 3600)
                    )

                    if not self._token:
                        raise WdttError("auth failed: empty token", status=resp.status)

                    log.info("WDTT: JWT token obtained")

    # ------------------------------------------------------------ request

    async def _request(
        self,
        method: str,
        path: str,
        json: Any = None,
        params: dict | None = None,
        _retried: bool = False,
    ) -> Any:
        await self._ensure_token()
        url = f"{self.api_base}{path}"
        headers = self._auth_headers()

        async with self._session_ctx() as sess:
            async with sess.request(
                method, url, json=json, params=params, headers=headers
            ) as resp:
                raw = await resp.read()
                text = raw.decode("utf-8", "replace") if raw else ""
                body: Any = {}

                if text.strip():
                    try:
                        body = jsonlib.loads(text)
                    except Exception:
                        body = {}

                is_html = "<html" in text[:400].lower()

                if resp.status == 401 and not self.api_key and not _retried:
                    await self._ensure_token(force=True)
                    return await self._request(
                        method, path, json=json, params=params, _retried=True
                    )

                if resp.status >= 400:
                    error = body.get("error") if isinstance(body, dict) else None

                    if not error and is_html:
                        error = (
                            f"панель вернула HTML вместо JSON (HTTP {resp.status}); "
                            "проверь WAF/прокси перед панелью"
                        )

                    raise WdttError(
                        str(error or f"HTTP {resp.status}"),
                        code=body.get("code") if isinstance(body, dict) else None,
                        status=resp.status,
                    )

                if not body and is_html:
                    raise WdttError(
                        "панель вернула HTML вместо JSON — проверь WAF/прокси",
                        status=resp.status,
                    )

                if isinstance(body, dict):
                    if body.get("success") is False:
                        raise WdttError(
                            str(body.get("error") or "unknown panel error"),
                            code=body.get("code"),
                            status=resp.status,
                        )
                    if "data" in body:
                        return body["data"]
                    if isinstance(body.get("user"), dict):
                        return body["user"]
                    return body

                return body

    # --------------------------------------------------------------- users

    async def list_users(
        self,
        q: str | None = None,
        status: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> dict:
        params: dict[str, Any] = {
            "limit": max(1, min(int(limit), 200)),
            "offset": max(0, int(offset)),
        }
        if q:
            params["q"] = q
        if status and status != "all":
            params["status"] = status

        data = await self._request("GET", "/users", params=params)

        if isinstance(data, list):
            users = [normalize_user(u) for u in data if isinstance(u, dict)]
            return {"total": len(users), "users": users}

        if not isinstance(data, dict):
            return {"total": 0, "users": []}

        users = data.get("users") or data.get("items") or []
        if not isinstance(users, list):
            users = []

        users = [normalize_user(u) for u in users if isinstance(u, dict)]

        try:
            total = int(data.get("total") or data.get("count") or len(users))
        except (TypeError, ValueError):
            total = len(users)

        return {"total": total, "users": users}

    async def get_user(self, user_id: str, force: bool = False) -> dict:
        user_id = str(user_id or "").strip()
        if not user_id:
            raise WdttError("user id is empty")

        now = time.time()
        if not force:
            cached = self._user_cache.get(user_id)
            if cached and now - cached[0] < USER_CACHE_TTL:
                return cached[1]

        data = await self._request("GET", f"/users/{user_id}")
        user = normalize_user(data)
        self._user_cache[user_id] = (now, user)
        return user

    def invalidate_user(self, user_id: str) -> None:
        self._user_cache.pop(str(user_id or ""), None)

    async def create_user(
        self,
        name: str,
        comment: str = "",
        total_gb: int = 0,
        expires_at: int = 0,
        max_devices: int = 1,
        max_down_mbps: int = 0,
        max_up_mbps: int = 0,
        active: bool = True,
        password: str = "",
        vk_hash: str = "",
    ) -> dict:
        payload: dict[str, Any] = {
            "name": name,
            "total_gb": max(0, int(total_gb or 0)),
            "expires_at": max(0, int(expires_at or 0)),
            "max_devices": max(1, int(max_devices or 1)),
            "max_down_mbps": max(0, int(max_down_mbps or 0)),
            "max_up_mbps": max(0, int(max_up_mbps or 0)),
            "active": bool(active),
        }
        if comment:
            payload["comment"] = comment
        if password:
            payload["password"] = password
        if vk_hash:
            payload["vk_hash"] = vk_hash

        data = await self._request("POST", "/users", json=payload)
        result = normalize_user(data)
        user_id = str(result.get("id") or name)
        result["id"] = user_id
        self._user_cache[user_id] = (time.time(), result)
        return result

    async def add_vk_hashes(self, user_id: str, hashes: list[str]) -> dict:
        data = await self._request("POST", f"/users/{user_id}/vk-hashes", json={"hashes": hashes})
        self.invalidate_user(user_id)
        return normalize_user(data)

    async def update_user(self, user_id: str, **fields: Any) -> dict:
        allowed = {
            "name", "comment", "total_gb", "expires_at", "max_devices",
            "max_down_mbps", "max_up_mbps", "active", "password",
        }
        payload = {
            key: value for key, value in fields.items()
            if key in allowed and value is not None
        }
        data = await self._request("PUT", f"/users/{user_id}", json=payload)
        self.invalidate_user(user_id)
        return data if isinstance(data, dict) else {}

    async def activate_user(self, user_id: str) -> dict:
        data = await self._request("POST", f"/users/{user_id}/activate")
        self.invalidate_user(user_id)
        return data if isinstance(data, dict) else {}

    async def block_user(self, user_id: str) -> dict:
        data = await self._request("POST", f"/users/{user_id}/block")
        self.invalidate_user(user_id)
        return data if isinstance(data, dict) else {}

    async def reset_traffic(self, user_id: str) -> dict:
        data = await self._request("POST", f"/users/{user_id}/reset-traffic")
        self.invalidate_user(user_id)
        return data if isinstance(data, dict) else {}

    async def delete_user(self, user_id: str) -> dict:
        data = await self._request("DELETE", f"/users/{user_id}")
        self.invalidate_user(user_id)
        return data if isinstance(data, dict) else {}

    async def find_user(self, query: str) -> dict | None:
        """Поиск по name/comment/password. Возвращает первую запись."""
        query = (query or "").strip()
        if not query:
            return None

        data = await self.list_users(q=query, limit=50)
        users = data.get("users") or []
        low = query.lower()

        for user in users:
            if not isinstance(user, dict):
                continue
            values = [
                str(user.get("id") or ""),
                str(user.get("name") or ""),
                str(user.get("comment") or ""),
                str(user.get("password") or ""),
            ]
            if any(value.lower() == low for value in values):
                return user

        return users[0] if users and isinstance(users[0], dict) else None

    # --------------------------------------------------------------- nodes

    async def list_nodes(self, force: bool = False) -> list:
        now = time.time()
        if (
            not force
            and self._nodes_cache is not None
            and now - self._nodes_cached_at < NODES_CACHE_TTL
        ):
            return list(self._nodes_cache)

        data = await self._request("GET", "/nodes")
        if isinstance(data, dict):
            nodes = data.get("nodes") or data.get("items") or []
        elif isinstance(data, list):
            nodes = data
        else:
            nodes = []

        nodes = [normalize_node(n) for n in nodes if isinstance(n, dict)]

        self._nodes_cache = list(nodes)
        self._nodes_cached_at = now
        return list(nodes)

    async def add_node(self, payload: dict) -> dict:
        data = await self._request("POST", "/nodes", json=payload)
        self._nodes_cache = None
        return normalize_node(data)

    async def delete_node(self, node_id: str) -> dict:
        data = await self._request("DELETE", f"/nodes/{node_id}")
        self._nodes_cache = None
        return data if isinstance(data, dict) else {}

    async def ping_node(self, node_id: str) -> dict:
        data = await self._request("POST", f"/nodes/{node_id}/ping")
        return data if isinstance(data, dict) else {}

    # -------------------------------------------------------------- system

    async def status(self) -> dict:
        data = await self._request("GET", "/status")
        return data if isinstance(data, dict) else {}

    async def restart(self) -> dict:
        data = await self._request("POST", "/system/restart")
        return data if isinstance(data, dict) else {}

    # Backward-compatible aliases
    async def restart_wdtt(self) -> dict:
        return await self.restart()

    async def restart_xray(self) -> dict:
        return await self.restart()
