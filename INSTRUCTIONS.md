# Program Chair Copilot — Run & Build Instructions

## Prerequisites

Make sure you have these installed before anything else:

- **Python 3.10+** — `python --version`
- **Node.js 18+** — `node --version`
- **npm 9+** — `npm --version`

---

## Project layout

```
pcc-desktop/
├── backend/          ← Python/FastAPI server
│   ├── main.py
│   ├── requirements.txt
│   └── ...
├── frontend/         ← React/Vite app
│   ├── src/
│   │   ├── App.jsx               ← layout shell + navigation
│   │   ├── utils/                ← api.js, helpers.js, fileParser.js, theme.js
│   │   ├── components/ui.jsx     ← shared UI primitives
│   │   └── modules/              ← one file per feature tab
│   ├── package.json
│   └── vite.config.js
└── build/
    ├── build.sh
    └── inject_build_date.py
```

---

## 1 — Install dependencies (first time only)

### Backend
```bash
cd backend
pip install -r requirements.txt
```

### Frontend
```bash
cd frontend
npm install
```

---

## 2 — Development mode (fast iteration)

Run backend and frontend in two separate terminals.

**Terminal 1 — backend:**
```bash
cd backend
python main.py
# Server starts at http://127.0.0.1:8000
```

**Terminal 2 — frontend dev server:**
```bash
cd frontend
npm run dev
# Vite starts at http://localhost:5173
# All /api calls are proxied to :8000 automatically
```

Open **http://localhost:5173** in your browser. Changes to any `.jsx` or `.js` file hot-reload instantly.

---

## 3 — Production build (desktop app packaging)

### Step 1 — Build the React frontend
```bash
cd frontend
npm run build
# Output goes to frontend/dist/
```

This runs Terser minification + the JavaScript obfuscator (configured in `vite.config.js`). It takes ~30–60 seconds.

### Step 2 — Package with PyInstaller
```bash
cd build
bash build.sh
```

The script:
1. Runs `inject_build_date.py` to stamp the build date into `backend/trial.py`
2. Calls `pyinstaller` with the correct spec to bundle Python + frontend/dist into a single executable
3. Output lands in `build/dist/`

**macOS:** produces `ProgramChairCopilot.app`  
**Windows:** produces `ProgramChairCopilot.exe`  
**Linux:** produces `ProgramChairCopilot` binary

### Step 3 — Run the packaged app
Double-click the binary, or from the terminal:
```bash
# macOS
open build/dist/ProgramChairCopilot.app

# Windows
build\dist\ProgramChairCopilot.exe

# Linux
./build/dist/ProgramChairCopilot
```

The app opens a browser window at **http://localhost:8000** automatically.

---

## 4 — Configuration storage

API keys and LLM config are stored at:
- **macOS/Linux:** `~/.pcc/config.json`
- **Windows:** `C:\Users\<you>\.pcc\config.json`

Keys are never transmitted anywhere except to your chosen LLM provider.

Log output (when running as packaged app):
- **macOS/Linux:** `~/.pcc/pcc.log`
- **Windows:** `C:\Users\<you>\.pcc\pcc.log`

---

## 5 — Common problems

| Symptom | Fix |
|---|---|
| `npm run dev` fails with module not found | Run `npm install` in the `frontend/` directory |
| Backend import errors on startup | Run `pip install -r requirements.txt` |
| `npm run build` is slow | Normal — the obfuscator adds ~30s. Only needed for distribution. |
| App opens but API calls fail | Make sure the backend is running (`python main.py`) |
| Blank page in dev mode | Check the Vite terminal for JS errors; check backend terminal for Python errors |
| PyInstaller not found | `pip install pyinstaller` |
| Trial days wrong | Check `backend/trial.py` — `TRIAL_DAYS = 14` |

---

## 6 — Resetting the trial (development)

The trial gate reads a build date stamped into `trial.py` by `inject_build_date.py`.  
In **development mode** (`python main.py` directly, not packaged), the trial is inactive — all features are unlocked.

To force a specific build date for testing:
```python
# trial.py — change this line temporarily
BUILD_DATE = "2025-01-01"   # simulates an old build
```

---

## 7 — Adding or editing a module

Each module is a self-contained file in `frontend/src/modules/`. To add a new one:

1. Create `frontend/src/modules/MyModule.jsx`, export a named function component
2. Import it in `App.jsx`
3. Add an entry to the `PHASES` array in `App.jsx`
4. Add a `case "mymodule":` to `renderModule()` in `App.jsx`

If the module calls the LLM, use `callLLM(system, content, maxTokens, "task")` from `utils/api.js` — where `"task"` is one of `screening | reviews | decisions | program | emails | config`. This ensures the correct trial gate is enforced on the backend.
