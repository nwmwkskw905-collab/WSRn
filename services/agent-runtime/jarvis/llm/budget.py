"""Cost and call budgeting for model providers.

Prices are NOT hardcoded: they change and vary per account. The user configures
USD prices per 1M tokens; until then cost is recorded as "unavailable" and cloud
usage is blocked unless an explicit call budget is configured.
"""
from __future__ import annotations

import time
from datetime import datetime, timezone
from typing import Any

from ..db import get_db, now_iso


class BudgetManager:
    def __init__(self) -> None:
        self.db = get_db()

    def config(self) -> dict[str, Any]:
        return {
            "monthly_budget_usd": float(self.db.get_setting("llm.monthly_budget_usd", 0) or 0),
            "max_calls_per_day": int(self.db.get_setting("llm.max_calls_per_day", 0) or 0),
            "prices": self.db.get_setting("llm.prices", {}) or {},
            "allow_paid": bool(self.db.get_setting("llm.allow_paid", False)),
        }

    def usage_summary(self) -> dict[str, Any]:
        month = datetime.now(timezone.utc).strftime("%Y-%m")
        day = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        month_row = self.db.one(
            "SELECT COUNT(*) calls, COALESCE(SUM(cost_usd),0) cost, COALESCE(SUM(prompt_tokens+completion_tokens),0) tokens "
            "FROM usage_ledger WHERE ts LIKE ?",
            (f"{month}%",),
        ) or {}
        day_row = self.db.one(
            "SELECT COUNT(*) calls FROM usage_ledger WHERE ts LIKE ?", (f"{day}%",)
        ) or {}
        by_provider = self.db.query(
            "SELECT provider, COUNT(*) calls, COALESCE(SUM(cost_usd),0) cost FROM usage_ledger WHERE ts LIKE ? GROUP BY provider",
            (f"{month}%",),
        )
        return {
            "month": month,
            "calls_month": int(month_row.get("calls", 0)),
            "tokens_month": int(month_row.get("tokens", 0)),
            "cost_usd_month": round(float(month_row.get("cost", 0)), 6),
            "calls_today": int(day_row.get("calls", 0)),
            "by_provider": by_provider,
            "cost_source": "configured_prices" if self.config()["prices"] else "unavailable",
            "budget": self.config(),
        }

    def estimate_cost(self, provider: str, model: str, prompt_tokens: int, completion_tokens: int) -> float | None:
        prices = self.config()["prices"]
        entry = (prices or {}).get(f"{provider}:{model}") or (prices or {}).get(model)
        if not entry:
            return None
        try:
            prompt_price = float(entry.get("input_per_1m", 0))
            completion_price = float(entry.get("output_per_1m", 0))
        except (TypeError, ValueError):
            return None
        return (prompt_tokens / 1_000_000) * prompt_price + (completion_tokens / 1_000_000) * completion_price

    def check(self, estimated_tokens: int = 0) -> tuple[bool, str]:
        cfg = self.config()
        if not cfg["allow_paid"]:
            return False, "Uso de provedores pagos desativado (Configuracoes > IA)."
        if cfg["max_calls_per_day"] and self.usage_summary()["calls_today"] >= cfg["max_calls_per_day"]:
            return False, "Limite diario de chamadas de IA atingido."
        if cfg["monthly_budget_usd"] <= 0:
            return False, "Defina um orcamento mensal maior que zero antes de usar modelos pagos."
        spent = self.usage_summary()["cost_usd_month"]
        if spent >= cfg["monthly_budget_usd"]:
            return False, "Orcamento mensal de IA esgotado."
        return True, "ok"

    def record(
        self,
        provider: str,
        model: str,
        prompt_tokens: int,
        completion_tokens: int,
        latency_ms: int,
        task_id: str | None,
        outcome: str,
    ) -> dict[str, Any]:
        cost = self.estimate_cost(provider, model, prompt_tokens, completion_tokens)
        self.db.execute(
            "INSERT INTO usage_ledger(ts, task_id, provider, model, prompt_tokens, completion_tokens, cost_usd, latency_ms, outcome)"
            " VALUES (?,?,?,?,?,?,?,?,?)",
            (now_iso(), task_id, provider, model, prompt_tokens, completion_tokens, cost or 0.0, latency_ms, outcome),
        )
        self.db.execute(
            """INSERT INTO model_stats(provider, model, calls, failures, total_latency_ms, total_cost_usd, updated_at)
               VALUES (?,?,1,?,?,?,?)
               ON CONFLICT(provider, model) DO UPDATE SET calls=calls+1,
                 failures=failures+excluded.failures,
                 total_latency_ms=total_latency_ms+excluded.total_latency_ms,
                 total_cost_usd=total_cost_usd+excluded.total_cost_usd,
                 updated_at=excluded.updated_at""",
            (provider, model, 0 if outcome == "ok" else 1, latency_ms, cost or 0.0, now_iso()),
        )
        self._alert_if_needed()
        return {"cost_usd": cost, "cost_known": cost is not None}

    def _alert_if_needed(self) -> None:
        cfg = self.config()
        if cfg["monthly_budget_usd"] <= 0:
            return
        summary = self.usage_summary()
        ratio = summary["cost_usd_month"] / cfg["monthly_budget_usd"]
        if ratio >= 0.8:
            self.db.audit("system", "budget.alert", "llm", "warning", {"ratio": round(ratio, 2)})

    def model_stats(self) -> list[dict[str, Any]]:
        return self.db.query("SELECT * FROM model_stats ORDER BY calls DESC")


def now() -> float:
    return time.time()
