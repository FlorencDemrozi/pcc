# Program Chair Copilot

> A desktop tool that automates the mechanical work of running an IEEE conference — so you can focus on the science.

Program chairs spend 30–50 hours per conference on tasks that don't require judgment: checking PDFs for page limits, hunting for conflicts of interest, computing reviewer statistics, and drafting notifications. **PCC handles all of that in minutes**, running entirely on your machine with your own LLM API key.

---

## What it does

| Module | What gets automated |
|---|---|
| **PDF Compliance** | Page count, double-blind, column layout, copyright notice, camera-ready stamp — per paper, in bulk |
| **Metadata Checker** | Abstract length, keyword count, missing fields, valid track — from your EasyChair export |
| **COI Detector** | Fuzzy affiliation matching, email domain overlap, ROR institution lookup — flags potential conflicts before assignment |
| **Review Statistics** | Coverage gaps, overloaded reviewers, score variance, reviewer calibration, quality tiers |
| **Decision Assistant** | LLM-assisted accept/reject recommendations with rationale — you stay in control |
| **Program Builder** | Generates a structured conference program from your accepted papers |
| **Email Drafts** | Notification emails for authors, reviewers, and session chairs |

Everything runs **locally**. Your papers and reviews never leave your machine.

---

## How it works

PCC is a self-contained desktop app: a Python/FastAPI backend bundled with a React frontend, packaged as a single executable. Open it and a browser window appears at `localhost:8000`. No cloud, no subscription, no data sharing.

You bring your own LLM API key (Claude, OpenAI, Gemini, Groq, or a local Ollama model). Deterministic checks — PDF parsing, COI matching, statistics — run without any LLM call at all.

```
Your files  →  PCC (local)  →  Your LLM API  →  Results
              (never leaves your machine except the text sent to your chosen provider)
```

---

## Getting started

**Download** a pre-built binary from the [releases page](../../releases), or build from source:

```bash
# 1. Install dependencies
cd backend && pip install -r requirements.txt
cd ../frontend && npm install

# 2. Run in development mode
cd backend && python main.py          # terminal 1
cd frontend && npm run dev            # terminal 2
# → open http://localhost:5173
```

Full build and packaging instructions are in [`INSTRUCTIONS.md`](INSTRUCTIONS.md).

---

## Supported file formats

PCC reads whatever EasyChair exports:

- **Review files** — `.txt` (both `***** PAPER *****` and `LIST OF REVIEWS` formats), `review_summary.xlsx`
- **Submissions** — `submissions.xlsx`, `submissions.csv`
- **Author lists** — `authors.xlsx`
- **TPC lists** — `tpc_members.xlsx`, `.csv`
- **Papers** — `.pdf` (individual or as a `.zip` of a full batch)

---

## LLM providers

| Provider | Models | Notes |
|---|---|---|
| Anthropic Claude | claude-3-5-sonnet, claude-3-haiku | Recommended for screening and decisions |
| OpenAI | gpt-4o, gpt-4o-mini | Full support |
| Google Gemini | gemini-1.5-pro, gemini-1.5-flash | Full support |
| Groq | llama-3, mixtral | Fast, good for large batches |
| Ollama | any local model | Runs fully offline |

API keys are stored locally at `~/.pcc/config.json` and never transmitted anywhere except to your chosen provider.

---

## Research context

PCC is being developed as part of a research project on AI-assisted academic conference management at the University of Stavanger. If you use the tool to chair a conference, we'd appreciate 5 minutes of feedback — it directly informs our study.

**[Leave feedback →](https://your-form-link-here)**

---

## Project structure

```
pcc-desktop/
├── backend/          Python/FastAPI — all processing logic
├── frontend/         React/Vite — the UI
│   └── src/modules/  One file per feature tab
├── build/            PyInstaller packaging scripts
└── website/          Landing page (GitHub Pages)
```

---

## Contributing

Issues and pull requests are welcome. The codebase is intentionally modular — each feature tab in `frontend/src/modules/` and each backend checker in `backend/` are self-contained and easy to extend.

If you want to add support for a new submission system (HotCRP, OpenReview, Linklings), the place to start is `backend/file_parser.py`.

---

## License

MIT — use it, fork it, extend it. If you publish results using PCC, a citation would be appreciated (paper forthcoming).

---

*Built by [Florenc Demrozi](mailto:florenc1991@gmail.com) · University of Stavanger / University of Catania*
