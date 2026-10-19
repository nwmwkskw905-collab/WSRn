"""Conversational entry point. Routes commands to tasks and handles safety commands."""
from __future__ import annotations

import json
import re
from typing import Any

from ..db import get_db, new_id, now_iso
from ..security.permissions import get_permission_engine
from ..modules.sales import get_sales
from .planner import get_planner
from .tasks import get_engine


class ChatService:
    def __init__(self) -> None:
        self.db = get_db()
        self.engine = get_engine()
        self.planner = get_planner()
        self.permissions = get_permission_engine()

    def history(self, conversation_id: str = "default", limit: int = 100) -> list[dict[str, Any]]:
        rows = self.db.query(
            "SELECT * FROM messages WHERE conversation_id=? ORDER BY ts DESC LIMIT ?", (conversation_id, limit)
        )
        rows.reverse()
        for row in rows:
            try:
                row["meta"] = json.loads(row.pop("meta_json") or "{}")
            except json.JSONDecodeError:
                row["meta"] = {}
        return rows

    def add_message(self, conversation_id: str, role: str, content: str, meta: dict[str, Any] | None = None) -> dict[str, Any]:
        msg_id = new_id("msg_")
        self.db.execute(
            "INSERT INTO messages(id, conversation_id, ts, role, content, meta_json) VALUES (?,?,?,?,?,?)",
            (msg_id, conversation_id, now_iso(), role, content, json.dumps(meta or {}, ensure_ascii=False)),
        )
        return {"id": msg_id, "role": role, "content": content, "meta": meta or {}, "ts": now_iso()}

    async def handle(self, message: str, conversation_id: str = "default", autonomy_level: int = 1,
                     mode: str = "demo") -> dict[str, Any]:
        text = message.strip()
        self.add_message(conversation_id, "user", text)
        lower = text.lower()

        # Safety commands are intentionally handled before any model call.
        if re.search(r"\b(pare tudo|parar jarvis|pare todas as automa|emerg[eê]ncia|stop jarvis)\b", lower):
            result = self.engine.engage_kill_switch("Comando do usuario")
            reply = (
                f"Parada de emergencia ativada. {len(result['affected_tasks'])} tarefas suspensas. "
                "Novas acoes externas estao bloqueadas ate reativacao explicita."
            )
            return self._reply(conversation_id, reply, meta={"kill_switch": True, "affected": result["affected_tasks"]})
        if re.search(r"\b(reativar|retomar|pode voltar|desativar parada)\b", lower) and self.permissions.kill_switch_active():
            self.engine.release_kill_switch()
            return self._reply(conversation_id, "Parada de emergencia desativada. Nenhuma tarefa foi retomada automaticamente.")
        if re.search(r"\bcancele?\b", lower) and "tarefa" in lower:
            active = self.db.one(
                "SELECT id FROM tasks WHERE status IN ('running','planning','queued','awaiting_approval','paused') "
                "ORDER BY created_at DESC LIMIT 1"
            )
            if active:
                self.engine.cancel(active["id"], "cancelamento por voz/texto")
                return self._reply(conversation_id, f"Tarefa {active['id']} cancelada. Efeitos externos ja concluidos nao podem ser desfeitos.")
            return self._reply(conversation_id, "Nao ha tarefa ativa para cancelar.")
        if re.search(r"\b(continue|continuar)\b", lower) and ("tarefa" in lower or "projeto" in lower or "ontem" in lower):
            paused = self.db.one(
                "SELECT id, objective FROM tasks WHERE status IN ('paused','partially_completed') ORDER BY updated_at DESC LIMIT 1"
            )
            if paused:
                self.engine.resume(paused["id"])
                return self._reply(conversation_id, f"Retomei a tarefa {paused['id']}: {paused['objective'][:160]}")
            return self._reply(conversation_id, "Nao encontrei tarefa pausada ou parcial para continuar.")
        if re.search(r"\b(mostre|mostrar|liste)\b", lower) and ("executou" in lower or "fez hoje" in lower or "auditoria" in lower):
            events = self.db.query(
                "SELECT ts, action, resource, decision FROM audit_log WHERE ts >= date('now') ORDER BY id DESC LIMIT 30"
            )
            lines = [f"- {e['ts']} | {e['action']} | {e['resource'] or '-'} | {e['decision']}" for e in events] or ["- Nenhum evento hoje."]
            return self._reply(conversation_id, "Atividades registradas hoje:\n" + "\n".join(lines),
                               meta={"audit": events})
        if re.search(r"\bquanto (estamos vendendo|faturei|vendemos)\b", lower):
            report = get_sales().order_summary(7)
            if report["is_empty"]:
                reply = ("Nao ha pedidos sincronizados nos ultimos 7 dias, entao nao posso afirmar receita. "
                         "Conecte a Cakto e sincronize pedidos para consultar valores reais.")
            else:
                reply = (
                    f"Receita bruta confirmada nos ultimos 7 dias: R$ {report['gross_revenue_brl']:.2f} "
                    f"em {report['paid_orders']} pedidos pagos. Pendencias: {report['pending_orders']}. "
                    "Pix gerado nao entra como venda."
                )
            return self._reply(conversation_id, reply, meta={"sales_report": report})

        plan = self.planner.plan(text, autonomy_level)
        if plan["intent"] == "general":
            from ..llm.router import get_router

            internet = self.permissions.is_granted("internet")
            result = await get_router().complete(
                [{"role": "user", "content": text}], purpose="chat", privacy="normal" if internet else "high"
            )
            reply = result.text
            if result.provider == "local-rules":
                reply += (
                    "\n\nPara respostas de modelo, configure e autorize um provedor em Configuracoes > IA. "
                    "Posso executar tarefas locais (arquivos, projetos, relatorios) sem provedor externo."
                )
            meta = {"provider": result.provider, "model": result.model, "is_llm": result.provider != "local-rules"}
            return self._reply(conversation_id, reply, meta=meta)

        task = self.engine.create(text, autonomy_level=autonomy_level, mode=mode, auto_start=False)
        generated = await self.engine.plan(task["id"])
        reply_lines = [generated["summary"], ""]
        for idx, step in enumerate(generated["steps"], 1):
            reply_lines.append(f"{idx}. {step['title']} [{step['skill']}]")
        if generated.get("risks"):
            reply_lines += ["", "Riscos/limites:"] + [f"- {r}" for r in generated["risks"]]
        if generated.get("approval_expected"):
            reply_lines += ["", "Esta tarefa pode pausar para aprovacao com PIN antes de acoes de alto impacto."]
        reply_lines += ["", f"Tarefa {task['id']} criada. Iniciando execucao."]
        self.engine.schedule(task["id"])
        return self._reply(
            conversation_id,
            "\n".join(reply_lines),
            meta={"task_id": task["id"], "plan": generated, "planner": generated.get("planner")},
        )

    def _reply(self, conversation_id: str, content: str, meta: dict[str, Any] | None = None) -> dict[str, Any]:
        msg = self.add_message(conversation_id, "assistant", content, meta)
        return {"reply": content, "conversation_id": conversation_id, "message_id": msg["id"], "meta": meta or {}}


_service: ChatService | None = None


def get_chat() -> ChatService:
    global _service
    if _service is None:
        _service = ChatService()
    return _service
