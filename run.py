#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Удобный запускатель: python run.py"""
import asyncio

from bot.main import main

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
