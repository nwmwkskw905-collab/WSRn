import asyncio

import pytest


def test_filesystem_tools_scoped(grant_workspace, workspace):
    from jarvis.tools.registry import get_registry

    async def run():
        registry = get_registry()
        task = {"id": "t", "autonomy_level": 2}
        written = await registry.execute("fs.write_text", {"path": "nota.txt", "content": "conteudo"}, task)
        assert written["verification"]["status"] == "not_checked"
        read = await registry.execute("fs.read_text", {"path": "nota.txt"}, task)
        assert read["result"]["content"] == "conteudo"
        listing = await registry.execute("fs.list", {"path": "."}, task)
        assert any(e["name"] == "nota.txt" for e in listing["result"]["entries"])

    asyncio.run(run())


def test_tool_denied_without_permission(permissions, workspace):
    from jarvis.tools.registry import get_registry, ToolError

    async def run():
        with pytest.raises(ToolError):
            await get_registry().execute("fs.write_text", {"path": "x.txt", "content": "x"}, {"id": "t", "autonomy_level": 2})

    asyncio.run(run())


def test_high_risk_tool_creates_approval(grant_workspace, workspace):
    from jarvis.tools.registry import ApprovalRequired, get_registry

    async def run():
        grant_workspace.grant("automation.input", True)
        with pytest.raises(ApprovalRequired) as info:
            await get_registry().execute("windows.open_app", {"app": "notepad"}, {"id": "task-1", "autonomy_level": 2})
        assert info.value.approval["status"] == "pending"

    asyncio.run(run())


def test_hash_duplicates(grant_workspace, workspace):
    from jarvis.tools.registry import get_registry

    async def run():
        (workspace / "a.txt").write_text("same")
        (workspace / "b.txt").write_text("same")
        result = await get_registry().execute(
            "fs.hash", {"paths": [str(workspace / "a.txt"), str(workspace / "b.txt")]}, {"id": "t", "autonomy_level": 2}
        )
        assert len(result["result"]["duplicate_groups"]) == 1

    asyncio.run(run())
