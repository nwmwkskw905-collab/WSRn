def test_health(client):
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_status_and_security(client):
    status = client.get("/api/status").json()
    assert status["version"]
    assert "capabilities" in status
    security = client.get("/api/security/status").json()
    assert "kill_switch" in security


def test_permission_endpoint(client):
    response = client.post("/api/permissions", json={"scope": "fs.read", "granted": True, "config": {}})
    assert response.status_code == 200
    assert response.json()["granted"] is True
    updated = client.get("/api/permissions").json()
    assert any(p["scope"] == "fs.read" and p["granted"] for p in updated["permissions"])


def test_chat_local_fallback_and_kill_switch(client):
    response = client.post("/api/chat", json={"message": "Ola Jarvis, tudo bem?", "conversation_id": "api-test"})
    assert response.status_code == 200
    body = response.json()
    assert body["meta"]["provider"] in {"local-rules", "mock", "ollama"}
    stop = client.post("/api/chat", json={"message": "Jarvis, pare tudo", "conversation_id": "api-test"}).json()
    assert stop["meta"]["kill_switch"] is True
    assert client.get("/api/status").json()["kill_switch"] is True
    client.post("/api/security/release")
    assert client.get("/api/security/status").json()["kill_switch"] is False


def test_chat_creates_task_with_plan(client):
    response = client.post("/api/chat", json={"message": "Jarvis, mostre as vendas dos ultimos 7 dias",
                                              "conversation_id": "api-test-2", "speak": False})
    body = response.json()
    assert body["meta"]["task_id"]
    task = client.get(f"/api/tasks/{body['meta']['task_id']}").json()
    assert task["plan"]["steps"]


def test_approval_endpoint_requires_pin_when_configured(client):
    client.post("/api/security/pin", json={"pin": "654321"})
    from jarvis.security.approvals import get_approval_service

    approval = get_approval_service().request("cakto.create_product", "high", {"name": "teste"})
    denied = client.post(f"/api/approvals/{approval['id']}/resolve", json={"approve": True, "pin": "111111"})
    assert denied.status_code == 403
    approved = client.post(f"/api/approvals/{approval['id']}/resolve", json={"approve": True, "pin": "654321"})
    assert approved.status_code == 200
    assert approved.json()["status"] == "approved"


def test_cakto_status_without_credentials(client):
    from jarvis.modules.cakto import get_cakto

    get_cakto().disconnect()
    body = client.get("/api/integrations/cakto/status").json()
    assert body["connected"] is False
    assert body["credentials"] == "missing"


def test_llm_state(client):
    body = client.get("/api/llm/state").json()
    providers = {p["id"]: p for p in body["providers"]}
    assert "openai" in providers
    assert providers["openai"]["requires_key"] is True
    assert body["budget"]["budget"]["monthly_budget_usd"] >= 0


def test_diagnostics(client):
    body = client.get("/api/diagnostics").json()
    statuses = {c["name"]: c["status"] for c in body["checks"]}
    assert statuses["banco_sqlite"] == "ok"
    assert statuses["workflow_build"] in {"present", "missing"}


def test_agents_and_tools_listing(client):
    agents = client.get("/api/agents").json()["agents"]
    assert len(agents) >= 10
    assert any(a["id"] == "auditor" for a in agents)
    tools = client.get("/api/tools").json()["tools"]
    assert any(t["name"] == "fs.write_text" for t in tools)


def test_webhook_ingest_api(client, db):
    db.execute("DELETE FROM webhook_events")
    response = client.post("/api/webhooks/cakto", json={
        "event": "purchase_approved",
        "data": {"id": "api-order-1", "status": "paid", "amount": 10.0},
    })
    assert response.status_code == 200
    assert response.json()["status"] == "processed"
    duplicate = client.post("/api/webhooks/cakto", json={
        "event": "purchase_approved",
        "data": {"id": "api-order-1", "status": "paid", "amount": 10.0},
    })
    assert duplicate.json()["status"] == "duplicate"
