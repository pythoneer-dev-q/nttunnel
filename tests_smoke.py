# -*- coding: utf-8 -*-
"""Оффлайн-тесты: конфиг, форматирование, ссылки нод, клавиатуры, тексты."""
import os

os.environ.setdefault("BOT_TOKEN", "123:test")
os.environ.setdefault("ADMINS", "1")


def test_config():
    from bot.config import load_config

    cfg = load_config()
    assert cfg.panel_base.startswith("https")
    assert cfg.defaults_total_gb == 175
    assert cfg.defaults_max_devices >= 1
    assert cfg.nodes_copy_limit == 5
    print("config OK:", cfg.panel_base, cfg.defaults_total_gb)


def test_helpers():
    from bot.wdtt import (
        expires_text,
        extract_node_links,
        human_bytes,
        node_online,
        online_flag,
        panel_tg_id,
        traffic_bar,
    )
    from bot.services import as_int

    assert human_bytes(0) == "0 Б"
    assert human_bytes(1024) == "1.0 КБ"
    assert human_bytes(1024 ** 3) == "1.0 ГБ"

    bar, used, total, pct = traffic_bar(1024 ** 3, 100)
    assert "█" in bar and used == "1.0 ГБ" and total == "100 ГБ"
    assert pct == 1

    assert expires_text(0) == "бессрочно"
    assert panel_tg_id({"comment": "tg123456"}) == 123456
    assert panel_tg_id({"name": "tg_42"}) == 42

    detail = {
        "link": "wdtt://master",
        "nodes": [
            {"name": "NL", "link": "wdtt://nl"},
            {"node": {"name": "DE"}, "links": {"wdtt": "wdtt://de"}},
        ],
    }
    nodes = [{"id": "n1", "name": "NL", "host": "nl.example"}]
    links = extract_node_links(detail, nodes)

    assert any(x["link"] == "wdtt://nl" for x in links)
    assert any(x["link"] == "wdtt://de" for x in links)
    assert not any(x["link"] == "wdtt://master" for x in links)
    assert any(x["link"] == "wdtt://master" for x in extract_node_links(detail, nodes, include_main=True))
    duplicate = {"link": "wdtt://master", "nodes": [{"link": "wdtt://master"}, {"is_main": True, "link": "wdtt://other"}]}
    assert not extract_node_links(duplicate)

    # строковые булевы значения панели
    assert online_flag(True) and online_flag("true") and online_flag("online")
    assert not online_flag("false") and not online_flag("0") and not online_flag(None)
    assert node_online({"online": "false"}) is False
    assert node_online({"status": "active"}) is True
    assert node_online({"enabled": 1}) is False

    assert as_int("12") == 12
    assert as_int("12.9") == 12
    assert as_int(None) == 0
    assert as_int("n/a", 7) == 7
    print("helpers OK")


def test_keyboards():
    from bot.keyboards import (
        access_kb,
        adm_root_kb,
        agreement_kb,
        apps_kb,
        menu_kb,
        nodes_kb,
        sub_kb,
        subscribe_kb,
        support_kb,
    )

    ads = [{"title": "AD", "url": "https://ad.io"}]
    sections = [{"key": "faq", "title": "FAQ"}]
    links = [
        {"name": f"Node {i}", "link": f"wdtt://node-{i}"}
        for i in range(7)
    ]

    keyboards = [
        menu_kb(False, ads, sections),
        menu_kb(True, ads, sections),
        access_kb(links, "https://sub.example", 5, len(links)),
        sub_kb("https://sub.example", links, 5),
        apps_kb([{"label": "App", "url": "https://app"}]),
        agreement_kb(),
        support_kb(),
        subscribe_kb([{"channel_id": -100123, "title": "Ch"}]),
        adm_root_kb(),
        nodes_kb([{"id": "n1", "name": "N1", "online": True}], 0, 1),
    ]

    for kb in keyboards:
        assert kb.inline_keyboard

    # динамические разделы попали в меню
    data = [
        b.callback_data
        for row in menu_kb(True, ads, sections).inline_keyboard
        for b in row
        if b.callback_data
    ]
    assert "u:sec:faq" in data

    # Единственная кнопка копирования ведёт на подписку.
    copied = [
        b
        for row in access_kb(links, "https://sub", 5, 7).inline_keyboard
        for b in row
        if b.copy_text
    ]
    assert len(copied) == 1 and copied[0].copy_text.text == "https://sub"

    labels = [
        b.text
        for row in access_kb(links, "https://sub", 5, 7).inline_keyboard
        for b in row
    ]
    assert not any("Node" in (t or "") for t in labels)
    assert menu_kb(True, ads, sections).inline_keyboard[-1][0].callback_data == "u:apps"
    assert "u:ref" not in data and "u:sub" not in data

    # callback_data в пределах лимита Telegram
    for kb in keyboards:
        for row in kb.inline_keyboard:
            for button in row:
                if button.callback_data:
                    assert len(button.callback_data.encode()) <= 64

    print("keyboards OK")


def test_texts():
    from bot.texts import access_text, menu_text, sub_text

    user = {
        "tg_id": 1,
        "full_name": "Test",
        "registered": True,
        "panel_total_gb": 175,
        "panel_traffic_used_bytes": 10 * 1024 ** 3,
        "panel_expires_at": 0,
        "panel_max_devices": 2,
        "panel_devices_bound": 1,
        "panel_online": True,
        "panel_status": "active",
        "panel_password": "pwd",
        "subscription_url": "https://sub.example",
    }
    live = {
        "id": "tg_1",
        "password": "pwd",
        "total_gb": 175,
        "traffic_used_bytes": 10 * 1024 ** 3,
        "expires_at": 0,
        "max_devices": 2,
        "devices_bound": 1,
        "online": True,
        "active": True,
        "status": "active",
        "link": "wdtt://master",
        "subscription_url": "https://sub.example",
    }
    links = [
        {"name": f"Node {i}", "link": f"wdtt://node-{i}"} for i in range(6)
    ]

    menu = menu_text(user)
    access = access_text(user, live, links, 5)
    sub = sub_text(user, live, links)

    assert "10.0 ГБ" not in menu and "175 ГБ" not in menu
    assert "10.0 ГБ" in access and "https://sub.example" in access
    assert "10.0 ГБ" in sub and "https://sub.example" in sub
    print("texts OK")


def test_copy_limit():
    from bot.keyboards import copy_btn

    short = copy_btn("Copy", "wdtt://short")
    assert short.copy_text is not None

    long = copy_btn("Copy", "wdtt://" + "x" * 300, cb="u:show:0")
    assert long.copy_text is None
    assert long.callback_data == "u:show:0"
    print("copy limit OK")


if __name__ == "__main__":
    test_config()
    test_helpers()
    test_keyboards()
    test_texts()
    test_copy_limit()
    print("ALL_TESTS_OK")
