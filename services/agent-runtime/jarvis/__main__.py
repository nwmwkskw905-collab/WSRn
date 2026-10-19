"""`python -m jarvis` entrypoint for development and for the frozen executable."""
from __future__ import annotations

import os
import sys

import uvicorn

from .config import CONFIG


def _ensure_streams() -> None:
    """A windowed PyInstaller build has no stdout/stderr; logging would crash.

    We also duplicate the runtime log to `<data_dir>/logs/runtime.log` so the
    desktop's "Logs" screen and post-mortem analysis have something to read.
    """
    if sys.stdout is not None and sys.stderr is not None:
        return
    CONFIG.ensure_dirs()
    log_path = CONFIG.logs_dir / "runtime.log"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    stream = open(log_path, "a", encoding="utf-8", buffering=1)  # noqa: SIM115 - process lifetime
    if sys.stdout is None:
        sys.stdout = stream
    if sys.stderr is None:
        sys.stderr = stream


def main() -> None:
    _ensure_streams()
    host = os.environ.get("JARVIS_HOST", CONFIG.host)
    port = int(os.environ.get("JARVIS_PORT", CONFIG.port))
    uvicorn.run(
        "jarvis.main:app",
        host=host,
        port=port,
        log_level=os.environ.get("JARVIS_LOG_LEVEL", "info"),
        access_log=False,
    )


if __name__ == "__main__":
    main()
