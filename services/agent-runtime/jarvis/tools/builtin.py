"""Built-in tools. Every tool declares its scope, risk and verification."""
from __future__ import annotations

import asyncio
import hashlib
import json
import os
import platform
import re
import shutil
import subprocess
import sys
import time
import uuid
from pathlib import Path
from typing import Any

import httpx

from ..config import CONFIG
from ..db import get_db, now_iso
from .registry import ToolError, ToolRegistry, spec_from_fn, tool
from ..security.injection import inspect_external_text, wrap_untrusted

# ---------------------------------------------------------------------------
# Filesystem
# ---------------------------------------------------------------------------


def _workspace() -> Path:
    CONFIG.ensure_dirs()
    return CONFIG.workspace_dir


def _resolve_scoped(raw: str, must_exist: bool = False) -> Path:
    path = Path(raw).expanduser()
    if not path.is_absolute():
        path = _workspace() / path
    try:
        resolved = path.resolve()
    except (OSError, RuntimeError) as exc:
        raise ToolError(f"Caminho invalido: {exc}") from exc
    if must_exist and not resolved.exists():
        raise ToolError(f"Caminho nao existe: {resolved}")
    return resolved


@tool("fs.mkdir", "Cria uma pasta dentro do workspace autorizado.", "fs.write", "medium",
      {"path": "string"}, ["files"])
async def fs_mkdir(path: str) -> dict[str, Any]:
    target = _resolve_scoped(path)
    existed = target.exists()
    target.mkdir(parents=True, exist_ok=True)
    return {"path": str(target), "created": not existed, "exists": target.exists()}


@tool("fs.write_text", "Escreve um arquivo de texto (UTF-8) no workspace.", "fs.write", "medium",
      {"path": "string", "content": "string", "overwrite": "boolean"}, ["files"])
async def fs_write_text(path: str, content: str, overwrite: bool = True) -> dict[str, Any]:
    target = _resolve_scoped(path)
    if target.exists() and not overwrite:
        raise ToolError("Arquivo ja existe e overwrite=false")
    if target.exists():
        previous = target.read_bytes()
        if target.stat().st_size < 2_000_000:
            backup = target.with_suffix(target.suffix + f".bak-{int(time.time())}")
            backup.write_bytes(previous)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")
    digest = hashlib.sha256(content.encode()).hexdigest()
    return {"path": str(target), "bytes": target.stat().st_size, "sha256": digest}


@tool("fs.read_text", "Le um arquivo de texto do workspace.", "fs.read", "low",
      {"path": "string"}, ["files"])
async def fs_read_text(path: str) -> dict[str, Any]:
    target = _resolve_scoped(path, must_exist=True)
    if target.stat().st_size > 2_000_000:
        raise ToolError("Arquivo grande demais para leitura direta")
    return {"path": str(target), "content": target.read_text(encoding="utf-8", errors="replace")}


@tool("fs.list", "Lista entradas de uma pasta autorizada.", "fs.read", "low",
      {"path": "string", "recursive": "boolean"}, ["files"])
async def fs_list(path: str = ".", recursive: bool = False) -> dict[str, Any]:
    target = _resolve_scoped(path, must_exist=True)
    if not target.is_dir():
        raise ToolError("Caminho nao e uma pasta")
    entries = []
    iterator = target.rglob("*") if recursive else target.iterdir()
    for item in list(iterator)[:2000]:
        try:
            stat = item.stat()
        except OSError:
            continue
        entries.append(
            {
                "name": item.name,
                "path": str(item),
                "is_dir": item.is_dir(),
                "size": stat.st_size,
                "modified": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(stat.st_mtime)),
            }
        )
    return {"path": str(target), "entries": entries, "count": len(entries)}


@tool("fs.hash", "Calcula SHA-256 de arquivos para detectar duplicados.", "fs.read", "low",
      {"paths": "array"}, ["files"])
async def fs_hash(paths: list[str]) -> dict[str, Any]:
    out = {}
    for raw in paths:
        target = _resolve_scoped(raw, must_exist=True)
        digest = hashlib.sha256(target.read_bytes()).hexdigest()
        out[str(target)] = digest
    duplicates: dict[str, list[str]] = {}
    for path, digest in out.items():
        duplicates.setdefault(digest, []).append(path)
    return {"hashes": out, "duplicate_groups": [v for v in duplicates.values() if len(v) > 1]}


@tool("fs.move", "Move um arquivo de forma reversivel (mesmo disco, sem sobrescrever).", "fs.write", "medium",
      {"source": "string", "destination": "string"}, ["files"])
async def fs_move(source: str, destination: str) -> dict[str, Any]:
    src = _resolve_scoped(source, must_exist=True)
    dst = _resolve_scoped(destination)
    dst.parent.mkdir(parents=True, exist_ok=True)
    if dst.exists():
        raise ToolError("Destino ja existe; movimento cancelado para nao sobrescrever")
    shutil.move(str(src), str(dst))
    return {"source": str(src), "destination": str(dst), "source_exists": src.exists(), "destination_exists": dst.exists()}


# ---------------------------------------------------------------------------
# Research
# ---------------------------------------------------------------------------


def _strip_html(html: str) -> str:
    html = re.sub(r"(?is)<(script|style|noscript)[^>]*>.*?</\1>", " ", html)
    text = re.sub(r"(?s)<[^>]+>", " ", html)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


@tool("research.fetch_url", "Baixa uma URL HTTPS e extrai texto; trata o conteudo como nao confiavel.",
      "internet", "low", {"url": "string"}, ["research"])
async def research_fetch_url(url: str) -> dict[str, Any]:
    if not url.startswith(("https://", "http://")):
        raise ToolError("Apenas URLs HTTP(S) sao permitidas")
    if CONFIG.offline:
        raise ToolError("Modo offline ativo")
    async with httpx.AsyncClient(timeout=25, follow_redirects=True, headers={"User-Agent": "JARVIS/0.9 (research)"}) as client:
        resp = await client.get(url)
    if resp.status_code >= 400:
        raise ToolError(f"HTTP {resp.status_code} ao buscar {url}")
    content_type = resp.headers.get("content-type", "")
    raw = resp.text
    text = _strip_html(raw) if "html" in content_type else raw
    inspection = inspect_external_text(text)
    return {
        "url": str(resp.url),
        "status": resp.status_code,
        "content_type": content_type,
        "text": text[:20000],
        "length": len(text),
        "injection": inspection,
        "untrusted": True,
        "retrieved_at": now_iso(),
    }


@tool("research.search", "Busca na web por um provedor de busca configurado pelo usuario.",
      "internet", "low", {"query": "string", "limit": "integer"}, ["research"])
async def research_search(query: str, limit: int = 5) -> dict[str, Any]:
    if CONFIG.offline:
        raise ToolError("Modo offline ativo")
    db = get_db()
    from ..security.secrets import get_vault

    cfg = db.get_setting("research.provider", {"provider": "none"}) or {}
    provider = cfg.get("provider", "none")
    vault = get_vault()
    limit = max(1, min(int(limit), 10))
    if provider == "searxng":
        base = (cfg.get("base_url") or "").rstrip("/")
        if not base:
            raise ToolError("SearXNG sem base_url configurada")
        async with httpx.AsyncClient(timeout=25) as client:
            resp = await client.get(f"{base}/search", params={"q": query, "format": "json", "language": "pt-BR"})
        if resp.status_code >= 400:
            raise ToolError(f"SearXNG HTTP {resp.status_code}")
        results = [
            {"title": r.get("title"), "url": r.get("url"), "snippet": (r.get("content") or "")[:300]}
            for r in (resp.json().get("results") or [])[:limit]
        ]
        return {"provider": "searxng", "query": query, "results": results}
    secret = vault.get("research:api") or {}
    if provider in {"brave", "serper", "tavily"} and not secret.get("api_key"):
        raise ToolError(f"Provedor {provider} sem credencial configurada")
    if provider == "brave":
        async with httpx.AsyncClient(timeout=25) as client:
            resp = await client.get(
                "https://api.search.brave.com/res/v1/web/search",
                params={"q": query, "count": limit, "search_lang": "pt-br"},
                headers={"X-Subscription-Token": secret["api_key"]},
            )
        if resp.status_code >= 400:
            raise ToolError(f"Brave HTTP {resp.status_code}")
        results = [
            {"title": r.get("title"), "url": r.get("url"), "snippet": (r.get("description") or "")[:300]}
            for r in (resp.json().get("web", {}).get("results") or [])[:limit]
        ]
        return {"provider": "brave", "query": query, "results": results}
    if provider == "serper":
        async with httpx.AsyncClient(timeout=25) as client:
            resp = await client.post(
                "https://google.serper.dev/search",
                headers={"X-API-KEY": secret["api_key"], "Content-Type": "application/json"},
                json={"q": query, "num": limit, "gl": "br", "hl": "pt-br"},
            )
        if resp.status_code >= 400:
            raise ToolError(f"Serper HTTP {resp.status_code}")
        results = [
            {"title": r.get("title"), "url": r.get("link"), "snippet": (r.get("snippet") or "")[:300]}
            for r in (resp.json().get("organic") or [])[:limit]
        ]
        return {"provider": "serper", "query": query, "results": results}
    raise ToolError(
        "Nenhum provedor de busca configurado. Configure SearXNG, Brave, Serper ou Tavily em Configuracoes > Pesquisa."
    )


# ---------------------------------------------------------------------------
# Windows automation (real adapter on Windows, explicit unsupported elsewhere)
# ---------------------------------------------------------------------------


@tool("windows.open_app", "Abre um aplicativo Windows por nome ou caminho autorizado.",
      "automation.input", "high", {"app": "string"}, ["windows"], external_side_effect=True)
async def windows_open_app(app: str) -> dict[str, Any]:
    if platform.system() != "Windows":
        raise ToolError("Automacao de aplicativos Windows indisponivel nesta plataforma")
    allowed = get_db().get_setting("windows.allowed_apps", ["notepad", "calc", "mspaint", "explorer"]) or []
    normalized = app.strip().lower()
    if not any(normalized == a.lower() or normalized.endswith(a.lower()) for a in allowed):
        raise ToolError(f"Aplicativo fora da lista autorizada: {app}")
    proc = await asyncio.create_subprocess_exec(app, stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL)
    await asyncio.sleep(1.5)
    return {"app": app, "pid": proc.pid, "running": proc.returncode is None}


@tool("windows.type_text", "Digita texto em uma janela identificada por titulo.",
      "automation.input", "high", {"title": "string", "text": "string"}, ["windows"], external_side_effect=True)
async def windows_type_text(title: str, text: str) -> dict[str, Any]:
    if platform.system() != "Windows":
        raise ToolError("Automacao de teclado indisponivel nesta plataforma")
    try:
        from pywinauto import Desktop  # type: ignore
    except ImportError as exc:
        raise ToolError("pywinauto nao instalado no runtime empacotado") from exc
    window = Desktop(backend="uia").window(title_re=f".*{re.escape(title)}.*")
    window.set_focus()
    window.type_keys(text, with_spaces=True, pause=0.02)
    return {"title": title, "typed_chars": len(text)}


@tool("windows.capture", "Captura a tela primaria (requer permissao).", "screen.capture", "medium",
      {"path": "string"}, ["windows"])
async def windows_capture(path: str = "screenshots/capture.png") -> dict[str, Any]:
    target = _resolve_scoped(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    if platform.system() == "Windows":
        try:
            from PIL import ImageGrab  # type: ignore
        except ImportError as exc:
            raise ToolError("Pillow nao instalado") from exc
        ImageGrab.grab().save(target)
        return {"path": str(target), "bytes": target.stat().st_size}
    raise ToolError("Captura de tela disponivel apenas no Windows")


# ---------------------------------------------------------------------------
# Commands / tests / git
# ---------------------------------------------------------------------------


@tool("shell.run", "Executa um comando local autorizado (sem encadeamento), com timeout.",
      "shell.execute", "high", {"command": "string", "cwd": "string", "timeout": "integer"}, ["system"], external_side_effect=True)
async def shell_run(command: str, cwd: str = ".", timeout: int = 60) -> dict[str, Any]:
    workdir = _resolve_scoped(cwd, must_exist=True)
    if not workdir.is_dir():
        raise ToolError("cwd nao e uma pasta")
    timeout = max(1, min(int(timeout), 300))
    proc = await asyncio.create_subprocess_shell(
        command,
        cwd=str(workdir),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        start_new_session=True,
    )
    try:
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
    except asyncio.TimeoutError:
        proc.kill()
        return {"command": command, "timed_out": True, "exit_code": None, "stdout": "", "stderr": "timeout"}
    return {
        "command": command,
        "exit_code": proc.returncode,
        "stdout": stdout.decode(errors="replace")[-8000:],
        "stderr": stderr.decode(errors="replace")[-8000:],
    }


@tool("code.run_tests", "Executa testes de um projeto e retorna o resultado observado.",
      "shell.execute", "high", {"project_path": "string", "command": "string", "timeout": "integer"},
      ["development"], external_side_effect=True)
async def code_run_tests(project_path: str, command: str = "python3 -m pytest -q", timeout: int = 120) -> dict[str, Any]:
    return await shell_run(command=command, cwd=project_path, timeout=timeout)


@tool("git.status", "Mostra o estado do Git de um projeto.", "shell.execute", "medium",
      {"project_path": "string"}, ["development"])
async def git_status(project_path: str) -> dict[str, Any]:
    return await shell_run(command="git status --porcelain=v1 --branch", cwd=project_path, timeout=30)


# ---------------------------------------------------------------------------
# Utilities
# ---------------------------------------------------------------------------


@tool("system.info", "Informacoes basicas do ambiente local.", "fs.read", "low", {}, ["system"])
async def system_info() -> dict[str, Any]:
    try:
        import psutil  # optional dependency
    except ImportError:
        psutil = None  # type: ignore

    return {
        "platform": platform.platform(),
        "python": sys.version.split()[0],
        "machine": platform.machine(),
        "cpu_count": os.cpu_count(),
        "memory_total": psutil.virtual_memory().total if psutil else None,
        "data_dir": str(CONFIG.data_dir),
        "workspace": str(CONFIG.workspace_dir),
    }


@tool("noop", "Etapa sem efeito; usada para checkpoints e planejamento.", "fs.read", "low",
      {"note": "string"}, ["internal"])
async def noop(note: str = "") -> dict[str, Any]:
    return {"note": note, "ok": True}


def build_registry() -> ToolRegistry:
    registry = ToolRegistry()
    module = sys.modules[__name__]
    for name, obj in vars(module).items():
        if callable(obj) and hasattr(obj, "__tool_spec__"):
            registry.register(spec_from_fn(obj))
    return registry
