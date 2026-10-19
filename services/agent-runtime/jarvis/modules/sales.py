"""Sales engine: CRM, order consolidation and evidence-based reports.

Revenue is only counted from orders whose status is ``paid``. Pending Pix, refused
cards, refunds and chargebacks are reported separately. No synthetic sales data is
ever generated outside explicit demo fixtures, which are tagged.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from typing import Any

from ..db import get_db, new_id, now_iso

PAID_STATUSES = {"paid", "approved", "completed", "authorized"}
REFUNDED_STATUSES = {"refunded", "chargedback", "chargeback"}
PENDING_STATUSES = {"waiting_payment", "pending", "processing"}


class SalesService:
    def __init__(self) -> None:
        self.db = get_db()

    # -- CRM ---------------------------------------------------------------
    def create_lead(self, name: str, email: str | None = None, phone: str | None = None,
                    source: str | None = None, consent: bool = False, notes: str | None = None,
                    business_id: str | None = None) -> dict[str, Any]:
        lead_id = new_id("lead_")
        ts = now_iso()
        self.db.execute(
            "INSERT INTO leads(id, business_id, name, email, phone, stage, source, consent, notes, created_at, updated_at)"
            " VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (lead_id, business_id, name, email, phone, "new", source, 1 if consent else 0, notes, ts, ts),
        )
        return self.get_lead(lead_id)

    def get_lead(self, lead_id: str) -> dict[str, Any]:
        row = self.db.one("SELECT * FROM leads WHERE id=?", (lead_id,))
        if not row:
            raise KeyError("Lead nao encontrado")
        return self._lead_public(row)

    def list_leads(self, stage: str | None = None, limit: int = 200) -> list[dict[str, Any]]:
        if stage:
            rows = self.db.query("SELECT * FROM leads WHERE stage=? ORDER BY updated_at DESC LIMIT ?", (stage, limit))
        else:
            rows = self.db.query("SELECT * FROM leads ORDER BY updated_at DESC LIMIT ?", (limit,))
        return [self._lead_public(r) for r in rows]

    def update_lead(self, lead_id: str, **fields: Any) -> dict[str, Any]:
        allowed = {"name", "email", "phone", "stage", "source", "consent", "notes", "business_id"}
        updates = {k: v for k, v in fields.items() if k in allowed and v is not None}
        if "consent" in updates:
            updates["consent"] = 1 if updates["consent"] else 0
        if not updates:
            return self.get_lead(lead_id)
        sets = ", ".join(f"{k}=?" for k in updates)
        self.db.execute(f"UPDATE leads SET {sets}, updated_at=? WHERE id=?", (*updates.values(), now_iso(), lead_id))
        return self.get_lead(lead_id)

    def eligible_contacts(self) -> list[dict[str, Any]]:
        """Only contacts with recorded consent can ever receive outreach."""
        rows = self.db.query("SELECT * FROM leads WHERE consent=1 AND email IS NOT NULL ORDER BY updated_at DESC")
        return [self._lead_public(r) for r in rows]

    def funnel(self) -> dict[str, Any]:
        stages = ["new", "qualified", "proposal", "won", "lost"]
        rows = self.db.query("SELECT stage, COUNT(*) n FROM leads GROUP BY stage")
        counts = {s: 0 for s in stages}
        for row in rows:
            counts[row["stage"]] = row["n"]
        return {"stages": counts, "total": sum(counts.values()), "note": "Contagem real do CRM local."}

    # -- orders ------------------------------------------------------------
    def order_summary(self, days: int = 7) -> dict[str, Any]:
        since = (datetime.now(timezone.utc) - timedelta(days=days)).strftime("%Y-%m-%d")
        rows = self.db.query(
            "SELECT * FROM orders WHERE date(COALESCE(paid_at, created_at)) >= date(?)", (since,)
        )
        paid = [r for r in rows if (r["status"] or "").lower() in PAID_STATUSES]
        refunded = [r for r in rows if (r["status"] or "").lower() in REFUNDED_STATUSES]
        pending = [r for r in rows if (r["status"] or "").lower() in PENDING_STATUSES]
        gross_cents = sum(int(r["amount_cents"] or 0) for r in paid)
        refund_cents = sum(int(r["amount_cents"] or 0) for r in refunded)
        fees_cents = 0
        fees_known = True
        for row in paid + refunded:
            raw = {}
            try:
                raw = json.loads(row.get("raw_json") or "{}")
            except json.JSONDecodeError:
                raw = {}
            fees = raw.get("fees")
            if fees is None:
                fees_known = False
            else:
                try:
                    fees_cents += int(round(float(fees) * 100))
                except (TypeError, ValueError):
                    fees_known = False
        net_cents = gross_cents - refund_cents - (fees_cents if fees_known else 0)
        by_product: dict[str, int] = {}
        by_method: dict[str, int] = {}
        for row in paid:
            by_product[row.get("product_id") or "desconhecido"] = by_product.get(row.get("product_id") or "desconhecido", 0) + int(row["amount_cents"] or 0)
            method = row.get("payment_method") or "desconhecido"
            by_method[method] = by_method.get(method, 0) + int(row["amount_cents"] or 0)
        days_series: dict[str, int] = {}
        for row in paid:
            day = (row.get("paid_at") or row.get("created_at") or "")[:10]
            if day:
                days_series[day] = days_series.get(day, 0) + int(row["amount_cents"] or 0)
        return {
            "period_days": days,
            "data_source": "pedidos sincronizados localmente (Cakto ou importacao autorizada)",
            "orders_considered": len(rows),
            "paid_orders": len(paid),
            "pending_orders": len(pending),
            "refunded_orders": len(refunded),
            "gross_revenue_brl": round(gross_cents / 100, 2),
            "refunds_brl": round(refund_cents / 100, 2),
            "fees_brl": round(fees_cents / 100, 2) if fees_known else None,
            "net_revenue_estimate_brl": round(net_cents / 100, 2) if fees_known else None,
            "average_ticket_brl": round((gross_cents / len(paid)) / 100, 2) if paid else 0,
            "revenue_by_product": {k: round(v / 100, 2) for k, v in by_product.items()},
            "revenue_by_payment_method": {k: round(v / 100, 2) for k, v in by_method.items()},
            "daily_revenue": {k: round(v / 100, 2) for k, v in sorted(days_series.items())},
            "notes": [
                "Receita bruta confirmada considera apenas pedidos com status pago.",
                "Pix gerado nao e venda paga.",
                "Receita liquida e estimada e depende das taxas retornadas pela plataforma.",
                "" if fees_known else "Alguns pedidos nao tinham taxas disponiveis; liquido nao foi calculado.",
            ],
            "is_empty": len(rows) == 0,
        }

    def dashboard(self, business_id: str | None = None) -> dict[str, Any]:
        week = self.order_summary(7)
        month = self.order_summary(30)
        campaigns = self.db.query(
            "SELECT provider, SUM(spent_cents) spent, SUM(daily_budget_cents) budget FROM campaigns WHERE business_id IS ? GROUP BY provider",
            (business_id,),
        ) if business_id else self.db.query("SELECT provider, SUM(spent_cents) spent, SUM(daily_budget_cents) budget FROM campaigns GROUP BY provider")
        ad_spend = sum(int(c["spent"] or 0) for c in campaigns) / 100
        return {
            "week": week,
            "month": month,
            "ad_spend_brl": round(ad_spend, 2),
            "campaigns": campaigns,
            "funnel": self.funnel(),
            "revenue_minus_ads_brl": round(week["gross_revenue_brl"] - ad_spend, 2),
            "data_quality": "Somente dados sincronizados. Campos sem origem real permanecem vazios.",
        }

    @staticmethod
    def _lead_public(row: dict[str, Any]) -> dict[str, Any]:
        return {
            "id": row["id"],
            "business_id": row.get("business_id"),
            "name": row["name"],
            "email": row.get("email"),
            "phone": row.get("phone"),
            "stage": row["stage"],
            "source": row.get("source"),
            "consent": bool(row.get("consent")),
            "notes": row.get("notes"),
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
        }


_service: SalesService | None = None


def get_sales() -> SalesService:
    global _service
    if _service is None:
        _service = SalesService()
    return _service
