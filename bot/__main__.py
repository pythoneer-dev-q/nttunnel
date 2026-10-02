# -*- coding: utf-8 -*-
"""Позволяет запускать командой: python -m bot"""
from .main import main
import asyncio

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
