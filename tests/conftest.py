import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "services" / "agent-runtime"))

TEST_DATA = Path(os.environ.get("JARVIS_TEST_DATA", "/tmp/jarvis-tests"))
os.environ["JARVIS_DATA_DIR"] = str(TEST_DATA)
os.environ["JARVIS_REQUIRE_AUTH"] = "0"
os.environ["JARVIS_AUTO_WORKER"] = "0"


@pytest.fixture(scope="session", autouse=True)
def _clean_data():
    import shutil

    shutil.rmtree(TEST_DATA, ignore_errors=True)
    TEST_DATA.mkdir(parents=True, exist_ok=True)
    yield


@pytest.fixture()
def db():
    from jarvis.config import CONFIG
    from jarvis.db import get_db

    CONFIG.ensure_dirs()
    database = get_db()
    database.set_state("kill_switch", False)
    return database


@pytest.fixture()
def client():
    from fastapi.testclient import TestClient
    from jarvis.main import app

    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture()
def permissions(db):
    from jarvis.security.permissions import get_permission_engine

    engine = get_permission_engine()
    engine.revoke_all()
    return engine


@pytest.fixture()
def workspace(db):
    from jarvis.config import CONFIG

    CONFIG.ensure_dirs()
    return CONFIG.workspace_dir


@pytest.fixture()
def grant_workspace(permissions, workspace):
    permissions.grant("fs.read", True, {"roots": [str(workspace)]})
    permissions.grant("fs.write", True, {"roots": [str(workspace)]})
    permissions.grant("shell.execute", True, {"roots": [str(workspace)]})
    permissions.grant("internet", True)
    return permissions


@pytest.fixture(autouse=True)
def _reset_pin(db):
    db.execute("DELETE FROM runtime_state WHERE key='pin_hash'")
    yield
