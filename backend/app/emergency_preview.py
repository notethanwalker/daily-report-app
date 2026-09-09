"""Minimal, branch-only Render service that retries repair in the background."""

import asyncio
from typing import Any

from fastapi import FastAPI

from .emergency_db_repair import retry_repair


app = FastAPI()
state: dict[str, Any] = {"status": "waiting_for_database_resume"}


@app.on_event("startup")
async def start_repair() -> None:
    async def run() -> None:
        try:
            state.update(status="running")
            result = await asyncio.to_thread(retry_repair)
            state.update(status="success", result=result)
        except Exception as exc:
            state.update(status="failed", error=f"{type(exc).__name__}: {exc}")

    asyncio.create_task(run())


@app.get("/")
def health() -> dict[str, Any]:
    return state
