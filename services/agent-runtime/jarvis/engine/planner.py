"""Deterministic-first planner with an optional, strictly validated LLM planner.

The deterministic planner is not an LLM: it routes on explicit intents. When a model
is configured the router may propose a plan, but every step must reference a known
skill and pass parameter validation. Unknown skills are discarded, never executed.
"""
from __future__ import annotations

import json
import re
from typing import Any

from .skills import SKILLS

AGENT_BY_INTENT = {
    "files": "automation",
    "windows": "automation",
    "research": "research",
    "business": "strategy",
    "development": "programmer",
    "game": "game_developer",
    "cakto": "sales",
    "sales": "finance",
    "ads": "marketing",
    "memory": "orchestrator",
    "marketing": "marketing",
    "general": "orchestrator",
}


class Planner:
    def __init__(self) -> None:
        pass

    def plan(self, objective: str, autonomy_level: int = 1) -> dict[str, Any]:
        text = objective.strip()
        lower = text.lower()
        steps: list[dict[str, Any]] = []
        intent = "general"
        risks: list[str] = []
        assumptions: list[str] = []

        price_match = re.search(r"R\$\s*([\d\.]+(?:,\d{2})?)", text)
        price = None
        if price_match:
            raw = price_match.group(1).replace(".", "").replace(",", ".")
            try:
                price = float(raw)
            except ValueError:
                price = None
        target_match = re.search(r"([\d\.]+)\s*mil", lower)
        target = None
        if target_match:
            target = float(target_match.group(1).replace(".", "")) * 1000

        mentions_cakto = "cakto" in lower
        mentions_research = any(w in lower for w in ["pesquise", "pesquisar", "oportunidades", "tendências", "tendencias", "mercado"])
        mentions_business = any(w in lower for w in ["negócio", "negocio", "faturamento", "receita", "plano de negócio", "plano de negocio", "viabilidade"])
        mentions_ads = any(w in lower for w in ["anúncio", "anuncio", "campanha", "meta ads", "google ads", "tráfego pago", "trafego pago"])
        mentions_sales = any(w in lower for w in ["vendas", "faturei", "fatura", "pedidos", "receita confirmada"])
        mentions_game = any(w in lower for w in ["jogo", "godot", "corrida", "game"])
        mentions_dev = any(w in lower for w in ["crie um site", "criar um site", "aplicação", "aplicativo", "sistema", "software", "página de vendas", "pagina de vendas", "desenvolva"])
        mentions_files = any(w in lower for w in ["organize", "organizar", "arquivos", "downloads", "pasta"])
        mentions_notepad = any(w in lower for w in ["bloco de notas", "notepad"])
        mentions_memory = any(w in lower for w in ["lembre", "memória", "memoria", "anote", "preferência", "preferencia"])
        mentions_marketing = any(w in lower for w in ["conteúdo", "conteudo", "roteiro", "legenda", "copy", "post"])

        if mentions_notepad:
            intent = "windows"
            content = self._extract_text_after(text, ["escreva", "digite", "escrever"]) or "Lista de tarefas:\n- Revisar prioridades\n- Executar o proximo passo"
            steps.append(self._step("Abrir Bloco de Notas e digitar conteudo", "windows.notepad",
                                    {"text": content}, "Confirma janela aberta e texto digitado (Windows)."))
            risks.append("Automacao de teclado exige permissao explicita e foco na janela correta.")
        elif mentions_files:
            intent = "files"
            path = self._extract_path(text) or "organizar"
            steps.append(self._step("Organizar arquivos por categoria", "files.organize", {"path": path},
                                    "Confere pastas criadas e ausencia de exclusoes."))
            assumptions.append(f"Pasta alvo: {path} (dentro das raizes autorizadas). Arquivos nunca sao apagados.")
            risks.append("Movimentacao de arquivos e reversivel; revise o resumo antes de continuar.")
        elif mentions_cakto and any(w in lower for w in ["crie", "criar", "cadastre", "cadastrar", "prepare"]):
            intent = "cakto"
            name = self._extract_product_name(text)
            steps.append(self._step("Validar dados do produto", "noop", {"note": "validacao de nome, preco e pagina"},
                                    "Campos obrigatorios presentes."))
            steps.append(self._step("Criar produto e resolver checkout na Cakto", "cakto.create_product",
                                    {"name": name, "price": price, "type": "subscription" if "assinatura" in lower else "unique"},
                                    "Produto retornado pela API, checkout padrao e oferta identificados."))
            risks.append("Criacao real de produto exige credenciais e aprovacao com PIN. Nada e criado sem aprovacao.")
            steps.append(self._step("Verificar produto criado", "cakto.list_products", {"search": name},
                                    "Produto aparece na listagem autenticada."))
        elif mentions_cakto and any(w in lower for w in ["liste", "listar", "mostre", "produtos"]):
            intent = "cakto"
            steps.append(self._step("Listar produtos da conta Cakto", "cakto.list_products", {}, "Resposta autenticada da API."))
        elif mentions_ads:
            intent = "ads"
            steps.append(self._step("Preparar estrutura de campanha", "ads.prepare",
                                    {"provider": "meta", "daily_budget": 0, "monthly_limit": 0},
                                    "Rascunho criado; nenhum gasto realizado."))
            steps.append(self._step("Gerar variacoes de conteudo", "marketing.content", {"objective": text[:200]},
                                    "Variacoes textuais retornadas; imagens exigem provedor configurado."))
            assumptions.append("Orcamento inicial R$ 0,00. Publicacao exige conta conectada, limites aprovados e permissao ads.budget.")
            risks.append("Nao publicar sem revisar publico, politicas e rastreamento.")
        elif mentions_sales:
            intent = "sales"
            if "cakto" in lower:
                steps.append(self._step("Sincronizar pedidos da Cakto", "cakto.sync_orders", {},
                                        "Pedidos importados com deduplicacao."))
            steps.append(self._step("Consolidar vendas confirmadas", "sales.report", {"days": self._extract_days(lower)},
                                    "Somente status pagos entram como receita."))
            assumptions.append("Pix gerado nao e venda paga; pendencias sao reportadas separadamente.")
        elif mentions_game:
            intent = "game"
            steps.append(self._step("Criar projeto Godot e GDD", "gamestudio.build",
                                    {"name": self._extract_project_name(text, "JARVIS Racer"), "objective": text},
                                    "Arquivos do projeto existem; validacao depende do Godot instalado."))
            risks.append("Prototipo com primitivas; nao e um jogo AAA nem possui build validado sem Godot.")
        elif mentions_dev:
            kind = "inventory-system" if any(w in lower for w in ["estoque", "caixa", "inventário", "inventario"]) else "web-app"
            intent = "development"
            steps.append(self._step("Gerar projeto e testes", "development.build",
                                    {"kind": kind, "name": self._extract_project_name(text, "Projeto JARVIS"), "objective": text},
                                    "Arquivos escritos e pytest executado quando permitido."))
            risks.append("Build de instalador nao e gerado automaticamente; testes sao a evidencia disponivel.")
        elif mentions_research and (mentions_business or "oportunidade" in lower):
            intent = "research"
            steps.append(self._step("Pesquisar fontes publicas", "research.report",
                                    {"query": text[:300], "save": True}, "Fontes com URL e trecho; injection sinalizada."))
            steps.append(self._step("Calcular cenario comercial", "business.plan",
                                    {"price": price or 97, "target_monthly": target or 10000, "conversion_rate": 0.02},
                                    "Formulas e premissas explicitas."))
            assumptions.append("Nenhum dado de demanda foi inventado; o relatorio separa fontes de estimativas.")
        elif mentions_business:
            intent = "business"
            steps.append(self._step("Calcular economia unitaria e metas", "business.plan",
                                    {"price": price or 97, "target_monthly": target or 10000, "conversion_rate": 0.02},
                                    "Calculos conferiveis e premissas declaradas."))
            steps.append(self._step("Gerar esboco comercial", "marketing.content", {"objective": text[:200]},
                                    "Conteudo textual sem depoimentos ficticios."))
        elif mentions_memory:
            intent = "memory"
            steps.append(self._step("Salvar/consultar memoria", "memory.save",
                                    {"content": text if any(w in lower for w in ["lembre", "anote"]) else None,
                                     "query": None if any(w in lower for w in ["lembre", "anote"]) else text[:200],
                                     "kind": "preference"}, "Registro persistido e consultavel."))
        elif mentions_research:
            intent = "research"
            steps.append(self._step("Pesquisar e relatar", "research.report", {"query": text[:300], "save": True},
                                    "Relatorio com fontes e limitacoes."))
        elif mentions_marketing:
            intent = "marketing"
            steps.append(self._step("Criar conteudo comercial", "marketing.content", {"objective": text[:200]},
                                    "Variacoes textuais; imagens exigem ferramenta real."))
        else:
            intent = "general"
            steps.append(self._step("Responder com base no contexto disponivel", "general.answer", {"message": text},
                                    "Resposta marcada como nao fundamentada quando nao ha fontes."))

        if autonomy_level == 0 and any(SKILLS[s["skill"]].risk in {"high", "critical"} for s in steps):
            risks.append("Nivel 0: etapas de alto impacto serao bloqueadas pela politica de permissoes.")
        return {
            "intent": intent,
            "agent": AGENT_BY_INTENT.get(intent, "orchestrator"),
            "summary": self._summary(intent, text),
            "objective": text,
            "steps": steps,
            "risks": risks,
            "assumptions": assumptions,
            "approval_expected": any(SKILLS[s["skill"]].risk in {"high", "critical"} for s in steps),
            "planner": "deterministic-rules-v1",
            "production_ready": False,
            "notes": "Plano deterministico. Revise antes de autorizar etapas de alto impacto.",
        }

    async def plan_async(self, objective: str, autonomy_level: int = 1, task_id: str | None = None) -> dict[str, Any]:
        deterministic = self.plan(objective, autonomy_level)
        try:
            from ..llm.router import get_router

            schema = '{"intent":str,"agent":str,"summary":str,"steps":[{"title":str,"skill":str,"params":{},"verification":str}],"risks":[str],"assumptions":[str]}'
            available = "\n".join(f"- {name}: {spec.description} (risco {spec.risk})" for name, spec in SKILLS.items())
            parsed, result = await get_router().structured(
                "Monte um plano executavel em JSON para o objetivo abaixo usando SOMENTE estas skills:\n"
                f"{available}\nObjetivo: {objective}\nNivel de autonomia: {autonomy_level}\n"
                "Nao invente skills. Nao inclua credenciais. Maximo 6 etapas.",
                purpose="planning", schema_hint=schema, task_id=task_id,
            )
            if parsed and result.provider != "local-rules":
                steps = []
                for item in (parsed.get("steps") or [])[:6]:
                    skill = str(item.get("skill", ""))
                    params = item.get("params") if isinstance(item.get("params"), dict) else {}
                    if skill not in SKILLS:
                        continue
                    steps.append(self._step(str(item.get("title") or SKILLS[skill].description)[:200], skill, params,
                                            str(item.get("verification") or "Verificacao padrao")[:300]))
                if steps:
                    return {
                        "intent": str(parsed.get("intent") or deterministic["intent"]),
                        "agent": str(parsed.get("agent") or deterministic["agent"]),
                        "summary": str(parsed.get("summary") or deterministic["summary"])[:1000],
                        "objective": objective,
                        "steps": steps,
                        "risks": [str(r)[:300] for r in (parsed.get("risks") or [])][:10],
                        "assumptions": [str(a)[:300] for a in (parsed.get("assumptions") or [])][:10],
                        "approval_expected": any(SKILLS[s["skill"]].risk in {"high", "critical"} for s in steps),
                        "planner": f"llm:{result.provider}:{result.model}",
                        "production_ready": True,
                        "notes": "Plano proposto por modelo e validado contra skills registradas.",
                    }
        except Exception:  # noqa: BLE001 - planning always has a deterministic fallback
            pass
        return deterministic

    @staticmethod
    def _step(title: str, skill: str, params: dict[str, Any], verification: str) -> dict[str, Any]:
        return {
            "title": title,
            "skill": skill,
            "params": {k: v for k, v in params.items() if v is not None},
            "verification": verification,
            "risk": SKILLS[skill].risk if skill in SKILLS else "unknown",
        }

    @staticmethod
    def _summary(intent: str, text: str) -> str:
        return {
            "files": "Vou organizar arquivos de forma reversivel e relatar cada movimento.",
            "windows": "Vou abrir o Bloco de Notas e digitar o conteudo solicitado (Windows).",
            "research": "Vou pesquisar fontes publicas, registrar links e separar fatos de estimativas.",
            "business": "Vou calcular metas e economia unitaria com premissas explicitas.",
            "development": "Vou gerar um projeto real, executar testes e listar artefatos.",
            "game": "Vou gerar um prototipo Godot com GDD e validar o que for possivel.",
            "cakto": "Vou consultar a Cakto usando apenas endpoints documentados; criacao exige aprovacao.",
            "sales": "Vou consolidar apenas vendas pagas confirmadas e separar pendencias.",
            "ads": "Vou preparar a campanha sem gastar dinheiro; publicacao exige autorizacao.",
            "memory": "Vou registrar/consultar a informacao na memoria local.",
            "marketing": "Vou gerar variacoes de conteudo sem inventar provas.",
            "general": "Vou responder com o que estiver configurado, declarando limitacoes.",
        }.get(intent, "Vou executar o plano com verificacoes.")

    @staticmethod
    def _extract_text_after(text: str, markers: list[str]) -> str | None:
        for marker in markers:
            idx = text.lower().find(marker)
            if idx >= 0:
                return text[idx + len(marker):].strip(" :.-")[:2000]
        return None

    @staticmethod
    def _extract_path(text: str) -> str | None:
        quoted = re.search(r"[\"“']([^\"”']{2,200})[\"”']", text)
        if quoted:
            return quoted.group(1)
        match = re.search(r"(?:pasta|diret[oó]rio|folder)\s+([\w\-./\\ ]{2,80})", text, re.I)
        if match:
            return match.group(1).strip()
        match = re.search(r"(Downloads|Documentos|Desktop|Área de Trabalho)", text, re.I)
        return match.group(1) if match else None

    @staticmethod
    def _extract_days(lower: str) -> int:
        match = re.search(r"(\d+)\s*(?:dias|dias?|days)", lower)
        if match:
            return max(1, min(int(match.group(1)), 365))
        if "semana" in lower:
            return 7
        if "mês" in lower or "mes" in lower:
            return 30
        return 7

    @staticmethod
    def _extract_product_name(text: str) -> str | None:
        quoted = re.search(r"[\"“']([^\"”']{3,100})[\"”']", text)
        if quoted:
            return quoted.group(1)
        match = re.search(r"(?:curso|produto|ebook|e-book|treinamento)\s+(?:de\s+|do\s+|da\s+)?([\wÀ-ÿ\s]{3,60})", text, re.I)
        if match:
            return match.group(1).strip()
        return None

    @staticmethod
    def _extract_project_name(text: str, default: str) -> str:
        quoted = re.search(r"[\"“']([^\"”']{2,60})[\"”']", text)
        return quoted.group(1) if quoted else default


_planner: Planner | None = None


def get_planner() -> Planner:
    global _planner
    if _planner is None:
        _planner = Planner()
    return _planner
