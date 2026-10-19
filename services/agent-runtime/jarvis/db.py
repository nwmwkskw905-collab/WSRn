"""SQLite persistence with versioned migrations.

The runtime uses the standard library driver only. A single connection guarded by
an RLock keeps the write path simple and predictable for a desktop workload.
"""
from __future__ import annotations

import json
import sqlite3
import threading
import time
import uuid
from pathlib import Path
from typing import Any, Iterable

from .config import CONFIG

MIGRATIONS: list[tuple[int, str]] = [
    (
        1,
        """
        CREATE TABLE IF NOT EXISTS settings (
          key TEXT PRIMARY KEY,
          value TEXT NOT NULL,
          updated_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS tasks (
          id TEXT PRIMARY KEY,
          parent_id TEXT,
          objective TEXT NOT NULL,
          status TEXT NOT NULL,
          autonomy_level INTEGER NOT NULL DEFAULT 1,
          mode TEXT NOT NULL DEFAULT 'demo',
          plan_json TEXT,
          result_json TEXT,
          error TEXT,
          progress REAL NOT NULL DEFAULT 0,
          cancel_requested INTEGER NOT NULL DEFAULT 0,
          attempts INTEGER NOT NULL DEFAULT 0,
          tool_calls INTEGER NOT NULL DEFAULT 0,
          tokens INTEGER NOT NULL DEFAULT 0,
          cost_usd REAL NOT NULL DEFAULT 0,
          business_id TEXT,
          created_at TEXT NOT NULL,
          updated_at TEXT NOT NULL,
          started_at TEXT,
          finished_at TEXT
        );
        CREATE INDEX IF NOT EXISTS idx_tasks_status ON tasks(status);
        CREATE TABLE IF NOT EXISTS task_steps (
          id TEXT PRIMARY KEY,
          task_id TEXT NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
          idx INTEGER NOT NULL,
          title TEXT NOT NULL,
          description TEXT NOT NULL DEFAULT '',
          tool TEXT,
          status TEXT NOT NULL DEFAULT 'pending',
          attempts INTEGER NOT NULL DEFAULT 0,
          max_attempts INTEGER NOT NULL DEFAULT 2,
          depends_on TEXT,
          input_json TEXT,
          output_json TEXT,
          error TEXT,
          verification_json TEXT,
          idempotency_key TEXT,
          started_at TEXT,
          finished_at TEXT
        );
        CREATE INDEX IF NOT EXISTS idx_steps_task ON task_steps(task_id, idx);
        CREATE TABLE IF NOT EXISTS task_events (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          task_id TEXT,
          ts TEXT NOT NULL,
          kind TEXT NOT NULL,
          payload_json TEXT
        );
        CREATE INDEX IF NOT EXISTS idx_events_task ON task_events(task_id, id);
        CREATE TABLE IF NOT EXISTS audit_log (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          ts TEXT NOT NULL,
          actor TEXT NOT NULL,
          action TEXT NOT NULL,
          resource TEXT,
          decision TEXT NOT NULL,
          details_json TEXT
        );
        CREATE TABLE IF NOT EXISTS permissions (
          scope TEXT PRIMARY KEY,
          granted INTEGER NOT NULL DEFAULT 0,
          config_json TEXT NOT NULL DEFAULT '{}',
          granted_at TEXT,
          expires_at TEXT,
          revoked_at TEXT,
          updated_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS approvals (
          id TEXT PRIMARY KEY,
          ts TEXT NOT NULL,
          task_id TEXT,
          step_id TEXT,
          action TEXT NOT NULL,
          risk TEXT NOT NULL,
          payload_json TEXT,
          status TEXT NOT NULL DEFAULT 'pending',
          resolved_at TEXT,
          resolution_note TEXT,
          pin_required INTEGER NOT NULL DEFAULT 1
        );
        CREATE TABLE IF NOT EXISTS messages (
          id TEXT PRIMARY KEY,
          conversation_id TEXT NOT NULL,
          ts TEXT NOT NULL,
          role TEXT NOT NULL,
          content TEXT NOT NULL,
          meta_json TEXT
        );
        CREATE INDEX IF NOT EXISTS idx_messages_conv ON messages(conversation_id, ts);
        CREATE TABLE IF NOT EXISTS memories (
          id TEXT PRIMARY KEY,
          kind TEXT NOT NULL,
          key TEXT,
          content TEXT NOT NULL,
          tags TEXT NOT NULL DEFAULT '',
          source TEXT,
          sensitive INTEGER NOT NULL DEFAULT 0,
          created_at TEXT NOT NULL,
          updated_at TEXT NOT NULL
        );
        CREATE VIRTUAL TABLE IF NOT EXISTS memories_fts USING fts5(
          content, tags, content='memories', content_rowid='rowid'
        );
        CREATE TABLE IF NOT EXISTS integrations (
          provider TEXT PRIMARY KEY,
          status TEXT NOT NULL DEFAULT 'disconnected',
          env TEXT NOT NULL DEFAULT 'production',
          scopes TEXT,
          account_label TEXT,
          last_check_at TEXT,
          last_error TEXT,
          updated_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS secrets (
          name TEXT PRIMARY KEY,
          ciphertext TEXT NOT NULL,
          scheme TEXT NOT NULL,
          updated_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS businesses (
          id TEXT PRIMARY KEY,
          name TEXT NOT NULL,
          niche TEXT,
          audience TEXT,
          goals_json TEXT,
          brand_json TEXT,
          channels_json TEXT,
          created_at TEXT NOT NULL,
          updated_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS products (
          id TEXT PRIMARY KEY,
          business_id TEXT,
          name TEXT NOT NULL,
          description TEXT,
          price_cents INTEGER NOT NULL DEFAULT 0,
          currency TEXT NOT NULL DEFAULT 'BRL',
          type TEXT NOT NULL DEFAULT 'unique',
          status TEXT NOT NULL DEFAULT 'draft',
          provider TEXT,
          provider_id TEXT,
          provider_short_id TEXT,
          offer_id TEXT,
          checkout_id TEXT,
          checkout_url TEXT,
          sales_page TEXT,
          raw_json TEXT,
          created_at TEXT NOT NULL,
          updated_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS customers (
          id TEXT PRIMARY KEY,
          business_id TEXT,
          provider TEXT,
          provider_id TEXT UNIQUE,
          name TEXT,
          email TEXT,
          phone TEXT,
          consent INTEGER NOT NULL DEFAULT 0,
          tags TEXT DEFAULT '',
          created_at TEXT NOT NULL,
          updated_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS leads (
          id TEXT PRIMARY KEY,
          business_id TEXT,
          name TEXT,
          email TEXT,
          phone TEXT,
          stage TEXT NOT NULL DEFAULT 'new',
          source TEXT,
          consent INTEGER NOT NULL DEFAULT 0,
          notes TEXT,
          created_at TEXT NOT NULL,
          updated_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS orders (
          id TEXT PRIMARY KEY,
          provider TEXT NOT NULL,
          provider_order_id TEXT NOT NULL,
          business_id TEXT,
          product_id TEXT,
          customer_email TEXT,
          status TEXT NOT NULL,
          payment_method TEXT,
          amount_cents INTEGER NOT NULL DEFAULT 0,
          currency TEXT NOT NULL DEFAULT 'BRL',
          ref_id TEXT,
          created_at TEXT NOT NULL,
          paid_at TEXT,
          raw_json TEXT,
          UNIQUE(provider, provider_order_id)
        );
        CREATE TABLE IF NOT EXISTS webhook_events (
          id TEXT PRIMARY KEY,
          provider TEXT NOT NULL,
          event TEXT NOT NULL,
          dedupe_key TEXT NOT NULL,
          status TEXT NOT NULL DEFAULT 'received',
          payload_json TEXT NOT NULL,
          received_at TEXT NOT NULL,
          processed_at TEXT,
          error TEXT,
          UNIQUE(provider, dedupe_key)
        );
        CREATE TABLE IF NOT EXISTS campaigns (
          id TEXT PRIMARY KEY,
          business_id TEXT,
          provider TEXT NOT NULL,
          external_id TEXT,
          name TEXT NOT NULL,
          status TEXT NOT NULL DEFAULT 'draft',
          objective TEXT,
          daily_budget_cents INTEGER NOT NULL DEFAULT 0,
          monthly_limit_cents INTEGER NOT NULL DEFAULT 0,
          spent_cents INTEGER NOT NULL DEFAULT 0,
          authorized INTEGER NOT NULL DEFAULT 0,
          authorization_id TEXT,
          metrics_json TEXT,
          created_at TEXT NOT NULL,
          updated_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS schedules (
          id TEXT PRIMARY KEY,
          name TEXT NOT NULL,
          objective TEXT NOT NULL,
          cron TEXT,
          interval_seconds INTEGER,
          next_run_at TEXT,
          last_run_at TEXT,
          enabled INTEGER NOT NULL DEFAULT 1,
          autonomy_level INTEGER NOT NULL DEFAULT 1,
          last_task_id TEXT,
          last_error TEXT,
          created_at TEXT NOT NULL,
          updated_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS usage_ledger (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          ts TEXT NOT NULL,
          task_id TEXT,
          provider TEXT NOT NULL,
          model TEXT NOT NULL,
          prompt_tokens INTEGER NOT NULL DEFAULT 0,
          completion_tokens INTEGER NOT NULL DEFAULT 0,
          cost_usd REAL NOT NULL DEFAULT 0,
          latency_ms INTEGER,
          outcome TEXT
        );
        CREATE TABLE IF NOT EXISTS projects (
          id TEXT PRIMARY KEY,
          name TEXT NOT NULL,
          kind TEXT NOT NULL DEFAULT 'software',
          path TEXT NOT NULL,
          objective TEXT,
          status TEXT NOT NULL DEFAULT 'created',
          metadata_json TEXT,
          created_at TEXT NOT NULL,
          updated_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS artifacts (
          id TEXT PRIMARY KEY,
          task_id TEXT,
          project_id TEXT,
          name TEXT NOT NULL,
          path TEXT NOT NULL,
          kind TEXT,
          size_bytes INTEGER NOT NULL DEFAULT 0,
          sha256 TEXT,
          created_at TEXT NOT NULL
        );
        """,
    ),
    (
        2,
        """
        ALTER TABLE tasks ADD COLUMN verification_json TEXT;
        ALTER TABLE tasks ADD COLUMN checkpoint_json TEXT;
        ALTER TABLE tasks ADD COLUMN pause_requested INTEGER NOT NULL DEFAULT 0;
        ALTER TABLE tasks ADD COLUMN idempotency_key TEXT;
        CREATE INDEX IF NOT EXISTS idx_orders_paid ON orders(paid_at);
        CREATE INDEX IF NOT EXISTS idx_audit_ts ON audit_log(ts);
        """,
    ),
    (
        3,
        """
        CREATE TABLE IF NOT EXISTS model_stats (
          provider TEXT NOT NULL,
          model TEXT NOT NULL,
          calls INTEGER NOT NULL DEFAULT 0,
          failures INTEGER NOT NULL DEFAULT 0,
          total_latency_ms INTEGER NOT NULL DEFAULT 0,
          total_cost_usd REAL NOT NULL DEFAULT 0,
          updated_at TEXT NOT NULL,
          PRIMARY KEY (provider, model)
        );
        CREATE TABLE IF NOT EXISTS runtime_state (
          key TEXT PRIMARY KEY,
          value TEXT NOT NULL,
          updated_at TEXT NOT NULL
        );
        """,
    ),
]


def now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def new_id(prefix: str = "") -> str:
    raw = uuid.uuid4().hex
    return f"{prefix}{raw}" if prefix else raw


class Database:
    def __init__(self, path: Path | None = None):
        self.path = Path(path) if path else CONFIG.db_path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._conn = sqlite3.connect(str(self.path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA foreign_keys=ON")
        self._conn.execute("PRAGMA busy_timeout=5000")
        self.migrate()

    @property
    def conn(self) -> sqlite3.Connection:
        return self._conn

    def migrate(self) -> list[int]:
        applied: list[int] = []
        with self._lock:
            self._conn.execute(
                "CREATE TABLE IF NOT EXISTS schema_migrations (version INTEGER PRIMARY KEY, applied_at TEXT NOT NULL)"
            )
            done = {r[0] for r in self._conn.execute("SELECT version FROM schema_migrations")}
            for version, sql in MIGRATIONS:
                if version in done:
                    continue
                self._conn.executescript(sql)
                self._conn.execute(
                    "INSERT INTO schema_migrations(version, applied_at) VALUES (?, ?)", (version, now_iso())
                )
                applied.append(version)
            self._conn.commit()
        return applied

    def execute(self, sql: str, params: Iterable[Any] = ()) -> sqlite3.Cursor:
        with self._lock:
            cur = self._conn.execute(sql, tuple(params))
            self._conn.commit()
            return cur

    def executemany(self, sql: str, rows: Iterable[Iterable[Any]]) -> None:
        with self._lock:
            self._conn.executemany(sql, [tuple(r) for r in rows])
            self._conn.commit()

    def query(self, sql: str, params: Iterable[Any] = ()) -> list[dict[str, Any]]:
        with self._lock:
            cur = self._conn.execute(sql, tuple(params))
            return [dict(r) for r in cur.fetchall()]

    def one(self, sql: str, params: Iterable[Any] = ()) -> dict[str, Any] | None:
        rows = self.query(sql, params)
        return rows[0] if rows else None

    # -- settings -----------------------------------------------------------
    def get_setting(self, key: str, default: Any = None) -> Any:
        row = self.one("SELECT value FROM settings WHERE key=?", (key,))
        if not row:
            return default
        try:
            return json.loads(row["value"])
        except json.JSONDecodeError:
            return default

    def set_setting(self, key: str, value: Any) -> None:
        self.execute(
            "INSERT INTO settings(key, value, updated_at) VALUES (?, ?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_at=excluded.updated_at",
            (key, json.dumps(value), now_iso()),
        )

    # -- runtime state ------------------------------------------------------
    def get_state(self, key: str, default: Any = None) -> Any:
        row = self.one("SELECT value FROM runtime_state WHERE key=?", (key,))
        if not row:
            return default
        try:
            return json.loads(row["value"])
        except json.JSONDecodeError:
            return default

    def set_state(self, key: str, value: Any) -> None:
        self.execute(
            "INSERT INTO runtime_state(key, value, updated_at) VALUES (?, ?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_at=excluded.updated_at",
            (key, json.dumps(value, ensure_ascii=False), now_iso()),
        )

    def audit(self, actor: str, action: str, resource: str, decision: str, details: Any = None) -> None:
        self.execute(
            "INSERT INTO audit_log(ts, actor, action, resource, decision, details_json) VALUES (?,?,?,?,?,?)",
            (now_iso(), actor, action, resource, decision, json.dumps(details or {}, default=str)),
        )

    def backup(self, target: Path) -> Path:
        target.parent.mkdir(parents=True, exist_ok=True)
        with self._lock:
            dest = sqlite3.connect(str(target))
            try:
                self._conn.backup(dest)
            finally:
                dest.close()
        return target

    def close(self) -> None:
        with self._lock:
            self._conn.close()


_db_lock = threading.Lock()
_db_instance: Database | None = None


def get_db() -> Database:
    global _db_instance
    with _db_lock:
        if _db_instance is None:
            CONFIG.ensure_dirs()
            _db_instance = Database()
        return _db_instance


def reset_db_singleton() -> None:
    """Test helper: drop the process-wide database handle."""
    global _db_instance
    with _db_lock:
        if _db_instance is not None:
            _db_instance.close()
        _db_instance = None
