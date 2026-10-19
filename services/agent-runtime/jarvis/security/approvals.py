"""Human approval workflow.

High-impact actions never execute on model output alone. The UI asks for a local
PIN; voice confirmation is explicitly not sufficient.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import secrets as pysecrets
from datetime import datetime, timedelta, timezone
from typing import Any

from ..db import get_db, new_id, now_iso

PBKDF2_ITERATIONS = 210_000


class ApprovalService:
    def __init__(self) -> None:
        self.db = get_db()

    # -- PIN ---------------------------------------------------------------
    def pin_configured(self) -> bool:
        return bool(self.db.get_state("pin_hash"))

    def set_pin(self, pin: str, current_pin: str | None = None) -> None:
        if self.pin_configured():
            if not current_pin or not self.verify_pin(current_pin):
                raise PermissionError("PIN atual invalido")
        if not pin.isdigit() or len(pin) < 6:
            raise ValueError("PIN deve ter ao menos 6 digitos")
        salt = pysecrets.token_hex(16)
        digest = hashlib.pbkdf2_hmac("sha256", pin.encode(), salt.encode(), PBKDF2_ITERATIONS).hex()
        self.db.set_state("pin_hash", {"salt": salt, "digest": digest, "iterations": PBKDF2_ITERATIONS})
        self.db.audit("user", "pin.setup", "local", "granted", {})
        self.db.set_setting("high_risk_pin_enabled", True)

    def verify_pin(self, pin: str | None) -> bool:
        if not pin:
            return False
        state = self.db.get_state("pin_hash") or {}
        if not state.get("salt"):
            return False
        digest = hashlib.pbkdf2_hmac(
            "sha256", pin.encode(), state["salt"].encode(), int(state.get("iterations", PBKDF2_ITERATIONS))
        ).hex()
        return hmac.compare_digest(digest, state.get("digest", ""))

    # -- requests ----------------------------------------------------------
    def request(
        self,
        action: str,
        risk: str,
        payload: dict[str, Any] | None = None,
        task_id: str | None = None,
        step_id: str | None = None,
    ) -> dict[str, Any]:
        approval_id = new_id("apr_")
        pin_required = risk in {"high", "critical"}
        expires = (datetime.now(timezone.utc) + timedelta(hours=24)).isoformat()
        payload = dict(payload or {})
        payload["_expires_at"] = expires
        self.db.execute(
            """INSERT INTO approvals(id, ts, task_id, step_id, action, risk, payload_json, status, pin_required)
               VALUES (?,?,?,?,?,?,?,?,?)""",
            (approval_id, now_iso(), task_id, step_id, action, risk, json.dumps(payload), "pending", 1 if pin_required else 0),
        )
        self.db.audit("agent", "approval.request", action, "pending", {"approval_id": approval_id, "risk": risk, "task_id": task_id})
        return self.get(approval_id)

    def get(self, approval_id: str) -> dict[str, Any]:
        row = self.db.one("SELECT * FROM approvals WHERE id=?", (approval_id,))
        if not row:
            raise KeyError("Aprovacao nao encontrada")
        return self._public(row)

    def list(self, status: str | None = None) -> list[dict[str, Any]]:
        if status:
            rows = self.db.query("SELECT * FROM approvals WHERE status=? ORDER BY ts DESC", (status,))
        else:
            rows = self.db.query("SELECT * FROM approvals ORDER BY ts DESC")
        return [self._public(r) for r in rows]

    def resolve(self, approval_id: str, approve: bool, pin: str | None, note: str | None = None) -> dict[str, Any]:
        row = self.db.one("SELECT * FROM approvals WHERE id=?", (approval_id,))
        if not row:
            raise KeyError("Aprovacao nao encontrada")
        if row["status"] != "pending":
            raise ValueError(f"Aprovacao ja resolvida: {row['status']}")
        payload = json.loads(row["payload_json"] or "{}")
        expires = payload.get("_expires_at")
        if expires:
            try:
                if datetime.now(timezone.utc) > datetime.fromisoformat(expires):
                    self.db.execute(
                        "UPDATE approvals SET status='expired', resolved_at=?, resolution_note=? WHERE id=?",
                        (now_iso(), "expirada", approval_id),
                    )
                    raise ValueError("Aprovacao expirada")
            except ValueError as exc:
                if "expirada" in str(exc):
                    raise
        if approve and row["pin_required"]:
            if not self.pin_configured():
                raise PermissionError("Configure um PIN local antes de aprovar acoes sensiveis")
            if not self.verify_pin(pin):
                self.db.audit("user", "approval.resolve", row["action"], "denied", {"approval_id": approval_id, "reason": "pin_invalido"})
                raise PermissionError("PIN invalido")
        status = "approved" if approve else "rejected"
        self.db.execute(
            "UPDATE approvals SET status=?, resolved_at=?, resolution_note=? WHERE id=?",
            (status, now_iso(), note, approval_id),
        )
        self.db.audit("user", "approval.resolve", row["action"], status, {"approval_id": approval_id})
        return self.get(approval_id)

    def consume(self, approval_id: str, action: str) -> dict[str, Any]:
        """Validate that an approval covers this action, then mark it used."""
        row = self.get(approval_id)
        if row["status"] != "approved":
            raise PermissionError(f"Aprovacao nao esta aprovada: {row['status']}")
        if row["action"] != action:
            raise PermissionError("Aprovacao nao corresponde a acao solicitada")
        payload = row["payload"]
        expires = payload.get("_expires_at")
        if expires and datetime.now(timezone.utc) > datetime.fromisoformat(expires):
            raise PermissionError("Aprovacao expirada")
        self.db.execute("UPDATE approvals SET status='consumed' WHERE id=?", (approval_id,))
        self.db.audit("system", "approval.consume", action, "granted", {"approval_id": approval_id})
        return row

    @staticmethod
    def _public(row: dict[str, Any]) -> dict[str, Any]:
        try:
            payload = json.loads(row.get("payload_json") or "{}")
        except json.JSONDecodeError:
            payload = {}
        payload.pop("_expires_at", None)
        return {
            "id": row["id"],
            "created_at": row["ts"],
            "task_id": row.get("task_id"),
            "step_id": row.get("step_id"),
            "action": row["action"],
            "risk": row["risk"],
            "summary": payload.get("summary") or row["action"],
            "payload": payload,
            "status": row["status"],
            "pin_required": bool(row.get("pin_required")),
            "resolved_at": row.get("resolved_at"),
            "note": row.get("resolution_note"),
        }


_service: ApprovalService | None = None


def get_approval_service() -> ApprovalService:
    global _service
    if _service is None:
        _service = ApprovalService()
    return _service
