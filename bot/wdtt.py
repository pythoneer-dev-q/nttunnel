# -*- coding: utf-8 -*-
"""Асинхронный клиент WDTT Panel API."""

import asyncio
import json
import logging
import re
import ssl as ssl_mod
import time
from typing import Any, Optional

import aiohttp

log = logging.getLogger(__name__)

_CSRF_HTML_RE = re.compile(
    r'<input[^>]+(?:name=["\'][^"\']*csrf[^"\']*["\'][^>]*value=["\']([^"\']+)["\']'
    r'|value=["\']([^"\']+)["\'][^>]*name=["\'][^"\']*csrf[^"\']*["\'])',
    re.I,
)


class WdttError(Exception):
    pass


class WdttClient:
    PREV_NAME_LIST = ("wdtt-csrf",)

    def __init__(
        self,
        base_url: str,
        username: str,
        password: str,
        ssl_insecure: bool = True,
    ):
        self.base = base_url.rstrip("/")
        self.username = username
        self.password = password
        self.ssl_insecure = ssl_insecure

        self._session: Optional[aiohttp.ClientSession] = None
        self._logged_at = 0.0
        self._lock = asyncio.Lock()
        self._csrf = ""

        # Кэш списка пользователей панели + O(1)-индексы для поиска.
        # Панель не отдаёт пользователя по паролю, поэтому список
        # запрашиваем не на каждый поиск, а по TTL/при изменении данных.
        self._users_ttl = 15.0
        self._users_cache: Optional[dict] = None
        self._users_cached_at = 0.0
        self._users_index: dict[str, dict] = {}
        self._users_comment_index: dict[str, dict] = {}
        self._users_lock = asyncio.Lock()

        # Персистентное зеркало (Database). Подключается через attach_store.
        self._store = None

    def attach_store(self, store):
        """Подключает персистентное зеркало пользователей панели."""
        self._store = store

    # ------------------------------------------------------------------ core

    async def _get_session(self) -> aiohttp.ClientSession:
        session = self._session
        if session is not None and not session.closed:
            return session

        connector = None

        if self.base.startswith("https"):
            ctx = ssl_mod.create_default_context()

            if self.ssl_insecure:
                ctx.check_hostname = False
                ctx.verify_mode = ssl_mod.CERT_NONE

            connector = aiohttp.TCPConnector(
                ssl=ctx,
                limit=100,
                limit_per_host=100,
                ttl_dns_cache=300,
                enable_cleanup_closed=True,
            )
        else:
            connector = aiohttp.TCPConnector(
                limit=100,
                limit_per_host=100,
                ttl_dns_cache=300,
                enable_cleanup_closed=True,
            )

        self._session = aiohttp.ClientSession(
            timeout=aiohttp.ClientTimeout(
                total=25,
                connect=10,
                sock_connect=10,
                sock_read=20,
            ),
            cookie_jar=aiohttp.CookieJar(unsafe=True),
            connector=connector,
        )

        return self._session

    async def close(self):
        session = self._session
        self._session = None

        if session is not None and not session.closed:
            await session.close()

    def _dump_cookies(self, s) -> str:
        """Список имён и префиксов значений cookie для логирования."""
        try:
            cookies = s.cookie_jar.filter_cookies(self.base + "/")
            return "; ".join(
                f"{name}={cookie.value[:12]}..."
                for name, cookie in cookies.items()
            )
        except Exception:  # noqa: BLE001
            return "?"

    async def _seed_csrf(self, s) -> str:
        """Получает CSRF из cookie, при отсутствии один раз открывает /login."""

        cookies = s.cookie_jar.filter_cookies(self.base + "/")

        for name in self.PREV_NAME_LIST:
            cookie = cookies.get(name)
            if cookie is not None and cookie.value:
                return cookie.value

        try:
            async with s.get(f"{self.base}/login") as r:
                await r.release()
        except (aiohttp.ClientError, asyncio.TimeoutError) as e:
            log.debug("CSRF seed failed: %s", e)
            return ""

        cookies = s.cookie_jar.filter_cookies(f"{self.base}/login")

        for name in self.PREV_NAME_LIST:
            cookie = cookies.get(name)
            if cookie is not None and cookie.value:
                return cookie.value

        cookies = s.cookie_jar.filter_cookies(self.base + "/")

        for name in self.PREV_NAME_LIST:
            cookie = cookies.get(name)
            if cookie is not None and cookie.value:
                return cookie.value

        return ""

    async def _csrf_from_html(self, s) -> str:
        """Fallback: извлекает CSRF из HTML /login."""

        try:
            async with s.get(f"{self.base}/login") as r:
                html = await r.text()
        except (aiohttp.ClientError, asyncio.TimeoutError):
            return ""

        match = _CSRF_HTML_RE.search(html)

        if not match:
            return ""

        return match.group(1) or match.group(2) or ""

    async def _refresh_csrf(self, s) -> str:
        """Обновляет CSRF только при необходимости."""

        token = await self._seed_csrf(s)

        if not token:
            token = await self._csrf_from_html(s)

        if token:
            self._csrf = token

        return self._csrf

    async def _ensure_login(self):
        """Авторизация с защитой от параллельных повторных логинов."""

        if time.monotonic() - self._logged_at < 30 * 60:
            return

        async with self._lock:
            if time.monotonic() - self._logged_at < 30 * 60:
                return

            s = await self._get_session()

            try:
                await self._refresh_csrf(s)

                data = {
                    "username": self.username,
                    "password": self.password,
                }

                headers = {"Referer": self.base + "/"}

                if self._csrf:
                    headers["X-CSRF-Token"] = self._csrf

                async with s.post(
                    f"{self.base}/login",
                    json=data,
                    headers=headers,
                    allow_redirects=False,
                ) as r:
                    text = await r.text()

                    rejected = (
                        r.status not in (200, 201, 302, 303)
                        or self._login_rejected(text)
                    )

                if rejected:
                    await self._refresh_csrf(s)

                    if self._csrf:
                        headers["X-CSRF-Token"] = self._csrf
                    else:
                        headers.pop("X-CSRF-Token", None)

                    async with s.post(
                        f"{self.base}/login",
                        data=data,
                        headers=headers,
                        allow_redirects=False,
                    ) as r:
                        text = await r.text()

                        rejected = (
                            r.status not in (200, 201, 302, 303)
                            or self._login_rejected(text)
                        )

                if rejected:
                    raise WdttError(f"login rejected: {text[:200]}")

                await self._refresh_csrf(s)
                self._logged_at = time.monotonic()

                log.debug("WDTT panel login OK: %s", self.base)

            except WdttError:
                raise
            except (aiohttp.ClientError, asyncio.TimeoutError) as e:
                raise WdttError(f"panel unreachable: {e}") from e

    @staticmethod
    def _login_rejected(text: str) -> bool:
        """True, если сервер ответил {'success': false}."""

        try:
            data = json.loads(text)
        except (json.JSONDecodeError, TypeError):
            return False

        return isinstance(data, dict) and data.get("success") is False

    async def _request(
        self,
        method: str,
        path: str,
        payload: Any = None,
        retries: int = 2,
    ) -> Any:
        s = await self._get_session()
        url = f"{self.base}{path}"
        last_err = "unknown error"

        for attempt in range(retries + 1):
            await self._ensure_login()

            headers = {}

            if self._csrf:
                headers["X-CSRF-Token"] = self._csrf

            if isinstance(payload, dict):
                body = payload.copy()

                # Первый запрос идёт сразу с наиболее вероятным вариантом.
                if self._csrf:
                    body["_csrf"] = self._csrf
            else:
                body = payload

            try:
                async with s.request(
                    method,
                    url,
                    json=body if body is not None else {},
                    headers=headers,
                ) as r:
                    text = await r.text()

            except (aiohttp.ClientError, asyncio.TimeoutError) as e:
                last_err = f"{method} {path}: {e}"

                if attempt < retries:
                    continue

                raise WdttError(last_err) from e

            try:
                data = json.loads(text)
            except json.JSONDecodeError as e:
                raise WdttError(
                    f"{method} {path}: bad json ({text[:200]!r})"
                ) from e

            if not isinstance(data, dict) or data.get("success") is not False:
                return data.get("obj") if isinstance(data, dict) else data

            last_err = str(data.get("msg", "unknown error"))
            low = last_err.lower()

            if "csrf" not in low and "unauthorized" not in low:
                raise WdttError(last_err)

            # Сессия или CSRF протухли. Следующая итерация перелогинится.
            self._logged_at = 0.0
            self._csrf = ""

            if attempt < retries:
                continue

        raise WdttError(f"{method} {path}: {last_err}")

    # ------------------------------------------------------------ endpoints

    async def status(self) -> dict:
        return await self._request("GET", "/panel/api/status")

    async def get_inbound(self) -> dict:
        return await self._request("GET", "/panel/api/inbound")

    async def save_inbound(self, payload: dict) -> dict:
        return await self._request(
            "POST",
            "/panel/api/inbound/save",
            payload,
        )

    async def get_users(self, force: bool = False) -> dict:
        """{'main_password': ..., 'users': [...], 'inbound': {...}}.

        Результат кэшируется на ``_users_ttl`` секунд. ``force=True``
        заставляет перечитать список (после записи в панель).
        """
        return await self._load_users(force=force)

    # ------------------------------------------------------- users cache/index

    @staticmethod
    def _index_users(data: dict) -> tuple[dict, dict]:
        """Строит индексы O(1): по паролю и по комментарию."""
        by_password: dict[str, dict] = {}
        by_comment: dict[str, dict] = {}

        for u in (data.get("users") or []):
            if not isinstance(u, dict):
                continue

            for key in (u.get("password_key"), u.get("password")):
                if key:
                    by_password[str(key)] = u

            comment = u.get("comment")
            if comment:
                by_comment.setdefault(str(comment), u)

        return by_password, by_comment

    def invalidate_users(self):
        """Сбрасывает кэш списка пользователей (после add/update/delete)."""
        self._users_cache = None
        self._users_cached_at = 0.0
        self._users_index = {}
        self._users_comment_index = {}

    async def _load_users(self, force: bool = False) -> dict:
        """Отдаёт список пользователей из кэша или запрашивает один раз.

        Single-flight: параллельные вызовы не плодят запросы к панели.
        """
        now = time.monotonic()

        if (
            not force
            and self._users_cache is not None
            and now - self._users_cached_at < self._users_ttl
        ):
            return self._users_cache

        async with self._users_lock:
            now = time.monotonic()

            if (
                not force
                and self._users_cache is not None
                and now - self._users_cached_at < self._users_ttl
            ):
                return self._users_cache

            data = await self._request("GET", "/panel/api/users")

            if not isinstance(data, dict):
                data = {}

            self._users_cache = data
            self._users_cached_at = time.monotonic()
            (
                self._users_index,
                self._users_comment_index,
            ) = self._index_users(data)

            await self._persist(data)

            return data

    async def _persist(self, data: dict):
        """Сохраняет снапшот пользователей в персистентное зеркало."""
        if self._store is None or not data:
            return
        try:
            await self._store.sync_panel_users(
                data.get("users") or [],
                inbound=data.get("inbound"),
                main_password=data.get("main_password"),
            )
        except Exception as e:  # noqa: BLE001 — зеркало не должно ломать flow
            log.warning("panel mirror sync failed: %s", e)

    async def add_user(
        self,
        comment: str = "",
        total_gb: int = 0,
        max_devices: int = 1,
        expires_at: int = 0,
        active: bool = True,
    ) -> str:
        """Создаёт пользователя, возвращает его пароль."""

        payload = {
            "comment": comment,
            "expires_at": expires_at,
            "total_gb": total_gb,
            "max_down_mbps": 0,
            "max_up_mbps": 0,
            "max_devices": max_devices,
            "active": active,
            "count": 1,
        }

        obj = await self._request(
            "POST",
            "/panel/api/users/add",
            payload,
        )

        self.invalidate_users()

        if isinstance(obj, dict):
            passwords = obj.get("passwords")

            if passwords:
                return passwords[0]

            password = obj.get("password")

            if password:
                return password

        if isinstance(obj, str):
            return obj

        raise WdttError(f"unexpected add_user response: {obj!r}")

    async def update_user(self, password: str, **fields) -> dict:
        """Обновить пользователя."""

        payload = {"old_password": password}
        payload.update(fields)

        result = await self._request(
            "POST",
            "/panel/api/users/update",
            payload,
        )

        self.invalidate_users()

        return result

    async def delete_user(self, password: str) -> dict:
        result = await self._request(
            "POST",
            "/panel/api/users/delete",
            {"password": password},
        )

        self.invalidate_users()

        return result

    async def reset_traffic(self, password: str) -> dict:
        result = await self._request(
            "POST",
            "/panel/api/users/reset-traffic",
            {"password": password},
        )

        self.invalidate_users()

        return result

    async def restart_wdtt(self) -> Any:
        return await self._request(
            "POST",
            "/panel/api/server/restartWdttService",
            {},
        )

    async def restart_xray(self) -> Any:
        return await self._request(
            "POST",
            "/panel/api/server/restartXrayService",
            {},
        )

    # ------------------------------------------------------------- helpers

    def _indexed_user(self, key: str) -> Optional[dict]:
        """Ищет в прогретом in-memory индексе (обновляется фоновым sync)."""
        if self._users_cache is None:
            return None
        return self._users_index.get(key) or self._users_comment_index.get(key)

    async def _store_user(self, key: str) -> Optional[dict]:
        """Ищет в персистентном зеркале (если подключено)."""
        if self._store is None:
            return None
        try:
            return await self._store.get_panel_user(key)
        except Exception as e:  # noqa: BLE001
            log.warning("panel mirror read failed: %s", e)
            return None

    async def find_user(
        self,
        comment_or_password: str,
        force: bool = False,
    ) -> Optional[dict]:
        """Находит пользователя по паролю/комментарию.

        Порядок чтения (без перебора всех пользователей):
          1) прогретый in-memory индекс;
          2) персистентное зеркало в MongoDB;
          3) панель — только при ``force=True`` или холодном старте.

        Панель на обычные чтения не дёргается: свежесть обеспечивает
        фоновая синхронизация (``panel_sync_loop``).
        """
        if not comment_or_password:
            return None

        key = str(comment_or_password)

        if not force:
            user = self._indexed_user(key)

            if user is not None:
                return user

            user = await self._store_user(key)

            if user is not None:
                return user

        try:
            await self._load_users(force=force)
        except WdttError:
            # Панель недоступна — отдаём устаревшее зеркало/кэш, если есть.
            user = self._indexed_user(key)

            if user is None:
                user = await self._store_user(key)

            return user

        return self._indexed_user(key)

    @staticmethod
    def build_link(
        inbound: dict,
        password: str,
        ps: str = "",
        vk_hashes: list | None = None,
        app: str = "wdtt",
    ) -> str:
        """Генерирует WDTT-ссылку напрямую из данных inbound."""
        host = (
            inbound.get("server_host")
            or inbound.get("server_ip")
            or inbound.get("listen_host")
            or ""
        )

        host = str(host).strip()

        if not host or host == "0.0.0.0":
            raise WdttError("server host/ip is missing")

        dtls = inbound.get("dtls_port")
        wg = inbound.get("wg_port")
        client = inbound.get("client_port")

        if not dtls or not wg:
            raise WdttError(
                f"incomplete inbound data: dtls_port={dtls}, wg_port={wg}"
            )

        hashes = ",".join(
            h for h in (vk_hashes or [])
            if h
        )

        core = f"{host}:{dtls}:{wg}:{client or 0}:{password}"

        if hashes:
            core += f":{hashes}"

        return f"wdtt://{core}"