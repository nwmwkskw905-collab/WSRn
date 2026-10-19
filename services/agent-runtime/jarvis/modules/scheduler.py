"""Persistent scheduler. Local-only: if the PC is off, nothing runs."""
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from typing import Any, Awaitable, Callable

from ..db import get_db, new_id, now_iso


class Scheduler:
    def __init__(self) -> None:
        self.db = get_db()
        self._stop = asyncio.Event()
        self._task: asyncio.Task | None = None
        self._runner: Callable[[dict[str, Any]], Awaitable[Any]] | None = None

    def create(self, name: str, objective: str, interval_seconds: int | None = None,
               cron: str | None = None, autonomy_level: int = 1) -> dict[str, Any]:
        if not interval_seconds and not cron:
            raise ValueError("Informe interval_seconds ou cron")
        if cron and not _valid_simple_cron(cron):
            raise ValueError("Cron suportado: 'M H * * *' (UTC, diario)")
        schedule_id = new_id("sch_")
        next_run = _next_run(interval_seconds, cron)
        ts = now_iso()
        self.db.execute(
            "INSERT INTO schedules(id, name, objective, cron, interval_seconds, next_run_at, enabled, autonomy_level, created_at, updated_at)"
            " VALUES (?,?,?,?,?,?,1,?,?,?)",
            (schedule_id, name, objective, cron, interval_seconds, next_run.isoformat(), autonomy_level, ts, ts),
        )
        return self.get(schedule_id)

    def get(self, schedule_id: str) -> dict[str, Any]:
        row = self.db.one("SELECT * FROM schedules WHERE id=?", (schedule_id,))
        if not row:
            raise KeyError("Agendamento nao encontrado")
        return row

    def list(self) -> list[dict[str, Any]]:
        return self.db.query("SELECT * FROM schedules ORDER BY created_at DESC")

    def set_enabled(self, schedule_id: str, enabled: bool) -> dict[str, Any]:
        self.db.execute(
            "UPDATE schedules SET enabled=?, updated_at=?, next_run_at=? WHERE id=?",
            (1 if enabled else 0, now_iso(), _next_run(self.get(schedule_id).get("interval_seconds"), self.get(schedule_id).get("cron")).isoformat(), schedule_id),
        )
        return self.get(schedule_id)

    def due(self, now: datetime | None = None) -> list[dict[str, Any]]:
        now = now or datetime.now(timezone.utc)
        due = []
        for row in self.db.query("SELECT * FROM schedules WHERE enabled=1"):
            try:
                nxt = datetime.fromisoformat(row["next_run_at"]) if row["next_run_at"] else now
            except ValueError:
                nxt = now
            if nxt.tzinfo is None:
                nxt = nxt.replace(tzinfo=timezone.utc)
            if nxt <= now:
                due.append(row)
        return due

    def mark_run(self, schedule_id: str, task_id: str | None, error: str | None = None) -> None:
        row = self.get(schedule_id)
        nxt = _next_run(row.get("interval_seconds"), row.get("cron"))
        self.db.execute(
            "UPDATE schedules SET last_run_at=?, next_run_at=?, last_task_id=?, last_error=?, updated_at=? WHERE id=?",
            (now_iso(), nxt.isoformat(), task_id, error, now_iso(), schedule_id),
        )

    def start(self, runner: Callable[[dict[str, Any]], Awaitable[Any]]) -> None:
        if self._task and not self._task.done():
            return
        self._runner = runner
        self._stop.clear()
        self._task = asyncio.create_task(self._loop())

    async def stop(self) -> None:
        self._stop.set()
        if self._task:
            await asyncio.wait([self._task], timeout=5)

    async def _loop(self) -> None:
        while not self._stop.is_set():
            try:
                for row in self.due():
                    if self.db.get_state("kill_switch", False):
                        continue
                    try:
                        result = await self._runner(row) if self._runner else None
                        task_id = getattr(result, "id", None) or (result or {}).get("id") if isinstance(result, dict) else None
                        self.mark_run(row["id"], task_id)
                    except Exception as exc:  # noqa: BLE001
                        self.mark_run(row["id"], None, str(exc)[:500])
            except Exception:  # noqa: BLE001 - scheduler must never crash the app
                pass
            try:
                await asyncio.wait_for(self._stop.wait(), timeout=20)
            except asyncio.TimeoutError:
                continue


def _valid_simple_cron(expr: str) -> bool:
    parts = expr.split()
    if len(parts) != 5:
        return False
    try:
        minute, hour = int(parts[0]), int(parts[1])
    except ValueError:
        return False
    return 0 <= minute < 60 and 0 <= hour < 24 and parts[2:] == ["*", "*", "*"]


def _next_run(interval_seconds: int | None, cron: str | None) -> datetime:
    now = datetime.now(timezone.utc)
    if interval_seconds:
        return now + timedelta(seconds=max(60, int(interval_seconds)))
    if cron:
        minute, hour = [int(x) for x in cron.split()[:2]]
        candidate = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
        if candidate <= now:
            candidate += timedelta(days=1)
        return candidate
    return now + timedelta(days=1)


_scheduler: Scheduler | None = None


def get_scheduler() -> Scheduler:
    global _scheduler
    if _scheduler is None:
        _scheduler = Scheduler()
    return _scheduler
