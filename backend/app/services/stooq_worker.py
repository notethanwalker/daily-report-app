from __future__ import annotations

import asyncio

from ..database import SessionLocal
from .stooq_durable_import import process_batch


async def stooq_import_loop() -> None:
    await asyncio.sleep(20)
    while True:
        db = SessionLocal()
        delay = 60
        try:
            result = await asyncio.to_thread(process_batch, db)
            if result.get("status") == "importing":
                delay = 5
            elif result.get("status") == "ready":
                delay = 60
        except Exception:
            db.rollback()
            delay = 30
        finally:
            db.close()
        await asyncio.sleep(delay)
