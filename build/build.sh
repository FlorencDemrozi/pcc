#!/bin/bash
# build.sh — build the Program Chair Copilot desktop app
# Run from the project root: ./build/build.sh
# Produces: dist/ProgramChairCopilot (Linux/macOS) or dist/ProgramChairCopilot.exe (Windows)

set -e
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
echo ""
echo "══════════════════════════════════════════════"
echo "  Program Chair Copilot — build"
echo "  Root: $ROOT"
echo "══════════════════════════════════════════════"
echo ""

# One Python interpreter for pip and PyInstaller, so the packages and the
# packager always match. Set PYTHON=... to override. "python" first (Windows),
# then "python3" (macOS/Linux, where "python" may be missing or Python 2).
if [ -z "$PYTHON" ]; then
  for cand in python python3; do
    if command -v "$cand" >/dev/null 2>&1 && "$cand" -c 'import sys; sys.exit(sys.version_info[0] != 3)' 2>/dev/null; then
      PYTHON="$cand"; break
    fi
  done
fi
if [ -z "$PYTHON" ]; then
  echo "✗ Python 3 not found. Install it or set PYTHON=/path/to/python3." >&2
  exit 1
fi
echo "Using Python: $("$PYTHON" -c 'import sys; print(sys.executable, sys.version.split()[0])')"
echo ""

# ── 1. Build + minify + obfuscate React frontend ──────────────────────────────
# Terser minifies (drop_console, mangle toplevel)
# javascript-obfuscator runs on top: string array encoding, control flow
# flattening, dead code injection, hex identifier names.
echo "▶ Building and obfuscating React frontend…"
cd "$ROOT/frontend"
npm install --silent
npm run build
echo "✓ Frontend built, minified, and obfuscated → frontend/dist/"

# ── 2. Install Python dependencies ───────────────────────────────────────────
echo "▶ Installing Python dependencies…"
cd "$ROOT/backend"
"$PYTHON" -m pip install -r requirements.txt pyinstaller --quiet
echo "✓ Python dependencies installed"

# ── 3. Run PyInstaller ────────────────────────────────────────────────────────
# Python source is compiled to .pyc bytecode inside the binary.
# optimize=2 strips docstrings and assertions.
echo "▶ Running PyInstaller…"
cd "$ROOT"
"$PYTHON" -m PyInstaller build/pcc.spec \
  --distpath dist \
  --workpath build/work \
  --noconfirm \
  --clean

echo ""
echo "══════════════════════════════════════════════"
echo "  ✓ Build complete!"
echo ""
echo "  Output: $ROOT/dist/ProgramChairCopilot"
echo ""
echo "  Protection summary:"
echo "    Python  → compiled .pyc bytecode (not human-readable)"
echo "    JS/JSX  → Terser minified + javascript-obfuscator"
echo "              (hex identifiers, string arrays, control flow"
echo "               flattening, dead code injection)"
echo ""
echo "  Distribute only: dist/ProgramChairCopilot"
echo "  Never distribute: the source .py / .jsx files"
echo "══════════════════════════════════════════════"
echo ""
