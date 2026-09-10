from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from datetime import datetime
from zoneinfo import ZoneInfo

from fastapi import FastAPI

from .google_store import GoogleStore
from .runner import scheduler_loop
from .settings import settings


@asynccontextmanager
async def lifespan(app: FastAPI):
    try:
        store = GoogleStore()
        cfg = store.read_config()
        print(
            f"GOOGLE_SELF_TEST_OK auth_mode={settings.google_auth_mode} config_keys={len(cfg)} publish_transport={settings.publish_transport}",
            flush=True,
        )
    except Exception as exc:
        print(f"GOOGLE_SELF_TEST_ERROR {type(exc).__name__}: {exc}", flush=True)

    stop = asyncio.Event()
    task = asyncio.create_task(scheduler_loop(stop))
    app.state.stop = stop
    app.state.task = task
    yield
    stop.set()
    await task


app = FastAPI(title="Facebook Story Automation Control Plane", lifespan=lifespan)


@app.get("/health")
def health():
    return {
        "ok": True,
        "timezone": settings.timezone,
        "dry_run": settings.dry_run,
        "publish_transport": settings.publish_transport,
        "google_auth_mode": settings.google_auth_mode,
        "now": datetime.now(ZoneInfo(settings.timezone)).isoformat(),
    }
