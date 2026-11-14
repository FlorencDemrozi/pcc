"""Local storage: one SQLite file per conference under ~/.pcc/prereview/.

Uses Python's built-in sqlite3 -- nothing to install. Holds:
  papers / versions   which file (hash) each submission had, and when
  extractions         the cached document model per file hash (zlib JSON)
  check_runs          what ran on which file with which settings (skip if unchanged)
  findings            the findings of the latest run of each check per paper
  decisions           chair decisions per finding, plus a full history (audit trail)
  lookups             cached external lookups (DOI, retractions), shared across papers
  costs               spend records (for LLM checks later)
  settings            the screening profile of this conference
"""

import contextlib
import json
import re
import sqlite3
import threading
import time
import zlib
from pathlib import Path

BASE_DIR = Path.home() / ".pcc" / "prereview"

_SCHEMA = """
CREATE TABLE IF NOT EXISTS papers (
  paper_id TEXT PRIMARY KEY, filename TEXT, sha256 TEXT, track TEXT, title TEXT,
  paper_type TEXT, meta_json TEXT, last_run REAL);
CREATE TABLE IF NOT EXISTS versions (
  paper_id TEXT, sha256 TEXT, filename TEXT, first_seen REAL, n_pages INTEGER,
  PRIMARY KEY (paper_id, sha256));
CREATE TABLE IF NOT EXISTS extractions (
  sha256 TEXT PRIMARY KEY, model_version INTEGER, data BLOB, created REAL);
CREATE TABLE IF NOT EXISTS check_runs (
  paper_id TEXT, check_id TEXT, sha256 TEXT, check_version INTEGER, settings_hash TEXT,
  status TEXT, error TEXT, ran_at REAL, PRIMARY KEY (paper_id, check_id));
CREATE TABLE IF NOT EXISTS findings (
  paper_id TEXT, check_id TEXT, fkey TEXT, data TEXT, created REAL,
  PRIMARY KEY (paper_id, fkey));
CREATE INDEX IF NOT EXISTS findings_by_check ON findings (paper_id, check_id);
CREATE TABLE IF NOT EXISTS decisions (
  paper_id TEXT, fkey TEXT, decision TEXT, note TEXT, at REAL, PRIMARY KEY (paper_id, fkey));
CREATE TABLE IF NOT EXISTS decision_log (
  id INTEGER PRIMARY KEY AUTOINCREMENT, paper_id TEXT, fkey TEXT, decision TEXT, note TEXT, at REAL);
CREATE TABLE IF NOT EXISTS lookups (k TEXT PRIMARY KEY, data TEXT, at REAL);
CREATE TABLE IF NOT EXISTS costs (
  id INTEGER PRIMARY KEY AUTOINCREMENT, paper_id TEXT, check_id TEXT,
  tokens_in INTEGER, tokens_out INTEGER, usd REAL, at REAL);
CREATE TABLE IF NOT EXISTS settings (k TEXT PRIMARY KEY, data TEXT);
"""

DECISIONS = ("confirmed", "dismissed", "clarify", "open")

_locks: dict[str, threading.RLock] = {}
_locks_guard = threading.Lock()


def slug(conference: str) -> str:
    s = re.sub(r'[^A-Za-z0-9._-]+', '-', (conference or "").strip()).strip('-.').lower()
    return s[:60] or "default"


class Store:
    def __init__(self, conference: str, base_dir: Path = None):
        self.conference = slug(conference)
        base = Path(base_dir) if base_dir else BASE_DIR
        base.mkdir(parents=True, exist_ok=True)
        self.path = base / f"{self.conference}.db"
        with _locks_guard:
            self.lock = _locks.setdefault(str(self.path), threading.RLock())
        with self.lock, self._conn() as c:
            c.executescript(_SCHEMA)

    @contextlib.contextmanager
    def _conn(self):
        """Commit on success, roll back on error, and always close: sqlite3's own
        context manager only commits, which leaks open file handles (on Windows
        the .db file then cannot be deleted or moved while the app runs)."""
        c = sqlite3.connect(self.path, timeout=30)
        try:
            c.execute("PRAGMA journal_mode=WAL")
            c.execute("PRAGMA synchronous=NORMAL")
            yield c
            c.commit()
        except Exception:
            c.rollback()
            raise
        finally:
            c.close()

    # ── extraction cache ─────────────────────────────────────────────────────
    def get_extraction(self, sha256: str, model_version: int):
        with self.lock, self._conn() as c:
            row = c.execute("SELECT model_version, data FROM extractions WHERE sha256=?", (sha256,)).fetchone()
        if not row or row[0] != model_version:
            return None
        try:
            return json.loads(zlib.decompress(row[1]).decode("utf-8"))
        except Exception:
            return None

    def put_extraction(self, sha256: str, model_version: int, model: dict):
        blob = zlib.compress(json.dumps(model, ensure_ascii=False).encode("utf-8"), 6)
        with self.lock, self._conn() as c:
            c.execute("INSERT OR REPLACE INTO extractions VALUES (?,?,?,?)", (sha256, model_version, blob, time.time()))

    # ── papers / versions ────────────────────────────────────────────────────
    def upsert_paper(self, paper_id, filename, sha256, track, title, paper_type, meta, n_pages):
        now = time.time()
        with self.lock, self._conn() as c:
            c.execute("""INSERT INTO papers VALUES (?,?,?,?,?,?,?,?)
                         ON CONFLICT(paper_id) DO UPDATE SET filename=excluded.filename, sha256=excluded.sha256,
                         track=excluded.track, title=excluded.title, paper_type=excluded.paper_type,
                         meta_json=excluded.meta_json, last_run=excluded.last_run""",
                      (paper_id, filename, sha256, track, title, paper_type, json.dumps(meta, ensure_ascii=False), now))
            c.execute("INSERT OR IGNORE INTO versions VALUES (?,?,?,?,?)", (paper_id, sha256, filename, now, n_pages))

    def versions(self, paper_id):
        with self.lock, self._conn() as c:
            rows = c.execute("SELECT sha256, filename, first_seen, n_pages FROM versions WHERE paper_id=? ORDER BY first_seen",
                             (paper_id,)).fetchall()
        return [{"sha256": r[0], "filename": r[1], "first_seen": r[2], "n_pages": r[3]} for r in rows]

    def papers_with_hash(self, sha256, exclude_paper=None):
        with self.lock, self._conn() as c:
            rows = c.execute("SELECT paper_id FROM papers WHERE sha256=? AND paper_id<>?", (sha256, exclude_paper or "")).fetchall()
        return [r[0] for r in rows]

    # ── check runs + findings ────────────────────────────────────────────────
    def get_run(self, paper_id, check_id):
        with self.lock, self._conn() as c:
            r = c.execute("SELECT sha256, check_version, settings_hash, status, error, ran_at FROM check_runs "
                          "WHERE paper_id=? AND check_id=?", (paper_id, check_id)).fetchone()
        return None if not r else {"sha256": r[0], "check_version": r[1], "settings_hash": r[2],
                                   "status": r[3], "error": r[4], "ran_at": r[5]}

    def save_run(self, paper_id, check_id, sha256, check_version, settings_hash, status, error, findings: list[dict]):
        now = time.time()
        with self.lock, self._conn() as c:
            c.execute("INSERT OR REPLACE INTO check_runs VALUES (?,?,?,?,?,?,?,?)",
                      (paper_id, check_id, sha256, check_version, settings_hash, status, error, now))
            c.execute("DELETE FROM findings WHERE paper_id=? AND check_id=?", (paper_id, check_id))
            c.executemany("INSERT OR REPLACE INTO findings VALUES (?,?,?,?,?)",
                          [(paper_id, check_id, f["key"], json.dumps(f, ensure_ascii=False), now) for f in findings])

    def drop_runs_not_in(self, paper_id, check_ids):
        """Forget results of checks that are now switched off."""
        q = ",".join("?" * len(check_ids)) or "''"
        with self.lock, self._conn() as c:
            c.execute(f"DELETE FROM check_runs WHERE paper_id=? AND check_id NOT IN ({q})", (paper_id, *check_ids))
            c.execute(f"DELETE FROM findings WHERE paper_id=? AND check_id NOT IN ({q})", (paper_id, *check_ids))

    def findings(self, paper_id):
        with self.lock, self._conn() as c:
            rows = c.execute("SELECT data FROM findings WHERE paper_id=?", (paper_id,)).fetchall()
        return [json.loads(r[0]) for r in rows]

    def runs(self, paper_id):
        with self.lock, self._conn() as c:
            rows = c.execute("SELECT check_id, status, error, ran_at FROM check_runs WHERE paper_id=?", (paper_id,)).fetchall()
        return {r[0]: {"status": r[1], "error": r[2], "ran_at": r[3]} for r in rows}

    # ── decisions (audit trail) ──────────────────────────────────────────────
    def set_decision(self, paper_id, fkey, decision, note=""):
        if decision not in DECISIONS:
            raise ValueError(f"decision must be one of {DECISIONS}")
        now = time.time()
        with self.lock, self._conn() as c:
            if decision == "open":
                c.execute("DELETE FROM decisions WHERE paper_id=? AND fkey=?", (paper_id, fkey))
            else:
                c.execute("INSERT OR REPLACE INTO decisions VALUES (?,?,?,?,?)", (paper_id, fkey, decision, note, now))
            c.execute("INSERT INTO decision_log (paper_id, fkey, decision, note, at) VALUES (?,?,?,?,?)",
                      (paper_id, fkey, decision, note, now))

    def decisions(self, paper_id=None):
        with self.lock, self._conn() as c:
            if paper_id is None:
                rows = c.execute("SELECT paper_id, fkey, decision, note, at FROM decisions").fetchall()
            else:
                rows = c.execute("SELECT paper_id, fkey, decision, note, at FROM decisions WHERE paper_id=?", (paper_id,)).fetchall()
        return {(r[0], r[1]): {"decision": r[2], "note": r[3], "at": r[4]} for r in rows}

    def decision_log(self, paper_id=None):
        with self.lock, self._conn() as c:
            if paper_id:
                rows = c.execute("SELECT paper_id, fkey, decision, note, at FROM decision_log WHERE paper_id=? ORDER BY id", (paper_id,)).fetchall()
            else:
                rows = c.execute("SELECT paper_id, fkey, decision, note, at FROM decision_log ORDER BY id").fetchall()
        return [{"paper_id": r[0], "key": r[1], "decision": r[2], "note": r[3], "at": r[4]} for r in rows]

    # ── lookups (shared external cache) ──────────────────────────────────────
    def get_lookup(self, k, max_age_s=30 * 86400):
        with self.lock, self._conn() as c:
            r = c.execute("SELECT data, at FROM lookups WHERE k=?", (k,)).fetchone()
        if not r or time.time() - r[1] > max_age_s:
            return None
        return json.loads(r[0])

    def put_lookup(self, k, data):
        with self.lock, self._conn() as c:
            c.execute("INSERT OR REPLACE INTO lookups VALUES (?,?,?)", (k, json.dumps(data, ensure_ascii=False), time.time()))

    # ── settings / overview ──────────────────────────────────────────────────
    def get_setting(self, k, default=None):
        with self.lock, self._conn() as c:
            r = c.execute("SELECT data FROM settings WHERE k=?", (k,)).fetchone()
        return json.loads(r[0]) if r else default

    def put_setting(self, k, data):
        with self.lock, self._conn() as c:
            c.execute("INSERT OR REPLACE INTO settings VALUES (?,?)", (k, json.dumps(data, ensure_ascii=False)))

    def papers(self):
        with self.lock, self._conn() as c:
            rows = c.execute("SELECT paper_id, filename, sha256, track, title, paper_type, meta_json, last_run FROM papers").fetchall()
        return [{"paper_id": r[0], "filename": r[1], "sha256": r[2], "track": r[3], "title": r[4],
                 "paper_type": r[5], "meta": json.loads(r[6] or "{}"), "last_run": r[7]} for r in rows]

    def clear_results(self):
        """Delete papers, runs, findings (keeps decisions, their log, lookups and the extraction cache)."""
        with self.lock, self._conn() as c:
            for t in ("papers", "check_runs", "findings"):
                c.execute(f"DELETE FROM {t}")
