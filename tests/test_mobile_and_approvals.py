"""Mobile companion pairing and the UI approval allowlist.

These tests cover the two flows that grant a device or a high-impact action real
authority, so they assert both the happy path and the refusal paths.
"""
from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def _clean_mobile(db):
    db.set_state("mobile_tokens", {})
    db.set_state("mobile_pair_codes", {})
    db.set_state("mobile_claim_attempts", [])
    db.execute("DELETE FROM runtime_state WHERE key='pin_hash'")
    yield
    db.set_state("mobile_tokens", {})


def test_pairing_claim_and_device_listing(client):
    from jarvis.config import CONFIG

    first = client.post("/api/mobile/pair-code")
    assert first.status_code == 200
    body = first.json()
    assert len(body["code"]) == 6 and body["code"].isdigit()
    assert body["expires_in_seconds"] == 600

    wrong = client.post("/api/mobile/claim", json={"code": "000000" if body["code"] != "000000" else "111111", "device_name": "iPhone"})
    assert wrong.status_code == 403
    assert "codigo" in wrong.json()["detail"].lower()

    claim = client.post("/api/mobile/claim", json={"code": body["code"], "device_name": "iPhone da Ana"})
    assert claim.status_code == 200
    token = claim.json()["token"]
    assert token.startswith("mob_") and len(token) > 30
    assert claim.json()["scopes"] == ["read", "chat", "approvals"]

    reuse = client.post("/api/mobile/claim", json={"code": body["code"], "device_name": "Outro"})
    assert reuse.status_code == 403, "codigo de pareamento deve ser de uso unico"

    devices = client.get("/api/mobile/devices").json()["devices"]
    assert len(devices) == 1
    assert devices[0]["device"] == "iPhone da Ana"
    assert token not in str(devices), "token completo nunca retorna pela API"

    CONFIG.require_auth = True
    try:
        assert client.get("/api/status").status_code == 401
        assert client.get("/api/status", headers={"Authorization": "Bearer mob_invalido"}).status_code == 401
        mobile_status = client.get("/api/status", headers={"Authorization": f"Bearer {token}"})
        assert mobile_status.status_code == 200
    finally:
        CONFIG.require_auth = False

    revoked = client.delete(f"/api/mobile/devices/{devices[0]['prefix']}")
    assert revoked.status_code == 200
    assert client.get("/api/mobile/devices").json()["devices"] == []


def test_mobile_chat_creates_messages(client):
    code = client.post("/api/mobile/pair-code").json()["code"]
    token = client.post("/api/mobile/claim", json={"code": code, "device_name": "iPhone"}).json()["token"]
    headers = {"Authorization": f"Bearer {token}"}
    reply = client.post("/api/mobile/chat", json={
        "message": "Jarvis, mostre as vendas dos ultimos 7 dias", "conversation_id": "main",
    }, headers=headers)
    assert reply.status_code == 200
    assert reply.json()["reply"]
    history = client.get("/api/messages", params={"conversation_id": "main"}, headers=headers).json()["messages"]
    assert len(history) >= 2


def test_approval_allowlist_rejects_unknown_actions(client):
    rejected = client.post("/api/approvals/request", json={"action": "bank.transfer", "summary": "Transferir"})
    assert rejected.status_code == 400
    assert "permitida" in rejected.json()["detail"].lower()

    created = client.post("/api/approvals/request", json={
        "action": "ads.budget_policy", "summary": "Autorizar R$ 50/dia", "data": {"daily_limit": 50},
    })
    assert created.status_code == 200
    approval = created.json()
    assert approval["risk"] == "critical"
    assert approval["pin_required"] is True
    assert approval["summary"] == "Autorizar R$ 50/dia"
    assert approval["status"] == "pending"


def test_ads_budget_requires_matching_approval_and_pin(client):
    denied = client.post("/api/ads/budget", json={"daily_limit": 50, "monthly_limit": 500, "ad_account": "act_1"})
    assert denied.status_code == 403
    assert client.get("/api/ads/budget").json()["daily_limit_brl"] == 0.0

    approval = client.post("/api/approvals/request", json={
        "action": "ads.budget_policy", "summary": "Orcamento", "data": {},
    }).json()
    no_pin = client.post(f"/api/approvals/{approval['id']}/resolve", json={"approve": True})
    assert no_pin.status_code == 403, "sem PIN configurado nao pode aprovar gasto"

    client.post("/api/security/pin", json={"pin": "135790"})
    wrong = client.post(f"/api/approvals/{approval['id']}/resolve", json={"approve": True, "pin": "000000"})
    assert wrong.status_code == 403
    approved = client.post(f"/api/approvals/{approval['id']}/resolve", json={"approve": True, "pin": "135790"})
    assert approved.status_code == 200 and approved.json()["status"] == "approved"

    applied = client.post("/api/ads/budget", json={
        "daily_limit": 50, "monthly_limit": 500, "ad_account": "act_1", "approval_id": approval["id"],
    })
    assert applied.status_code == 200
    policy = applied.json()
    assert policy["enabled"] is True and policy["daily_limit_brl"] == 50.0
    assert client.get("/api/ads/budget").json()["daily_limit_brl"] == 50.0

    replay = client.post("/api/ads/budget", json={
        "daily_limit": 90, "monthly_limit": 900, "ad_account": "act_1", "approval_id": approval["id"],
    })
    assert replay.status_code == 403, "aprovacao consumida nao pode ser reaproveitada"


def test_product_creation_without_approval_is_blocked(client, grant_workspace):
    response = client.post("/api/cakto/products", json={
        "name": "Curso", "description": "Curso completo de exemplo", "price": 97, "type": "unique",
        "sales_page": "https://example.com/curso", "confirm_create": True,
    })
    assert response.status_code == 403
    assert "aprov" in response.json()["detail"].lower()
