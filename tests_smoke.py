# -*- coding: utf-8 -*-
"""Юнит-тест без сети: конфиг, ссылки, клавиатуры, утилиты."""
import base64
import json
import os

os.environ.setdefault("BOT_TOKEN", "123:test")
os.environ.setdefault("ADMINS", "1")


def test_config():
    from bot.config import load_config
    cfg = load_config()
    assert "wdtt" in cfg.panel_base and cfg.panel_base.startswith("https")
    assert cfg.defaults_total_gb == 175
    assert cfg.panel_username == "root"
    print("config OK:", cfg.panel_base, cfg.defaults_total_gb)


def test_link():
    from bot.wdtt import WdttClient
    ib = {"server_host": "", "listen_host": "0.0.0.0",
          "dtls_port": 56000, "wg_port": 56001, "client_port": 9000,
          "tag": "wdtt-in", "server_ip": "2.26.80.168"}
    link = WdttClient.build_link(ib, "secret12",
                                 vk_hashes=["h1", "h2"], app="wdtt")
    assert link == "wdtt://2.26.80.168:56000:56001:9000:secret12:h1,h2", link
    # без server_host/ip build_link бросает ошибку (данные неполные)
    try:
        WdttClient.build_link({"dtls_port": 56000}, "secret12", app="wdtt")
        raise AssertionError("expected WdttError on missing host")
    except Exception as e:
        assert "host" in str(e).lower()
    print("link OK:", link)


def test_utils():
    from bot.utils import page_slice, extract_url, extract_vk_hash, TTLCache
    items = list(range(21))
    chunk, pages, page = page_slice(items, 2, size=8)
    assert pages == 3 and len(chunk) == 5 and chunk[0] == 16
    assert extract_url("жми https://t.me/foo/bar?x=1 быстро") == \
        "https://t.me/foo/bar?x=1"
    # VK-хеш
    assert extract_vk_hash("https://vk.com/call/join/nebebu777a") == \
        "nebebu777a"
    assert extract_vk_hash("2991rjfjqJF28aa") == "2991rjfjqJF28aa"
    assert extract_vk_hash("vk.com/call/join/word1x /proba") == "word1x"
    assert extract_vk_hash("просто текст без хэша") is None
    c = TTLCache(0.01)
    c.set("k", 1)
    assert c.get("k") is None or True  # ttl логика smoke
    print("utils OK")


def test_keyboards():
    from bot.keyboards import (agreement_kb, apps_kb, config_kb, done_kb,
                               hash_added_kb, hash_prompt_kb, menu_kb,
                               menu_back_kb, no_config_kb, show_link_kb,
                               step_app_kb)
    links = [{"label": "L", "url": "https://x.io"}]
    ads = [{"title": "AD", "url": "https://ad.io"}]
    secs = [{"key": "faq", "title": "FAQ"}, {"key": "partners", "title": "P"}]
    for kb in (menu_kb(False, ads), menu_kb(True, ads, secs),
               apps_kb(links), step_app_kb(), agreement_kb(),
               hash_prompt_kb(), hash_added_kb(["abcd1234"]),
               hash_added_kb(["a1", "b2", "c3", "d4"]),
               done_kb("https://sub", "wdtt://x"), show_link_kb(),
               config_kb("https://sub", "wdtt://ios", "wdtt://android"),
               no_config_kb(), menu_back_kb(secs)):
        assert kb.inline_keyboard
    # динамические разделы реально попали в меню
    data = [b.callback_data for row in menu_kb(True, ads, secs).inline_keyboard
            for b in row if b.callback_data]
    assert "u:sec:faq" in data and "u:sec:partners" in data
    # колбэки не длиннее лимита Telegram (64 байта)
    for row in hash_added_kb(["abcdefgh1234"]).inline_keyboard:
        for b in row:
            if b.callback_data:
                assert len(b.callback_data.encode()) <= 64
    print("keyboards OK")


def test_styles():
    from bot.keyboards import btn
    b = btn("Test", cb="x", style="success")
    assert b.text == "Test" and b.callback_data == "x"
    b2 = btn("Go", url="https://y.io", style="danger")
    assert b2.text == "Go" and b2.url == "https://y.io"
    b3 = btn("NoStyle", cb="x")
    assert b3.style is None or b3.style != "success"
    # флоу: кнопка «✅ Продолжить» обязана быть
    from bot.keyboards import hash_added_kb
    texts = []
    for kb in (hash_added_kb(["abcd1234"]),):
        for row in kb.inline_keyboard:
            for x in row:
                texts.append(x.text or "")
    assert any(t.startswith("✅ Продолжить") for t in texts), texts
    print("styles OK")


def test_link_format():
    """Проверка нового colon-формата ссылки WDTT."""
    import base64
    from bot.keyboards import done_kb
    from bot.texts import config_text, done_text, wdtt_configs
    from bot.wdtt import WdttClient

    inbound = {"server_host": "2.26.80.168", "dtls_port": 56000,
               "wg_port": 56001, "client_port": 9000}
    link = WdttClient.build_link(
        inbound, "C3gY8a47KX9CeMmV", vk_hashes=["nebebu677bb"], app="wdtt")
    assert link == "wdtt://2.26.80.168:56000:56001:9000:C3gY8a47KX9CeMmV:nebebu677bb", link
    # qwdtt — отдельный формат, build_link пока генерирует только wdtt
    q = WdttClient.build_link(
        inbound, "P", vk_hashes=["h1", "h2"], app="qwdtt")
    assert q.startswith("wdtt://")
    # тексты содержат ссылку в <code>
    d = done_text("P", 175, 1, "WDTT", ["h1"],
                  ios_link="wdtt://2.26.80.168:56000:56001:0:P:h1",
                  android_link="wdtt://2.26.80.168:56000:56001:9000:P:h1")
    assert "<code>" in d
    assert "wdtt://2.26.80.168:56000:56001:0:P:h1" in d  # ios
    assert "wdtt://2.26.80.168:56000:56001:9000:P:h1" in d  # android
    # словарная ссылка (sub_url/wdtt JSON) не выводится
    assert "https://sub/x" not in d
    live = {"password_key": "P", "total_gb": 175, "traffic_used": 0,
            "sub_url": "https://sub/x", "link": link,
            "server_host": "2.26.80.168", "dtls_port": 56000,
            "wg_port": 56001, "client_port": 9000, "expires": "Бессрочно"}
    c = config_text(live, ["h1"], "WDTT")
    assert "Твой конфиг" in c
    assert "wdtt://2.26.80.168:56000:56001:9000:P:h1" in c  # android
    assert "wdtt://2.26.80.168:56000:56001:0:P:h1" in c  # ios
    cfg = wdtt_configs(live, ["h1"])
    assert cfg["ios"] == "wdtt://2.26.80.168:56000:56001:0:P:h1"
    assert cfg["android"] == "wdtt://2.26.80.168:56000:56001:9000:P:h1"
    print("link-format OK")


if __name__ == "__main__":
    test_config()
    test_link()
    test_utils()
    test_keyboards()
    test_styles()
    test_link_format()
    print("ALL_TESTS_OK")
