import json
import time


def test_generate_web_app_and_run_tests(workspace, db):
    from jarvis.modules.development import get_development

    result = get_development().create("web-app", f"Validacao Web {int(time.time())}",
                                      "Aplicacao web de cadastro de produtos", run_tests=True)
    assert result["syntax_check"]["status"] == "passed"
    assert result["tests"]["exit_code"] == 0, result["tests"]["stdout"][-2000:]
    assert result["status"] == "validated"
    path = result["path"]
    assert (__import__("pathlib").Path(path) / "app" / "main.py").exists()
    rows = db.query("SELECT * FROM projects WHERE id=?", (result["project_id"],))
    assert rows and rows[0]["status"] == "validated"
    artifacts = db.query("SELECT * FROM artifacts WHERE project_id=?", (result["project_id"],))
    assert len(artifacts) >= 5


def test_generate_inventory_system(workspace):
    from jarvis.modules.development import get_development
    import time

    result = get_development().create("inventory-system", f"Estoque {int(time.time())}",
                                      "Sistema de estoque vendas e caixa", run_tests=True)
    assert result["tests"]["exit_code"] == 0, result["tests"]["stdout"][-2000:]
    assert any("Tkinter" in limitation for limitation in result["limitations"])


def test_generate_godot_project(workspace):
    from jarvis.modules.gamestudio import get_gamestudio
    import time

    result = get_gamestudio().create_racer(f"Racer {int(time.time())}", "corrida de motos 3D simples", run_tests=False)
    assert (__import__("pathlib").Path(result["path"]) / "project.godot").exists()
    assert result["godot_validation"]["godot_installed"] is False
    assert result["status"] == "validation_pending"
    assert (__import__("pathlib").Path(result["path"]) / "docs" / "GAME_DESIGN.md").exists()
