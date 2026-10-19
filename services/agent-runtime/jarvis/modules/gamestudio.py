"""Game Studio: Godot 4 project generation plus honest validation status.

A real Godot executable is required to open/export the project. When it is absent we
report ``validation_pending`` instead of pretending to have produced an .exe.
"""
from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any

from ..config import CONFIG
from ..db import get_db
from .development import get_development

GDD_TEMPLATE = """# Game Design Document - {name}

## Objetivo
{objective}

## Escopo do prototipo
- Genero: corrida em terceira pessoa (3D simples, primitivas)
- Plataforma alvo: Windows x64
- Motor: Godot 4.3+ (Forward+)
- Loop principal: acelerar, dirigir, passar checkpoints, concluir volta, reiniciar

## Controles
- W: acelerar
- S: frear
- A/D: dirigir
- R: reiniciar apos concluir

## Sistemas implementados
1. Movimento com CharacterBody3D e velocidade limitada
2. Camera em terceira pessoa seguindo a moto
3. Pista circular com marcadores visuais
4. Checkpoints sequenciais (Area3D)
5. Cronometro e HUD
6. Condicao de vitoria e reinicio

## Fora de escopo (limitacoes declaradas)
- Modelos 3D texturizados e animacoes
- Fisica avancada de suspensao/pneus
- Multiplayer, som, menus completos, save
- Exportacao .exe (requer Godot instalado e template de exportacao)

## Criterios de aceite
- Projeto abre no Godot 4.3 sem erro de parse
- Moto se move com WASD
- Checkpoints incrementam apenas na ordem correta
- Volta concluida exibe tempo

## Status de validacao
- Arquivos: gerados
- Parse/execucao: PENDENTE (Godot nao disponivel neste ambiente)
"""


class GameStudio:
    def __init__(self) -> None:
        self.db = get_db()

    def create_racer(self, name: str, objective: str, run_tests: bool = True) -> dict[str, Any]:
        result = get_development().create("godot-2d-racer", name, objective, run_tests=run_tests)
        root = Path(result["path"])
        (root / "docs").mkdir(exist_ok=True)
        gdd = GDD_TEMPLATE.format(name=name, objective=objective)
        (root / "docs" / "GAME_DESIGN.md").write_text(gdd, encoding="utf-8")
        godot = shutil.which("godot") or shutil.which("godot4")
        validation = {
            "godot_installed": bool(godot),
            "godot_path": godot,
            "build": "not_generated",
            "reason": "Godot nao encontrado no PATH" if not godot else "Godot presente, exportacao nao executada automaticamente",
            "status": "validation_pending",
        }
        if godot:
            import subprocess

            check = subprocess.run([godot, "--headless", "--path", str(root), "--quit"], capture_output=True, text=True, timeout=120)
            validation["import_check_exit_code"] = check.returncode
            validation["import_check_output"] = (check.stdout + check.stderr)[-3000:]
            validation["status"] = "import_validated" if check.returncode == 0 else "import_failed"
        result["gdd"] = str(root / "docs" / "GAME_DESIGN.md")
        result["godot_validation"] = validation
        result["status"] = validation["status"]
        self.db.execute(
            "UPDATE projects SET metadata_json=?, status=?, updated_at=strftime('%Y-%m-%dT%H:%M:%SZ','now') WHERE id=?",
            (__import__("json").dumps({**result, "files": result["files"]}, default=str), validation["status"], result["project_id"]),
        )
        return result

    def automation_policy(self, game: str) -> dict[str, Any]:
        allowed = self.db.get_setting("games.automation_allowed", []) or []
        normalized = game.strip().lower()
        allowed_match = any(normalized == a.lower() for a in allowed)
        return {
            "game": game,
            "allowed": allowed_match,
            "reason": "Jogo na lista branca local" if allowed_match else
            "Automacao bloqueada: apenas jogos offline/QA explicitamente autorizados. Nunca burlar anticheat.",
        }


_service: GameStudio | None = None


def get_gamestudio() -> GameStudio:
    global _service
    if _service is None:
        _service = GameStudio()
    return _service
