"""Credential storage and log redaction.

Windows uses DPAPI (per-user, tied to the login). Other platforms use AES-GCM with
a 0600 key file. If neither is available the vault refuses to store secrets in
production mode instead of pretending to be secure.
"""
from __future__ import annotations

import base64
import ctypes
import json
import os
import re
import sys
from ctypes import wintypes
from typing import Any

from ..config import CONFIG
from ..db import get_db, now_iso

try:  # pragma: no cover - availability depends on the target machine
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    _HAVE_AESGCM = True
except Exception:  # pragma: no cover
    AESGCM = None  # type: ignore
    _HAVE_AESGCM = False


REDACTION_PATTERNS = [
    re.compile(r"(?i)(authorization\s*:\s*bearer\s+)[A-Za-z0-9._\-]+"),
    re.compile(r"(?i)(client_secret[\"']?\s*[:=]\s*[\"']?)[A-Za-z0-9._\-]{6,}"),
    re.compile(r"(?i)(api[_-]?key[\"']?\s*[:=]\s*[\"']?)[A-Za-z0-9._\-]{8,}"),
    re.compile(r"\bsk-[A-Za-z0-9_\-]{12,}"),
    re.compile(r"\beyJ[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{5,}"),
]


def redact(value: Any) -> Any:
    """Recursively redact credentials from data before logging or prompts."""
    if isinstance(value, str):
        out = value
        for pattern in REDACTION_PATTERNS:
            out = pattern.sub(lambda m: (m.group(1) if m.groups() else "") + "[REDACTED]", out)
        return out
    if isinstance(value, dict):
        clean: dict[str, Any] = {}
        for k, v in value.items():
            if re.search(r"(secret|token|password|authorization|api_key|apikey|pin)", str(k), re.I):
                clean[k] = "[REDACTED]"
            else:
                clean[k] = redact(v)
        return clean
    if isinstance(value, list):
        return [redact(v) for v in value]
    return value


def _dpapi_encrypt(data: bytes) -> bytes:
    class DATA_BLOB(ctypes.Structure):
        _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_char))]

    def blob(payload: bytes) -> DATA_BLOB:
        buf = ctypes.create_string_buffer(payload, len(payload))
        return DATA_BLOB(len(payload), ctypes.cast(buf, ctypes.POINTER(ctypes.c_char)))

    crypt32 = ctypes.windll.crypt32  # type: ignore[attr-defined]
    kernel32 = ctypes.windll.kernel32  # type: ignore[attr-defined]
    input_blob = blob(data)
    output_blob = DATA_BLOB()
    ok = crypt32.CryptProtectData(
        ctypes.byref(input_blob), "JARVIS", None, None, None, 0, ctypes.byref(output_blob)
    )
    if not ok:
        raise OSError("Falha DPAPI ao cifrar")
    try:
        return ctypes.string_at(output_blob.pbData, output_blob.cbData)
    finally:
        kernel32.LocalFree(output_blob.pbData)


def _dpapi_decrypt(data: bytes) -> bytes:
    class DATA_BLOB(ctypes.Structure):
        _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_char))]

    def blob(payload: bytes) -> DATA_BLOB:
        buf = ctypes.create_string_buffer(payload, len(payload))
        return DATA_BLOB(len(payload), ctypes.cast(buf, ctypes.POINTER(ctypes.c_char)))

    crypt32 = ctypes.windll.crypt32  # type: ignore[attr-defined]
    kernel32 = ctypes.windll.kernel32  # type: ignore[attr-defined]
    input_blob = blob(data)
    output_blob = DATA_BLOB()
    ok = crypt32.CryptUnprotectData(
        ctypes.byref(input_blob), None, None, None, None, 0, ctypes.byref(output_blob)
    )
    if not ok:
        raise OSError("Falha DPAPI ao decifrar")
    try:
        return ctypes.string_at(output_blob.pbData, output_blob.cbData)
    finally:
        kernel32.LocalFree(output_blob.pbData)


class SecretVault:
    def __init__(self) -> None:
        self.db = get_db()
        CONFIG.ensure_dirs()
        self._key: bytes | None = None

    @property
    def backend(self) -> str:
        if sys.platform == "win32":
            return "dpapi"
        if _HAVE_AESGCM:
            return "aesgcm"
        return "unavailable"

    def _load_key(self) -> bytes:
        if self._key is not None:
            return self._key
        path = CONFIG.vault_key_path
        if path.exists():
            key = path.read_bytes()
        else:
            key = os.urandom(32)
            path.write_bytes(key)
            try:
                os.chmod(path, 0o600)
            except OSError:
                pass
        if len(key) != 32:
            raise RuntimeError("Chave do cofre invalida")
        self._key = key
        return key

    def available(self) -> bool:
        return self.backend != "unavailable"

    def put(self, name: str, value: dict[str, Any]) -> None:
        raw = json.dumps(value, ensure_ascii=False).encode("utf-8")
        if self.backend == "dpapi":
            ciphertext, scheme = _dpapi_encrypt(raw), "dpapi"
        elif self.backend == "aesgcm":
            nonce = os.urandom(12)
            ciphertext = nonce + AESGCM(self._load_key()).encrypt(nonce, raw, name.encode())  # type: ignore[union-attr]
            scheme = "aesgcm-v1"
        else:
            raise RuntimeError(
                "Cofre indisponivel: instale o pacote 'cryptography' ou execute no Windows (DPAPI)."
            )
        self.db.execute(
            """INSERT INTO secrets(name, ciphertext, scheme, updated_at) VALUES (?,?,?,?)
               ON CONFLICT(name) DO UPDATE SET ciphertext=excluded.ciphertext,
               scheme=excluded.scheme, updated_at=excluded.updated_at""",
            (name, base64.b64encode(ciphertext).decode(), scheme, now_iso()),
        )
        self.db.audit("system", "secret.store", name, "granted", {"scheme": scheme})

    def get(self, name: str) -> dict[str, Any] | None:
        row = self.db.one("SELECT * FROM secrets WHERE name=?", (name,))
        if not row:
            return None
        ciphertext = base64.b64decode(row["ciphertext"])
        if row["scheme"] == "dpapi":
            raw = _dpapi_decrypt(ciphertext)
        elif row["scheme"] == "aesgcm-v1":
            nonce, payload = ciphertext[:12], ciphertext[12:]
            raw = AESGCM(self._load_key()).decrypt(nonce, payload, name.encode())  # type: ignore[union-attr]
        else:
            raise RuntimeError("Esquema de cofre desconhecido")
        return json.loads(raw.decode("utf-8"))

    def delete(self, name: str) -> bool:
        cur = self.db.execute("DELETE FROM secrets WHERE name=?", (name,))
        self.db.audit("user", "secret.delete", name, "granted", {})
        return cur.rowcount > 0

    def names(self) -> list[str]:
        return [r["name"] for r in self.db.query("SELECT name FROM secrets ORDER BY name")]


_vault: SecretVault | None = None


def get_vault() -> SecretVault:
    global _vault
    if _vault is None:
        _vault = SecretVault()
    return _vault
