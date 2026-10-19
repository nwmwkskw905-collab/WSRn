"""MCP stdio server (JSON-RPC 2.0) for the JARVIS tool registry.

Design decisions:

* Read-only by default. `JARVIS_MCP_ALLOW_WRITE=1` is required before tools with
  filesystem/shell side effects are even listed.
* Every call still passes through `PermissionEngine.require()` with autonomy level 1,
  so an MCP client cannot bypass the desktop permissions.
* No secrets are returned: tool results are sanitized before leaving the process.
* The server never executes a tool named by the client without checking the registry.

Run: `python -m jarvis.mcp`
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
from typing import Any

from ..engine.skills import sanitize
from ..security.permissions import get_permission_engine
from ..tools.registry import ApprovalRequired, ToolError, get_registry

PROTOCOL_VERSION = "2024-11-05"
SERVER_INFO = {"name": "jarvis-agent-runtime", "version": "0.9.0"}

READ_ONLY_RISK = {"low"}
ALLOW_WRITE = os.environ.get("JARVIS_MCP_ALLOW_WRITE", "0") == "1"


def _allowed(tool: dict[str, Any]) -> bool:
    if tool.get("name") == "noop":
        return False
    if ALLOW_WRITE:
        return True
    return tool.get("risk") in READ_ONLY_RISK and not tool.get("external_side_effect")


def list_tools() -> list[dict[str, Any]]:
    out = []
    for tool in get_registry().list():
        if not _allowed(tool):
            continue
        properties = {name: {"type": "string", "description": f"parametro {name}"} for name in (tool.get("params") or {})}
        out.append(
            {
                "name": tool["name"],
                "description": f"{tool['description']} (escopo {tool['scope']}, risco {tool['risk']})",
                "inputSchema": {"type": "object", "properties": properties, "additionalProperties": True},
            }
        )
    return out


async def call_tool(name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    known = {tool["name"] for tool in get_registry().list()}
    if name not in known:
        raise ToolError(f"Ferramenta desconhecida: {name}")
    tool = next(tool for tool in get_registry().list() if tool["name"] == name)
    if not _allowed(tool):
        raise PermissionError(
            f"{name} nao esta exposta via MCP (escopo {tool['scope']}). "
            "Defina JARVIS_MCP_ALLOW_WRITE=1 para permitir efeitos colaterais."
        )
    decision = get_permission_engine().require(tool["scope"], arguments, {"autonomy_level": 1})
    if not decision.allowed:
        raise PermissionError(f"Acesso negado para {tool['scope']}: {decision.reason}")
    if decision.requires_approval:
        raise PermissionError("Esta ferramenta exige aprovacao com PIN no aplicativo desktop")
    result = await get_registry().execute(name, arguments, {"id": "mcp", "autonomy_level": 1})
    return sanitize(result)


async def handle(request: dict[str, Any]) -> dict[str, Any]:
    """Handle one JSON-RPC request object. Exposed for tests."""
    method = request.get("method")
    request_id = request.get("id")
    try:
        if method == "initialize":
            result: Any = {
                "protocolVersion": PROTOCOL_VERSION,
                "capabilities": {"tools": {"listChanged": False}},
                "serverInfo": SERVER_INFO,
            }
        elif method == "tools/list":
            result = {"tools": list_tools()}
        elif method == "tools/call":
            params = request.get("params") or {}
            name = params.get("name")
            if not name:
                raise ValueError("params.name obrigatorio")
            content = await call_tool(str(name), params.get("arguments") or {})
            result = {
                "content": [{"type": "text", "text": json.dumps(content, ensure_ascii=False, default=str)}],
                "isError": False,
            }
        elif method == "ping":
            result = {}
        else:
            return {"jsonrpc": "2.0", "id": request_id, "error": {"code": -32601, "message": f"Metodo nao suportado: {method}"}}
        return {"jsonrpc": "2.0", "id": request_id, "result": result}
    except ApprovalRequired as exc:
        return {"jsonrpc": "2.0", "id": request_id, "error": {"code": -32001, "message": "Aprovacao necessaria", "data": exc.approval}}
    except (ToolError, PermissionError, ValueError, KeyError) as exc:
        return {"jsonrpc": "2.0", "id": request_id, "error": {"code": -32000, "message": str(exc)[:500]}}
    except Exception as exc:  # noqa: BLE001 - never leak a traceback over the wire
        return {"jsonrpc": "2.0", "id": request_id, "error": {"code": -32603, "message": f"{type(exc).__name__}: {exc}"[:300]}}


async def serve(stdin=None, stdout=None) -> None:
    stdin = stdin or sys.stdin
    stdout = stdout or sys.stdout
    loop = asyncio.get_running_loop()
    while True:
        line = await loop.run_in_executor(None, stdin.readline)
        if not line:
            break
        line = line.strip()
        if not line:
            continue
        try:
            request = json.loads(line)
        except json.JSONDecodeError:
            stdout.write(json.dumps({"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": "JSON invalido"}}) + "\n")
            stdout.flush()
            continue
        response = await handle(request)
        stdout.write(json.dumps(response, ensure_ascii=False, default=str) + "\n")
        stdout.flush()


def main() -> None:
    from ..config import CONFIG

    CONFIG.ensure_dirs()
    asyncio.run(serve())


if __name__ == "__main__":
    main()
