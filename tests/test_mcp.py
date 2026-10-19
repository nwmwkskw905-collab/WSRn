"""MCP stdio server: read-only by default and never bypassing permissions."""
from __future__ import annotations

import json

import pytest

from jarvis.mcp import server as mcp


@pytest.fixture(autouse=True)
def _read_only(monkeypatch):
    monkeypatch.setattr(mcp, "ALLOW_WRITE", False)


def test_initialize_and_protocol_version():
    response = mcp.asyncio.run(mcp.handle({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}}))
    assert response["jsonrpc"] == "2.0"
    assert response["id"] == 1
    assert response["result"]["protocolVersion"] == "2024-11-05"
    assert response["result"]["capabilities"]["tools"] is not None


def test_tools_list_is_read_only_by_default():
    response = mcp.asyncio.run(mcp.handle({"jsonrpc": "2.0", "id": 2, "method": "tools/list"}))
    names = {tool["name"] for tool in response["result"]["tools"]}
    assert "system.info" in names
    assert "fs.read_text" in names
    assert "fs.write_text" not in names
    assert "fs.move" not in names
    assert "shell.run" not in names
    assert "noop" not in names
    for tool in response["result"]["tools"]:
        assert tool["inputSchema"]["type"] == "object"


def test_call_read_tool_executes_real_handler(permissions):
    permissions.grant("fs.read", True, {})
    response = mcp.asyncio.run(
        mcp.handle({"jsonrpc": "2.0", "id": 3, "method": "tools/call", "params": {"name": "system.info", "arguments": {}}})
    )
    assert "error" not in response, response
    payload = json.loads(response["result"]["content"][0]["text"])
    assert payload.get("platform") or payload.get("python") or payload.get("ok") is not None


def test_write_tools_are_rejected_without_opt_in(permissions, workspace):
    permissions.grant("fs.write", True, {"roots": [str(workspace)]})
    response = mcp.asyncio.run(
        mcp.handle({"jsonrpc": "2.0", "id": 4, "method": "tools/call",
                    "params": {"name": "fs.write_text", "arguments": {"path": "x.txt", "content": "oi"}}})
    )
    assert response["error"]["code"] == -32000
    assert "mcp" in response["error"]["message"].lower()
    assert not (workspace / "x.txt").exists()


def test_unknown_tool_and_method_are_errors():
    unknown = mcp.asyncio.run(
        mcp.handle({"jsonrpc": "2.0", "id": 5, "method": "tools/call", "params": {"name": "database.drop", "arguments": {}}})
    )
    assert unknown["error"]["code"] == -32000
    method = mcp.asyncio.run(mcp.handle({"jsonrpc": "2.0", "id": 6, "method": "resources/list"}))
    assert method["error"]["code"] == -32601


def test_write_mode_still_requires_permission(monkeypatch, permissions, workspace):
    monkeypatch.setattr(mcp, "ALLOW_WRITE", True)
    listing = mcp.asyncio.run(mcp.handle({"jsonrpc": "2.0", "id": 7, "method": "tools/list"}))
    assert "fs.write_text" in {tool["name"] for tool in listing["result"]["tools"]}

    permissions.revoke_all()
    denied = mcp.asyncio.run(
        mcp.handle({"jsonrpc": "2.0", "id": 8, "method": "tools/call",
                    "params": {"name": "fs.write_text", "arguments": {"path": "y.txt", "content": "nao"}}})
    )
    assert denied["error"]["code"] == -32000
    assert "negado" in denied["error"]["message"].lower()
