# -*- coding: utf-8 -*-
"""Конфигурация бота.

Основной источник — ``.env``. ``creds.txt`` остаётся запасным вариантом для
старых установок. Все параметры панели WDTT REST API v2 задаются здесь.
"""
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlparse


def _load_env_file(path: str) -> None:
    """Парсит .env вручную (без python-dotenv)."""
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
    """Парсит creds.txt (fallback). Строки ``KEY = value``."""
    out: dict[str, str] = {}
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

    # WDTT REST API v2
    panel_base: str = ""
    panel_api_key: str = ""
    panel_username: str = ""
    panel_password: str = ""
    panel_timeout: int = 30
    ssl_insecure: bool = True

    # Дополнительно (для ссылок/подписок и legacy-полей)
    host: str = ""
    vpn_password: str = ""
    sub_url: str = ""
    sub_path: str = ""
    admin_path: str = ""

    # Значения по умолчанию для новых доступов
    defaults_total_gb: int = 175
    defaults_max_devices: int = 2
    defaults_expires_days: int = 0

    # Сколько нод показывать кнопками CopyTextButton. Остальные — в подписке.
    nodes_copy_limit: int = 5

    # Реферальный бонус (ГБ). 0 = выключить начисление.
    referral_bonus_gb: int = 5


def load_config(base_dir: str | None = None) -> Config:
    base_dir = base_dir or os.path.dirname(
        os.path.dirname(os.path.abspath(__file__))
    )

    _load_env_file(os.path.join(base_dir, ".env"))
    creds = _parse_creds(os.path.join(base_dir, "creds.txt"))

    def _get(env_key: str, creds_key: str = "", default: str = "") -> str:
        """env имеет приоритет над creds.txt."""
        return os.getenv(env_key, "") or creds.get(creds_key, "") or default

    def _int(env_key: str, default: int, minimum: int = 0) -> int:
        try:
            return max(minimum, int(_get(env_key, env_key, str(default))))
        except ValueError:
            return default

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

    # Панель WDTT (REST API v2)
    cfg.panel_base = _get(
        "PANEL_BASE", "BASE_URL", "https://127.0.0.1:2860/"
    ).rstrip("/")
    cfg.panel_api_key = _get("PANEL_API_KEY", "PANEL_API_KEY")
    cfg.panel_username = _get("ADMIN_USERNAME", "ADMIN_USERNAME", "admin")
    cfg.panel_password = _get("ADMIN_PASSWORD", "ADMIN_PASSWORD")
    cfg.panel_timeout = _int("PANEL_TIMEOUT", 30, minimum=5)
    cfg.ssl_insecure = _get(
        "SSL_INSECURE", "SSL_INSECURE", "1"
    ).lower() not in ("0", "false", "no")

    parsed = urlparse(cfg.panel_base)
    cfg.host = parsed.hostname or ""

    cfg.vpn_password = _get("VPN_PASSWORD", "VPN_PASSWORD")
    cfg.sub_url = _get("SUB_URL", "SUB_URL").rstrip("/")
    cfg.sub_path = _get("SUB_PATH", "SUB_PATH")
    cfg.admin_path = _get("ADMIN_PATH", "ADMIN_PATH", "/godmode/")

    # Лимит трафика: новый ключ DEFAULT_TOTAL_GB, старый USER_DEFAULT_LIMIT.
    raw_limit = _get("DEFAULT_TOTAL_GB", "DEFAULT_TOTAL_GB") or _get(
        "USER_DEFAULT_LIMIT", "USER_DEFAULT_LIMIT"
    )
    cfg.defaults_total_gb = parse_limit_gb(raw_limit) if raw_limit else 175

    cfg.defaults_max_devices = _int("DEFAULT_MAX_DEVICES", 2, minimum=1)
    cfg.defaults_expires_days = _int("DEFAULT_EXPIRES_DAYS", 0)
    cfg.nodes_copy_limit = _int("NODES_COPY_LIMIT", 5, minimum=1)
    cfg.referral_bonus_gb = _int("REFERRAL_BONUS_GB", 5)

    return cfg


config = load_config()
