"""PyInstaller entrypoint.

Kept outside the `jarvis` package on purpose: PyInstaller executes the entry script as
`__main__`, which breaks relative imports (`from .config import ...`). Importing the
package explicitly keeps `jarvis.__main__` working exactly as in development.
"""
from jarvis.__main__ import main

if __name__ == "__main__":
    main()
