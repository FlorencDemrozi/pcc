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
    └── pcc.spec
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
# from the project root
bash build/build.sh
```

The script:
1. Builds the frontend and installs the Python dependencies
2. Calls `pyinstaller` with `build/pcc.spec` to bundle Python + frontend/dist into a single executable
3. Output lands in `dist/` (at the project root); intermediate files go to `build/work/`

**macOS:** produces `ProgramChairCopilot.app`  
**Windows:** produces `ProgramChairCopilot.exe`  
**Linux:** produces `ProgramChairCopilot` binary

### Step 3 — Run the packaged app
Double-click the binary, or from the terminal:
```bash
# macOS
open dist/ProgramChairCopilot.app

# Windows
dist\ProgramChairCopilot.exe

# Linux
./dist/ProgramChairCopilot
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

---

## 6 — Adding or editing a module

Each module is a self-contained file in `frontend/src/modules/`. To add a new one:

1. Create `frontend/src/modules/MyModule.jsx`, export a named function component
2. Import it in `App.jsx`
3. Add an entry to the `PHASES` array in `App.jsx`
4. Add a `case "mymodule":` to `renderModule()` in `App.jsx`

If the module calls the LLM, use `callLLM(system, content, maxTokens, "task")` from `utils/api.js` — where `"task"` is a module/task name (e.g. `screening | reviews | decisions | program | emails | config`). The backend uses it to pick the fast or full model tier (configurable per module in Settings). All features are free and unrestricted — there is no trial or licence gate.
