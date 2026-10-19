"""Module manifests are executable documentation, not brochures.

Each `modules/*/module.json` must reference skills, tools, permissions and routes
that really exist in the runtime. A manifest that drifts fails CI.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
MODULES = ROOT / "modules"


def _manifests() -> list[tuple[Path, dict]]:
    return [(path, json.loads(path.read_text(encoding="utf-8"))) for path in sorted(MODULES.glob("*/module.json"))]


def test_manifest_files_present_and_unique():
    manifests = _manifests()
    assert len(manifests) >= 10
    ids = [data["id"] for _, data in manifests]
    assert len(ids) == len(set(ids))
    for path, data in manifests:
        assert path.parent.name == data["id"]
        assert data["name"] and data["objective"]
        assert data["status"] in {"implemented", "requires_external_configuration", "validation_pending"}
        assert isinstance(data["limitations"], list) and data["limitations"]


def test_manifest_skills_and_tools_exist():
    from jarvis.engine.skills import get_skills
    from jarvis.tools.registry import get_registry

    skills = {skill["name"] for skill in get_skills().list()}
    tools = {tool["name"] for tool in get_registry().list()}
    problems = []
    for path, data in _manifests():
        for skill in data["skills"]:
            if skill not in skills:
                problems.append(f"{path.name}: skill desconhecida {skill}")
        for tool in data["tools"]:
            if tool not in tools:
                problems.append(f"{path.name}: tool desconhecida {tool}")
    assert not problems, problems


def test_manifest_permissions_exist():
    from jarvis.security.permissions import PERMISSION_DEFS

    problems = []
    for path, data in _manifests():
        for scope in data["permissions"]:
            if scope not in PERMISSION_DEFS:
                problems.append(f"{path.name}: permissao inexistente {scope}")
    assert not problems, problems


def test_manifest_routes_exist():
    from jarvis.main import app

    known = set(app.openapi()["paths"])

    def normalize(route: str) -> str:
        import re

        return re.sub(r"\{[^}]*\}", "{}", route)

    normalized = {normalize(route) for route in known}
    problems = []
    for path, data in _manifests():
        assert data["routes"], f"{path.name} sem rotas declaradas"
        for route in data["routes"]:
            if normalize(route) not in normalized:
                problems.append(f"{path.name}: rota inexistente {route}")
    assert not problems, problems


def test_implementation_paths_exist():
    missing = []
    for path, data in _manifests():
        target = ROOT / data["implementation"]
        if not target.exists():
            missing.append(f"{path.name}: {data['implementation']}")
    assert not missing, missing
