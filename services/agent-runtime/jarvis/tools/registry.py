"""Tool registry: the only path from agent intent to observable effects."""
from __future__ import annotations

import inspect
import json
import time
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable

from ..db import get_db, now_iso
from ..security.approvals import get_approval_service
from ..security.permissions import get_permission_engine


class ToolError(RuntimeError):
    pass


class ApprovalRequired(ToolError):
    def __init__(self, approval: dict[str, Any], scope: str, risk: str):
        super().__init__(f"Aprovacao necessaria para {scope}")
        self.approval = approval
        self.scope = scope
        self.risk = risk


@dataclass
class ToolSpec:
    name: str
    description: str
    scope: str
    risk: str
    params: dict[str, str]
    handler: Callable[..., Awaitable[dict[str, Any]]]
    verify: Callable[..., Awaitable[dict[str, Any]]] | None = None
    categories: list[str] = field(default_factory=list)
    external_side_effect: bool = False

    def public(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "scope": self.scope,
            "risk": self.risk,
            "params": self.params,
            "categories": self.categories,
            "external_side_effect": self.external_side_effect,
        }


class ToolRegistry:
    def __init__(self) -> None:
        self._tools: dict[str, ToolSpec] = {}
        self.db = get_db()
        self.permissions = get_permission_engine()
        self.approvals = get_approval_service()

    def register(self, spec: ToolSpec) -> None:
        if spec.name in self._tools:
            raise ValueError(f"Ferramenta duplicada: {spec.name}")
        self._tools[spec.name] = spec

    def get(self, name: str) -> ToolSpec:
        if name not in self._tools:
            raise ToolError(f"Ferramenta inexistente: {name}")
        return self._tools[name]

    def list(self) -> list[dict[str, Any]]:
        return [t.public() for t in self._tools.values()]

    def available_for(self, level: int) -> list[str]:
        out = []
        for name, spec in self._tools.items():
            risk = spec.risk
            if level == 0 and spec.scope not in {"fs.read", "internet", "cakto.read", "ads.read"}:
                continue
            if risk in {"high", "critical"} and level < 2:
                continue
            out.append(name)
        return out

    async def execute(
        self,
        name: str,
        params: dict[str, Any],
        task: dict[str, Any] | None = None,
        step_id: str | None = None,
        approval_id: str | None = None,
    ) -> dict[str, Any]:
        spec = self.get(name)
        task = task or {}
        decision = self.permissions.require(spec.scope, params, task)
        self.db.audit(
            "agent",
            "tool.invoke",
            name,
            "allowed" if decision.allowed else "denied",
            {"scope": spec.scope, "risk": spec.risk, "reason": decision.reason, "task_id": task.get("id")},
        )
        if not decision.allowed:
            raise ToolError(f"Acesso negado: {decision.reason}")
        if decision.requires_approval:
            consumed = None
            if approval_id:
                consumed = self.approvals.consume(approval_id, name)
            if consumed is None:
                approval = self.approvals.request(
                    name,
                    spec.risk,
                    {"params": {k: v for k, v in params.items() if k != "approval_id"}, "task_id": task.get("id")},
                    task_id=task.get("id"),
                    step_id=step_id,
                )
                raise ApprovalRequired(approval, spec.scope, spec.risk)
        started = time.monotonic()
        result = await spec.handler(**params)
        elapsed = int((time.monotonic() - started) * 1000)
        verification: dict[str, Any] = {"status": "not_checked"}
        if spec.verify:
            try:
                verification = await spec.verify(**(params | {"_result": result}))
            except TypeError:
                verification = await spec.verify(**params)
            except Exception as exc:  # noqa: BLE001
                verification = {"status": "failed", "error": str(exc)}
        payload = {"ok": True, "result": result, "verification": verification, "elapsed_ms": elapsed}
        self.db.audit(
            "agent",
            "tool.result",
            name,
            "ok",
            {"elapsed_ms": elapsed, "verification": verification.get("status"), "task_id": task.get("id")},
        )
        return payload


_registry: ToolRegistry | None = None


def get_registry() -> ToolRegistry:
    global _registry
    if _registry is None:
        from . import builtin  # noqa: F401  (registers tools on import)

        _registry = builtin.build_registry()
    return _registry


def reset_registry() -> None:
    global _registry
    _registry = None


def tool(name: str, description: str, scope: str, risk: str, params: dict[str, str], categories: list[str] | None = None,
         external_side_effect: bool = False):
    """Decorator used by builtin tool modules."""
    def wrapper(fn: Callable[..., Awaitable[dict[str, Any]]]):
        fn.__tool_spec__ = {  # type: ignore[attr-defined]
            "name": name,
            "description": description,
            "scope": scope,
            "risk": risk,
            "params": params,
            "categories": categories or [],
            "external_side_effect": external_side_effect,
        }
        return fn

    return wrapper


def spec_from_fn(fn: Callable[..., Awaitable[dict[str, Any]]]) -> ToolSpec:
    meta = getattr(fn, "__tool_spec__", None)
    if not meta:
        raise ValueError(f"Funcao sem metadados de ferramenta: {fn}")
    signature = inspect.signature(fn)
    async def handler(**kwargs: Any) -> dict[str, Any]:
        allowed = {p for p in signature.parameters if p != "kwargs"}
        extra = set(kwargs) - allowed
        if extra:
            raise ToolError(f"Parametros desconhecidos: {sorted(extra)}")
        return await fn(**kwargs)

    return ToolSpec(handler=handler, **meta)
