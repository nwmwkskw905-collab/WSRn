"""Persistent, user-controlled memory.

Full-text search works offline (SQLite FTS5). Semantic search is optional and only
enabled when the user configures an embeddings provider; no vectors are invented.
"""
from __future__ import annotations

import json
import math
from typing import Any

from ..db import get_db, new_id, now_iso


class MemoryService:
    def __init__(self) -> None:
        self.db = get_db()

    def add(self, content: str, kind: str = "preference", key: str | None = None,
            tags: list[str] | None = None, source: str = "user", sensitive: bool = False) -> dict[str, Any]:
        mem_id = new_id("mem_")
        ts = now_iso()
        self.db.execute(
            "INSERT INTO memories(id, kind, key, content, tags, source, sensitive, created_at, updated_at)"
            " VALUES (?,?,?,?,?,?,?,?,?)",
            (mem_id, kind, key, content, ",".join(tags or []), source, 1 if sensitive else 0, ts, ts),
        )
        self.db.execute(
            "INSERT INTO memories_fts(rowid, content, tags) SELECT rowid, content, tags FROM memories WHERE id=?",
            (mem_id,),
        )
        return self.get(mem_id)

    def get(self, mem_id: str) -> dict[str, Any]:
        row = self.db.one("SELECT * FROM memories WHERE id=?", (mem_id,))
        if not row:
            raise KeyError("Memoria nao encontrada")
        return self._public(row)

    def list(self, kind: str | None = None, limit: int = 200) -> list[dict[str, Any]]:
        if kind:
            rows = self.db.query("SELECT * FROM memories WHERE kind=? ORDER BY updated_at DESC LIMIT ?", (kind, limit))
        else:
            rows = self.db.query("SELECT * FROM memories ORDER BY updated_at DESC LIMIT ?", (limit,))
        return [self._public(r) for r in rows]

    def search(self, query: str, limit: int = 20) -> list[dict[str, Any]]:
        query = (query or "").strip()
        if not query:
            return []
        safe = " ".join(f'"{t}"' for t in query.split() if t.isalnum() or "-" in t)
        if not safe:
            return []
        try:
            rows = self.db.query(
                "SELECT m.*, bm25(memories_fts) AS score FROM memories_fts f "
                "JOIN memories m ON m.rowid = f.rowid WHERE memories_fts MATCH ? ORDER BY score LIMIT ?",
                (safe, limit),
            )
        except Exception:  # noqa: BLE001 - FTS syntax can reject odd input
            rows = self.db.query(
                "SELECT * FROM memories WHERE content LIKE ? ORDER BY updated_at DESC LIMIT ?",
                (f"%{query}%", limit),
            )
        return [self._public(r) for r in rows]

    def update(self, mem_id: str, content: str | None = None, tags: list[str] | None = None) -> dict[str, Any]:
        current = self.get(mem_id)
        new_content = content if content is not None else current["content"]
        new_tags = tags if tags is not None else current["tags"]
        self.db.execute(
            "UPDATE memories SET content=?, tags=?, updated_at=? WHERE id=?",
            (new_content, ",".join(new_tags), now_iso(), mem_id),
        )
        self.db.execute(
            "INSERT INTO memories_fts(memories_fts) VALUES('rebuild')",
        )
        return self.get(mem_id)

    def delete(self, mem_id: str) -> bool:
        cur = self.db.execute("DELETE FROM memories WHERE id=?", (mem_id,))
        self.db.execute("INSERT INTO memories_fts(memories_fts) VALUES('rebuild')")
        self.db.audit("user", "memory.delete", mem_id, "granted", {})
        return cur.rowcount > 0

    def export(self) -> list[dict[str, Any]]:
        return [self._public(r) for r in self.db.query("SELECT * FROM memories ORDER BY created_at")]

    @staticmethod
    def _public(row: dict[str, Any]) -> dict[str, Any]:
        return {
            "id": row["id"],
            "kind": row["kind"],
            "key": row.get("key"),
            "content": row["content"],
            "tags": [t for t in (row.get("tags") or "").split(",") if t],
            "source": row.get("source"),
            "sensitive": bool(row.get("sensitive")),
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
        }


_service: MemoryService | None = None


def get_memory() -> MemoryService:
    global _service
    if _service is None:
        _service = MemoryService()
    return _service
