# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for the JARVIS local runtime (Windows x64).

The Electron main process spawns `<resources>/backend/jarvis-agent-runtime.exe`.
The build is onedir on purpose: onefile extracts to a temp directory and Windows
Defender frequently delays that, which would push startup past the 40s health
timeout used by apps/desktop/src/main/backend.ts.
"""
from PyInstaller.utils.hooks import collect_submodules, collect_data_files

hiddenimports = []
hiddenimports += collect_submodules("uvicorn")
hiddenimports += collect_submodules("jarvis")
hiddenimports += collect_submodules("pydantic")
hiddenimports += collect_submodules("fastapi")
hiddenimports += [
    "uvicorn.logging",
    "uvicorn.loops.auto",
    "uvicorn.loops.asyncio",
    "uvicorn.protocols.http.auto",
    "uvicorn.protocols.http.h11_impl",
    "uvicorn.protocols.websockets.auto",
    "uvicorn.lifespan.on",
    "sqlite3",
    "cryptography.hazmat.backends.openssl",
    "cryptography.hazmat.primitives.ciphers.aead",
]

datas = collect_data_files("certifi")

a = Analysis(
    ["runtime_entry.py"],
    pathex=["."],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    runtime_hooks=[],
    excludes=["tkinter", "matplotlib", "numpy", "PIL", "pytest", "IPython"],
    noarchive=False,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="jarvis-agent-runtime",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    # console=True keeps uvicorn's logging working and turns crashes into stderr
    # output instead of a modal dialog. Electron spawns it with windowsHide:true.
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch="x86_64",
    codesign_identity=None,
    entitlements_file=None,
    icon=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="jarvis-agent-runtime",
)
