"""HTTPS webhook receiver for Cakto events.

Designed to run on a small always-on host (VPS/serverless container) so events are
captured even when the Windows PC is off. It stores events idempotently and can
forward them to the local runtime when it is online.

Security:
  * HMAC-SHA256 signature over `{timestamp}.{raw_body}` (X-Cakto-Signature: v1=...)
  * 5-minute timestamp tolerance
  * body `secret` compared with hmac.compare_digest as fallback
  * read/sync endpoints require RELAY_TOKEN
  * no event is trusted as a paid sale without order status validation
"""
from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import os
import sqlite3
import time
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

import httpx
from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.responses import JSONResponse

SECRET = os.environ.get("CAKTO_WEBHOOK_SECRET", "")
RELAY_TOKEN = os.environ.get("RELAY_TOKEN", "")
RUNTIME_URL = os.environ.get("JARVIS_RUNTIME_URL", "").rstrip("/")
RUNTIME_TOKEN = os.environ.get("JARVIS_RUNTIME_TOKEN", "")
DB_PATH = Path(os.environ.get("RELAY_DB", Path(__file__).resolve().parents[1] / ".runtime" / "relay.sqlite3"))
TOLERANCE_SECONDS = 300
FORWARD_INTERVAL = int(os.environ.get("RELAY_FORWARD_INTERVAL", "30"))


def db() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def init_db() -> None:
    with db() as conn:
        conn.execute(
            """CREATE TABLE IF NOT EXISTS events (
                   id TEXT PRIMARY KEY,
                   event TEXT NOT NULL,
                   dedupe_key TEXT NOT NULL UNIQUE,
                   payload TEXT NOT NULL,
                   received_at REAL NOT NULL,
                   forwarded INTEGER NOT NULL DEFAULT 0,
                   forwarded_at REAL,
                   forward_error TEXT
               )"""
        )


def verify_signature(raw: bytes, timestamp: str, signature: str, secret: str) -> bool:
    if not secret or not timestamp or not signature:
        return False
    try:
        if abs(time.time() - int(timestamp)) > TOLERANCE_SECONDS:
            return False
    except ValueError:
        return False
    expected = hmac.new(secret.encode(), f"{timestamp}.".encode() + raw, hashlib.sha256).hexdigest()
    return hmac.compare_digest(signature, f"v1={expected}")


def verify_body_secret(received: str, secret: str) -> bool:
    if not received or not secret:
        return False
    return hmac.compare_digest(received, secret)


def dedupe_key(event: str, data: Any) -> str:
    if isinstance(data, list):
        ids = [str(item.get("id", "")) for item in data if isinstance(item, dict)]
        return f"{event}:{','.join(ids) or hashlib.sha256(json.dumps(data, sort_keys=True).encode()).hexdigest()[:24]}"
    if isinstance(data, dict):
        if data.get("id"):
            return f"{event}:{data['id']}"
        stable = json.dumps(data, sort_keys=True, ensure_ascii=False)
        return f"{event}:{hashlib.sha256(stable.encode()).hexdigest()[:32]}"
    return f"{event}:{hashlib.sha256(str(data).encode()).hexdigest()[:32]}"


async def forward_pending() -> dict[str, Any]:
    if not RUNTIME_URL or not RUNTIME_TOKEN:
        return {"skipped": "runtime nao configurado"}
    sent = 0
    failed = 0
    with db() as conn:
        rows = conn.execute("SELECT * FROM events WHERE forwarded=0 ORDER BY received_at LIMIT 50").fetchall()
    for row in rows:
        try:
            async with httpx.AsyncClient(timeout=20) as client:
                resp = await client.post(
                    f"{RUNTIME_URL}/api/webhooks/cakto",
                    headers={"Authorization": f"Bearer {RUNTIME_TOKEN}"},
                    json=json.loads(row["payload"]),
                )
            if resp.status_code >= 400:
                raise RuntimeError(f"HTTP {resp.status_code}: {resp.text[:200]}")
            with db() as conn:
                conn.execute("UPDATE events SET forwarded=1, forwarded_at=? WHERE id=?", (time.time(), row["id"]))
            sent += 1
        except Exception as exc:  # noqa: BLE001
            failed += 1
            with db() as conn:
                conn.execute("UPDATE events SET forward_error=? WHERE id=?", (str(exc)[:400], row["id"]))
    return {"forwarded": sent, "failed": failed}


async def _forward_loop(stop: asyncio.Event) -> None:
    while not stop.is_set():
        try:
            await forward_pending()
        except Exception:  # noqa: BLE001
            pass
        try:
            await asyncio.wait_for(stop.wait(), timeout=FORWARD_INTERVAL)
        except asyncio.TimeoutError:
            continue


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    if not SECRET:
        # Fail loudly in logs; endpoints reject all deliveries without a secret.
        print("WARNING: CAKTO_WEBHOOK_SECRET nao configurado; entregas serao rejeitadas", flush=True)
    if not RELAY_TOKEN:
        print("WARNING: RELAY_TOKEN nao configurado; endpoints de leitura ficarao bloqueados", flush=True)
    stop = asyncio.Event()
    task = asyncio.create_task(_forward_loop(stop))
    yield
    stop.set()
    await asyncio.wait([task], timeout=5)


app = FastAPI(title="JARVIS Webhook Relay", version="0.9.0", lifespan=lifespan)


def _require_token(authorization: str | None) -> None:
    if not RELAY_TOKEN:
        raise HTTPException(503, "RELAY_TOKEN nao configurado")
    supplied = (authorization or "")[7:] if (authorization or "").lower().startswith("bearer ") else ""
    if not supplied or not hmac.compare_digest(supplied, RELAY_TOKEN):
        raise HTTPException(401, "Nao autenticado")


@app.get("/health")
async def health() -> dict[str, Any]:
    with db() as conn:
        count = conn.execute("SELECT COUNT(*) n FROM events").fetchone()["n"]
        pending = conn.execute("SELECT COUNT(*) n FROM events WHERE forwarded=0").fetchone()["n"]
    return {
        "status": "ok",
        "configured": bool(SECRET),
        "events": count,
        "pending_forward": pending,
        "runtime_forwarding": bool(RUNTIME_URL and RUNTIME_TOKEN),
    }


@app.post("/webhooks/cakto")
async def cakto_webhook(
    request: Request,
    x_cakto_timestamp: str | None = Header(default=None),
    x_cakto_signature: str | None = Header(default=None),
):
    raw = await request.body()
    if len(raw) > 2_000_000:
        raise HTTPException(413, "payload muito grande")
    if x_cakto_signature:
        if not verify_signature(raw, x_cakto_timestamp or "", x_cakto_signature, SECRET):
            raise HTTPException(401, "assinatura invalida ou expirada")
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError:
            raise HTTPException(400, "JSON invalido")
    else:
        # Legacy fallback: body secret only when no signature header was supplied.
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError:
            raise HTTPException(401, "assinatura ausente")
        if not verify_body_secret(str(payload.get("secret", "")), SECRET):
            raise HTTPException(401, "origem nao verificada")
    event = payload.get("event")
    data = payload.get("data")
    if not event or data is None:
        raise HTTPException(400, "event/data ausentes")
    key = dedupe_key(event, data)
    event_id = hashlib.sha256(f"{key}:{raw[:200]}".encode()).hexdigest()[:32]
    stored = {"event": event, "data": data, "received_via": "relay", "secret_checked": True}
    with db() as conn:
        existing = conn.execute("SELECT id FROM events WHERE dedupe_key=?", (key,)).fetchone()
        if existing:
            return JSONResponse({"received": True, "duplicate": True, "id": existing["id"]}, status_code=200)
        conn.execute(
            "INSERT INTO events(id, event, dedupe_key, payload, received_at) VALUES (?,?,?,?,?)",
            (event_id, event, key, json.dumps(stored, ensure_ascii=False), time.time()),
        )
    return {"received": True, "duplicate": False, "id": event_id, "event": event}


@app.get("/events")
async def events(limit: int = 100, authorization: str | None = Header(default=None)) -> dict[str, Any]:
    _require_token(authorization)
    with db() as conn:
        rows = [dict(r) for r in conn.execute("SELECT * FROM events ORDER BY received_at DESC LIMIT ?", (min(limit, 500),))]
    for row in rows:
        row["payload"] = json.loads(row["payload"])
    return {"events": rows}


@app.post("/sync")
async def sync(authorization: str | None = Header(default=None)) -> dict[str, Any]:
    _require_token(authorization)
    return await forward_pending()


@app.get("/")
async def index() -> dict[str, str]:
    return {"service": "JARVIS Webhook Relay", "docs": "/docs", "webhook": "POST /webhooks/cakto"}
