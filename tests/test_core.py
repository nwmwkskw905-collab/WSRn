import json
from pathlib import Path

import pytest


def test_migrations_and_settings(db):
    versions = [r["version"] for r in db.query("SELECT version FROM schema_migrations ORDER BY version")]
    assert versions == [1, 2, 3]
    db.set_setting("ui.theme", {"accent": "cyan"})
    assert db.get_setting("ui.theme") == {"accent": "cyan"}


def test_backup_creates_file(db, tmp_path):
    target = db.backup(tmp_path / "backup.sqlite3")
    assert target.exists() and target.stat().st_size > 0


def test_task_idempotency(db):
    from jarvis.engine.tasks import get_engine

    engine = get_engine()
    first = engine.create("Objetivo idempotente", mode="test", auto_start=False, idempotency_key="idem-1")
    second = engine.create("Objetivo idempotente", mode="test", auto_start=False, idempotency_key="idem-1")
    assert first["id"] == second["id"]


def test_database_persists_messages(db):
    from jarvis.engine.chat import get_chat

    chat = get_chat()
    msg = chat.add_message("conv-test", "user", "ola")
    history = chat.history("conv-test")
    assert any(m["id"] == msg["id"] for m in history)
