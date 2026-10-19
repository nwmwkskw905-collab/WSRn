"""HTTP API consumed by the Electron main process."""
from __future__ import annotations

import json
import os
import platform
import shutil
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Body, HTTPException, Query
from pydantic import BaseModel, Field

from .. import __version__
from ..agents.roles import list_agents
from ..config import CONFIG
from ..db import get_db, now_iso
from ..engine.chat import get_chat
from ..engine.skills import get_skills
from ..engine.tasks import get_engine
from ..llm.router import get_router
from ..llm.budget import BudgetManager
from ..models import (
    AdsDraft, ApprovalDecision, BuildRequest, CaktoCredentials, CaktoProductDraft,
    ChatMessage, LeadCreate, MemoryCreate, PermissionUpdate, PinSetup, ScheduleCreate, TaskCreate,
)
from ..modules.ads import AdsError, get_ads
from ..modules.business import get_business
from ..modules.cakto import CaktoError, get_cakto
from ..modules.development import get_development
from ..modules.gamestudio import get_gamestudio
from ..modules.memory import get_memory
from ..modules.sales import get_sales
from ..modules.scheduler import get_scheduler
from ..security.approvals import get_approval_service
from ..security.permissions import PERMISSION_DEFS, get_permission_engine
from ..security.secrets import get_vault
from ..tools.registry import ToolError, get_registry
from ..validation import run_safe_scenarios

router = APIRouter()


def _db():
    return get_db()


def _error(exc: Exception, status: int = 400) -> HTTPException:
    message = str(exc)
    if isinstance(exc, (PermissionError,)):
        return HTTPException(status_code=403, detail=message)
    if isinstance(exc, KeyError):
        return HTTPException(status_code=404, detail=message)
    return HTTPException(status_code=status, detail=message)


# ---------------------------------------------------------------------------
# Status / settings / diagnostics
# ---------------------------------------------------------------------------


@router.get("/status")
async def status() -> dict[str, Any]:
    db = _db()
    permissions = get_permission_engine()
    vault = get_vault()
    budget = BudgetManager().usage_summary()
    tasks = db.query("SELECT status, COUNT(*) n FROM tasks GROUP BY status")
    return {
        "version": __version__,
        "platform": platform.platform(),
        "python": sys.version.split()[0],
        "host": CONFIG.host,
        "port": CONFIG.port,
        "mode": "demo" if CONFIG.demo_mode else "production",
        "kill_switch": permissions.kill_switch_active(),
        "pin_configured": get_approval_service().pin_configured(),
        "permissions_granted": sum(1 for p in permissions.list_grants() if p["granted"]),
        "permissions_total": len(PERMISSION_DEFS),
        "tasks": {row["status"]: row["n"] for row in tasks},
        "pending_approvals": len([a for a in get_approval_service().list() if a["status"] == "pending"]),
        "vault_backend": vault.backend,
        "vault_available": vault.available(),
        "llm": {
            "routing_mode": db.get_setting("llm.routing_mode", "auto"),
            "allow_paid": budget["budget"]["allow_paid"],
            "budget_monthly_usd": budget["budget"]["monthly_budget_usd"],
            "cost_usd_month": budget["cost_usd_month"],
            "cost_source": budget["cost_source"],
        },
        "webhook_relay": db.get_setting("webhook.relay", {"configured": False}),
        "capabilities": {
            "windows_automation": platform.system() == "Windows",
            "cakto": "configured" if get_cakto()._stored() else "credentials_required",
            "ads": "guardrails_only",
            "godot": bool(shutil.which("godot") or shutil.which("godot4")),
            "voice_stt": "configurable (faster-whisper optional)",
            "voice_tts": "browser speechSynthesis / provider optional",
        },
        "data_dir": str(CONFIG.data_dir),
        "server_time": now_iso(),
    }


@router.get("/settings")
async def get_settings() -> dict[str, Any]:
    db = _db()
    keys = [
        "ui", "voice", "windows.allowed_apps", "research.provider", "ads.meta", "ads.budget_policy",
        "llm.providers", "llm.routing_mode", "llm.allow_paid", "llm.monthly_budget_usd", "llm.max_calls_per_day",
        "llm.prices", "cakto.demo_fallback", "games.automation_allowed", "webhook.relay", "build.github_workflow",
    ]
    return {key: db.get_setting(key) for key in keys}


@router.put("/settings/{key}")
async def put_setting(key: str, payload: dict[str, Any] = Body(...)) -> dict[str, Any]:
    allowed_prefixes = ("ui.", "voice.", "windows.", "research.", "ads.", "llm.", "cakto.", "games.", "webhook.", "build.")
    allowed_exact = {"ui", "voice", "llm.providers", "llm.routing_mode", "llm.allow_paid", "llm.monthly_budget_usd",
                     "llm.max_calls_per_day", "llm.prices", "ads.meta", "ads.budget_policy", "research.provider",
                     "cakto.demo_fallback", "games.automation_allowed", "webhook.relay", "windows.allowed_apps"}
    if key not in allowed_exact and not key.startswith(allowed_prefixes):
        raise HTTPException(400, "Chave de configuracao nao permitida")
    value = payload.get("value")
    _db().set_setting(key, value)
    _db().audit("user", "settings.update", key, "granted", {"value": _redact_cfg(value)})
    return {"key": key, "value": value}


def _redact_cfg(value: Any) -> Any:
    from ..security.secrets import redact

    return redact(value)


# ---------------------------------------------------------------------------
# Security
# ---------------------------------------------------------------------------


@router.get("/permissions")
async def permissions() -> dict[str, Any]:
    return {"permissions": get_permission_engine().list_grants(),
            "definitions": [{"scope": k, **v} for k, v in PERMISSION_DEFS.items()]}


@router.post("/permissions")
async def set_permission(payload: PermissionUpdate) -> dict[str, Any]:
    try:
        return get_permission_engine().grant(payload.scope, payload.granted, payload.config, payload.expires_in_hours)
    except ValueError as exc:
        raise _error(exc)


@router.post("/permissions/revoke-all")
async def revoke_permissions() -> dict[str, Any]:
    get_permission_engine().revoke_all()
    return {"ok": True, "permissions": get_permission_engine().list_grants()}


@router.get("/security/status")
async def security_status() -> dict[str, Any]:
    db = _db()
    return {
        "kill_switch": get_permission_engine().kill_switch_active(),
        "kill_switch_at": db.get_state("kill_switch_at"),
        "kill_switch_reason": db.get_state("kill_switch_reason"),
        "pin_configured": get_approval_service().pin_configured(),
        "vault_backend": get_vault().backend,
    }


@router.post("/security/pin")
async def set_pin(payload: PinSetup) -> dict[str, Any]:
    try:
        get_approval_service().set_pin(payload.pin, payload.current_pin)
    except (PermissionError, ValueError) as exc:
        raise _error(exc)
    return {"ok": True, "pin_configured": True}


@router.post("/security/verify-pin")
async def verify_pin(payload: dict[str, str] = Body(...)) -> dict[str, Any]:
    return {"valid": get_approval_service().verify_pin(payload.get("pin"))}


@router.post("/security/stop")
async def emergency_stop(payload: dict[str, str] | None = Body(default=None)) -> dict[str, Any]:
    reason = (payload or {}).get("reason", "Botao PARAR JARVIS")
    return get_engine().engage_kill_switch(reason)


@router.post("/security/release")
async def emergency_release() -> dict[str, Any]:
    return get_engine().release_kill_switch()


@router.get("/approvals")
async def approvals(status: str | None = None) -> dict[str, Any]:
    return {"approvals": get_approval_service().list(status)}


@router.post("/approvals/{approval_id}/resolve")
async def resolve_approval(approval_id: str, payload: ApprovalDecision) -> dict[str, Any]:
    try:
        resolved = get_approval_service().resolve(approval_id, payload.approve, payload.pin, payload.note)
    except (PermissionError, ValueError, KeyError) as exc:
        raise _error(exc)
    if resolved["status"] == "approved" and resolved.get("task_id"):
        get_engine().resume_after_approval(resolved["task_id"], approval_id)
    return resolved


# ---------------------------------------------------------------------------
# Tasks / chat
# ---------------------------------------------------------------------------


@router.post("/tasks")
async def create_task(payload: TaskCreate) -> dict[str, Any]:
    if get_permission_engine().kill_switch_active():
        raise HTTPException(423, "Parada de emergencia ativa; reative antes de criar tarefas")
    task = get_engine().create(
        payload.objective, payload.autonomy_level, payload.mode, payload.business_id,
        payload.idempotency_key, auto_start=payload.auto_start,
    )
    return task


@router.get("/tasks")
async def list_tasks(status: str | None = None, limit: int = 100) -> dict[str, Any]:
    return {"tasks": get_engine().list(status, limit)}


@router.get("/tasks/{task_id}")
async def get_task(task_id: str) -> dict[str, Any]:
    try:
        return get_engine().get(task_id)
    except KeyError as exc:
        raise _error(exc)


@router.get("/tasks/{task_id}/events")
async def task_events(task_id: str, after_id: int = 0, limit: int = 200) -> dict[str, Any]:
    return {"events": get_engine().events(task_id, limit=limit, after_id=after_id)}


@router.post("/tasks/{task_id}/cancel")
async def cancel_task(task_id: str) -> dict[str, Any]:
    try:
        return get_engine().cancel(task_id)
    except KeyError as exc:
        raise _error(exc)


@router.post("/tasks/{task_id}/pause")
async def pause_task(task_id: str) -> dict[str, Any]:
    return get_engine().pause(task_id)


@router.post("/tasks/{task_id}/resume")
async def resume_task(task_id: str) -> dict[str, Any]:
    try:
        return get_engine().resume(task_id)
    except PermissionError as exc:
        raise _error(exc)


@router.post("/chat")
async def chat(payload: ChatMessage) -> dict[str, Any]:
    return await get_chat().handle(payload.message, payload.conversation_id)


@router.get("/messages")
async def messages(conversation_id: str = "default", limit: int = 100) -> dict[str, Any]:
    return {"messages": get_chat().history(conversation_id, limit)}


@router.get("/agents")
async def agents() -> dict[str, Any]:
    return {"agents": list_agents()}


@router.get("/skills")
async def skills() -> dict[str, Any]:
    return {"skills": get_skills().list()}


@router.get("/tools")
async def tools() -> dict[str, Any]:
    return {"tools": get_registry().list()}


# ---------------------------------------------------------------------------
# LLM
# ---------------------------------------------------------------------------


@router.get("/llm/state")
async def llm_state() -> dict[str, Any]:
    return get_router().providers_state()


@router.post("/llm/configure")
async def llm_configure(payload: dict[str, Any] = Body(...)) -> dict[str, Any]:
    provider = payload.get("provider")
    if not provider:
        raise HTTPException(400, "provider obrigatorio")
    try:
        return get_router().configure(
            provider, api_key=payload.get("api_key"), model=payload.get("model"),
            base_url=payload.get("base_url"), enabled=bool(payload.get("enabled", True)),
        )
    except RuntimeError as exc:
        raise _error(exc)


@router.post("/llm/budget")
async def llm_budget(payload: dict[str, Any] = Body(...)) -> dict[str, Any]:
    db = _db()
    if "monthly_budget_usd" in payload:
        db.set_setting("llm.monthly_budget_usd", max(0.0, float(payload["monthly_budget_usd"])))
    if "max_calls_per_day" in payload:
        db.set_setting("llm.max_calls_per_day", max(0, int(payload["max_calls_per_day"])))
    if "allow_paid" in payload:
        db.set_setting("llm.allow_paid", bool(payload["allow_paid"]))
    if "prices" in payload and isinstance(payload["prices"], dict):
        db.set_setting("llm.prices", payload["prices"])
    db.audit("user", "llm.budget", "llm", "granted", _redact_cfg(payload))
    return BudgetManager().usage_summary()


# ---------------------------------------------------------------------------
# Cakto
# ---------------------------------------------------------------------------


@router.get("/integrations/cakto/status")
async def cakto_status(verify: bool = False) -> dict[str, Any]:
    return await get_cakto().status(verify=verify)


@router.post("/integrations/cakto/connect")
async def cakto_connect(payload: CaktoCredentials) -> dict[str, Any]:
    try:
        return get_cakto().connect(payload.client_id, payload.client_secret, payload.environment)
    except RuntimeError as exc:
        raise _error(exc)


@router.delete("/integrations/cakto")
async def cakto_disconnect() -> dict[str, Any]:
    return get_cakto().disconnect()


@router.post("/integrations/cakto/sync")
async def cakto_sync(days: int = 30) -> dict[str, Any]:
    try:
        return await get_cakto().sync_orders(days)
    except CaktoError as exc:
        raise _error(exc)


@router.get("/cakto/products")
async def cakto_products(search: str | None = None) -> dict[str, Any]:
    try:
        return await get_cakto().list_products(search)
    except CaktoError as exc:
        raise _error(exc)


@router.post("/cakto/products")
async def cakto_create_product(payload: CaktoProductDraft) -> dict[str, Any]:
    if not payload.confirm_create:
        raise HTTPException(400, "confirm_create=true obrigatorio apos revisar os dados")
    if not payload.approval_id:
        raise HTTPException(403, "Aprovacao registrada com PIN obrigatoria")
    try:
        get_approval_service().consume(payload.approval_id, "cakto.create_product")
        draft = payload.model_dump()
        return await get_cakto().create_product(draft, approved=True)
    except (PermissionError, CaktoError, RuntimeError) as exc:
        raise _error(exc)


@router.get("/cakto/webhook-events")
async def cakto_webhook_events(limit: int = 100) -> dict[str, Any]:
    return {"events": get_cakto().webhook_events(limit)}


@router.get("/products")
async def local_products() -> dict[str, Any]:
    return {"products": _db().query("SELECT * FROM products ORDER BY created_at DESC")}


@router.get("/orders")
async def local_orders(limit: int = 200) -> dict[str, Any]:
    return {"orders": _db().query("SELECT id, provider, status, amount_cents, currency, payment_method, created_at, paid_at FROM orders ORDER BY COALESCE(paid_at, created_at) DESC LIMIT ?", (limit,))}


# ---------------------------------------------------------------------------
# Sales / business / ads
# ---------------------------------------------------------------------------


@router.get("/sales/report")
async def sales_report(days: int = Query(7, ge=1, le=365)) -> dict[str, Any]:
    return get_sales().order_summary(days)


@router.get("/sales/dashboard")
async def sales_dashboard() -> dict[str, Any]:
    return get_sales().dashboard()


@router.get("/sales/funnel")
async def sales_funnel() -> dict[str, Any]:
    return get_sales().funnel()


@router.get("/leads")
async def leads(stage: str | None = None) -> dict[str, Any]:
    return {"leads": get_sales().list_leads(stage), "eligible_for_contact": get_sales().eligible_contacts()}


@router.post("/leads")
async def create_lead(payload: LeadCreate) -> dict[str, Any]:
    return get_sales().create_lead(**payload.model_dump())


@router.put("/leads/{lead_id}")
async def update_lead(lead_id: str, payload: dict[str, Any] = Body(...)) -> dict[str, Any]:
    try:
        return get_sales().update_lead(lead_id, **payload)
    except KeyError as exc:
        raise _error(exc)


@router.get("/businesses")
async def businesses() -> dict[str, Any]:
    return {"businesses": get_business().list()}


@router.post("/businesses")
async def create_business(payload: dict[str, Any] = Body(...)) -> dict[str, Any]:
    if not payload.get("name"):
        raise HTTPException(400, "name obrigatorio")
    return get_business().create(
        payload["name"], payload.get("niche"), payload.get("audience"),
        payload.get("goals"), payload.get("brand"), payload.get("channels"),
    )


@router.post("/businesses/plan")
async def business_plan(payload: dict[str, Any] = Body(...)) -> dict[str, Any]:
    try:
        return get_business().goal_plan(
            target_monthly=float(payload.get("target_monthly", 10000)),
            price=float(payload.get("price", 97)),
            conversion_rate=float(payload.get("conversion_rate", 0.02)),
            traffic_source=payload.get("traffic_source", "organico + pago"),
            monthly_investment=float(payload.get("monthly_investment", 0)),
        )
    except ValueError as exc:
        raise _error(exc)


@router.get("/ads/budget")
async def ads_budget() -> dict[str, Any]:
    return get_ads().budget_policy()


@router.post("/ads/budget")
async def set_ads_budget(payload: dict[str, Any] = Body(...)) -> dict[str, Any]:
    try:
        return get_ads().set_budget_policy(
            daily_limit=float(payload.get("daily_limit", 0)),
            monthly_limit=float(payload.get("monthly_limit", 0)),
            ad_account=str(payload.get("ad_account", "")),
            expires_in_days=int(payload.get("expires_in_days", 7)),
            allow_auto_pause=bool(payload.get("allow_auto_pause", False)),
            approval_id=payload.get("approval_id"),
        )
    except (AdsError, PermissionError, ValueError) as exc:
        raise _error(exc)


@router.post("/ads/prepare")
async def ads_prepare(payload: AdsDraft) -> dict[str, Any]:
    try:
        plan = get_ads().prepare(
            payload.objective, payload.provider, payload.daily_budget, payload.monthly_limit,
            payload.audience, payload.product_id, payload.business_id,
        )
        plan["published"] = False
        if payload.publish:
            plan["publish_blocked_reason"] = "Publicacao exige endpoint dedicado com aprovacao e credenciais Meta."
        return plan
    except AdsError as exc:
        raise _error(exc)


@router.post("/ads/analyze")
async def ads_analyze(payload: dict[str, Any] = Body(...)) -> dict[str, Any]:
    return get_ads().analyze(payload.get("metrics", []), float(payload.get("target_cpa", 0)))


@router.get("/ads/campaigns")
async def ads_campaigns() -> dict[str, Any]:
    return {"campaigns": _db().query("SELECT * FROM campaigns ORDER BY created_at DESC")}


# ---------------------------------------------------------------------------
# Development / game studio / memory / schedules
# ---------------------------------------------------------------------------


@router.post("/development/build")
async def development_build(payload: BuildRequest) -> dict[str, Any]:
    if not get_permission_engine().is_granted("fs.write"):
        raise HTTPException(403, "Permissao fs.write necessaria")
    try:
        return get_development().create(payload.kind, payload.name, payload.objective, payload.run_tests)
    except (ValueError, OSError) as exc:
        raise _error(exc)


@router.get("/projects")
async def projects() -> dict[str, Any]:
    return {"projects": get_development().list_projects(), "artifacts": _db().query("SELECT * FROM artifacts ORDER BY created_at DESC LIMIT 200")}


@router.post("/gamestudio/build")
async def gamestudio_build(payload: BuildRequest) -> dict[str, Any]:
    if not get_permission_engine().is_granted("fs.write"):
        raise HTTPException(403, "Permissao fs.write necessaria")
    return get_gamestudio().create_racer(payload.name, payload.objective, payload.run_tests)


@router.get("/memories")
async def memories(kind: str | None = None) -> dict[str, Any]:
    return {"memories": get_memory().list(kind)}


@router.post("/memories")
async def create_memory(payload: MemoryCreate) -> dict[str, Any]:
    return get_memory().add(payload.content, payload.kind, payload.key, payload.tags, payload.source)


@router.get("/memories/search")
async def search_memories(q: str) -> dict[str, Any]:
    return {"results": get_memory().search(q)}


@router.delete("/memories/{memory_id}")
async def delete_memory(memory_id: str) -> dict[str, Any]:
    return {"deleted": get_memory().delete(memory_id)}


@router.get("/schedules")
async def schedules() -> dict[str, Any]:
    return {"schedules": get_scheduler().list(), "note": "Execucao local: nada roda com o PC desligado."}


@router.post("/schedules")
async def create_schedule(payload: ScheduleCreate) -> dict[str, Any]:
    try:
        return get_scheduler().create(payload.name, payload.objective, payload.interval_seconds, payload.cron, payload.autonomy_level)
    except ValueError as exc:
        raise _error(exc)


@router.post("/schedules/{schedule_id}/toggle")
async def toggle_schedule(schedule_id: str, enabled: bool = True) -> dict[str, Any]:
    try:
        return get_scheduler().set_enabled(schedule_id, enabled)
    except KeyError as exc:
        raise _error(exc)


# ---------------------------------------------------------------------------
# Logs / diagnostics / validation
# ---------------------------------------------------------------------------


@router.get("/logs/audit")
async def audit(limit: int = 200) -> dict[str, Any]:
    rows = _db().query("SELECT * FROM audit_log ORDER BY id DESC LIMIT ?", (min(limit, 1000),))
    for row in rows:
        try:
            row["details"] = json.loads(row.pop("details_json") or "{}")
        except json.JSONDecodeError:
            row["details"] = {}
    return {"audit": rows}


@router.get("/logs/events")
async def events(limit: int = 200) -> dict[str, Any]:
    return {"events": get_engine().events(limit=min(limit, 500))}


@router.get("/usage")
async def usage() -> dict[str, Any]:
    return BudgetManager().usage_summary()


@router.get("/diagnostics")
async def diagnostics() -> dict[str, Any]:
    db = _db()
    checks = []
    checks.append({"name": "banco_sqlite", "status": "ok" if db.one("SELECT 1") else "fail"})
    token_path = CONFIG.token_path
    perms = oct(os.stat(token_path).st_mode & 0o777) if token_path.exists() else None
    checks.append({"name": "token_local", "status": "ok" if perms in {"0o600", "0o400"} else "warning",
                   "detail": f"permissions={perms}"})
    checks.append({"name": "cofre", "status": "ok" if get_vault().available() else "error",
                   "detail": get_vault().backend})
    checks.append({"name": "pin", "status": "ok" if get_approval_service().pin_configured() else "warning",
                   "detail": "PIN local para aprovacoes sensiveis"})
    checks.append({"name": "cakto", "status": "configured" if get_cakto()._stored() else "not_configured"})
    workflow = Path(__file__).resolve().parents[4] / ".github" / "workflows" / "jarvis-release.yml"
    checks.append({"name": "workflow_build", "status": "present" if workflow.exists() else "missing"})
    checks.append({"name": "godot", "status": "present" if (shutil.which("godot") or shutil.which("godot4")) else "missing"})
    return {
        "checks": checks,
        "paths": {"data_dir": str(CONFIG.data_dir), "db": str(CONFIG.db_path), "workspace": str(CONFIG.workspace_dir)},
        "python": sys.version,
        "disk_free_bytes": shutil.disk_usage(CONFIG.data_dir).free,
        "generated_at": now_iso(),
    }


@router.post("/validation/run")
async def run_validation() -> dict[str, Any]:
    return await run_safe_scenarios()


@router.get("/backup")
async def create_backup() -> dict[str, Any]:
    target = CONFIG.backups_dir / f"jarvis-{datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S')}.sqlite3"
    _db().backup(target)
    _db().audit("user", "backup.create", str(target), "granted", {"bytes": target.stat().st_size})
    return {"path": str(target), "bytes": target.stat().st_size}


@router.get("/health/deep")
async def deep_health() -> dict[str, Any]:
    started = time.monotonic()
    return {
        "db": bool(_db().one("SELECT 1")),
        "engine": get_engine() is not None,
        "skills": len(get_skills().list()),
        "tools": len(get_registry().list()),
        "elapsed_ms": round((time.monotonic() - started) * 1000, 2),
    }


@router.post("/webhooks/cakto")
async def ingest_cakto_webhook(payload: dict[str, Any] = Body(...)) -> dict[str, Any]:
    """Receive events forwarded by the relay (already origin-verified by HMAC).

    The runtime still deduplicates by order id and never treats a Pix generation as
    a paid sale.
    """
    event = payload.get("event")
    data = payload.get("data")
    if not event or data is None:
        raise HTTPException(400, "event/data ausentes")
    if isinstance(data, list):
        key = ",".join(str(item.get("id", "")) for item in data if isinstance(item, dict)) or str(len(data))
    elif isinstance(data, dict):
        key = str(data.get("id") or data.get("checkoutUrl") or json.dumps(data, sort_keys=True)[:120])
    else:
        key = str(data)[:120]
    result = get_cakto().record_webhook(event, data, f"{event}:{key}"[:200])
    _db().audit("relay", "cakto.webhook", event, result["status"], {"dedupe_key": key[:120]})
    return result


# ---------------------------------------------------------------------------
# Approval requests initiated by the UI (allowlisted actions only)
# ---------------------------------------------------------------------------

APPROVAL_ACTIONS = {
    "cakto.create_product": ("high", "Criar produto real na Cakto"),
    "ads.publish_meta": ("high", "Publicar campanha na Meta Ads"),
    "ads.budget_policy": ("critical", "Alterar limites de orcamento publicitario"),
    "cakto.refund": ("critical", "Aprovar reembolso"),
    "fs.delete": ("high", "Excluir ou mover arquivos permanentemente"),
    "windows.install": ("high", "Instalar programa"),
}


@router.post("/approvals/request")
async def request_approval(payload: dict[str, Any] = Body(...)) -> dict[str, Any]:
    action = payload.get("action")
    if action not in APPROVAL_ACTIONS:
        raise HTTPException(400, f"Acao nao permitida para aprovacao manual: {action}")
    risk, label = APPROVAL_ACTIONS[action]
    approval = get_approval_service().request(
        action, risk, {"label": label, "summary": payload.get("summary", ""), "data": payload.get("data", {})},
        task_id=payload.get("task_id"),
    )
    return approval


# ---------------------------------------------------------------------------
# Research / ads configuration
# ---------------------------------------------------------------------------


@router.get("/research/config")
async def research_config() -> dict[str, Any]:
    cfg = _db().get_setting("research.provider", {"provider": "none"}) or {"provider": "none"}
    vault = get_vault()
    return {
        "provider": cfg.get("provider", "none"),
        "base_url": cfg.get("base_url", ""),
        "has_key": bool(vault.get("research:api")),
        "providers": ["none", "searxng", "brave", "serper"],
        "note": "SearXNG nao exige chave; Brave e Serper exigem credencial propria.",
    }


@router.post("/research/config")
async def set_research_config(payload: dict[str, Any] = Body(...)) -> dict[str, Any]:
    provider = payload.get("provider", "none")
    if provider not in {"none", "searxng", "brave", "serper"}:
        raise HTTPException(400, "Provedor de pesquisa invalido")
    _db().set_setting("research.provider", {"provider": provider, "base_url": payload.get("base_url", "")})
    api_key = payload.get("api_key")
    if api_key:
        vault = get_vault()
        if not vault.available():
            raise HTTPException(503, "Cofre de credenciais indisponivel")
        vault.put("research:api", {"api_key": api_key})
    if provider == "none":
        get_vault().delete("research:api")
    _db().audit("user", "research.configure", provider, "granted", {"has_key": bool(api_key)})
    return await research_config()


@router.get("/ads/config")
async def ads_config() -> dict[str, Any]:
    cfg = _db().get_setting("ads.meta", {}) or {}
    return {
        "meta": {"ad_account_id": cfg.get("ad_account_id", ""), "page_id": cfg.get("page_id", ""),
                 "has_token": bool(get_vault().get("ads:meta"))},
        "budget_policy": get_ads().budget_policy(),
        "validation": "VALIDACAO REAL PENDENTE",
    }


@router.post("/ads/config")
async def set_ads_config(payload: dict[str, Any] = Body(...)) -> dict[str, Any]:
    cfg = {"ad_account_id": payload.get("ad_account_id", ""), "page_id": payload.get("page_id", "")}
    _db().set_setting("ads.meta", cfg)
    token = payload.get("access_token")
    if token:
        vault = get_vault()
        if not vault.available():
            raise HTTPException(503, "Cofre de credenciais indisponivel")
        vault.put("ads:meta", {"access_token": token})
    _db().audit("user", "ads.configure", cfg.get("ad_account_id", ""), "granted", {"has_token": bool(token)})
    return await ads_config()


@router.post("/ads/publish/{campaign_id}")
async def ads_publish(campaign_id: str, payload: dict[str, Any] = Body(default={})) -> dict[str, Any]:
    approval_id = payload.get("approval_id")
    if not approval_id:
        raise HTTPException(403, "Aprovacao com PIN obrigatoria")
    try:
        return await get_ads().publish_meta(campaign_id, approval_id)
    except (AdsError, PermissionError, KeyError) as exc:
        raise _error(exc)


# ---------------------------------------------------------------------------
# Mobile companion pairing (scoped, expiring tokens)
# ---------------------------------------------------------------------------


def _mobile_tokens() -> dict[str, Any]:
    return _db().get_state("mobile_tokens", {}) or {}


@router.post("/mobile/pair-code")
async def mobile_pair_code() -> dict[str, Any]:
    import secrets as pysecrets

    code = f"{pysecrets.randbelow(900000) + 100000}"
    expires = datetime.now(timezone.utc).timestamp() + 600
    codes = _db().get_state("mobile_pair_codes", {}) or {}
    now_ts = datetime.now(timezone.utc).timestamp()
    codes = {k: v for k, v in codes.items() if v.get("expires", 0) > now_ts}
    codes[code] = {"expires": expires, "created_at": now_iso()}
    _db().set_state("mobile_pair_codes", codes)
    host = _db().get_setting("mobile.public_url", "")
    return {
        "code": code,
        "expires_in_seconds": 600,
        "runtime_url": host or "Configure um tunel HTTPS (ex.: Tailscale Funnel) e informe em mobile.public_url",
        "instructions": "No iPhone, abra a PWA do JARVIS, informe a URL HTTPS e este codigo.",
    }


@router.post("/mobile/claim")
async def mobile_claim(payload: dict[str, Any] = Body(...)) -> dict[str, Any]:
    import secrets as pysecrets

    code = str(payload.get("code", "")).strip()
    db = _db()
    now_ts = datetime.now(timezone.utc).timestamp()
    # Brute-force guard: a 6-digit code is only safe with a small attempt budget.
    attempts = [ts for ts in (db.get_state("mobile_claim_attempts", []) or []) if now_ts - float(ts) < 60]
    if len(attempts) >= 10:
        raise HTTPException(429, "Muitas tentativas de pareamento; aguarde um minuto")
    attempts.append(now_ts)
    db.set_state("mobile_claim_attempts", attempts[-20:])
    codes = db.get_state("mobile_pair_codes", {}) or {}
    entry = codes.get(code)
    if not entry or entry.get("expires", 0) <= now_ts:
        raise HTTPException(403, "Codigo invalido ou expirado")
    codes.pop(code, None)
    _db().set_state("mobile_pair_codes", codes)
    token = "mob_" + pysecrets.token_urlsafe(40)
    tokens = _mobile_tokens()
    tokens[token] = {"device": str(payload.get("device_name", "iPhone"))[:80], "created_at": now_iso(),
                     "scopes": ["read", "chat", "approvals"]}
    _db().set_state("mobile_tokens", tokens)
    _db().audit("mobile", "mobile.pair", token[:8], "granted", {"device": tokens[token]["device"]})
    return {"token": token, "scopes": tokens[token]["scopes"], "device": tokens[token]["device"],
            "warning": "Guarde este token no iPhone. Ele nao sera exibido novamente."}


@router.get("/mobile/devices")
async def mobile_devices() -> dict[str, Any]:
    tokens = _mobile_tokens()
    return {"devices": [{"device": v["device"], "created_at": v["created_at"],
                          "prefix": k[:8], "masked": k[:8] + "…"} for k, v in tokens.items()]}


@router.delete("/mobile/devices/{prefix}")
async def revoke_mobile(prefix: str) -> dict[str, Any]:
    tokens = _mobile_tokens()
    kept = {k: v for k, v in tokens.items() if not k.startswith(prefix)}
    _db().set_state("mobile_tokens", kept)
    _db().audit("user", "mobile.revoke", prefix, "granted", {})
    return {"revoked": len(tokens) - len(kept)}


@router.get("/mobile/status")
async def mobile_status() -> dict[str, Any]:
    db = _db()
    return {
        "version": __version__,
        "kill_switch": get_permission_engine().kill_switch_active(),
        "tasks": db.query("SELECT status, COUNT(*) n FROM tasks GROUP BY status"),
        "today_revenue_note": "Consulte /api/sales/report para dados confirmados.",
    }


@router.get("/mobile/tasks")
async def mobile_tasks(limit: int = 20) -> dict[str, Any]:
    return {"tasks": get_engine().list(limit=min(limit, 50))}


@router.post("/mobile/chat")
async def mobile_chat(payload: ChatMessage) -> dict[str, Any]:
    return await get_chat().handle(payload.message, payload.conversation_id, autonomy_level=1, mode="production")


@router.get("/mobile/approvals")
async def mobile_approvals() -> dict[str, Any]:
    return {"approvals": get_approval_service().list("pending")}
