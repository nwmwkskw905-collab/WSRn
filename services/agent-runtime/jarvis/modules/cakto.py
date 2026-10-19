"""Cakto integration built only on verified public API contracts.

Verified against https://docs.cakto.com.br (Oct/2026):
  POST /public_api/token/                       form-urlencoded client_id/client_secret
  GET/POST /public_api/products/                required: name, description, price, type, salesPage
  GET /public_api/products/{id}/                product detail
  GET /public_api/products/{id}/checkouts/      list checkouts (default flag)
  GET /public_api/products/{id}/checkouts/{id}/ checkout detail (offers)
  GET /public_api/offers/?product={id}          offers
  GET /public_api/orders/                       orders
  GET /public_api/orders/analytics/             group_by, start_date, end_date (DD-MM-YYYY)
  POST /public_api/webhooks/                    webhook registration
  POST /public_api/orders/{id}/refund/          refund (approval-gated)

Creating a product creates the default offer, checkout and payment link
(https://pay.cakto.com.br/{offer_id}); there is no separate "create checkout"
endpoint. This module does not invent one.
"""
from __future__ import annotations

import json
import time
from typing import Any

import httpx

from ..db import get_db, new_id, now_iso
from ..security.secrets import get_vault, redact

CAKTO_API = "https://api.cakto.com.br/public_api"
REQUIRED_PRODUCT_FIELDS = ("name", "description", "price", "type", "salesPage")


class CaktoError(RuntimeError):
    def __init__(self, message: str, status: int | None = None, detail: Any = None, retryable: bool = False):
        super().__init__(message)
        self.status = status
        self.detail = detail
        self.retryable = retryable


DEMO_PRODUCTS = [
    {
        "id": "demo-prod-001",
        "short_id": "DEMO01",
        "name": "[DEMONSTRACAO] Curso Exemplo",
        "description": "Produto ficticio usado apenas no modo demonstracao.",
        "price": "97.00",
        "type": "unique",
        "status": "active",
        "_demo": True,
    }
]


class CaktoClient:
    def __init__(self, client_id: str = "", client_secret: str = "", environment: str = "production",
                 timeout: float = 30.0, transport: httpx.AsyncBaseTransport | None = None):
        self.client_id = client_id
        self.client_secret = client_secret
        self.environment = environment
        self.timeout = timeout
        self.transport = transport
        self._token: str | None = None
        self._token_expiry: float = 0.0
        self._scopes: str = ""
        self.db = get_db()

    # -- auth --------------------------------------------------------------
    async def token(self, force: bool = False) -> str:
        if not force and self._token and time.time() < self._token_expiry - 60:
            return self._token
        if not self.client_id or not self.client_secret:
            raise CaktoError("Credenciais Cakto ausentes")
        async with httpx.AsyncClient(timeout=self.timeout, transport=self.transport) as client:
            resp = await client.post(
                f"{CAKTO_API}/token/",
                data={"client_id": self.client_id, "client_secret": self.client_secret},
                headers={"Content-Type": "application/x-www-form-urlencoded"},
            )
        if resp.status_code == 401:
            raise CaktoError("Credenciais Cakto invalidas (401)", status=401, detail=_safe_json(resp))
        if resp.status_code == 400:
            raise CaktoError("Credenciais ou escopos invalidos (400)", status=400, detail=_safe_json(resp))
        if resp.status_code == 429:
            raise CaktoError("Limite de emissao de tokens atingido (429)", status=429, retryable=True)
        if resp.status_code >= 400:
            raise CaktoError(f"Falha ao autenticar na Cakto ({resp.status_code})", status=resp.status_code, retryable=resp.status_code >= 500)
        data = resp.json()
        if not data.get("access_token"):
            raise CaktoError("Resposta de token sem access_token")
        self._token = data["access_token"]
        self._token_expiry = time.time() + int(data.get("expires_in", 3600))
        self._scopes = data.get("scope", "")
        return self._token

    @property
    def scopes(self) -> list[str]:
        return [s for s in self._scopes.split() if s]

    def has_scope(self, scope: str) -> bool:
        scopes = self.scopes
        if not scopes:
            return True  # token response omitted scope; verify by calling the endpoint
        if scope in scopes:
            return True
        parts = scope.split()
        if len(parts) == 2 and f"{parts[0]} *" in scopes:
            return True
        return False

    # -- HTTP --------------------------------------------------------------
    async def request(self, method: str, path: str, *, params: dict[str, Any] | None = None,
                      json_body: dict[str, Any] | None = None, retry_auth: bool = True) -> dict[str, Any]:
        token = await self.token()
        url = f"{CAKTO_API}{path}"
        async with httpx.AsyncClient(timeout=self.timeout, transport=self.transport) as client:
            resp = await client.request(
                method,
                url,
                params={k: v for k, v in (params or {}).items() if v is not None},
                json=json_body,
                headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
            )
        if resp.status_code == 401 and retry_auth:
            await self.token(force=True)
            return await self.request(method, path, params=params, json_body=json_body, retry_auth=False)
        if resp.status_code == 403:
            raise CaktoError(
                "Sem permissao (403). Verifique os escopos da chave de API.",
                status=403,
                detail=_safe_json(resp),
            )
        if resp.status_code == 429:
            retry_after = resp.headers.get("Retry-After", "60")
            raise CaktoError(f"Limite de requisicoes da Cakto (429). Tente em {retry_after}s.", status=429, retryable=True)
        if resp.status_code >= 400:
            raise CaktoError(
                f"Cakto HTTP {resp.status_code}",
                status=resp.status_code,
                detail=_safe_json(resp),
                retryable=resp.status_code >= 500,
            )
        if resp.status_code == 204 or not resp.content:
            return {}
        return resp.json()

    # -- products ----------------------------------------------------------
    async def list_products(self, page: int = 1, limit: int = 20, search: str | None = None) -> dict[str, Any]:
        data = await self.request("GET", "/products/", params={"page": page, "limit": limit, "search": search})
        return {
            "count": data.get("count", len(data.get("results", []))),
            "next": data.get("next"),
            "previous": data.get("previous"),
            "results": data.get("results", []),
            "source": "cakto_api",
        }

    async def get_product(self, product_id: str) -> dict[str, Any]:
        return await self.request("GET", f"/products/{product_id}/")

    async def create_product(self, payload: dict[str, Any]) -> dict[str, Any]:
        missing = [f for f in REQUIRED_PRODUCT_FIELDS if payload.get(f) in (None, "")]
        if missing:
            raise CaktoError(f"Campos obrigatorios ausentes: {', '.join(missing)}")
        if payload.get("type") not in {"unique", "subscription"}:
            raise CaktoError("type deve ser 'unique' ou 'subscription'")
        try:
            price = float(payload["price"])
        except (TypeError, ValueError) as exc:
            raise CaktoError("price invalido") from exc
        if price <= 0:
            raise CaktoError("price deve ser positivo")
        sales_page = str(payload["salesPage"])
        if not sales_page.startswith(("https://", "http://")):
            raise CaktoError("salesPage deve ser uma URL valida")
        body = dict(payload)
        body.pop("approval_id", None)
        return await self.request("POST", "/products/", json_body=body)

    async def list_checkouts(self, product_id: str) -> dict[str, Any]:
        return await self.request("GET", f"/products/{product_id}/checkouts/")

    async def get_checkout(self, product_id: str, checkout_id: str | int) -> dict[str, Any]:
        return await self.request("GET", f"/products/{product_id}/checkouts/{checkout_id}/")

    async def list_offers(self, product_id: str) -> dict[str, Any]:
        return await self.request("GET", "/offers/", params={"product": product_id})

    async def resolve_checkout(self, product_id: str) -> dict[str, Any]:
        """Follow the documented flow: product -> checkouts -> default -> offer -> link."""
        checkouts = await self.list_checkouts(product_id)
        results = checkouts.get("results", [])
        if not results:
            raise CaktoError("Produto sem checkout retornado pela Cakto")
        default = next((c for c in results if c.get("default")), results[0])
        detail = await self.get_checkout(product_id, default.get("id"))
        offer_id = None
        offers = detail.get("offers") or []
        if offers:
            offer_id = offers[0].get("id")
        if not offer_id:
            offer_list = await self.list_offers(product_id)
            offer_results = offer_list.get("results", [])
            chosen = next((o for o in offer_results if o.get("default")), offer_results[0] if offer_results else None)
            offer_id = (chosen or {}).get("id")
        if not offer_id:
            raise CaktoError("Nao foi possivel identificar a oferta padrao do checkout")
        return {
            "checkout_id": default.get("id"),
            "checkout_name": default.get("name"),
            "checkout_default": bool(default.get("default")),
            "offer_id": offer_id,
            "checkout_url": f"https://pay.cakto.com.br/{offer_id}",
            "checkout_detail_offers": offers,
            "source": "documented_flow",
        }

    # -- orders ------------------------------------------------------------
    async def list_orders(self, page: int = 1, limit: int = 20, status: str | None = None,
                          start_date: str | None = None, end_date: str | None = None) -> dict[str, Any]:
        params = {"page": page, "limit": limit, "status": status, "start_date": start_date, "end_date": end_date}
        return await self.request("GET", "/orders/", params=params)

    async def analytics(self, start_date: str, end_date: str, group_by: str = "utm_source",
                        status: str = "paid") -> dict[str, Any]:
        return await self.request(
            "GET",
            "/orders/analytics/",
            params={"start_date": start_date, "end_date": end_date, "group_by": group_by, "status": status},
        )

    async def refund_order(self, order_id: str) -> dict[str, Any]:
        return await self.request("POST", f"/orders/{order_id}/refund/")

    # -- webhooks ----------------------------------------------------------
    async def create_webhook(self, name: str, url: str, events: list[str] | None = None) -> dict[str, Any]:
        body: dict[str, Any] = {"name": name, "url": url}
        if events:
            body["events"] = events
        return await self.request("POST", "/webhooks/", json_body=body)

    async def list_webhooks(self) -> dict[str, Any]:
        return await self.request("GET", "/webhooks/")


def _safe_json(resp: httpx.Response) -> Any:
    try:
        return redact(resp.json())
    except json.JSONDecodeError:
        return redact(resp.text[:500])


class CaktoService:
    def __init__(self) -> None:
        self.db = get_db()
        self.vault = get_vault()
        self._client: CaktoClient | None = None
        self._client_signature: tuple[str, str, str] | None = None
        self._test_transport: httpx.AsyncBaseTransport | None = None

    # -- connection --------------------------------------------------------
    def _stored(self) -> dict[str, Any] | None:
        try:
            return self.vault.get("cakto")
        except RuntimeError:
            return None

    def connect(self, client_id: str, client_secret: str, environment: str = "production") -> dict[str, Any]:
        if not self.vault.available():
            raise RuntimeError("Cofre de credenciais indisponivel; instale 'cryptography' ou use Windows")
        self.vault.put("cakto", {"client_id": client_id, "client_secret": client_secret, "environment": environment})
        self._client = None
        self.db.execute(
            "INSERT INTO integrations(provider, status, env, updated_at) VALUES ('cakto','configured',?,?) "
            "ON CONFLICT(provider) DO UPDATE SET status='configured', env=excluded.env, updated_at=excluded.updated_at",
            (environment, now_iso()),
        )
        self.db.audit("user", "integration.configure", "cakto", "granted", {"environment": environment})
        return {
            "provider": "cakto",
            "connected": True,
            "credentials": "stored",
            "environment": environment,
            "status": "credentials_stored",
            "note": "Use status?verify=true para validar o token contra a API.",
        }

    def disconnect(self) -> dict[str, Any]:
        self.vault.delete("cakto")
        self._client = None
        self.db.execute(
            "UPDATE integrations SET status='disconnected', updated_at=? WHERE provider='cakto'", (now_iso(),)
        )
        self.db.audit("user", "integration.disconnect", "cakto", "granted", {})
        return {"provider": "cakto", "connected": False, "credentials": "missing", "status": "disconnected"}

    async def status(self, verify: bool = False) -> dict[str, Any]:
        stored = self._stored()
        row = self.db.one("SELECT * FROM integrations WHERE provider='cakto'") or {}
        if not stored:
            return {
                "provider": "cakto",
                "connected": False,
                "credentials": "missing",
                "environment": "none",
                "status": "aguardando configuracao externa",
                "last_check_at": row.get("last_check_at"),
                "last_error": row.get("last_error"),
                "scopes": [],
                "docs": "https://docs.cakto.com.br",
            }
        out = {
            "provider": "cakto",
            "connected": True,
            "credentials": "stored",
            "environment": stored.get("environment", "production"),
            "status": "credentials_stored",
            "scopes": [],
            "last_check_at": row.get("last_check_at"),
            "last_error": row.get("last_error"),
        }
        if verify:
            try:
                client = self.client()
                await client.token(force=True)
                out["status"] = "authenticated"
                out["scopes"] = client.scopes
                out["last_check_at"] = now_iso()
                self.db.execute(
                    "UPDATE integrations SET status='connected', scopes=?, last_check_at=?, last_error=NULL, updated_at=? WHERE provider='cakto'",
                    (" ".join(client.scopes), out["last_check_at"], now_iso()),
                )
            except CaktoError as exc:
                out["status"] = "auth_failed"
                out["last_error"] = str(exc)
                self.db.execute(
                    "UPDATE integrations SET status='error', last_error=?, updated_at=? WHERE provider='cakto'",
                    (str(exc), now_iso()),
                )
        return out

    def client(self) -> CaktoClient:
        stored = self._stored()
        if not stored:
            raise CaktoError("Cakto nao conectada. Informe client_id e client_secret em Integracoes.")
        sig = (stored["client_id"], stored["client_secret"], stored.get("environment", "production"))
        if self._client is None or self._client_signature != sig:
            self._client = CaktoClient(*sig, transport=self._test_transport)
            self._client_signature = sig
        return self._client

    def set_test_transport(self, transport: httpx.AsyncBaseTransport | None) -> None:
        """Test hook: route adapter traffic through an httpx MockTransport."""
        self._test_transport = transport
        self._client = None

    # -- products ----------------------------------------------------------
    async def list_products(self, search: str | None = None) -> dict[str, Any]:
        if not self._stored():
            if self.db.get_setting("cakto.demo_fallback", True):
                return {
                    "mode": "demonstracao",
                    "warning": "Nenhuma credencial Cakto conectada. Estes dados sao ficticios e nao representam sua conta.",
                    "count": len(DEMO_PRODUCTS),
                    "results": DEMO_PRODUCTS,
                }
            raise CaktoError("Cakto nao conectada")
        data = await self.client().list_products(search=search)
        data["mode"] = "producao"
        return data

    async def create_product(self, draft: dict[str, Any], approved: bool) -> dict[str, Any]:
        if not approved:
            raise PermissionError("Criacao de produto exige aprovacao registrada")
        client = self.client()
        payload = {
            "name": draft["name"],
            "description": draft["description"],
            "price": float(draft["price"]),
            "type": draft["type"],
            "salesPage": draft["sales_page"],
        }
        idem_key = f"cakto:product:{draft['name']}:{payload['price']}:{draft['type']}"
        cached = self.db.one(
            "SELECT value FROM runtime_state WHERE key=?", (f"idempotency:{idem_key}",)
        )
        if cached:
            return {"mode": "producao", "deduplicated": True, "product": json.loads(cached["value"])}
        created = await client.create_product(payload)
        product_id = created.get("id")
        if not product_id:
            raise CaktoError("Cakto nao retornou o id do produto criado")
        resolved = await client.resolve_checkout(product_id)
        product_record = {
            "id": new_id("prd_"),
            "provider_id": product_id,
            "short_id": created.get("short_id"),
            "name": created.get("name", draft["name"]),
            "price_cents": int(round(float(created.get("price", draft["price"])) * 100)),
            "type": created.get("type", draft["type"]),
            "checkout_id": resolved["checkout_id"],
            "offer_id": resolved["offer_id"],
            "checkout_url": resolved["checkout_url"],
            "sales_page": draft["sales_page"],
            "status": created.get("status", "active"),
        }
        ts = now_iso()
        self.db.execute(
            """INSERT INTO products(id, business_id, name, description, price_cents, currency, type, status, provider,
                 provider_id, provider_short_id, offer_id, checkout_id, checkout_url, sales_page, raw_json, created_at, updated_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                product_record["id"], draft.get("business_id"), product_record["name"], draft["description"],
                product_record["price_cents"], "BRL", product_record["type"], product_record["status"], "cakto",
                product_id, product_record["short_id"], product_record["offer_id"], product_record["checkout_id"],
                product_record["checkout_url"], draft["sales_page"], json.dumps(created, default=str), ts, ts,
            ),
        )
        self.db.set_state(f"idempotency:{idem_key}", product_record)
        self.db.audit("agent", "cakto.product.create", product_id, "granted", {"offer_id": product_record["offer_id"]})
        return {"mode": "producao", "deduplicated": False, "product": product_record, "checkout": resolved}

    # -- orders ------------------------------------------------------------
    async def sync_orders(self, days: int = 30) -> dict[str, Any]:
        if not self._stored():
            raise CaktoError("Cakto nao conectada")
        page = 1
        inserted = 0
        updated = 0
        total = 0
        while page <= 20:
            data = await self.client().list_orders(page=page, limit=50)
            results = data.get("results", [])
            total += len(results)
            for order in results:
                created = self._upsert_order(order)
                if created == "inserted":
                    inserted += 1
                elif created == "updated":
                    updated += 1
            if not data.get("next"):
                break
            page += 1
        self.db.execute(
            "UPDATE integrations SET last_check_at=?, updated_at=? WHERE provider='cakto'", (now_iso(), now_iso())
        )
        return {"source": "cakto_api", "fetched": total, "inserted": inserted, "updated": updated}

    def _upsert_order(self, order: dict[str, Any]) -> str:
        provider_order_id = str(order.get("id") or order.get("refId") or "")
        if not provider_order_id:
            return "skipped"
        customer = order.get("customer") or {}
        product = order.get("product") or {}
        amount = order.get("amount")
        try:
            amount_cents = int(round(float(amount) * 100)) if amount is not None else 0
        except (TypeError, ValueError):
            amount_cents = 0
        existing = self.db.one(
            "SELECT id FROM orders WHERE provider='cakto' AND provider_order_id=?", (provider_order_id,)
        )
        ts = now_iso()
        if existing:
            self.db.execute(
                "UPDATE orders SET status=?, amount_cents=?, paid_at=? WHERE id=?",
                (order.get("status", "unknown"), amount_cents, order.get("paidAt"), existing["id"]),
            )
            return "updated"
        self.db.execute(
            """INSERT INTO orders(id, provider, provider_order_id, business_id, product_id, customer_email, status,
                 payment_method, amount_cents, currency, ref_id, created_at, paid_at, raw_json)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                new_id("ord_"), "cakto", provider_order_id, None, product.get("id"), customer.get("email"),
                order.get("status", "unknown"), order.get("paymentMethod"), amount_cents,
                order.get("currency", "BRL"), order.get("refId"), order.get("createdAt") or ts,
                order.get("paidAt"), json.dumps(redact(order), default=str),
            ),
        )
        return "inserted"

    def record_webhook(self, event: str, data: dict[str, Any], dedupe_key: str) -> dict[str, Any]:
        payload = {"event": event, "data": data}
        existing = self.db.one(
            "SELECT * FROM webhook_events WHERE provider='cakto' AND dedupe_key=?", (dedupe_key,)
        )
        if existing:
            return {"status": "duplicate", "id": existing["id"]}
        event_id = new_id("evt_")
        self.db.execute(
            "INSERT INTO webhook_events(id, provider, event, dedupe_key, status, payload_json, received_at)"
            " VALUES (?,?,?,?,?,?,?)",
            (event_id, "cakto", event, dedupe_key, "received", json.dumps(redact(payload), default=str), now_iso()),
        )
        if event == "checkout_abandonment":
            self.db.execute("UPDATE webhook_events SET status='processed', processed_at=? WHERE id=?", (now_iso(), event_id))
            return {"status": "processed", "id": event_id, "kind": "abandonment"}
        if isinstance(data, list):
            for item in data:
                self._upsert_order(item) if isinstance(item, dict) else None
        elif isinstance(data, dict):
            self._upsert_order(data)
        self.db.execute("UPDATE webhook_events SET status='processed', processed_at=? WHERE id=?", (now_iso(), event_id))
        return {"status": "processed", "id": event_id}

    def webhook_events(self, limit: int = 100) -> list[dict[str, Any]]:
        rows = self.db.query("SELECT * FROM webhook_events ORDER BY received_at DESC LIMIT ?", (limit,))
        for row in rows:
            row["payload_json"] = json.loads(row["payload_json"])
        return rows


_service: CaktoService | None = None


def get_cakto() -> CaktoService:
    global _service
    if _service is None:
        _service = CaktoService()
    return _service
