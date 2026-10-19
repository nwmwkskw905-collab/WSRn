"""Ads manager with hard budget guardrails.

Default autonomous spend is R$ 0.00. Campaigns can always be prepared for free.
Publishing requires: platform credentials, ads.write permission, ads.budget
permission, an approved budget grant and an explicit approval record.

Meta Marketing API calls are implemented against the documented Graph endpoints but
are marked VALIDACAO REAL PENDENTE until executed with a real ad account.
Google Ads / TikTok are adapter placeholders that refuse to pretend success.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from typing import Any

import httpx

from ..db import get_db, new_id, now_iso
from ..security.approvals import get_approval_service
from ..security.secrets import get_vault

META_BASE = "https://graph.facebook.com/v21.0"


class AdsError(RuntimeError):
    pass


class AdsService:
    def __init__(self) -> None:
        self.db = get_db()
        self.vault = get_vault()
        self.approvals = get_approval_service()

    # -- budget authorization ---------------------------------------------
    def budget_policy(self) -> dict[str, Any]:
        return self.db.get_setting(
            "ads.budget_policy",
            {
                "enabled": False,
                "daily_limit_brl": 0.0,
                "monthly_limit_brl": 0.0,
                "ad_account": "",
                "expires_at": None,
                "allow_auto_pause": False,
            },
        )

    def set_budget_policy(self, daily_limit: float, monthly_limit: float, ad_account: str,
                          expires_in_days: int = 7, allow_auto_pause: bool = False, approval_id: str | None = None) -> dict[str, Any]:
        if not approval_id:
            raise PermissionError("Alterar limites de gasto exige aprovacao com PIN")
        self.approvals.consume(approval_id, "ads.budget_policy")
        if daily_limit < 0 or monthly_limit < 0:
            raise AdsError("Limites nao podem ser negativos")
        if monthly_limit and daily_limit > monthly_limit:
            raise AdsError("Limite diario maior que o mensal")
        policy = {
            "enabled": daily_limit > 0,
            "daily_limit_brl": round(daily_limit, 2),
            "monthly_limit_brl": round(monthly_limit, 2),
            "ad_account": ad_account,
            "expires_at": (datetime.now(timezone.utc) + timedelta(days=expires_in_days)).isoformat(),
            "allow_auto_pause": allow_auto_pause,
            "configured_at": now_iso(),
        }
        self.db.set_setting("ads.budget_policy", policy)
        self.db.audit("user", "ads.budget_policy", ad_account or "none", "granted", policy)
        return policy

    def _check_budget(self, daily_budget: float, monthly_limit: float) -> None:
        policy = self.budget_policy()
        if not policy.get("enabled"):
            raise AdsError("Investimento automatico desativado (limite R$ 0,00). Configure e aprove um orcamento.")
        expires = policy.get("expires_at")
        if expires and datetime.now(timezone.utc) > datetime.fromisoformat(expires):
            raise AdsError("Autorizacao de orcamento expirada")
        if daily_budget > float(policy.get("daily_limit_brl", 0)):
            raise AdsError("Orcamento diario acima do limite autorizado")
        if monthly_limit > float(policy.get("monthly_limit_brl", 0)):
            raise AdsError("Orcamento mensal acima do limite autorizado")
        month_spend = self._month_spend()
        if month_spend + monthly_limit > float(policy.get("monthly_limit_brl", 0)):
            raise AdsError("Orcamento mensal restante insuficiente")

    def _month_spend(self) -> float:
        month = datetime.now(timezone.utc).strftime("%Y-%m")
        row = self.db.one(
            "SELECT COALESCE(SUM(spent_cents),0) v FROM campaigns WHERE updated_at LIKE ?", (f"{month}%",)
        ) or {}
        return float(row.get("v", 0)) / 100

    # -- campaign preparation --------------------------------------------
    def prepare(self, objective: str, provider: str = "meta", daily_budget: float = 0,
                monthly_limit: float = 0, audience: str | None = None, product_id: str | None = None,
                business_id: str | None = None) -> dict[str, Any]:
        policy = self.budget_policy()
        guard_errors = []
        if daily_budget > 0:
            try:
                self._check_budget(daily_budget, monthly_limit or daily_budget)
            except AdsError as exc:
                guard_errors.append(str(exc))
        campaign_id = new_id("cmp_")
        plan = {
            "provider": provider,
            "objective": objective,
            "audience": audience or "Definir publico com base em dados reais do produto; nao presumido.",
            "budget": {
                "daily_brl": daily_budget,
                "monthly_limit_brl": monthly_limit,
                "policy": policy,
                "guard_errors": guard_errors,
            },
            "structure": {
                "campaign": "1 campanha por oferta para evitar duplicidade",
                "ad_sets": ["publico amplo (interesses validados)", "lookalike/retargeting quando houver base"],
                "creatives": ["3 variacoes de gancho", "2 provas", "1 CTA direto"],
            },
            "copy_drafts": self._copy_drafts(objective),
            "measurement": [
                "Validar pixel e eventos de compra antes de investir",
                "Amostra minima de 100 cliques antes de julgar CPA",
                "Nao atribuir venda sem UTM/pixel confiavel",
            ],
            "status": "draft_requires_approval" if not guard_errors else "blocked_budget",
            "spend_now_brl": 0.0,
            "note": "Preparar campanha nao gasta dinheiro. Publicacao exige aprovacao e conta conectada.",
        }
        self.db.execute(
            """INSERT INTO campaigns(id, business_id, provider, external_id, name, status, objective,
                 daily_budget_cents, monthly_limit_cents, spent_cents, authorized, metrics_json, created_at, updated_at)
               VALUES (?,?,?,?,?,?,?,?,?,0,0,?,?,?)""",
            (
                campaign_id, business_id, provider, None, f"Campanha {objective[:60]}", "draft", objective,
                int(round(daily_budget * 100)), int(round(monthly_limit * 100)), json.dumps(plan), now_iso(), now_iso(),
            ),
        )
        return {"campaign_id": campaign_id, "plan": plan, "published": False, "spent_brl": 0.0}

    def _copy_drafts(self, objective: str) -> list[dict[str, str]]:
        subject = objective.strip().rstrip(".")[:120]
        return [
            {"headline": "Resolva isso sem complicacao", "body": f"{subject}. Veja como funciona na pratica.", "cta": "Saiba mais"},
            {"headline": "O proximo passo para o seu objetivo", "body": f"Foco em {subject}. Sem promessas irreais.", "cta": "Conhecer"},
            {"headline": "Feito para quem quer resultado", "body": f"{subject}. Metodo claro, sem atalhos falsos.", "cta": "Comecar"},
        ]

    # -- publishing (Meta) ------------------------------------------------
    async def publish_meta(self, campaign_id: str, approval_id: str | None) -> dict[str, Any]:
        campaign = self.db.one("SELECT * FROM campaigns WHERE id=?", (campaign_id,))
        if not campaign:
            raise AdsError("Campanha nao encontrada")
        if not approval_id:
            raise PermissionError("Publicacao exige aprovacao registrada")
        self.approvals.consume(approval_id, "ads.publish_meta")
        daily = campaign["daily_budget_cents"] / 100
        monthly = campaign["monthly_limit_cents"] / 100
        self._check_budget(daily, monthly)
        cfg = self.db.get_setting("ads.meta", {}) or {}
        secret = self.vault.get("ads:meta") or {}
        token = secret.get("access_token")
        ad_account = cfg.get("ad_account_id")
        page_id = cfg.get("page_id")
        if not token or not ad_account:
            raise AdsError("Meta Ads nao conectado (access_token e ad_account_id ausentes)")
        # Protection against duplicate launches
        existing = self.db.one(
            "SELECT 1 FROM campaigns WHERE provider='meta' AND name=? AND external_id IS NOT NULL",
            (campaign["name"],),
        )
        if existing:
            raise AdsError("Ja existe campanha publicada com o mesmo nome; lancamento duplicado bloqueado")
        payload = {
            "name": campaign["name"],
            "objective": "OUTCOME_SALES",
            "status": "PAUSED",
            "special_ad_categories": [],
            "access_token": token,
        }
        async with httpx.AsyncClient(timeout=40) as client:
            resp = await client.post(f"{META_BASE}/{ad_account}/campaigns", data=payload)
            if resp.status_code >= 400:
                raise AdsError(f"Meta API HTTP {resp.status_code}: {resp.text[:400]}")
            meta_campaign = resp.json()
            adset_payload = {
                "name": f"{campaign['name']} - AdSet",
                "campaign_id": meta_campaign.get("id"),
                "daily_budget": int(round(daily * 100)),
                "billing_event": "IMPRESSIONS",
                "optimization_goal": "OFFSITE_CONVERSIONS",
                "bid_strategy": "LOWEST_COST_WITHOUT_CAP",
                "status": "PAUSED",
                "access_token": token,
            }
            if page_id:
                adset_payload["promoted_object"] = {"page_id": page_id}
            adset = await client.post(f"{META_BASE}/{ad_account}/adsets", data=adset_payload)
            if adset.status_code >= 400:
                raise AdsError(f"Meta adset HTTP {adset.status_code}: {adset.text[:400]}")
        self.db.execute(
            "UPDATE campaigns SET external_id=?, status='paused_pending_activation', authorized=1, updated_at=? WHERE id=?",
            (meta_campaign.get("id"), now_iso(), campaign_id),
        )
        self.db.audit("agent", "ads.publish_meta", meta_campaign.get("id", ""), "granted",
                      {"campaign_id": campaign_id, "daily_budget": daily})
        return {
            "provider": "meta",
            "campaign_external_id": meta_campaign.get("id"),
            "adset_external_id": adset.json().get("id"),
            "status": "PAUSED",
            "spent_brl": 0.0,
            "validation": "VALIDACAO REAL PENDENTE",
            "note": "Criada pausada na Meta. Ative manualmente apos revisar publico, criativos e conformidade.",
        }

    # -- metrics -----------------------------------------------------------
    def analyze(self, metrics: list[dict[str, Any]], target_cpa: float = 0, min_clicks: int = 100) -> dict[str, Any]:
        out = []
        for m in metrics:
            clicks = int(m.get("clicks", 0))
            impressions = int(m.get("impressions", 0))
            spend = float(m.get("spend", 0))
            conversions = int(m.get("conversions", 0))
            revenue = float(m.get("revenue", 0))
            ctr = (clicks / impressions) if impressions else None
            cpc = (spend / clicks) if clicks else None
            cpa = (spend / conversions) if conversions else None
            roas = (revenue / spend) if spend else None
            confidence = "insuficiente" if clicks < min_clicks else "amostra minima atingida"
            alert = None
            if target_cpa and cpa and cpa > target_cpa and clicks >= min_clicks:
                alert = "CPA acima da meta com amostra minima; revisar criativo/publico antes de pausar"
            out.append({
                "campaign_id": m.get("campaign_id"),
                "ctr": round(ctr, 4) if ctr is not None else None,
                "cpc_brl": round(cpc, 2) if cpc is not None else None,
                "cpa_brl": round(cpa, 2) if cpa is not None else None,
                "roas": round(roas, 2) if roas is not None else None,
                "confidence": confidence,
                "alert": alert,
                "sample_clicks": clicks,
            })
        return {
            "campaigns": out,
            "caveats": [
                "ROAS depende de atribuicao confiavel; correlacao nao prova causalidade.",
                "Amostras pequenas produzem metricas instaveis.",
            ],
        }

    def evaluate_pause_rules(self, metrics: list[dict[str, Any]], target_cpa: float, min_spend: float = 50.0) -> list[dict[str, Any]]:
        decisions = []
        for m in metrics:
            spend = float(m.get("spend", 0))
            conversions = int(m.get("conversions", 0))
            if spend >= min_spend and conversions == 0:
                decisions.append({"campaign_id": m.get("campaign_id"), "action": "pause_suggested",
                                  "reason": f"R$ {spend:.2f} gastos sem conversoes registradas"})
            elif conversions and (spend / conversions) > target_cpa * 1.5:
                decisions.append({"campaign_id": m.get("campaign_id"), "action": "review_suggested",
                                  "reason": "CPA 50% acima da meta"})
        return decisions


_service: AdsService | None = None


def get_ads() -> AdsService:
    global _service
    if _service is None:
        _service = AdsService()
    return _service
