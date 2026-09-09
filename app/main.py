from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from datetime import datetime
from zoneinfo import ZoneInfo

from fastapi import FastAPI

from .runner import scheduler_loop
from .settings import settings


@asynccontextmanager
async def lifespan(app: FastAPI):
    stop = asyncio.Event()
    task = asyncio.create_task(scheduler_loop(stop))
    app.state.stop = stop
    app.state.task = task
    yield
    stop.set()
    await task


app = FastAPI(title="Facebook Story Automation Worker", lifespan=lifespan)


@app.get("/health")
def health():
    return {"ok": True, "timezone": settings.timezone, "dry_run": settings.dry_run, "now": datetime.now(ZoneInfo(settings.timezone)).isoformat()}
