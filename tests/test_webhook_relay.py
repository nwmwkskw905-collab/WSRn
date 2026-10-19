import hashlib
import hmac
import importlib
import importlib.util
import json
import sys
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
RELAY = ROOT / "services" / "webhook-relay"


@pytest.fixture()
def relay_app(tmp_path, monkeypatch):
    monkeypatch.setenv("CAKTO_WEBHOOK_SECRET", "relay-secret-123")
    monkeypatch.setenv("RELAY_TOKEN", "relay-read-token")
    monkeypatch.setenv("RELAY_DB", str(tmp_path / "relay.sqlite3"))
    monkeypatch.setenv("JARVIS_RUNTIME_URL", "")
    sys.path.insert(0, str(RELAY))
    sys.modules.pop("relay.app", None)
    module = importlib.import_module("relay.app")
    module.SECRET = "relay-secret-123"
    module.RELAY_TOKEN = "relay-read-token"
    module.DB_PATH = tmp_path / "relay.sqlite3"
    module.RUNTIME_URL = ""
    module.RUNTIME_TOKEN = ""
    from fastapi.testclient import TestClient

    with TestClient(module.app) as client:
        yield client, module


def sign(secret: str, body: bytes, timestamp: str | None = None) -> tuple[str, str]:
    ts = timestamp or str(int(time.time()))
    digest = hmac.new(secret.encode(), f"{ts}.".encode() + body, hashlib.sha256).hexdigest()
    return ts, f"v1={digest}"


def test_rejects_missing_signature(relay_app):
    client, _ = relay_app
    response = client.post("/webhooks/cakto", json={"event": "purchase_approved", "data": {"id": "1"}})
    assert response.status_code == 401


def test_accepts_valid_signature_and_deduplicates(relay_app):
    client, _ = relay_app
    payload = {"secret": "relay-secret-123", "event": "purchase_approved",
               "data": {"id": "order-abc", "status": "paid", "amount": 97.0}}
    body = json.dumps(payload).encode()
    ts, signature = sign("relay-secret-123", body)
    headers = {"X-Cakto-Timestamp": ts, "X-Cakto-Signature": signature, "Content-Type": "application/json"}
    first = client.post("/webhooks/cakto", content=body, headers=headers)
    assert first.status_code == 200 and first.json()["received"] is True
    second = client.post("/webhooks/cakto", content=body, headers=headers)
    assert second.json()["duplicate"] is True


def test_rejects_stale_timestamp(relay_app):
    client, _ = relay_app
    payload = {"secret": "relay-secret-123", "event": "purchase_approved", "data": {"id": "old"}}
    body = json.dumps(payload).encode()
    ts, signature = sign("relay-secret-123", body, str(int(time.time()) - 1000))
    response = client.post("/webhooks/cakto", content=body,
                           headers={"X-Cakto-Timestamp": ts, "X-Cakto-Signature": signature})
    assert response.status_code == 401


def test_events_require_token(relay_app):
    client, _ = relay_app
    assert client.get("/events").status_code == 401
    ok = client.get("/events", headers={"Authorization": "Bearer relay-read-token"})
    assert ok.status_code == 200
    assert "events" in ok.json()


def test_abandonment_payload_accepted(relay_app):
    client, _ = relay_app
    payload = {"secret": "relay-secret-123", "event": "checkout_abandonment",
               "data": {"customerEmail": "x@y.com", "product": {"id": "p1"}, "createdAt": "2026-10-18T00:00:00Z"}}
    body = json.dumps(payload).encode()
    ts, signature = sign("relay-secret-123", body)
    response = client.post("/webhooks/cakto", content=body,
                           headers={"X-Cakto-Timestamp": ts, "X-Cakto-Signature": signature})
    assert response.status_code == 200
