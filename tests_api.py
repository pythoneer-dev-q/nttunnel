# -*- coding: utf-8 -*-
"""Тест клиента WDTT API против локальной мок-панели (aiohttp).

Проверяет:
  * заголовок X-API-Key и разворачивание конверта {"success","data"};
  * JWT-режим (POST /api/auth/token) + Bearer;
  * повтор запроса после 401 с перевыпуском токена;
  * создание/чтение/блокировку/сброс/удаление пользователя;
  * список нод, ping, добавление, удаление, статус, рестарт;
  * сборку ссылок нод из ответа панели.
"""
import asyncio
import os

os.environ.setdefault("BOT_TOKEN", "123:test")
os.environ.setdefault("ADMINS", "1")

from aiohttp import web  # noqa: E402

from bot.wdtt import WdttClient, WdttError, extract_node_links, node_online, panel_tg_id  # noqa: E402
from bot.services import public_subscription_url  # noqa: E402

API_KEY = "test-api-key"
USER = {
    "id": "tg_42",
    "name": "tg_42",
    "comment": "tg42",
    "password": "secret",
    "active": True,
    "status": "active",
    "expires_at": 0,
    "total_gb": 100,
    "traffic_used_bytes": 1024 ** 3,
    "max_devices": 2,
    "devices_bound": 1,
    "online": True,
    "sub_id": "abc",
    "subscription_url": "https://sub.example/abc",
    "link": "wdtt://master",
    "nodes": [
        {"id": "n1", "name": "NL", "link": "wdtt://nl"},
        {"id": "n2", "name": "DE", "links": {"wdtt": "wdtt://de"}},
    ],
}

# Реальная форма панели: без id, трафик в traffic_used, подписка в sub_url,
# пароль замаскирован, ссылки нод в node_links.
REAL_USER = {
    "name": "tg_77",
    "comment": "tg77",
    "password": "wdt****",
    "password_key": "realpass77",
    "active": True,
    "is_deactivated": False,
    "expires_at": 0,
    "total_gb": 0,
    "traffic_used": 356186820,
    "traffic_used_fmt": "339.7 MB",
    "max_devices": 1,
    "devices_bound": 1,
    "online": False,
    "sub_id": "s7w4uma0nloec356",
    "sub_url": "http://178.216.64.217:2096/sub/s7w4uma0nloec356",
    "link": "wdtt://real-master",
    "node_links": [
        {
            "node_id": "node_1f52a2b3",
            "node_name": "nl-1",
            "host": "85.31.148.176",
            "link": "wdtt://real-nl",
        }
    ],
}

state = {"logins": 0, "token": "jwt-token-1", "seen_headers": [], "methods": []}


def ok(data=None, **extra):
    payload = {"success": True, "data": data if data is not None else {}}
    payload.update(extra)
    return web.json_response(payload)


def err(message: str, status: int = 400):
    return web.json_response(
        {"success": False, "error": message, "code": status}, status=status
    )


async def auth_token(request: web.Request):
    body = await request.json()
    if body.get("username") != "root" or body.get("password") != "pw":
        return err("bad credentials", 401)
    state["logins"] += 1
    token = f"jwt-token-{state['logins']}"
    state["token"] = token
    return ok({"token": token, "expires_at": 9999999999, "user": "root"})


async def users(request: web.Request):
    state["methods"].append(("GET", "/api/users"))
    state["seen_headers"].append(dict(request.headers))
    users_list = [USER, REAL_USER]
    q = request.query.get("q", "")

    if q and q not in ("tg42", "tg_42", "tg42x"):
        users_list = []

    return ok({"total": len(users_list), "users": users_list})


async def create_user(request: web.Request):
    body = await request.json()
    state["create_body"] = body
    state["methods"].append(("POST", "/api/users"))
    if not body.get("name"):
        return err("name required")
    return ok({
        "id": body["name"],
        "password": "generated-pw",
        "subscription_url": "https://sub.example/new",
        "link": "wdtt://new",
    })


async def get_user(request: web.Request):
    user_id = request.match_info["user_id"]
    state["methods"].append(("GET", f"/api/users/{user_id}"))

    if user_id == USER["id"]:
        payload = dict(USER)
    elif user_id in (REAL_USER["sub_id"], REAL_USER["password_key"]):
        payload = dict(REAL_USER)
    else:
        return err("user not found", 404)

    # Реальная панель отдаёт карточку в ключе "user" (без "data").
    return web.json_response({"success": True, "user": payload})


async def update_user(request: web.Request):
    body = await request.json()
    state["methods"].append(("PUT", "/api/users"))
    return ok({"id": request.match_info["user_id"], **body})


async def action_user(request: web.Request):
    action = request.match_info["action"]
    state["methods"].append(("POST", f"/api/users/action/{action}"))
    if action == "vk-hashes":
        body = await request.json()
        state["added_hashes"] = body["hashes"]
        return web.json_response({"success": True, "user": {"id": request.match_info["user_id"], "vk_hash": ",".join(body["hashes"])}})
    return ok({}, message=f"user {action}")


async def delete_user(request: web.Request):
    state["methods"].append(("DELETE", "/api/users"))
    return ok({}, message="user deleted")


async def nodes(request: web.Request):
    state["methods"].append(("GET", "/api/nodes"))
    # реальная форма: статус в "status", флаг в "is_active"
    return ok({"nodes": [
        {"id": "n1", "name": "NL", "host": "nl.example", "is_active": True,
         "status": "online"},
        {"id": "n2", "name": "DE", "host": "de.example", "is_active": False,
         "status": "offline"},
    ]})


async def add_node(request: web.Request):
    body = await request.json()
    state["methods"].append(("POST", "/api/nodes"))
    return ok({"id": body.get("name"), **body})


async def ping_node(request: web.Request):
    state["methods"].append(("POST", "/api/nodes/ping"))
    return ok({"resolved": True})


async def delete_node(request: web.Request):
    state["methods"].append(("DELETE", "/api/nodes"))
    return ok({})


async def status(request: web.Request):
    if request.headers.get("Authorization") == "Bearer stale":
        return err("token expired", 401)
    return ok({"version": "2.0", "uptime": "1d", "traffic": {"up": 10, "down": 20}})


async def restart(request: web.Request):
    return ok({}, message="restarted")


def make_app() -> web.Application:
    app = web.Application()
    app.router.add_post("/api/auth/token", auth_token)
    app.router.add_post("/custom/api/auth/token", auth_token)
    app.router.add_get("/api/users", users)
    app.router.add_post("/api/users", create_user)
    app.router.add_get("/api/users/{user_id}", get_user)
    app.router.add_put("/api/users/{user_id}", update_user)
    app.router.add_post("/api/users/{user_id}/{action}", action_user)
    app.router.add_delete("/api/users/{user_id}", delete_user)
    app.router.add_get("/api/nodes", nodes)
    app.router.add_post("/api/nodes", add_node)
    app.router.add_post("/api/nodes/{node_id}/ping", ping_node)
    app.router.add_delete("/api/nodes/{node_id}", delete_node)
    app.router.add_get("/api/status", status)
    app.router.add_get("/custom/api/status", status)
    app.router.add_post("/api/system/restart", restart)
    return app


async def main():
    assert public_subscription_url({"sub_id": "abc", "subscription_url": "http://127.0.0.1:2096/sub/abc"}, {}, "https://public.example", "not-a-sub") == "https://public.example/not-a-sub/abc"
    assert public_subscription_url({"subscription_url": "http://127.0.0.1:2096/sub/abc"}, {}, "https://public.example/not-a-sub", "not-a-sub") == "https://public.example/not-a-sub/abc"
    assert public_subscription_url({}, {}, "https://public.example", "sub") == ""
    assert public_subscription_url({"subscription_url": "https://panel.example/sub/abc"}, {}, "", "") == "https://panel.example/sub/abc"
    assert not node_online({"enabled": True, "status": "offline"})
    assert not node_online({"enabled": True})
    assert panel_tg_id({"name": "tg_1234"}) != 123
    app = make_app()
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "127.0.0.1", 0)
    await site.start()
    port = runner.addresses[0][1]
    base = f"http://127.0.0.1:{port}"
    assert WdttClient(base + "/wdtt").api_base == base + "/api"
    assert WdttClient(base, api_url=base + "/custom/api/").api_base == base + "/custom/api"

    custom = WdttClient(base + "/wdtt", api_url=base + "/custom/api", username="root", password="pw")
    assert (await custom.status())["version"] == "2.0"
    await custom.close()
    state["logins"] = 0

    # ------------------------------------------------ 1. API-key режим
    client = WdttClient(base, api_key=API_KEY, timeout=10)

    users_data = await client.list_users(limit=10)
    assert users_data["total"] == 2, users_data
    assert users_data["users"][0]["id"] == "tg_42"

    # реальная карточка нормализуется к каноническим полям
    real = next(u for u in users_data["users"] if u["name"] == "tg_77")
    assert real["id"] == "s7w4uma0nloec356", real
    assert real["password"] == "realpass77", real
    assert real["traffic_used_bytes"] == 356186820, real
    assert real["subscription_url"].endswith("s7w4uma0nloec356"), real
    assert real["total_gb"] == 0 and real["online"] is False

    real_detail = await client.get_user("s7w4uma0nloec356", force=True)
    assert real_detail["password"] == "realpass77", real_detail
    assert real_detail["traffic_used_bytes"] == 356186820, real_detail

    real_links = extract_node_links(real_detail, [])
    assert [x["link"] for x in real_links] == ["wdtt://real-nl"]

    # ключ уходит в X-API-Key, JWT при этом не запрашивается
    headers = state["seen_headers"][-1]
    assert headers.get("X-API-Key") == API_KEY, headers
    assert "Authorization" not in headers, headers
    assert state["logins"] == 0, "JWT не должен запрашиваться при наличии ключа"

    user = await client.get_user("tg_42")
    assert user["traffic_used_bytes"] == 1024 ** 3

    # кеш: повторный get_user не должен ходить в сеть
    calls_before = len(state["methods"])
    await client.get_user("tg_42")
    assert len(state["methods"]) == calls_before, "user cache не работает"

    created = await client.create_user(
        name="tg_77", comment="tg77", total_gb=50, max_devices=2,
        vk_hash="hash1,hash2"
    )
    assert created["id"] == "tg_77" and created["password"] == "generated-pw"
    assert state["create_body"]["vk_hash"] == "hash1,hash2"
    updated = await client.add_vk_hashes("tg_42", ["hash1", "hash2"])
    assert updated["vk_hash"] == "hash1,hash2" and state["added_hashes"] == ["hash1", "hash2"]

    await client.update_user("tg_42", total_gb=150)
    await client.block_user("tg_42")
    await client.activate_user("tg_42")
    await client.reset_traffic("tg_42")

    nodes_list = await client.list_nodes()
    assert len(nodes_list) == 2

    added = await client.add_node({"name": "FI", "host": "fi.example"})
    assert added["id"] == "FI"

    ping = await client.ping_node("n1")
    assert ping["resolved"] is True

    await client.delete_node("n1")

    st = await client.status()
    assert st["version"] == "2.0"
    await client.restart()

    # 404 → WdttError со статусом
    try:
        await client.get_user("missing")
    except WdttError as e:
        assert e.status == 404, e
    else:
        raise AssertionError("ожидалась ошибка 404")

    # ссылки нод
    links = extract_node_links(user, nodes_list)
    values = [x["link"] for x in links]
    assert "wdtt://nl" in values and "wdtt://de" in values
    assert "wdtt://master" not in values
    assert "wdtt://master" in [x["link"] for x in extract_node_links(user, nodes_list, include_main=True)]

    await client.close()

    # ------------------------------------------------ 2. JWT-режим
    state["logins"] = 0
    jwt = WdttClient(base, username="root", password="pw", timeout=10)

    data = await jwt.list_users(limit=5)
    assert data["total"] == 2
    assert state["logins"] == 1, state["logins"]
    assert jwt._token == "jwt-token-1"

    headers = state["seen_headers"][-1]
    assert headers.get("Authorization") == "Bearer jwt-token-1", headers
    assert "X-API-Key" not in headers, headers

    # токен переиспользуется
    await jwt.get_user("tg_42", force=True)
    assert state["logins"] == 1, "токен не кешируется"

    # 401 → перевыпуск токена и автоматический повтор запроса
    import time as _time

    jwt._token = "stale"
    jwt._token_expires_at = _time.time() + 3600
    logins_before = state["logins"]

    st2 = await jwt.status()
    assert st2["version"] == "2.0", st2
    assert state["logins"] == logins_before + 1, state["logins"]
    assert jwt._token == f"jwt-token-{state['logins']}"

    await jwt.close()
    await runner.cleanup()

    print("API_TEST_OK")


if __name__ == "__main__":
    asyncio.run(main())
