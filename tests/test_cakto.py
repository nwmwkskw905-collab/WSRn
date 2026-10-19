import json

import httpx
import pytest

BASE = "https://api.cakto.com.br/public_api"


def make_transport(created_products=None):
    created_products = created_products if created_products is not None else []

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path == f"{BASE}/token/".replace("https://api.cakto.com.br", "") or request.url.host == "api.cakto.com.br" and path.endswith("/token/"):
            return httpx.Response(200, json={"access_token": "test-token", "expires_in": 36000, "token_type": "Bearer",
                                             "scope": "read write products offers orders"})
        if request.headers.get("authorization") != "Bearer test-token":
            return httpx.Response(401, json={"detail": "missing token"})
        if path.endswith("/products/") and request.method == "GET":
            return httpx.Response(200, json={"count": 1, "next": None, "previous": None,
                                             "results": [{"id": "prod-1", "name": "Curso", "price": "97.00"}]})
        if path.endswith("/products/") and request.method == "POST":
            body = json.loads(request.content)
            created_products.append(body)
            return httpx.Response(201, json={"id": "prod-new", "short_id": "NEW1", "name": body["name"],
                                             "price": str(body["price"]), "type": body["type"], "status": "active"})
        if path.endswith("/checkouts/") and request.method == "GET":
            return httpx.Response(200, json={"count": 1, "results": [{"id": 55, "name": "Checkout", "default": True}]})
        if path.endswith("/checkouts/55/") and request.method == "GET":
            return httpx.Response(200, json={"id": 55, "name": "Checkout", "offers": [{"id": "OFF123"}]})
        if path.endswith("/offers/") and request.method == "GET":
            return httpx.Response(200, json={"count": 1, "results": [{"id": "OFF123", "default": True, "product": "prod-new"}]})
        if path.endswith("/orders/") and request.method == "GET":
            return httpx.Response(200, json={"count": 2, "next": None, "results": [
                {"id": "ord-1", "status": "paid", "amount": 97.0, "fees": 6.0, "currency": "BRL",
                 "paymentMethod": "pix", "refId": "R1", "customer": {"email": "a@b.com"}, "product": {"id": "prod-1"},
                 "createdAt": "2026-10-18T10:00:00Z", "paidAt": "2026-10-18T10:01:00Z"},
                {"id": "ord-2", "status": "waiting_payment", "amount": 97.0, "fees": 0, "currency": "BRL",
                 "paymentMethod": "pix", "refId": "R2", "customer": {"email": "c@d.com"}, "product": {"id": "prod-1"},
                 "createdAt": "2026-10-18T11:00:00Z", "paidAt": None},
            ]})
        if path.endswith("/orders/analytics/"):
            return httpx.Response(200, json={"group_by": "utm_source",
                                             "results": [{"utm_source": "google", "order_count": 1, "gross_volume": "97.00",
                                                          "net_value": "91.00", "total_discount": "0.00", "total_fees": "6.00"}],
                                             "totals": {"order_count": 1, "gross_volume": "97.00", "net_value": "91.00"}})
        return httpx.Response(404, json={"detail": f"unexpected {request.method} {path}"})

    return httpx.MockTransport(handler)


@pytest.fixture()
def cakto(db):
    from jarvis.modules.cakto import get_cakto

    service = get_cakto()
    service.set_test_transport(make_transport())
    yield service
    service.set_test_transport(None)


def test_auth_and_list_products(cakto, db):
    db.set_setting("cakto.demo_fallback", False)
    cakto.connect("client-abc", "secret-abcdef", "production")

    async def run():
        status = await cakto.status(verify=True)
        products = await cakto.list_products()
        return status, products

    import asyncio

    status, products = asyncio.run(run())
    assert status["status"] == "authenticated"
    assert "products" in status["scopes"]
    assert products["mode"] == "producao"
    assert products["results"][0]["name"] == "Curso"


def test_create_product_resolves_real_checkout(cakto, db):
    db.set_setting("cakto.demo_fallback", False)
    cakto.connect("client-abc", "secret-abcdef")
    import asyncio

    result = asyncio.run(cakto.create_product({
        "name": "Curso Validacao API",
        "description": "Descricao suficientemente longa para o teste",
        "price": 97.0,
        "type": "unique",
        "sales_page": "https://example.com/curso",
    }, approved=True))
    assert result["product"]["provider_id"] == "prod-new"
    assert result["checkout"]["checkout_id"] == 55
    assert result["checkout"]["offer_id"] == "OFF123"
    assert result["checkout"]["checkout_url"] == "https://pay.cakto.com.br/OFF123"
    # Idempotency: same payload must not be created twice.
    second = asyncio.run(cakto.create_product({
        "name": "Curso Validacao API",
        "description": "Descricao suficientemente longa para o teste",
        "price": 97.0,
        "type": "unique",
        "sales_page": "https://example.com/curso",
    }, approved=True))
    assert second["deduplicated"] is True


def test_create_requires_approval(cakto):
    import asyncio

    with pytest.raises(PermissionError):
        asyncio.run(cakto.create_product({"name": "x", "description": "descricao longa", "price": 10,
                                          "type": "unique", "sales_page": "https://x.com"}, approved=False))


def test_demo_mode_without_credentials(db):
    from jarvis.modules.cakto import get_cakto

    service = get_cakto()
    service.set_test_transport(None)
    service.disconnect()
    db.set_setting("cakto.demo_fallback", True)
    import asyncio

    data = asyncio.run(service.list_products())
    assert data["mode"] == "demonstracao"
    assert "ficticios" in data["warning"]


def test_sync_orders_and_webhook_dedupe(cakto, db):
    db.set_setting("cakto.demo_fallback", False)
    cakto.connect("client-abc", "secret-abcdef")
    import asyncio

    sync = asyncio.run(cakto.sync_orders())
    assert sync["fetched"] == 2
    first = cakto.record_webhook("purchase_approved", {"id": "ord-1", "status": "paid", "amount": 97.0}, "purchase_approved:ord-1")
    second = cakto.record_webhook("purchase_approved", {"id": "ord-1", "status": "paid", "amount": 97.0}, "purchase_approved:ord-1")
    assert first["status"] == "processed"
    assert second["status"] == "duplicate"


def test_sales_counts_only_paid(cakto, db):
    from jarvis.modules.sales import get_sales

    db.execute("DELETE FROM orders")
    cakto.connect("client-abc", "secret-abcdef")
    import asyncio

    asyncio.run(cakto.sync_orders())
    report = get_sales().order_summary(3650)
    assert report["paid_orders"] == 1
    assert report["pending_orders"] == 1
    assert report["gross_revenue_brl"] == 97.0
    assert report["fees_brl"] == 6.0
