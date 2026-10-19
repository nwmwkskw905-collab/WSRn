"""Runtime configuration and filesystem layout.

All mutable state lives outside the repository, in the per-user data directory.
"""
from __future__ import annotations

import os
import sys
from dataclasses import dataclass, field
from pathlib import Path


def _default_data_dir() -> Path:
    override = os.environ.get("JARVIS_DATA_DIR")
    if override:
        return Path(override).expanduser().resolve()
    if sys.platform == "win32":
        base = os.environ.get("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
        return Path(base) / "JARVIS"
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / "JARVIS"
    return Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share")) / "jarvis"


def _env_bool(name: str, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


@dataclass
class RuntimeConfig:
    data_dir: Path = field(default_factory=_default_data_dir)
    host: str = field(default_factory=lambda: os.environ.get("JARVIS_HOST", "127.0.0.1"))
    port: int = field(default_factory=lambda: int(os.environ.get("JARVIS_PORT", "8765")))
    demo_mode: bool = field(default_factory=lambda: _env_bool("JARVIS_DEMO_MODE", False))
    require_auth: bool = field(default_factory=lambda: _env_bool("JARVIS_REQUIRE_AUTH", True))
    # Comma separated origins allowed to call the local API (vite dev + packaged app).
    allowed_origins: tuple[str, ...] = field(
        default_factory=lambda: tuple(
            o.strip()
            for o in os.environ.get(
                "JARVIS_ALLOWED_ORIGINS",
                "http://localhost:5173,http://127.0.0.1:5173,file://,null",
            ).split(",")
            if o.strip()
        )
    )
    max_concurrent_tasks: int = field(default_factory=lambda: int(os.environ.get("JARVIS_MAX_TASKS", "3")))
    api_budget_usd: float = field(default_factory=lambda: float(os.environ.get("JARVIS_API_BUDGET_USD", "0")))
    api_budget_monthly_usd: float = field(
        default_factory=lambda: float(os.environ.get("JARVIS_API_BUDGET_MONTHLY_USD", "0"))
    )
    max_tool_calls_per_task: int = field(default_factory=lambda: int(os.environ.get("JARVIS_MAX_TOOL_CALLS", "40")))
    offline: bool = field(default_factory=lambda: _env_bool("JARVIS_OFFLINE", False))
    auto_start_worker: bool = field(default_factory=lambda: _env_bool("JARVIS_AUTO_WORKER", True))

    @property
    def db_path(self) -> Path:
        return self.data_dir / "jarvis.sqlite3"

    @property
    def token_path(self) -> Path:
        return self.data_dir / "runtime-token"

    @property
    def vault_key_path(self) -> Path:
        return self.data_dir / "vault.key"

    @property
    def workspace_dir(self) -> Path:
        return self.data_dir / "workspace"

    @property
    def logs_dir(self) -> Path:
        return self.data_dir / "logs"

    @property
    def backups_dir(self) -> Path:
        return self.data_dir / "backups"

    @property
    def downloads_guard_dir(self) -> Path:
        return self.data_dir / "sandbox"

    def ensure_dirs(self) -> None:
        for path in (
            self.data_dir,
            self.workspace_dir,
            self.logs_dir,
            self.backups_dir,
            self.downloads_guard_dir,
        ):
            path.mkdir(parents=True, exist_ok=True)
        if os.name != "nt":
            try:
                os.chmod(self.data_dir, 0o700)
            except OSError:
                pass


CONFIG = RuntimeConfig()
