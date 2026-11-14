"""Runs the enabled checks on one paper.

- Extracts the document model once per file hash (cached in the store).
- Runs deterministic checks first, then network checks (only if allowed).
- Skips a check when the file, the check version and its settings are all
  unchanged since the last run, and reuses the stored findings.
- A failing check is recorded as an error; it never stops the other checks.
"""

import hashlib
import json
import traceback

from . import docmodel
from .findings import Finding, SEVERITIES
from .registry import CHECKS, ordered_checks, CATEGORIES

# Conference-level settings the checks read, with defaults.
CONF_DEFAULTS = {
    "max_pages": 6,
    "refs_excluded": False,      # references do not count towards the page limit
    "double_blind": True,
    "paper_size": "any",         # any | letter | a4
    "template": "any",           # any | ieee | acm | lncs
}


class Ctx:
    """What a check gets besides the document model."""
    def __init__(self, paper: dict, conf: dict, params: dict, store, spec):
        self.paper = paper           # {paper_id, title, abstract, keywords, track, paper_type, authors: [names]}
        self.conf = conf
        self.params = params
        self.store = store
        self.spec = spec


def effective_profile(profile: dict | None) -> dict:
    profile = profile or {}
    out = {"enabled": {}, "params": {}, "allow_network": bool(profile.get("allow_network", False))}
    for spec in CHECKS.values():
        out["enabled"][spec.id] = bool((profile.get("enabled") or {}).get(spec.id, spec.default_enabled))
        p = dict(spec.params)
        p.update({k: v for k, v in ((profile.get("params") or {}).get(spec.id) or {}).items() if k in spec.params})
        out["params"][spec.id] = p
    return out


def _hash(obj) -> str:
    return hashlib.sha1(json.dumps(obj, sort_keys=True, ensure_ascii=False, default=str).encode()).hexdigest()[:16]


def _status(findings: list[dict]) -> str:
    outs = {f["outcome"] for f in findings}
    if "issue" in outs:
        return "issue"
    if "possible" in outs:
        return "possible"
    return "pass"


def get_doc(store, pdf_bytes: bytes, filename: str):
    sha = hashlib.sha256(pdf_bytes).hexdigest()
    doc = store.get_extraction(sha, docmodel.DOCMODEL_VERSION)
    cached = doc is not None
    if not cached:
        doc = docmodel.build(pdf_bytes, sha, filename)
        store.put_extraction(sha, docmodel.DOCMODEL_VERSION, doc)
    return sha, doc, cached


def run_paper(store, pdf_bytes: bytes, filename: str, paper: dict, conf: dict, profile: dict, force=False) -> dict:
    conf = {**CONF_DEFAULTS, **{k: v for k, v in (conf or {}).items() if v is not None}}
    prof = effective_profile(profile)
    sha, doc, cached = get_doc(store, pdf_bytes, filename)
    pid = str(paper.get("paper_id") or filename)
    store.upsert_paper(pid, filename, sha, paper.get("track", ""), paper.get("title", ""),
                       paper.get("paper_type", ""), paper, doc.get("n_pages", 0))

    active = []
    for spec in ordered_checks():
        if not prof["enabled"].get(spec.id):
            continue
        if spec.needs_double_blind and not conf.get("double_blind"):
            continue
        if spec.exec_kind == "network" and not prof["allow_network"]:
            continue
        if spec.exec_kind == "llm":
            continue  # not wired yet
        active.append(spec)
    store.drop_runs_not_in(pid, [s.id for s in active])

    reused = 0
    for spec in active:
        params = prof["params"][spec.id]
        settings_hash = _hash({"params": params, "conf": conf, "paper": paper, "model": docmodel.DOCMODEL_VERSION})
        prev = store.get_run(pid, spec.id)
        if (not force and not spec.volatile and prev and prev["sha256"] == sha
                and prev["check_version"] == spec.version and prev["settings_hash"] == settings_hash
                and prev["status"] != "error"):
            reused += 1
            continue
        if doc.get("error") and spec.id != "file_opens":
            store.save_run(pid, spec.id, sha, spec.version, settings_hash, "skipped", "PDF could not be read", [])
            continue
        try:
            raw = spec.fn(doc, Ctx(paper, conf, params, store, spec)) or []
            out = []
            for f in raw:
                if not isinstance(f, Finding):
                    continue
                f.category = spec.category; f.kind = spec.kind; f.section = spec.section
                if f.severity not in SEVERITIES:
                    f.severity = "medium"
                out.append(f.to_dict())
            # identical keys (same evidence) collapse into one
            uniq = {f["key"]: f for f in out}
            out = list(uniq.values())
            store.save_run(pid, spec.id, sha, spec.version, settings_hash, _status(out), None, out)
        except Exception as e:
            err = f"{type(e).__name__}: {e}"
            traceback.print_exc()
            store.save_run(pid, spec.id, sha, spec.version, settings_hash, "error", err[:300], [])

    res = paper_result(store, pid)
    res["extraction_cached"] = cached
    res["checks_reused"] = reused
    return res


def paper_result(store, pid: str) -> dict:
    p = next((x for x in store.papers() if x["paper_id"] == pid), None) or {"paper_id": pid}
    decisions = store.decisions(pid)
    findings = store.findings(pid)
    for f in findings:
        d = decisions.get((pid, f["key"]))
        f["decision"] = d["decision"] if d else "open"
        f["decision_note"] = d["note"] if d else ""
    order = {s: i for i, s in enumerate(SEVERITIES)}
    findings.sort(key=lambda f: (f["kind"] != "technical", order.get(f["severity"], 9), f["category"], f["check_id"]))
    runs = store.runs(pid)
    doc = store.get_extraction(p.get("sha256", ""), docmodel.DOCMODEL_VERSION) or {}
    return {
        "paper_id": pid, "filename": p.get("filename", ""), "sha256": p.get("sha256", ""),
        "track": p.get("track", ""), "title": p.get("title", ""), "paper_type": p.get("paper_type", ""),
        "n_pages": doc.get("n_pages", 0), "extraction_error": doc.get("error"),
        "versions": store.versions(pid), "last_run": p.get("last_run"),
        "checks": {k: {**v, "title": CHECKS[k].title if k in CHECKS else k,
                       "category": CHECKS[k].category if k in CHECKS else ""} for k, v in runs.items()},
        "findings": findings,
    }


def all_results(store) -> list[dict]:
    return [paper_result(store, p["paper_id"]) for p in store.papers()]


def catalogue() -> dict:
    return {"categories": CATEGORIES, "checks": [s.public() for s in ordered_checks()],
            "conf_defaults": CONF_DEFAULTS}
