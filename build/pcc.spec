# pcc.spec — PyInstaller build specification for Program Chair Copilot
# Run: pyinstaller pcc.spec

import sys
from pathlib import Path

ROOT = Path(SPECPATH).parent
BACKEND = ROOT / "backend"
FRONTEND_DIST = ROOT / "frontend" / "dist"

a = Analysis(
    [str(BACKEND / "main.py")],
    pathex=[str(BACKEND)],
    binaries=[],
    datas=[
        # Bundle the entire built React frontend
        (str(ROOT / 'LICENSE.txt'), '.'),
        (str(FRONTEND_DIST), "frontend/dist"),
    ],
    hiddenimports=[
        "uvicorn.logging",
        "uvicorn.loops",
        "uvicorn.loops.auto",
        "uvicorn.loops.asyncio",
        "uvicorn.protocols",
        "uvicorn.protocols.http",
        "uvicorn.protocols.http.auto",
        "uvicorn.protocols.http.h11_impl",
        "uvicorn.protocols.websockets",
        "uvicorn.protocols.websockets.auto",
        "uvicorn.lifespan",
        "uvicorn.lifespan.on",
        "fastapi",
        "pdfplumber",
        "pdfminer",
        "pdfminer.high_level",
        "pdfminer.layout",
        "pdfminer.pdfpage",
        "openpyxl",
        "httpx",
        "anyio",
        "anyio._backends._asyncio",
        "starlette",
        "starlette.middleware.cors",
        "starlette.staticfiles",
        "multipart",
        "config",
        "pdf_checker",
        "meta_checker",
        "review_stats",
        "coi_checker",
        "llm_provider",
        "file_parser",
        "decisions",
        "affiliation_expander",
        "rapidfuzz",
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["tkinter", "matplotlib", "numpy", "pandas", "PIL"],
    noarchive=False,
    optimize=2,  # .pyc bytecode optimisation — removes docstrings, asserts
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    name="ProgramChairCopilot",
    debug=False,
    bootloader_ignore_signals=False,
    strip=True,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,   # No terminal window on Windows/macOS
    onefile=True,    # Single executable
    icon=None,       # Add icon path here if you have one: "assets/icon.ico"
)

# macOS .app bundle
if sys.platform == "darwin":
    app = BUNDLE(
        exe,
        name="ProgramChairCopilot.app",
        icon=None,
        bundle_identifier="org.pcc.programchaircopilot",
        info_plist={
            "CFBundleShortVersionString": "1.0.0",
            "CFBundleVersion": "1.0.0",
            "NSHighResolutionCapable": True,
        },
    )
