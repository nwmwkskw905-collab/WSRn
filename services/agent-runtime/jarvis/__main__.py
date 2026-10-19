"""`python -m jarvis` entrypoint for development and for the frozen executable."""
from __future__ import annotations

import os

import uvicorn

from .config import CONFIG


def main() -> None:
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
