"""Explicit, revocable capability grants.

No model output is trusted to decide access: tools call ``require()`` before doing
anything observable, and the engine consults persisted grants, path allowlists,
kill-switch state and autonomy level.
"""
from __future__ import annotations

import fnmatch
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from ..config import CONFIG
from ..db import get_db, now_iso

PERMISSION_DEFS: dict[str, dict[str, Any]] = {
    "fs.read": {"label": "Ler arquivos", "risk": "low", "category": "files"},
    "fs.write": {"label": "Criar e editar arquivos", "risk": "medium", "category": "files"},
    "fs.delete": {"label": "Mover para lixeira / excluir", "risk": "high", "category": "files"},
    "automation.input": {"label": "Controlar mouse e teclado", "risk": "high", "category": "windows"},
    "screen.capture": {"label": "Capturar tela", "risk": "medium", "category": "windows"},
    "microphone": {"label": "Usar microfone", "risk": "medium", "category": "audio"},
    "internet": {"label": "Acessar a internet", "risk": "low", "category": "network"},
    "shell.execute": {"label": "Executar comandos locais", "risk": "high", "category": "system"},
    "apps.install": {"label": "Instalar programas", "risk": "high", "category": "system"},
    "cakto.read": {"label": "Ler dados da Cakto", "risk": "medium", "category": "commerce"},
    "cakto.write": {"label": "Criar/alterar produtos na Cakto", "risk": "high", "category": "commerce"},
    "cakto.refund": {"label": "Aprovar reembolsos", "risk": "critical", "category": "commerce"},
    "ads.read": {"label": "Ler metricas de anuncios", "risk": "low", "category": "ads"},
    "ads.write": {"label": "Criar/alterar campanhas", "risk": "high", "category": "ads"},
    "ads.budget": {"label": "Usar orcamento publicitario", "risk": "critical", "category": "ads"},
    "publish.content": {"label": "Publicar conteudo", "risk": "high", "category": "content"},
    "messaging.send": {"label": "Enviar mensagens", "risk": "high", "category": "content"},
    "remote.access": {"label": "Acesso remoto", "risk": "high", "category": "network"},
    "data.delete": {"label": "Excluir dados permanentemente", "risk": "critical", "category": "files"},
}

HIGH_RISK = {"high", "critical"}


@dataclass
class Decision:
    allowed: bool
    requires_approval: bool
    risk: str
    reason: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "allowed": self.allowed,
            "requires_approval": self.requires_approval,
            "risk": self.risk,
            "reason": self.reason,
        }


class PermissionEngine:
    def __init__(self) -> None:
        self.db = get_db()

    # -- bootstrap ---------------------------------------------------------
    def seed_defaults(self) -> None:
        for scope, meta in PERMISSION_DEFS.items():
            exists = self.db.one("SELECT scope FROM permissions WHERE scope=?", (scope,))
            if not exists:
                self.db.execute(
                    "INSERT INTO permissions(scope, granted, config_json, updated_at) VALUES (?,0,'{}',?)",
                    (scope, now_iso()),
                )

    def _row(self, scope: str) -> dict[str, Any] | None:
        return self.db.one("SELECT * FROM permissions WHERE scope=?", (scope,))

    def grant(self, scope: str, granted: bool, config: dict[str, Any] | None = None, expires_in_hours: int | None = None) -> dict[str, Any]:
        if scope not in PERMISSION_DEFS:
            raise ValueError(f"Escopo desconhecido: {scope}")
        config = config or {}
        expires_at = None
        if expires_in_hours:
            expires_at = (datetime.now(timezone.utc) + timedelta(hours=expires_in_hours)).isoformat()
        ts = now_iso()
        self.db.execute(
            """INSERT INTO permissions(scope, granted, config_json, granted_at, expires_at, revoked_at, updated_at)
               VALUES (?,?,?,?,?,?,?)
               ON CONFLICT(scope) DO UPDATE SET granted=excluded.granted, config_json=excluded.config_json,
                 granted_at=excluded.granted_at, expires_at=excluded.expires_at, revoked_at=excluded.revoked_at,
                 updated_at=excluded.updated_at""",
            (scope, 1 if granted else 0, __import__("json").dumps(config), ts if granted else None,
             expires_at, None if granted else ts, ts),
        )
        self.db.audit("user", "permission.update", scope, "granted" if granted else "revoked", config)
        row = self._row(scope) or {}
        return self._public(row)

    def revoke_all(self) -> None:
        ts = now_iso()
        self.db.execute("UPDATE permissions SET granted=0, revoked_at=?, updated_at=?", (ts, ts))
        self.db.audit("user", "permission.revoke_all", "*", "granted", {})

    def list_grants(self) -> list[dict[str, Any]]:
        self.seed_defaults()
        return [self._public(r) for r in self.db.query("SELECT * FROM permissions ORDER BY scope")]

    def is_granted(self, scope: str) -> bool:
        row = self._row(scope)
        if not row or not row["granted"]:
            return False
        if row["expires_at"]:
            try:
                exp = datetime.fromisoformat(row["expires_at"])
                if exp.tzinfo is None:
                    exp = exp.replace(tzinfo=timezone.utc)
                if datetime.now(timezone.utc) > exp:
                    return False
            except ValueError:
                return False
        return True

    def _pre_authorized(self, scope: str) -> bool:
        """An explicit, revocable, per-scope authorization recorded by the user.

        Only levels 3 and 4 honour it, and only for `high` risk. `critical` scopes
        always demand a PIN, so no configuration can silently authorize a refund or
        an ad budget increase.
        """
        row = self._row(scope) or {}
        import json

        try:
            cfg = json.loads(row.get("config_json") or "{}")
        except json.JSONDecodeError:
            return False
        if not cfg.get("pre_authorize"):
            return False
        expires = cfg.get("pre_authorize_until")
        if not expires:
            return True
        try:
            until = datetime.fromisoformat(str(expires))
            if until.tzinfo is None:
                until = until.replace(tzinfo=timezone.utc)
            return datetime.now(timezone.utc) <= until
        except ValueError:
            return False

    def kill_switch_active(self) -> bool:
        return bool(self.db.get_state("kill_switch", False))

    def engage_kill_switch(self, reason: str) -> None:
        self.db.set_state("kill_switch", True)
        self.db.set_state("kill_switch_at", now_iso())
        self.db.set_state("kill_switch_reason", reason)
        self.db.audit("user" if reason != "internal" else "system", "kill_switch", "*", "engaged", {"reason": reason})

    def release_kill_switch(self) -> None:
        self.db.set_state("kill_switch", False)
        self.db.set_state("kill_switch_at", None)
        self.db.audit("user", "kill_switch", "*", "released", {})

    # -- policy ------------------------------------------------------------
    def require(self, scope: str, context: dict[str, Any] | None = None, task: dict[str, Any] | None = None) -> Decision:
        context = context or {}
        if scope not in PERMISSION_DEFS:
            return Decision(False, False, "high", "Escopo invalido; bloqueado por padrao")
        if self.kill_switch_active() and scope not in {"fs.read", "internet", "cakto.read", "ads.read"}:
            return Decision(False, False, "high", "Parada de emergencia ativa: novas acoes bloqueadas")
        if not self.is_granted(scope):
            return Decision(False, True, PERMISSION_DEFS[scope]["risk"], f"Permissao {scope} nao concedida")

        path_error = self._check_path(scope, context)
        if path_error:
            return Decision(False, False, "high", path_error)

        command_error = self._check_command(scope, context)
        if command_error:
            return Decision(False, False, "high", command_error)

        try:
            level = max(0, min(4, int((task or {}).get("autonomy_level", 2))))
        except (TypeError, ValueError):
            level = 0
        risk = PERMISSION_DEFS[scope]["risk"]
        if level == 0 and scope not in {"fs.read", "internet", "cakto.read", "ads.read"}:
            return Decision(False, False, risk, "Nivel de autonomia 0 permite apenas observacao")
        if risk == "critical":
            # Reembolsos, gasto publicitario e exclusao permanente nunca ficam sem PIN.
            return Decision(True, True, risk, "Acao critica exige aprovacao com PIN em qualquer nivel")
        if risk == "high":
            if level < 2:
                return Decision(True, True, risk, "Acao de alto impacto exige nivel 2+ e aprovacao")
            if level >= 3 and self._pre_authorized(scope):
                return Decision(True, False, risk, f"Nivel {level}: alto impacto coberto por pre-autorizacao registrada")
            return Decision(True, True, risk, "Acao de alto impacto exige aprovacao explicita")
        if level == 1 and scope in {"fs.write", "microphone", "screen.capture"}:
            return Decision(True, False, risk, "Permitido no nivel de assistencia (sem efeito externo critico)")
        return Decision(True, False, risk, "Permissao concedida")

    def _check_path(self, scope: str, context: dict[str, Any]) -> str | None:
        if not scope.startswith("fs."):
            return None
        raw = context.get("path")
        if raw is None:
            return None
        row = self._row(scope) or {}
        import json

        try:
            cfg = json.loads(row.get("config_json") or "{}")
        except json.JSONDecodeError:
            cfg = {}
        roots = cfg.get("roots") or [str(CONFIG.workspace_dir)]
        try:
            candidate = Path(str(raw)).expanduser()
            if not candidate.is_absolute():
                candidate = CONFIG.workspace_dir / candidate
            candidate = candidate.resolve()
        except (OSError, RuntimeError):
            return "Caminho invalido"
        for root in roots:
            try:
                root_path = Path(root).expanduser().resolve()
            except (OSError, RuntimeError):
                continue
            if candidate == root_path or root_path in candidate.parents:
                if cfg.get("allow_globs"):
                    rel = str(candidate.relative_to(root_path))
                    if not any(fnmatch.fnmatch(rel, g) for g in cfg["allow_globs"]):
                        return f"Arquivo fora dos padroes permitidos: {rel}"
                return None
        return f"Caminho fora das pastas autorizadas: {candidate}"

    def _check_command(self, scope: str, context: dict[str, Any]) -> str | None:
        if scope != "shell.execute":
            return None
        command = str(context.get("command", "")).strip()
        if not command:
            return "Comando vazio"
        import json

        row = self._row(scope) or {}
        try:
            cfg = json.loads(row.get("config_json") or "{}")
        except json.JSONDecodeError:
            cfg = {}
        allow = cfg.get("allow_commands") or ["git", "npm", "python", "python3", "node", "npx", "pytest"]
        denied_fragments = ["rm -rf /", "format ", "del /f /s /q c:\\", "shutdown", "reg delete", "diskpart"]
        lowered = command.lower()
        if any(frag in lowered for frag in denied_fragments):
            return "Comando bloqueado por politica de seguranca"
        first = command.split()[0].split("/")[-1].split("\\")[-1]
        if first not in allow:
            return f"Comando nao autorizado: {first}"
        if any(ch in command for ch in ["&&", "||", ";", "|", ">", "<", "`", "$("]):
            return "Encadeamento de comandos nao permitido"
        return None

    @staticmethod
    def _public(row: dict[str, Any]) -> dict[str, Any]:
        import json

        try:
            config = json.loads(row.get("config_json") or "{}")
        except json.JSONDecodeError:
            config = {}
        return {
            "scope": row["scope"],
            "label": PERMISSION_DEFS.get(row["scope"], {}).get("label", row["scope"]),
            "risk": PERMISSION_DEFS.get(row["scope"], {}).get("risk", "unknown"),
            "granted": bool(row.get("granted")),
            "config": config,
            "granted_at": row.get("granted_at"),
            "expires_at": row.get("expires_at"),
        }


_engine: PermissionEngine | None = None


def get_permission_engine() -> PermissionEngine:
    global _engine
    if _engine is None:
        _engine = PermissionEngine()
        _engine.seed_defaults()
    return _engine


def now_epoch() -> int:
    return int(time.time())
