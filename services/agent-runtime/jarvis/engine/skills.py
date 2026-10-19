"""Skills: high-level operations composed from permissioned tools.

A skill declares the capability it needs. The executor checks the permission engine
before calling it; high-risk skills require a persisted human approval with PIN.
"""
from __future__ import annotations

import hashlib
import json
import platform
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Awaitable, Callable

from ..config import CONFIG
from ..db import get_db, now_iso
from ..modules.business import get_business
from ..modules.cakto import CaktoError, get_cakto
from ..modules.development import get_development
from ..modules.gamestudio import get_gamestudio
from ..modules.memory import get_memory
from ..modules.sales import get_sales
from ..modules.ads import AdsError, get_ads
from ..security.permissions import get_permission_engine
from ..tools.registry import ApprovalRequired, ToolError, get_registry


@dataclass
class SkillSpec:
    name: str
    description: str
    scope: str
    risk: str
    handler: Callable[..., Awaitable[dict[str, Any]]]
    external_side_effect: bool = False
    requires_tools: tuple[str, ...] = ()

    def public(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "scope": self.scope,
            "risk": self.risk,
            "external_side_effect": self.external_side_effect,
            "requires_tools": list(self.requires_tools),
        }


class Skills:
    def __init__(self) -> None:
        self.db = get_db()
        self.permissions = get_permission_engine()
        self.tools = get_registry()

    async def execute(self, name: str, params: dict[str, Any], task: dict[str, Any] | None = None,
                      approval_id: str | None = None, step_id: str | None = None) -> dict[str, Any]:
        task = task or {}
        spec = SKILLS.get(name)
        if not spec:
            raise ToolError(f"Skill desconhecida: {name}")
        decision = self.permissions.require(spec.scope, params, task)
        if not decision.allowed:
            raise ToolError(f"Acesso negado para {spec.scope}: {decision.reason}")
        if self.db.get_state("kill_switch", False):
            raise ToolError("Parada de emergencia ativa")
        approved = False
        if decision.requires_approval:
            if approval_id:
                from ..security.approvals import get_approval_service

                get_approval_service().consume(approval_id, name)
                approved = True
            else:
                from ..security.approvals import get_approval_service

                approval = get_approval_service().request(
                    name, spec.risk, {"params": sanitize(params)}, task_id=task.get("id"), step_id=step_id
                )
                raise ApprovalRequired(approval, spec.scope, spec.risk)
        if spec.external_side_effect:
            idem = idempotency_key(name, params)
            cached = self.db.get_state(f"skill-result:{idem}")
            if cached:
                return {"cached": True, "result": cached}
        result = await spec.handler(params, task, approved=approved)
        result.setdefault("verification", {"status": "reported_by_skill"})
        if spec.external_side_effect and result.get("ok", True):
            self.db.set_state(f"skill-result:{idempotency_key(name, params)}", redact_for_state(result))
        self.db.audit("agent", "skill.execute", name, "ok", {"task_id": task.get("id"), "approved": approved})
        return result

    def list(self) -> list[dict[str, Any]]:
        return [s.public() for s in SKILLS.values()]


def sanitize(params: dict[str, Any]) -> dict[str, Any]:
    banned = {"client_secret", "api_key", "token", "password", "pin"}
    return {k: ("[REDACTED]" if k.lower() in banned else v) for k, v in params.items()}


def redact_for_state(value: Any) -> Any:
    from ..security.secrets import redact

    return redact(value)


def idempotency_key(name: str, params: dict[str, Any]) -> str:
    payload = json.dumps({"name": name, "params": params}, sort_keys=True, default=str)
    return hashlib.sha256(payload.encode()).hexdigest()[:32]


# ---------------------------------------------------------------------------
# Skill implementations
# ---------------------------------------------------------------------------

CATEGORIES = {
    "imagens": {".jpg", ".jpeg", ".png", ".gif", ".webp", ".svg", ".bmp", ".tiff", ".heic"},
    "documentos": {".pdf", ".doc", ".docx", ".txt", ".md", ".odt", ".rtf", ".xls", ".xlsx", ".csv", ".ppt", ".pptx"},
    "audio": {".mp3", ".wav", ".flac", ".ogg", ".m4a", ".aac"},
    "video": {".mp4", ".mkv", ".mov", ".avi", ".webm"},
    "compactados": {".zip", ".rar", ".7z", ".tar", ".gz"},
    "instaladores": {".exe", ".msi", ".msix", ".appx"},
    "codigo": {".py", ".js", ".ts", ".tsx", ".jsx", ".html", ".css", ".json", ".yml", ".yaml", ".sh", ".ps1"},
}


async def skill_files_organize(params: dict[str, Any], task: dict[str, Any], approved: bool = False) -> dict[str, Any]:
    db = get_db()
    raw_path = params.get("path") or "sandbox/organizar"
    target = Path(raw_path).expanduser()
    if not target.is_absolute():
        target = CONFIG.workspace_dir / raw_path
    target = target.resolve()
    if not target.exists():
        target.mkdir(parents=True, exist_ok=True)
    files = [p for p in target.iterdir() if p.is_file() and not p.name.startswith(".")]
    moved: list[dict[str, str]] = []
    duplicates: list[list[str]] = []
    by_hash: dict[str, list[str]] = {}
    errors: list[str] = []
    for file in files:
        digest = hashlib.sha256(file.read_bytes()).hexdigest() if file.stat().st_size < 50_000_000 else ""
        if digest:
            by_hash.setdefault(digest, []).append(str(file))
    duplicates = [v for v in by_hash.values() if len(v) > 1]
    for file in files:
        ext = file.suffix.lower()
        category = next((name for name, exts in CATEGORIES.items() if ext in exts), "outros")
        destination_dir = target / category
        destination_dir.mkdir(exist_ok=True)
        destination = destination_dir / file.name
        if destination.exists():
            destination = destination_dir / f"{file.stem}-{int(file.stat().st_mtime)}{file.suffix}"
        try:
            file.rename(destination)
            moved.append({"from": str(file), "to": str(destination), "category": category})
        except OSError as exc:
            errors.append(f"{file.name}: {exc}")
    db.audit("agent", "files.organize", str(target), "granted", {"moved": len(moved)})
    return {
        "path": str(target),
        "files_found": len(files),
        "moved": moved,
        "duplicates_by_hash": duplicates,
        "errors": errors,
        "reversible": True,
        "deleted_anything": False,
        "summary": f"{len(moved)} arquivos organizados em {target.name}; nenhum arquivo apagado.",
        "verification": {
            "status": "passed" if not errors and len(moved) == len(files) else "partial",
            "destination_folders": sorted({m["category"] for m in moved}),
            "everything_moved": len(moved) == len(files),
        },
    }


async def skill_windows_notepad(params: dict[str, Any], task: dict[str, Any], approved: bool = False) -> dict[str, Any]:
    if platform.system() != "Windows":
        return {
            "ok": False,
            "supported": False,
            "reason": "Automacao do Windows nao pode ser validada nesta plataforma (Linux).",
            "status": "PLATAFORMA_NAO_SUPORTADA",
            "requested_text": params.get("text", "")[:500],
        }
    text = params.get("text", "")
    registry = get_registry()
    opened = await registry.execute("windows.open_app", {"app": "notepad"}, task, approval_id=params.get("open_approval_id"))
    typed = await registry.execute("windows.type_text", {"title": "Bloco de Notas", "text": text}, task,
                                  approval_id=params.get("type_approval_id"))
    return {"ok": True, "opened": opened["result"], "typed": typed["result"], "verified_by": "pywinauto window focus",
            "verification": {"status": "passed"}}


async def skill_research_report(params: dict[str, Any], task: dict[str, Any], approved: bool = False) -> dict[str, Any]:
    query = params.get("query", task.get("objective", ""))
    registry = get_registry()
    urls = params.get("urls") or []
    sources: list[dict[str, Any]] = []
    if urls:
        for url in urls[:6]:
            result = await registry.execute("research.fetch_url", {"url": url}, task)
            data = result["result"]
            sources.append({
                "url": data["url"], "title": url, "chars": data["length"],
                "excerpt": data["text"][:1200], "injection_risk": data["injection"]["risk"],
            })
    else:
        search = await registry.execute("research.search", {"query": query, "limit": params.get("limit", 5)}, task)
        for item in search["result"]["results"]:
            try:
                page = await registry.execute("research.fetch_url", {"url": item["url"]}, task)
                sources.append({
                    "url": item["url"], "title": item.get("title"), "snippet": item.get("snippet"),
                    "excerpt": page["result"]["text"][:1200],
                    "injection_risk": page["result"]["injection"]["risk"],
                })
            except ToolError as exc:
                sources.append({"url": item["url"], "title": item.get("title"), "error": str(exc)})
    if not sources:
        raise ToolError("Pesquisa nao retornou fontes. Configure um provedor de busca ou informe URLs.")
    report = _build_research_report(query, sources)
    out_path = None
    if params.get("save"):
        out_dir = CONFIG.workspace_dir / "reports"
        out_dir.mkdir(parents=True, exist_ok=True)
        slug = re.sub(r"[^a-z0-9]+", "-", query.lower())[:50].strip("-") or "pesquisa"
        out_path = out_dir / f"{slug}.md"
        out_path.write_text(report["markdown"], encoding="utf-8")
        report["saved_to"] = str(out_path)
    report["verification"] = {"status": "passed", "sources_fetched": len(sources)}
    return report


def _build_research_report(query: str, sources: list[dict[str, Any]]) -> dict[str, Any]:
    credible_markers = ["gov.br", "ibge", "edu", "org", "docs.", "github.com", "wikipedia"]
    lines = [
        f"# Relatorio de pesquisa: {query}",
        "",
        f"Gerado em {now_iso()} pelo modulo de pesquisa do JARVIS.",
        "",
        "## Metodologia",
        "- Consulta a fontes publicas acessiveis no momento da execucao.",
        "- Conteudo externo tratado como evidencia, com deteccao de prompt injection.",
        "- Nenhum dado de mercado foi inventado; ausencias sao declaradas.",
        "",
        "## Fontes",
    ]
    for idx, src in enumerate(sources, 1):
        marker = "alta" if any(m in (src.get("url") or "") for m in credible_markers) else "nao classificada"
        lines.append(f"### {idx}. {src.get('title') or src['url']}")
        lines.append(f"- URL: {src['url']}")
        lines.append(f"- Credibilidade automatica: {marker} (heuristica por dominio, nao auditoria)")
        if src.get("error"):
            lines.append(f"- Falha ao acessar: {src['error']}")
        else:
            lines.append(f"- Trecho: {(src.get('excerpt') or '')[:600].strip()}")
            if src.get("injection_risk") in {"medium", "high"}:
                lines.append(f"- ALERTA: possivel prompt injection ({src['injection_risk']}); trecho neutralizado no raciocinio.")
        lines.append("")
    lines += [
        "## Limitacoes",
        "- Resultados dependem do provedor de busca configurado e da disponibilidade dos sites.",
        "- Nao foram validados dados privados, pagos ou autenticados.",
        "- Numeros de mercado exigem cruzamento com relatorios oficiais e data de referencia.",
    ]
    return {
        "query": query,
        "sources": sources,
        "source_count": len(sources),
        "markdown": "\n".join(lines),
        "data_quality": "fontes publicas; nenhuma estimativa inventada",
    }


async def skill_business_plan(params: dict[str, Any], task: dict[str, Any], approved: bool = False) -> dict[str, Any]:
    price = float(params.get("price", 97))
    target = float(params.get("target_monthly", 10000))
    conversion = float(params.get("conversion_rate", 0.02))
    business_id = params.get("business_id")
    service = get_business()
    plan = service.goal_plan(target, price, conversion)
    econ = service.unit_economics(price=price, target_monthly_revenue=target, conversion_rate=conversion)
    narrative = None
    try:
        from ..llm.router import get_router

        result = await get_router().complete(
            [{"role": "user", "content": (
                "Explique em portugues, em no maximo 12 linhas, este plano comercial calculado. "
                "Nao invente dados de mercado. Diferencie fato/estimativa. Dados: " + json.dumps(plan["scenarios"])
            )}],
            purpose="business", task_id=task.get("id"),
        )
        if result.provider != "local-rules":
            narrative = {"text": result.text, "provider": result.provider, "model": result.model}
    except Exception as exc:  # noqa: BLE001
        narrative = {"error": str(exc)[:300], "provider": "unavailable"}
    return {
        "business_id": business_id,
        "plan": plan,
        "unit_economics": econ,
        "narrative": narrative,
        "narrative_status": "gerado por modelo" if narrative and narrative.get("text") else
        "nao gerado: configure um provedor de IA autorizado (opcional)",
        "verification": {"status": "calculated", "formulas_documented": True},
    }


async def skill_development_build(params: dict[str, Any], task: dict[str, Any], approved: bool = False) -> dict[str, Any]:
    kind = params.get("kind", "web-app")
    name = params.get("name") or "Projeto JARVIS"
    objective = params.get("objective") or task.get("objective", "")
    run_tests = bool(params.get("run_tests", True)) and get_permission_engine().is_granted("shell.execute")
    result = get_development().create(kind, name, objective, run_tests=run_tests)
    if not run_tests:
        result.setdefault("limitations", []).append("Testes nao executados: permissao shell.execute ausente.")
        result["status"] = "created_tests_skipped"
    return result


async def skill_gamestudio_build(params: dict[str, Any], task: dict[str, Any], approved: bool = False) -> dict[str, Any]:
    name = params.get("name") or "JARVIS Racer"
    objective = params.get("objective") or task.get("objective", "")
    return get_gamestudio().create_racer(name, objective, run_tests=params.get("run_tests", True))


async def skill_cakto_list_products(params: dict[str, Any], task: dict[str, Any], approved: bool = False) -> dict[str, Any]:
    data = await get_cakto().list_products(search=params.get("search"))
    data["verification"] = {"status": "queried" if data.get("mode") == "producao" else "demo_data",
                            "count": data.get("count", 0)}
    return data


def _parse_product_from_text(text: str) -> dict[str, Any]:
    price_match = re.search(r"R\$\s*([\d\.]+(?:,\d{2})?)", text)
    price = None
    if price_match:
        raw = price_match.group(1).replace(".", "").replace(",", ".")
        try:
            price = float(raw)
        except ValueError:
            price = None
    quoted = re.search(r"[Cc]urso\s+(?:de\s+)?([\w\s]{3,60})", text)
    name = quoted.group(1).strip() if quoted else None
    return {
        "price": price,
        "name": name,
        "type": "subscription" if re.search(r"assinatura|recorrente|mensal", text, re.I) else "unique",
    }


async def skill_cakto_create_product(params: dict[str, Any], task: dict[str, Any], approved: bool = False) -> dict[str, Any]:
    parsed = _parse_product_from_text(task.get("objective", ""))
    name = params.get("name") or parsed["name"]
    price = params.get("price") or parsed["price"]
    if not name or not price:
        raise ToolError(
            "Dados insuficientes para criar o produto. Informe nome e preco (ex.: 'curso de fotografia por R$ 97'). "
            "Nada foi criado."
        )
    sales_page = params.get("sales_page") or f"https://example.com/{re.sub(r'[^a-z0-9]+', '-', name.lower()).strip('-')}"
    if not params.get("sales_page"):
        raise ToolError("Informe a URL real da pagina de vendas antes de criar o produto na Cakto.")
    draft = {
        "name": name[:150],
        "description": params.get("description") or f"{name} - produto digital. Descricao a revisar antes da publicacao.",
        "price": float(price),
        "type": params.get("type") or parsed["type"],
        "sales_page": sales_page,
        "business_id": params.get("business_id"),
    }
    result = await get_cakto().create_product(draft, approved=approved)
    result["verification"] = {
        "status": "created_and_resolved" if result.get("checkout") else "created_checkout_unresolved",
        "checkout_url": (result.get("product") or {}).get("checkout_url"),
    }
    return result


async def skill_cakto_sync(params: dict[str, Any], task: dict[str, Any], approved: bool = False) -> dict[str, Any]:
    result = await get_cakto().sync_orders(days=int(params.get("days", 30)))
    result["verification"] = {"status": "synced", "inserted": result["inserted"]}
    return result


async def skill_sales_report(params: dict[str, Any], task: dict[str, Any], approved: bool = False) -> dict[str, Any]:
    days = int(params.get("days", 7))
    report = get_sales().order_summary(days)
    note = None
    if report["is_empty"]:
        note = "Nenhum pedido sincronizado no periodo. Conecte a Cakto e sincronize antes de interpretar como 'zero vendas'."
    report["interpretation"] = note or (
        f"{report['paid_orders']} pedidos pagos somam R$ {report['gross_revenue_brl']:.2f} no periodo. "
        "Pix gerado e pedidos pendentes nao entram como receita."
    )
    report["verification"] = {"status": "queried", "rows": report["orders_considered"]}
    return report


async def skill_ads_prepare(params: dict[str, Any], task: dict[str, Any], approved: bool = False) -> dict[str, Any]:
    result = get_ads().prepare(
        objective=params.get("objective") or task.get("objective", ""),
        provider=params.get("provider", "meta"),
        daily_budget=float(params.get("daily_budget", 0)),
        monthly_limit=float(params.get("monthly_limit", 0)),
        audience=params.get("audience"),
        product_id=params.get("product_id"),
        business_id=params.get("business_id"),
    )
    result["spend_brl"] = 0.0
    result["verification"] = {"status": "draft_created", "no_external_call": True}
    return result


async def skill_memory_save(params: dict[str, Any], task: dict[str, Any], approved: bool = False) -> dict[str, Any]:
    memory = get_memory()
    if params.get("query"):
        return {"results": memory.search(params["query"]), "operation": "search"}
    if not params.get("content"):
        raise ToolError("Informe o conteudo da memoria")
    item = memory.add(params["content"], kind=params.get("kind", "preference"), key=params.get("key"),
                      tags=params.get("tags") or [], source="task")
    return {"memory": item, "verification": {"status": "stored"}}


async def skill_marketing_content(params: dict[str, Any], task: dict[str, Any], approved: bool = False) -> dict[str, Any]:
    objective = params.get("objective") or task.get("objective", "")
    product = params.get("product") or "produto digital"
    variants = [
        {"channel": "Instagram Reels", "hook": f"Se voce quer {objective[:80]}, evite este erro.",
         "body": f"Apresente o problema, mostre o metodo de {product} e um CTA claro.", "cta": "Saiba mais"},
        {"channel": "Email", "subject": f"Uma forma mais clara de {objective[:60]}",
         "body": "Prova real, objecao principal e convite para conhecer a oferta.", "cta": "Ver detalhes"},
        {"channel": "Pagina de vendas", "headline": f"{product}: o que voce precisa saber antes de decidir",
         "body": "Problema, mecanismo, provas verificaveis, oferta, garantia e FAQ.", "cta": "Comecar agora"},
    ]
    return {
        "variants": variants,
        "claim_policy": "Nao usar depoimentos ou resultados inventados; provas devem ser reais e autorizadas.",
        "verification": {"status": "generated_text_only", "files_created": 0},
    }


async def skill_general_answer(params: dict[str, Any], task: dict[str, Any], approved: bool = False) -> dict[str, Any]:
    from ..llm.router import get_router

    message = params.get("message") or task.get("objective", "")
    internet = get_permission_engine().is_granted("internet")
    result = await get_router().complete(
        [{"role": "user", "content": message}],
        purpose="chat",
        task_id=task.get("id"),
        privacy="normal" if internet else "high",
    )
    return {
        "answer": result.text,
        "provider": result.provider,
        "model": result.model,
        "is_llm": result.provider not in {"local-rules"},
        "fallback_reason": (result.raw or {}).get("reason"),
        "verification": {"status": "answered", "grounded": False},
    }


async def skill_noop(params: dict[str, Any], task: dict[str, Any], approved: bool = False) -> dict[str, Any]:
    return {"note": params.get("note", ""), "verification": {"status": "not_applicable"}}


SKILLS: dict[str, SkillSpec] = {
    "files.organize": SkillSpec("files.organize", "Organiza arquivos por categoria sem apagar nada.",
                                "fs.write", "medium", skill_files_organize, requires_tools=("fs.list", "fs.move")),
    "windows.notepad": SkillSpec("windows.notepad", "Abre o Bloco de Notas e digita uma lista.",
                                 "automation.input", "high", skill_windows_notepad, external_side_effect=True),
    "research.report": SkillSpec("research.report", "Pesquisa fontes publicas e gera relatorio com links.",
                                 "internet", "low", skill_research_report),
    "business.plan": SkillSpec("business.plan", "Calcula plano comercial e economia unitaria.",
                               "fs.read", "low", skill_business_plan),
    "development.build": SkillSpec("development.build", "Gera projeto real e executa testes.",
                                   "fs.write", "medium", skill_development_build, external_side_effect=False),
    "gamestudio.build": SkillSpec("gamestudio.build", "Cria projeto Godot e documenta validacao.",
                                  "fs.write", "medium", skill_gamestudio_build),
    "cakto.list_products": SkillSpec("cakto.list_products", "Lista produtos da conta Cakto.",
                                     "cakto.read", "medium", skill_cakto_list_products),
    "cakto.create_product": SkillSpec("cakto.create_product", "Cria produto e resolve checkout na Cakto.",
                                      "cakto.write", "high", skill_cakto_create_product, external_side_effect=True),
    "cakto.sync_orders": SkillSpec("cakto.sync_orders", "Sincroniza pedidos confirmados da Cakto.",
                                   "cakto.read", "medium", skill_cakto_sync),
    "sales.report": SkillSpec("sales.report", "Consolida vendas confirmadas e pendencias.",
                              "fs.read", "low", skill_sales_report),
    "ads.prepare": SkillSpec("ads.prepare", "Prepara campanha sem gastar dinheiro.",
                             "ads.read", "low", skill_ads_prepare),
    "memory.save": SkillSpec("memory.save", "Armazena ou consulta memoria autorizada.",
                             "fs.write", "low", skill_memory_save),
    "marketing.content": SkillSpec("marketing.content", "Cria variacoes de conteudo comercial.",
                                   "fs.write", "low", skill_marketing_content),
    "general.answer": SkillSpec("general.answer", "Resposta conversacional via provedor autorizado.",
                                "fs.read", "low", skill_general_answer),
    "noop": SkillSpec("noop", "Etapa sem efeito usada para checkpoints.", "fs.read", "low", skill_noop),
}


_skills: Skills | None = None


def get_skills() -> Skills:
    global _skills
    if _skills is None:
        _skills = Skills()
    return _skills


def reset_skills() -> None:
    global _skills
    _skills = None
