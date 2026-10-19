"""Durable task engine: planning, execution, retries, checkpoints, cancellation.

State is persisted after every transition so a crash or restart can be recovered
without duplicating completed steps. External side effects additionally use
idempotency keys in the skills layer.
"""
from __future__ import annotations

import asyncio
import json
import traceback
from datetime import datetime, timezone
from typing import Any

from ..config import CONFIG
from ..db import get_db, new_id, now_iso
from ..security.permissions import get_permission_engine
from ..tools.registry import ApprovalRequired, ToolError
from .planner import get_planner
from .skills import get_skills

ACTIVE_STATES = {"planning", "running", "awaiting_approval", "paused", "queued"}


class TaskEngine:
    def __init__(self) -> None:
        self.db = get_db()
        self.skills = get_skills()
        self.planner = get_planner()
        self.permissions = get_permission_engine()
        self._semaphore = asyncio.Semaphore(max(1, CONFIG.max_concurrent_tasks))
        self._running: dict[str, asyncio.Task] = {}
        self._lock = asyncio.Lock()

    # -- creation ----------------------------------------------------------
    def create(self, objective: str, autonomy_level: int = 1, mode: str = "demo",
               business_id: str | None = None, idempotency_key: str | None = None,
               auto_start: bool = True) -> dict[str, Any]:
        objective = objective.strip()
        try:
            autonomy_level = max(0, min(4, int(autonomy_level)))
        except (TypeError, ValueError):
            autonomy_level = 1
        if idempotency_key:
            existing = self.db.one("SELECT * FROM tasks WHERE idempotency_key=?", (idempotency_key,))
            if existing:
                return self.get(existing["id"])
        task_id = new_id("tsk_")
        ts = now_iso()
        self.db.execute(
            """INSERT INTO tasks(id, objective, status, autonomy_level, mode, business_id, idempotency_key,
                 created_at, updated_at) VALUES (?,?,?,?,?,?,?,?,?)""",
            (task_id, objective, "queued", autonomy_level, mode, business_id, idempotency_key, ts, ts),
        )
        self._event(task_id, "task.created", {"objective": objective[:500], "autonomy_level": autonomy_level, "mode": mode})
        if auto_start:
            self.schedule(task_id)
        return self.get(task_id)

    def get(self, task_id: str) -> dict[str, Any]:
        row = self.db.one("SELECT * FROM tasks WHERE id=?", (task_id,))
        if not row:
            raise KeyError("Tarefa nao encontrada")
        row["plan"] = _load(row.pop("plan_json", None), {})
        row["result"] = _load(row.pop("result_json", None), {})
        row["verification"] = _load(row.pop("verification_json", None), {})
        row["checkpoint"] = _load(row.pop("checkpoint_json", None), {})
        row["steps"] = self.steps(task_id)
        row["events"] = self.events(task_id, limit=100)
        return row

    def steps(self, task_id: str) -> list[dict[str, Any]]:
        rows = self.db.query("SELECT * FROM task_steps WHERE task_id=? ORDER BY idx", (task_id,))
        for row in rows:
            row["input"] = _load(row.pop("input_json", None), {})
            row["output"] = _load(row.pop("output_json", None), {})
            row["verification"] = _load(row.pop("verification_json", None), {})
        return rows

    def events(self, task_id: str | None = None, limit: int = 200, after_id: int = 0) -> list[dict[str, Any]]:
        if task_id:
            rows = self.db.query(
                "SELECT * FROM task_events WHERE task_id=? AND id>? ORDER BY id DESC LIMIT ?", (task_id, after_id, limit)
            )
        else:
            rows = self.db.query("SELECT * FROM task_events WHERE id>? ORDER BY id DESC LIMIT ?", (after_id, limit))
        rows.reverse()
        for row in rows:
            row["payload"] = _load(row.pop("payload_json", None), {})
        return rows

    def list(self, status: str | None = None, limit: int = 100) -> list[dict[str, Any]]:
        if status:
            rows = self.db.query("SELECT * FROM tasks WHERE status=? ORDER BY created_at DESC LIMIT ?", (status, limit))
        else:
            rows = self.db.query("SELECT * FROM tasks ORDER BY created_at DESC LIMIT ?", (limit,))
        for row in rows:
            row["plan"] = _load(row.pop("plan_json", None), {})
            row["result"] = _load(row.pop("result_json", None), {})
            row["step_count"] = row.pop("tool_calls", 0)
        return rows

    # -- planning ----------------------------------------------------------
    async def plan(self, task_id: str) -> dict[str, Any]:
        task = self.db.one("SELECT * FROM tasks WHERE id=?", (task_id,))
        if not task:
            raise KeyError("Tarefa nao encontrada")
        self._update(task_id, status="planning")
        self._event(task_id, "task.planning", {})
        plan = await self.planner.plan_async(task["objective"], task["autonomy_level"], task_id=task_id)
        self._update(task_id, plan_json=json.dumps(plan, ensure_ascii=False), progress=0.05)
        self.db.execute("DELETE FROM task_steps WHERE task_id=?", (task_id,))
        for idx, step in enumerate(plan["steps"]):
            self.db.execute(
                """INSERT INTO task_steps(id, task_id, idx, title, description, tool, status, max_attempts, dependencies, input_json)
                   VALUES (?,?,?,?,?,?,?,?,?,?)""".replace("dependencies", "depends_on"),
                (
                    new_id("stp_"), task_id, idx, step["title"][:300], step.get("verification", "")[:500],
                    step["skill"], "pending", 2, json.dumps([idx - 1] if idx > 0 else []),
                    json.dumps(step.get("params", {}), ensure_ascii=False),
                ),
            )
        self._event(task_id, "task.planned", {"planner": plan.get("planner"), "steps": len(plan["steps"])})
        return plan

    # -- execution ---------------------------------------------------------
    def schedule(self, task_id: str) -> None:
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            # Called from sync context (e.g. startup); defer until loop exists.
            return
        if task_id in self._running and not self._running[task_id].done():
            return
        self._running[task_id] = loop.create_task(self._run_guarded(task_id))

    async def _run_guarded(self, task_id: str) -> None:
        async with self._semaphore:
            await self.run(task_id)

    async def run(self, task_id: str) -> dict[str, Any]:
        task = self.db.one("SELECT * FROM tasks WHERE id=?", (task_id,))
        if not task:
            raise KeyError("Tarefa nao encontrada")
        if task["status"] in {"completed", "cancelled", "failed", "partially_completed"}:
            return self.get(task_id)
        try:
            if not task.get("plan_json"):
                await self.plan(task_id)
            task = self.db.one("SELECT * FROM tasks WHERE id=?", (task_id,))
            self._update(task_id, status="running", started_at=task.get("started_at") or now_iso())
            self._event(task_id, "task.started", {})
            steps = self.db.query("SELECT * FROM task_steps WHERE task_id=? ORDER BY idx", (task_id,))
            signatures: list[str] = []
            for step in steps:
                if step["status"] in {"completed", "skipped"}:
                    continue
                fresh_task = self.db.one("SELECT * FROM tasks WHERE id=?", (task_id,))
                if fresh_task["cancel_requested"]:
                    self._finish(task_id, "cancelled", error="Cancelada pelo usuario")
                    return self.get(task_id)
                if fresh_task["pause_requested"]:
                    self._update(task_id, status="paused", pause_requested=0)
                    self._event(task_id, "task.paused", {"step": step["idx"]})
                    return self.get(task_id)
                if self.permissions.kill_switch_active():
                    self._update(task_id, status="paused")
                    self._event(task_id, "task.stopped_kill_switch", {"step": step["idx"]})
                    return self.get(task_id)
                if fresh_task["tool_calls"] >= CONFIG.max_tool_calls_per_task:
                    self._finish(task_id, "partially_completed", error="Limite de chamadas de ferramenta atingido")
                    return self.get(task_id)
                signature = f"{step['idx']}:{step['tool']}:{step['input_json']}"
                signatures.append(signature)
                if signatures.count(signature) > 2:
                    self._finish(task_id, "failed", error="Loop detectado: etapa repetida sem progresso")
                    return self.get(task_id)
                result = await self._execute_step(task, step)
                if result == "awaiting_approval":
                    self._update(task_id, status="awaiting_approval")
                    self._event(task_id, "task.awaiting_approval", {"step": step["idx"]})
                    return self.get(task_id)
                if result != "completed":
                    # A failed step stops dependent work; prior results are preserved.
                    self._finish(task_id, "partially_completed", error=f"Etapa {step['idx'] + 1} falhou")
                    return self.get(task_id)
                progress = round((step["idx"] + 1) / max(1, len(steps)), 2)
                self._update(task_id, progress=progress)
            self._finish(task_id, "completed")
            return self.get(task_id)
        except Exception as exc:  # noqa: BLE001 - persist unexpected failures
            self.db.audit("engine", "task.exception", task_id, "error", {"error": str(exc)[:500]})
            self._finish(task_id, "failed", error=f"{type(exc).__name__}: {exc}"[:1000])
            self._event(task_id, "task.error", {"error": str(exc)[:1000], "trace": traceback.format_exc()[-2000:]})
            return self.get(task_id)
        finally:
            self._running.pop(task_id, None)

    async def _execute_step(self, task: dict[str, Any], step: dict[str, Any]) -> str:
        task_id = task["id"]
        params = _load(step["input_json"], {})
        self.db.execute(
            "UPDATE task_steps SET status='running', started_at=?, attempts=attempts+1 WHERE id=?",
            (now_iso(), step["id"]),
        )
        self._event(task_id, "step.started", {"idx": step["idx"], "skill": step["tool"], "title": step["title"]})
        try:
            approval_id = params.pop("approval_id", None)
            result = await self.skills.execute(
                step["tool"], params, task=task, step_id=step["id"], approval_id=approval_id
            )
            verification = result.get("verification", {})
            status = "passed" if verification.get("status") not in {"failed", "partial"} else "partial"
            self.db.execute(
                "UPDATE task_steps SET status='completed', output_json=?, verification_json=?, finished_at=?, error=NULL WHERE id=?",
                (json.dumps(result, ensure_ascii=False, default=str), json.dumps(verification, default=str), now_iso(), step["id"]),
            )
            self.db.execute("UPDATE tasks SET tool_calls=tool_calls+1, updated_at=? WHERE id=?", (now_iso(), task_id))
            self._event(task_id, "step.completed", {"idx": step["idx"], "skill": step["tool"], "verification": status})
            return "completed"
        except ApprovalRequired as approval:
            self.db.execute(
                "UPDATE task_steps SET status='awaiting_approval', output_json=? WHERE id=?",
                (json.dumps({"approval_id": approval.approval["id"]}), step["id"]),
            )
            self._event(task_id, "step.approval_required", {
                "idx": step["idx"], "skill": step["tool"], "approval_id": approval.approval["id"], "risk": approval.risk,
            })
            return "awaiting_approval"
        except (ToolError, Exception) as exc:  # noqa: BLE001
            attempts = step["attempts"] + 1
            retryable = not isinstance(exc, PermissionError) and attempts < step["max_attempts"]
            self.db.execute(
                "UPDATE task_steps SET status=?, error=?, attempts=? WHERE id=?",
                ("pending" if retryable else "failed", str(exc)[:1000], attempts, step["id"]),
            )
            self._event(task_id, "step.failed", {"idx": step["idx"], "skill": step["tool"], "error": str(exc)[:500], "will_retry": retryable})
            if retryable:
                await asyncio.sleep(min(2 * attempts, 5))
                fresh = self.db.one("SELECT * FROM task_steps WHERE id=?", (step["id"],))
                return await self._execute_step(task, fresh)
            return "failed"

    # -- control -----------------------------------------------------------
    def cancel(self, task_id: str, reason: str = "solicitado pelo usuario") -> dict[str, Any]:
        row = self.db.one("SELECT * FROM tasks WHERE id=?", (task_id,))
        if not row:
            raise KeyError("Tarefa nao encontrada")
        self.db.execute("UPDATE tasks SET cancel_requested=1, updated_at=? WHERE id=?", (now_iso(), task_id))
        if row["status"] in {"queued", "planning", "awaiting_approval", "paused"}:
            self._finish(task_id, "cancelled", error=reason)
        self._event(task_id, "task.cancel_requested", {"reason": reason})
        self.db.audit("user", "task.cancel", task_id, "granted", {"reason": reason})
        return self.get(task_id)

    def pause(self, task_id: str) -> dict[str, Any]:
        self.db.execute("UPDATE tasks SET pause_requested=1, updated_at=? WHERE id=?", (now_iso(), task_id))
        if self.db.one("SELECT status FROM tasks WHERE id=?", (task_id,))["status"] in {"queued", "planning"}:
            self._update(task_id, status="paused", pause_requested=0)
        self._event(task_id, "task.pause_requested", {})
        return self.get(task_id)

    def resume(self, task_id: str) -> dict[str, Any]:
        row = self.db.one("SELECT * FROM tasks WHERE id=?", (task_id,))
        if not row:
            raise KeyError("Tarefa nao encontrada")
        if self.permissions.kill_switch_active():
            raise PermissionError("Desative a parada de emergencia antes de retomar")
        self.db.execute(
            "UPDATE tasks SET pause_requested=0, cancel_requested=0, status='queued', updated_at=? WHERE id=?",
            (now_iso(), task_id),
        )
        self._event(task_id, "task.resumed", {})
        self.schedule(task_id)
        return self.get(task_id)

    def resume_after_approval(self, task_id: str, approval_id: str) -> dict[str, Any]:
        step = self.db.one(
            "SELECT * FROM task_steps WHERE task_id=? AND status='awaiting_approval' ORDER BY idx LIMIT 1", (task_id,)
        )
        if step:
            try:
                parsed = _load(step["output_json"], {})
            except Exception:  # noqa: BLE001
                parsed = {}
            params = _load(step["input_json"], {})
            params["approval_id"] = approval_id
            self.db.execute(
                "UPDATE task_steps SET input_json=?, status='pending' WHERE id=?",
                (json.dumps(params), step["id"]),
            )
        self.db.execute("UPDATE tasks SET status='queued', updated_at=? WHERE id=?", (now_iso(), task_id))
        self.schedule(task_id)
        return self.get(task_id)

    def engage_kill_switch(self, reason: str = "PARAR JARVIS") -> dict[str, Any]:
        self.permissions.engage_kill_switch(reason)
        cancelled = []
        for row in self.db.query("SELECT id FROM tasks WHERE status IN ('running','planning','queued','awaiting_approval')"):
            self.db.execute(
                "UPDATE tasks SET cancel_requested=1, status='paused', updated_at=? WHERE id=?", (now_iso(), row["id"])
            )
            self._event(row["id"], "task.stopped_kill_switch", {"reason": reason})
            cancelled.append(row["id"])
        return {"kill_switch": True, "affected_tasks": cancelled, "reason": reason}

    def release_kill_switch(self) -> dict[str, Any]:
        self.permissions.release_kill_switch()
        return {"kill_switch": False}

    # -- recovery ----------------------------------------------------------
    def recover_on_startup(self) -> dict[str, Any]:
        recovered = []
        for row in self.db.query(
            "SELECT id, status FROM tasks WHERE status IN ('running','planning','queued','awaiting_approval')"
        ):
            self.db.execute(
                "UPDATE tasks SET status='paused', updated_at=?, error=? WHERE id=?",
                (now_iso(), "Recuperada apos reinicio; retome para continuar de onde parou", row["id"]),
            )
            self.db.execute(
                "UPDATE task_steps SET status='pending', started_at=NULL WHERE task_id=? AND status='running'", (row["id"],)
            )
            self._event(row["id"], "task.recovered", {"previous_status": row["status"]})
            recovered.append(row["id"])
        return {"recovered": recovered, "count": len(recovered)}

    # -- helpers -----------------------------------------------------------
    def _finish(self, task_id: str, status: str, error: str | None = None) -> None:
        row = self.db.one("SELECT * FROM tasks WHERE id=?", (task_id,))
        if not row:
            return
        steps = self.db.query("SELECT status, verification_json FROM task_steps WHERE task_id=? ORDER BY idx", (task_id,))
        completed = sum(1 for s in steps if s["status"] == "completed")
        verification = {
            "steps_total": len(steps),
            "steps_completed": completed,
            "verified_steps": sum(1 for s in steps if s["status"] == "completed" and s.get("verification_json")),
            "status": status,
            "finished_at": now_iso(),
        }
        # Fetch richer step data for the result payload.
        full_steps = self.db.query("SELECT idx, title, status, verification_json, output_json, error FROM task_steps WHERE task_id=? ORDER BY idx", (task_id,))
        result = {
            "summary": self._result_summary(status, completed, len(full_steps)),
            "steps": [
                {
                    "idx": s["idx"], "title": s["title"], "status": s["status"],
                    "verification": _load(s["verification_json"], {}),
                    "error": s["error"],
                }
                for s in full_steps
            ],
        }
        self.db.execute(
            "UPDATE tasks SET status=?, error=?, result_json=?, verification_json=?, checkpoint_json=?, finished_at=?, updated_at=?, progress=? WHERE id=?",
            (
                status, error, json.dumps(result, ensure_ascii=False, default=str),
                json.dumps(verification, default=str),
                json.dumps({"last_completed_idx": max([s["idx"] for s in full_steps if s["status"] == "completed"], default=-1)}),
                now_iso(), now_iso(), 1.0 if status == "completed" else round(completed / max(1, len(full_steps)), 2),
                task_id,
            ),
        )
        self._event(task_id, f"task.{status}", {"error": error, "steps_completed": completed})
        self.db.audit("engine", "task.finish", task_id, status, {"steps_completed": completed, "error": error})

    @staticmethod
    def _result_summary(status: str, completed: int, total: int) -> str:
        mapping = {
            "completed": f"Tarefa concluida: {completed}/{total} etapas com verificacao registrada.",
            "partially_completed": f"Tarefa parcialmente concluida: {completed}/{total} etapas. Veja falhas e pendencias.",
            "failed": f"Tarefa falhou apos {completed}/{total} etapas. Consulte o erro registrado.",
            "cancelled": f"Tarefa cancelada apos {completed}/{total} etapas.",
        }
        return mapping.get(status, status)

    def _update(self, task_id: str, **fields: Any) -> None:
        if not fields:
            return
        fields["updated_at"] = now_iso()
        sets = ", ".join(f"{k}=?" for k in fields)
        self.db.execute(f"UPDATE tasks SET {sets} WHERE id=?", (*fields.values(), task_id))

    def _event(self, task_id: str, kind: str, payload: dict[str, Any]) -> None:
        self.db.execute(
            "INSERT INTO task_events(task_id, ts, kind, payload_json) VALUES (?,?,?,?)",
            (task_id, now_iso(), kind, json.dumps(payload, ensure_ascii=False, default=str)),
        )


def _load(raw: str | None, default: Any) -> Any:
    if not raw:
        return default
    try:
        return json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return default


_engine: TaskEngine | None = None


def get_engine() -> TaskEngine:
    global _engine
    if _engine is None:
        _engine = TaskEngine()
    return _engine


def reset_engine() -> None:
    global _engine
    _engine = None
