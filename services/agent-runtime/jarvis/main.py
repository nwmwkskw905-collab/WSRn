"""FastAPI entrypoint for the JARVIS local runtime.

Binds to 127.0.0.1 by default and requires a bearer token generated per install.
The Electron main process reads that token from the data directory; the renderer
never sees it.
"""
from __future__ import annotations

import asyncio
import os
import platform
import secrets
import sys
import time
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from . import __version__
from .api.routes import router
from .config import CONFIG
from .db import get_db, now_iso
from .engine.tasks import get_engine
from .modules.scheduler import get_scheduler
from .security.permissions import get_permission_engine

STARTED_AT = time.time()


def _ensure_token() -> str:
    CONFIG.ensure_dirs()
    path = CONFIG.token_path
    if path.exists():
        token = path.read_text(encoding="utf-8").strip()
        if len(token) >= 32:
            return token
    token = secrets.token_urlsafe(48)
    path.write_text(token, encoding="utf-8")
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass
    return token


async def _scheduled_runner(schedule: dict) -> object:
    engine = get_engine()
    return engine.create(
        objective=schedule["objective"],
        autonomy_level=int(schedule.get("autonomy_level", 1)),
        mode="production",
        idempotency_key=None,
    )


@asynccontextmanager
async def lifespan(app: FastAPI):
    CONFIG.ensure_dirs()
    token = _ensure_token()
    app.state.token = token
    db = get_db()
    get_permission_engine().seed_defaults()
    recovery = get_engine().recover_on_startup()
    db.set_state("runtime_started_at", now_iso())
    db.audit("system", "runtime.start", "agent-runtime", "granted",
             {"version": __version__, "python": sys.version.split()[0], "platform": platform.platform(),
              "recovered_tasks": recovery["count"]})
    scheduler = get_scheduler()
    if CONFIG.auto_start_worker:
        scheduler.start(_scheduled_runner)
    yield
    await scheduler.stop()
    db.set_state("runtime_stopped_at", now_iso())
    db.audit("system", "runtime.stop", "agent-runtime", "granted", {})


app = FastAPI(title="JARVIS Agent Runtime", version=__version__, lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=list(CONFIG.allowed_origins),
    allow_credentials=False,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type"],
)

PUBLIC_PATHS = {"/health", "/docs", "/openapi.json", "/api/mobile/claim"}


@app.middleware("http")
async def auth_and_guard(request: Request, call_next):
    if request.method == "OPTIONS":
        return await call_next(request)
    if request.url.path in PUBLIC_PATHS:
        return await call_next(request)
    token = getattr(request.app.state, "token", None)
    if CONFIG.require_auth:
        header = request.headers.get("authorization", "")
        supplied = header[7:] if header.lower().startswith("bearer ") else request.headers.get("x-jarvis-token", "")
        valid = bool(token and supplied and secrets.compare_digest(supplied, token))
        if not valid and supplied.startswith("mob_"):
            mobile = get_db().get_state("mobile_tokens", {}) or {}
            valid = supplied in mobile
        if not valid:
            return JSONResponse({"detail": "Nao autenticado"}, status_code=401)
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Cache-Control"] = "no-store"
    return response


@app.get("/health")
async def health() -> dict:
    data = {
        "status": "ok",
        "version": __version__,
        "uptime_seconds": round(time.time() - STARTED_AT, 1),
        "platform": platform.platform(),
        "requires_auth": CONFIG.require_auth,
        "kill_switch": get_db().get_state("kill_switch", False),
    }
    if not CONFIG.require_auth:
        data["warning"] = "Autenticacao local desativada por configuracao explicita (JARVIS_REQUIRE_AUTH=0)."
    return data


app.include_router(router, prefix="/api")


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "jarvis.main:app",
        host=CONFIG.host,
        port=CONFIG.port,
        reload=False,
        log_level=os.environ.get("JARVIS_LOG_LEVEL", "info"),
    )
