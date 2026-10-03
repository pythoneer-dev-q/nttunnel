# -*- coding: utf-8 -*-
"""Конфигурация: читает .env (основной) + creds.txt (fallback).

Все параметры WDTT и Telegram задаются в .env. creds.txt — запасной
источник, если .env не заполнен.
"""
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlparse


def _load_env_file(path: str):
    """Парсит .env вручную (без зависимости от python-dotenv).

    Устанавливает переменные в os.environ, если их там ещё нет.
    """
    p = Path(path)
    if not p.exists():
        return
    for line in p.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, val = line.partition("=")
        key = key.strip()
        val = val.strip().strip("'\"")
        if key and val and key not in os.environ:
            os.environ[key] = val


def _parse_creds(path: str) -> dict:
    """Парсит creds.txt (fallback). Строки 'KEY = value', кавычки срезаются."""
    out = {}
    p = Path(path)
    if not p.exists():
        return out
    for line in p.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or "=" not in line:
            continue
        key, _, val = line.partition("=")
        key = key.strip().upper().replace("-", "_")
        val = val.strip().strip("'\"")
        if val:
            out[key] = val
    return out


def parse_limit_gb(s: str) -> int:
    m = re.search(r"(\d+(?:[.,]\d+)?)", str(s))
    return int(float(m.group(1).replace(",", "."))) if m else 0


@dataclass
class Config:
    bot_token: str = ""
    admin_ids: list = field(default_factory=list)
    mongo_uri: str = "mongodb://localhost:27017"
    mongo_db: str = "nttunnel"

    # WDTT
    host: str = ""                # хост панели (без порта и пути)
    panel_base: str = ""          # https://host:2860/wdtt
    panel_username: str = ""
    panel_password: str = ""
    vpn_password: str = ""
    sub_url: str = ""             # https://host/ (база подписок)
    sub_path: str = ""            # not-a-sub
    admin_path: str = ""          # /godmode/
    ssl_insecure: bool = True

    defaults_total_gb: int = 175

    # Панель: интервал фоновой синхронизации зеркала пользователей (сек).
    # Панель отдаёт список медленно (~35-40с) — по умолчанию раз в час.
    panel_sync_sec: int = 3600


def load_config(base_dir: str | None = None) -> Config:
    base_dir = base_dir or os.path.dirname(
        os.path.dirname(os.path.abspath(__file__))
    )

    # 1. Загружаем .env (основной источник).
    _load_env_file(os.path.join(base_dir, ".env"))

    # 2. creds.txt — fallback, если .env не заполнен.
    creds = _parse_creds(os.path.join(base_dir, "creds.txt"))

    def _get(env_key: str, creds_key: str = "", default: str = "") -> str:
        """env имеет приоритет над creds.txt."""
        return os.getenv(env_key, "") or creds.get(creds_key, "") or default

    cfg = Config()

    # Telegram
    cfg.bot_token = _get("BOT_TOKEN", "BOT_TOKEN")
    admins_raw = _get("ADMINS", "ADMINS")
    cfg.admin_ids = [
        int(x) for x in re.split(r"[,\s]+", admins_raw)
        if x.strip().lstrip("-").isdigit()
    ]

    # MongoDB
    cfg.mongo_uri = _get("MONGO_URI", "MONGO_URI", "mongodb://localhost:27017")
    cfg.mongo_db = _get("MONGO_DB", "MONGO_DB", "nttunnel")

    # WDTT panel
    raw_base = _get("PANEL_BASE", "BASE_URL",
                    "https://127.0.0.1:2860/").rstrip("/")
    if "/wdtt" not in raw_base:
        cfg.panel_base = f"{raw_base}/wdtt"
    else:
        cfg.panel_base = raw_base

    # Хост панели из URL (без порта и пути)
    parsed = urlparse(cfg.panel_base)
    cfg.host = parsed.hostname or ""

    cfg.panel_username = _get("ADMIN_USERNAME", "ADMIN_USERNAME", "admin")
    cfg.panel_password = _get("ADMIN_PASSWORD", "ADMIN_PASSWORD")
    cfg.vpn_password = _get("VPN_PASSWORD", "VPN_PASSWORD")
    cfg.sub_url = _get("SUB_URL", "SUB_URL").rstrip("/")
    cfg.sub_path = _get("SUB_PATH", "SUB_PATH")
    cfg.admin_path = _get("ADMIN_PATH", "ADMIN_PATH")
    cfg.ssl_insecure = _get(
        "SSL_INSECURE", "SSL_INSECURE", "1"
    ).lower() not in ("0", "false", "no")

    limit_str = _get("USER_DEFAULT_LIMIT", "USER_DEFAULT_LIMIT", "175 GB")
    cfg.defaults_total_gb = parse_limit_gb(limit_str) or 175

    try:
        cfg.panel_sync_sec = max(
            10, int(_get("PANEL_SYNC_SEC", "PANEL_SYNC_SEC", "3600"))
        )
    except ValueError:
        cfg.panel_sync_sec = 3600

    return cfg


config = load_config()
