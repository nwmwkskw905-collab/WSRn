import asyncio
import json

import pytest


def test_planner_intents():
    from jarvis.engine.planner import get_planner

    planner = get_planner()
    files = planner.plan("Jarvis, organize meus arquivos da pasta projetos", 2)
    assert files["steps"][0]["skill"] == "files.organize"
    org = planner.plan("Jarvis, organize meus Downloads", 2)
    assert org["steps"][0]["params"]["path"] == "Downloads"
    game = planner.plan("Jarvis, crie um jogo de corrida de motos", 1)
    assert game["steps"][0]["skill"] == "gamestudio.build"
    cakto = planner.plan("Jarvis, crie um curso de fotografia por R$ 97 na Cakto", 2)
    assert any(s["skill"] == "cakto.create_product" for s in cakto["steps"])
    assert cakto["approval_expected"] is True
    sales = planner.plan("Jarvis, mostre as vendas dos ultimos 7 dias", 1)
    assert "sales.report" in [s["skill"] for s in sales["steps"]]
    ads = planner.plan("Jarvis, prepare uma campanha de Meta Ads", 1)
    assert ads["steps"][0]["skill"] == "ads.prepare"
    general = planner.plan("Qual a capital do Brasil?", 1)
    assert general["steps"][0]["skill"] == "general.answer"
    assert general["planner"] == "deterministic-rules-v1"


def test_task_files_organize_end_to_end(grant_workspace, workspace):
    from jarvis.engine.tasks import get_engine

    base = workspace / "sandbox" / "engine-organize"
    base.mkdir(parents=True, exist_ok=True)
    for name in ["a.txt", "b.png", "c.mp3"]:
        (base / name).write_text("x", encoding="utf-8")

    async def run():
        engine = get_engine()
        task = engine.create(f'organize a pasta "{base}"', autonomy_level=2, mode="test", auto_start=False)
        finished = await engine.run(task["id"])
        return finished

    task = asyncio.run(run())
    assert task["status"] == "completed", task.get("error")
    assert task["verification"]["steps_completed"] == 1
    assert (base / "documentos" / "a.txt").exists()
    assert (base / "imagens" / "b.png").exists()
    assert (base / "audio" / "c.mp3").exists()


def test_task_denied_permission_partial(permissions, workspace):
    from jarvis.engine.tasks import get_engine

    async def run():
        engine = get_engine()
        task = engine.create("crie um site de cadastro", autonomy_level=1, mode="test", auto_start=False)
        return await engine.run(task["id"])

    task = asyncio.run(run())
    assert task["status"] in {"partially_completed", "failed"}
    assert task["error"]


def test_high_risk_task_waits_for_approval(grant_workspace, workspace, db):
    from jarvis.engine.skills import get_skills
    from jarvis.security.approvals import get_approval_service
    from jarvis.tools.registry import ApprovalRequired

    grant_workspace.grant("automation.input", True)

    async def run():
        with pytest.raises(ApprovalRequired):
            await get_skills().execute("windows.notepad", {"text": "lista"}, {"id": "t", "autonomy_level": 2})
        return True

    assert asyncio.run(run())
    pending = [a for a in get_approval_service().list("pending")]
    assert pending


def test_recovery_pauses_running_task(db):
    from jarvis.engine.tasks import get_engine

    engine = get_engine()
    task = engine.create("Tarefa recuperavel", mode="test", auto_start=False)
    db.execute("UPDATE tasks SET status='running' WHERE id=?", (task["id"],))
    db.execute("UPDATE task_steps SET status='running' WHERE task_id=?", (task["id"],))
    result = engine.recover_on_startup()
    restored = engine.get(task["id"])
    assert restored["status"] == "paused"
    assert task["id"] in result["recovered"]


def test_cancel_and_resume(db):
    from jarvis.engine.tasks import get_engine

    engine = get_engine()
    task = engine.create("Tarefa para cancelar", mode="test", auto_start=False)
    cancelled = engine.cancel(task["id"])
    assert cancelled["status"] == "cancelled"
    resumed = engine.resume(task["id"])
    assert resumed["status"] in {"queued", "planning", "running", "paused"}


def test_kill_switch_pauses_active(db):
    from jarvis.engine.tasks import get_engine

    engine = get_engine()
    task = engine.create("Tarefa ativa", mode="test", auto_start=False)
    db.execute("UPDATE tasks SET status='running' WHERE id=?", (task["id"],))
    result = engine.engage_kill_switch("teste")
    assert task["id"] in result["affected_tasks"]
    assert engine.get(task["id"])["status"] == "paused"
    engine.release_kill_switch()


def test_validation_scenarios_safe(permissions, workspace):
    from jarvis.validation import run_safe_scenarios

    permissions.grant("fs.read", True, {"roots": [str(workspace)]})
    permissions.grant("fs.write", True, {"roots": [str(workspace)]})
    permissions.grant("shell.execute", True, {"roots": [str(workspace)]})
    result = asyncio.run(run_safe_scenarios())
    scenarios = result["scenarios"]
    assert scenarios["B_files"]["status"] == "passed"
    assert scenarios["K_injection"]["status"] == "passed"
    assert scenarios["J_recovery"]["status"] == "passed"
    assert scenarios["L_cancel"]["status"] == "passed"
    assert scenarios["memory"]["status"] == "passed"
