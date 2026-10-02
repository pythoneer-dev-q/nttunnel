# -*- coding: utf-8 -*-
"""Глобальный контекст приложения (инициализируется в main.py)."""
from dataclasses import dataclass
from typing import Optional

from .config import Config
from .db import Database
from .middlewares.check_sub import UserGate
from .wdtt import WdttClient


@dataclass
class Ctx:
    cfg: Config
    db: Database
    wdtt: WdttClient
    gate: UserGate


_app: Optional[Ctx] = None


def init_ctx(cfg: Config, db: Database, wdtt: WdttClient, gate: UserGate):
    global _app
    _app = Ctx(cfg=cfg, db=db, wdtt=wdtt, gate=gate)


def app() -> Ctx:
    assert _app is not None, "context not initialised"
    return _app


def admin_ids(data: dict) -> list:
    """Достаём админ-ids из middleware_data (кладутся в main)."""
    return list((data or {}).get("admin_ids", []) or [])
