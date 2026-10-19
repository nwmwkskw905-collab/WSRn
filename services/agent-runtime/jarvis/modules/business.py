"""Business intelligence: unit economics and planning with explicit assumptions.

Nothing here invents market data. External facts must come from the research module
with sources; the numbers below are calculator outputs derived from user inputs and
labelled assumptions.
"""
from __future__ import annotations

import json
from typing import Any

from ..db import get_db, new_id, now_iso


class BusinessService:
    def __init__(self) -> None:
        self.db = get_db()

    def create(self, name: str, niche: str | None = None, audience: str | None = None,
               goals: dict[str, Any] | None = None, brand: dict[str, Any] | None = None,
               channels: list[str] | None = None) -> dict[str, Any]:
        business_id = new_id("biz_")
        ts = now_iso()
        self.db.execute(
            "INSERT INTO businesses(id, name, niche, audience, goals_json, brand_json, channels_json, created_at, updated_at)"
            " VALUES (?,?,?,?,?,?,?,?,?)",
            (business_id, name, niche, audience, json.dumps(goals or {}), json.dumps(brand or {}),
             json.dumps(channels or []), ts, ts),
        )
        return self.get(business_id)

    def get(self, business_id: str) -> dict[str, Any]:
        row = self.db.one("SELECT * FROM businesses WHERE id=?", (business_id,))
        if not row:
            raise KeyError("Negocio nao encontrado")
        return self._public(row)

    def list(self) -> list[dict[str, Any]]:
        return [self._public(r) for r in self.db.query("SELECT * FROM businesses ORDER BY created_at DESC")]

    def update(self, business_id: str, **fields: Any) -> dict[str, Any]:
        allowed = {"name", "niche", "audience", "goals_json", "brand_json", "channels_json"}
        updates = {k: v for k, v in fields.items() if k in allowed}
        if not updates:
            return self.get(business_id)
        sets = ", ".join(f"{k}=?" for k in updates)
        self.db.execute(
            f"UPDATE businesses SET {sets}, updated_at=? WHERE id=?",
            (*[json.dumps(v) if isinstance(v, (dict, list)) else v for v in updates.values()], now_iso(), business_id),
        )
        return self.get(business_id)

    def unit_economics(
        self,
        price: float,
        target_monthly_revenue: float = 0,
        conversion_rate: float = 0.02,
        ad_cost_per_click: float = 0,
        payment_fee_percent: float = 0,
        payment_fee_fixed: float = 0,
        refund_rate: float = 0,
        recurring: bool = False,
        churn_rate: float = 0,
    ) -> dict[str, Any]:
        if price <= 0:
            raise ValueError("Preco deve ser positivo")
        conversion_rate = min(max(conversion_rate, 0.0001), 1)
        ad_cost_per_click = max(ad_cost_per_click, 0)
        refund_rate = min(max(refund_rate, 0), 1)
        net_per_sale = price * (1 - payment_fee_percent / 100) - payment_fee_fixed
        net_per_sale *= (1 - refund_rate)
        cac = ad_cost_per_click / conversion_rate if conversion_rate else None
        contribution = net_per_sale - (cac or 0)
        customers_needed = target_monthly_revenue / price if target_monthly_revenue else None
        traffic_needed = (customers_needed / conversion_rate) if customers_needed else None
        ad_spend_needed = (traffic_needed * ad_cost_per_click) if traffic_needed is not None else None
        ltv = None
        if recurring and churn_rate > 0:
            ltv = net_per_sale / (churn_rate / 100)
        payback_sales = None
        if cac and net_per_sale > 0:
            payback_sales = cac / net_per_sale
        return {
            "inputs": {
                "price": price,
                "target_monthly_revenue": target_monthly_revenue,
                "conversion_rate": conversion_rate,
                "ad_cost_per_click": ad_cost_per_click,
                "payment_fee_percent": payment_fee_percent,
                "payment_fee_fixed": payment_fee_fixed,
                "refund_rate": refund_rate,
                "recurring": recurring,
                "churn_rate": churn_rate,
            },
            "math": {
                "net_revenue_per_sale": round(net_per_sale, 2),
                "cac_estimate": round(cac, 2) if cac is not None else None,
                "contribution_margin_per_sale": round(contribution, 2),
                "customers_needed_for_target": round(customers_needed, 1) if customers_needed else None,
                "traffic_needed_for_target": round(traffic_needed, 0) if traffic_needed else None,
                "ad_spend_needed_for_target": round(ad_spend_needed, 2) if ad_spend_needed is not None else None,
                "ltv_estimate": round(ltv, 2) if ltv else None,
                "sales_to_payback_cac": round(payback_sales, 2) if payback_sales else None,
                "ltv_cac_ratio": round(ltv / cac, 2) if ltv and cac else None,
            },
            "classification": {
                "net_revenue_per_sale": "calculado",
                "cac_estimate": "estimativa baseada em conversao informada",
                "ltv_estimate": "estimativa",
                "customers_needed_for_target": "calculado",
                "traffic_needed_for_target": "estimativa",
            },
            "assumptions": [
                "Conversao, CPC, taxas, reembolso e churn foram informados ou assumidos; nao sao dados de mercado verificados.",
                "Nao ha garantia de receita. Valide demanda e custos reais antes de investir.",
            ],
            "disclaimer": "Cenarios matematicos, nao previsoes. Dados externos exigem pesquisa com fontes.",
        }

    def goal_plan(self, target_monthly: float, price: float, conversion_rate: float,
                  traffic_source: str = "organico + pago", monthly_investment: float = 0) -> dict[str, Any]:
        econ = self.unit_economics(
            price=price,
            target_monthly_revenue=target_monthly,
            conversion_rate=conversion_rate,
            ad_cost_per_click=0,
        )
        scenarios = {}
        for name, conv in {"pessimista": conversion_rate * 0.5, "base": conversion_rate, "otimista": conversion_rate * 1.5}.items():
            conv = max(conv, 0.0001)
            customers = target_monthly / price
            scenarios[name] = {
                "conversion_rate": round(conv, 4),
                "customers_needed": round(customers, 1),
                "traffic_needed": round(customers / conv, 0),
            }
        return {
            "target_monthly_revenue": target_monthly,
            "price": price,
            "scenarios": scenarios,
            "unit_economics": econ,
            "traffic_source": traffic_source,
            "monthly_investment": monthly_investment,
            "next_experiments": [
                "Validar preco com 20-50 potenciais clientes antes de escalar",
                "Testar 3 promessas comerciais com amostra minima de 1000 visitas",
                "Medir conversao real do checkout por origem de trafego",
                "Comparar CAC real com contribuicao por venda",
            ],
            "data_quality": "Calculado a partir de premissas do usuario; nenhuma venda real foi consultada.",
        }

    @staticmethod
    def _public(row: dict[str, Any]) -> dict[str, Any]:
        def load(value: str | None, default: Any) -> Any:
            try:
                return json.loads(value) if value else default
            except json.JSONDecodeError:
                return default

        return {
            "id": row["id"],
            "name": row["name"],
            "niche": row.get("niche"),
            "audience": row.get("audience"),
            "goals": load(row.get("goals_json"), {}),
            "brand": load(row.get("brand_json"), {}),
            "channels": load(row.get("channels_json"), []),
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
        }


_service: BusinessService | None = None


def get_business() -> BusinessService:
    global _service
    if _service is None:
        _service = BusinessService()
    return _service
