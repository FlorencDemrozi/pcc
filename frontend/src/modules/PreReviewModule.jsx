import { useState, useEffect, useMemo } from "react";
import { C } from "../utils/theme.js";
import { StatCard, SectionTitle, ProgressBar, PrimaryButton, GhostButton, EmptyState, InfoBanner } from "../components/ui.jsx";
import { backendPost, errorFromResponse } from "../utils/api.js";
import { exportCSV, extractPaperId, knownIdSet, matchMeta, getField, rowId } from "../utils/helpers.js";
import { useRunGuard } from "../utils/useRunGuard.js";

// Pre-review screening: evidence for the chairs, never a verdict.
// Results, decisions and the extraction cache are stored by the backend in a
// local SQLite file per conference, so they are still here after a restart.

const SEV_ORDER = { high: 0, medium: 1, low: 2, info: 3 };
const SEV_LABEL = { high: "High", medium: "Medium", low: "Low", info: "Info" };
const OUTCOME_LABEL = { issue: "Issue", possible: "Possible", info: "Info" };
const DECISION_LABEL = { open: "Open", confirmed: "Confirmed", dismissed: "Dismissed", clarify: "Ask authors" };

const sevColor = s => ({ high: C.red, medium: C.amber, low: C.blue, info: C.muted }[s] || C.muted);
const decColor = d => ({ confirmed: C.red, dismissed: C.muted, clarify: C.amber, open: C.textSoft }[d] || C.muted);

async function getJSON(path) {
  const r = await fetch(path);
  if (!r.ok) throw await errorFromResponse(r);
  return r.json();
}
async function postJSON(path, body) {
  const r = await fetch(path, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
  if (!r.ok) throw await errorFromResponse(r);
  return r.json();
}

function confKey(conf) {
  const k = [conf.acronym || conf.name, conf.year].filter(Boolean).join("-");
  return k || "default";
}

function SevPill({ sev, outcome }) {
  const col = sevColor(sev);
  return (
    <span style={{ fontSize: 10, fontWeight: 700, padding: "1px 6px", borderRadius: 3, whiteSpace: "nowrap",
      background: col + "1c", color: col, border: `1px ${outcome === "possible" ? "dashed" : "solid"} ${col}55`, fontFamily: C.sans }}>
      {SEV_LABEL[sev] || sev}{outcome === "possible" ? " · possible" : ""}
    </span>
  );
}

function Toggle({ checked, onChange, label, hint }) {
  return (
    <label style={{ display: "flex", gap: 8, alignItems: "flex-start", fontSize: 12, color: C.text, cursor: "pointer", marginBottom: 6 }}>
      <input type="checkbox" checked={!!checked} onChange={e => onChange(e.target.checked)} style={{ marginTop: 2 }} />
      <span>{label}{hint && <span style={{ display: "block", fontSize: 10, color: C.muted, marginTop: 1 }}>{hint}</span>}</span>
    </label>
  );
}

const selStyle = () => ({ background: C.panelAlt, color: C.text, border: `1px solid ${C.border}`, borderRadius: 5,
  padding: "4px 8px", fontSize: 12, fontFamily: C.sans });

export function PreReviewModule({ conf, pdfFiles, metaRows, authorRows, activeTrack = "All" }) {
  const conference = confKey(conf);
  const [catalogue, setCatalogue] = useState(null);
  const [profile, setProfile]     = useState({ enabled: {}, allow_network: false });
  const [screenConf, setScreenConf] = useState({ paper_size: "any", template: "any" });
  const [papers, setPapers]       = useState([]);       // results from the backend
  const [dbPath, setDbPath]       = useState("");
  const [loadErr, setLoadErr]     = useState("");
  const [running, setRunning]     = useState(false);
  const [prog, setProg]           = useState({ done: 0, total: 0, cur: "" });
  const [runErrors, setRunErrors] = useState([]);
  const [force, setForce]         = useState(false);
  const [showSettings, setShowSettings] = useState(false);
  const [trackFilter, setTrackFilter] = useState(activeTrack);
  const [catFilter, setCatFilter] = useState("All");
  const [minSev, setMinSev]       = useState("low");
  const [onlyOpen, setOnlyOpen]   = useState(false);
  const [search, setSearch]       = useState("");
  const [selected, setSelected]   = useState(null);
  const [pdfUrl, setPdfUrl]       = useState(null);
  const guard = useRunGuard();

  useEffect(() => setTrackFilter(activeTrack), [activeTrack]);
  useEffect(() => () => { if (pdfUrl) URL.revokeObjectURL(pdfUrl); }, [pdfUrl]);

  // Load the check catalogue, this conference's profile and stored results
  useEffect(() => {
    let alive = true;
    (async () => {
      try {
        const [cat, prof, res] = await Promise.all([
          getJSON("/api/prereview/catalogue"),
          getJSON(`/api/prereview/profile?conference=${encodeURIComponent(conference)}`),
          getJSON(`/api/prereview/results?conference=${encodeURIComponent(conference)}`),
        ]);
        if (!alive) return;
        setCatalogue(cat);
        setProfile({ enabled: {}, allow_network: false, ...(prof.profile || {}) });
        setScreenConf(s => ({ ...s, ...(prof.conf || {}) }));
        setPapers(res.papers || []);
        setDbPath(res.db_path || "");
        setLoadErr("");
      } catch (e) { if (alive) setLoadErr(e.message); }
    })();
    return () => { alive = false; };
  }, [conference]);

  const saveProfile = async (p = profile, sc = screenConf) => {
    try { await postJSON("/api/prereview/profile", { conference, profile: p, conf: sc }); } catch { /* non-fatal */ }
  };
  const isEnabled = spec => profile.enabled?.[spec.id] ?? spec.default_enabled;
  const setEnabled = (id, v) => { const p = { ...profile, enabled: { ...profile.enabled, [id]: v } }; setProfile(p); saveProfile(p); };
  const setSC = (k, v) => { const sc = { ...screenConf, [k]: v }; setScreenConf(sc); saveProfile(profile, sc); };

  const knownIds = useMemo(() => knownIdSet(metaRows), [metaRows]);
  const authorsById = useMemo(() => {
    const m = {};
    for (const r of authorRows || []) {
      const id = rowId(r); const n = getField(r, "name", "author", "Author");
      if (id && n) (m[id] = m[id] || []).push(n);
    }
    return m;
  }, [authorRows]);

  const paperInfo = file => {
    const pid = extractPaperId(file.name, knownIds) || file.name;
    const row = matchMeta(file.name, metaRows || [], knownIds) || {};
    return {
      paper_id: pid,
      title: getField(row, "title", "Title"),
      abstract: getField(row, "abstract", "Abstract"),
      keywords: getField(row, "keywords", "Keywords"),
      track: String(row.track || row.Track || "").trim(),
      paper_type: getField(row, "format", "type", "paper_type"),
      authors: authorsById[pid] || [],
    };
  };

  const effConf = () => ({
    max_pages: Number(conf.maxPages) || 6,
    refs_excluded: !!conf.refsExcluded,
    double_blind: conf.doubleBlind !== false,
    paper_size: screenConf.paper_size || "any",
    template: screenConf.template || "any",
  });

  const filesToRun = pdfFiles.filter(f => trackFilter === "All" || paperInfo(f).track === trackFilter);

  const run = async () => {
    if (!filesToRun.length) return;
    const signal = guard.start();
    setRunning(true); setRunErrors([]);
    const errs = [];
    setProg({ done: 0, total: filesToRun.length, cur: "" });
    for (let i = 0; i < filesToRun.length; i++) {
      if (guard.isCancelled()) break;
      const f = filesToRun[i];
      setProg({ done: i, total: filesToRun.length, cur: f.name });
      try {
        const fd = new FormData();
        fd.append("file", f, f.name);
        fd.append("conference", conference);
        fd.append("paper_json", JSON.stringify(paperInfo(f)));
        fd.append("conf_json", JSON.stringify(effConf()));
        fd.append("profile_json", JSON.stringify(profile));
        fd.append("force", String(force));
        const res = await backendPost("/api/prereview/run", fd, { signal });
        setPapers(prev => [...prev.filter(p => p.paper_id !== res.paper_id), res]);
      } catch (e) {
        if (e?.name === "AbortError") break;
        errs.push(`${f.name}: ${e.message}`);
      }
    }
    setProg(p => ({ ...p, done: p.total }));
    setRunErrors(errs);
    setRunning(false);
  };

  const decide = async (paper, finding, decision) => {
    const note = decision === "open" ? "" : (finding.decision_note || "");
    try {
      await postJSON("/api/prereview/decision", { conference, paper_id: paper.paper_id, key: finding.key, decision, note });
      setPapers(prev => prev.map(p => p.paper_id !== paper.paper_id ? p : {
        ...p, findings: p.findings.map(f => f.key === finding.key ? { ...f, decision, decision_note: note } : f) }));
    } catch (e) { alert(`Could not save the decision: ${e.message}`); }
  };

  const patchFinding = (paper, key, patch) =>
    setPapers(prev => prev.map(p => p.paper_id !== paper.paper_id ? p : {
      ...p, findings: p.findings.map(f => f.key === key ? { ...f, ...patch } : f) }));
  const setNote = (paper, finding, note) => patchFinding(paper, finding.key, { decision_note: note });
  // A note on an undecided finding turns it into "Ask authors" (a note implies a follow-up).
  const saveNote = async (paper, finding) => {
    const decision = finding.decision === "open" ? "clarify" : finding.decision;
    try {
      await postJSON("/api/prereview/decision", { conference, paper_id: paper.paper_id, key: finding.key,
        decision, note: finding.decision_note || "" });
      patchFinding(paper, finding.key, { decision });
    } catch (e) { alert(`Could not save the note: ${e.message}`); }
  };

  const openPdf = (paper, page) => {
    const file = pdfFiles.find(f => f.name === paper.filename);
    if (!file) return;
    if (pdfUrl) URL.revokeObjectURL(pdfUrl);
    const url = URL.createObjectURL(file);
    setPdfUrl(url);
    window.open(page ? `${url}#page=${page}` : url, "_blank", "noopener");
  };

  // ── Derived views ───────────────────────────────────────────────────────
  const cats = catalogue?.categories || {};
  const visibleFinding = f =>
    SEV_ORDER[f.severity] <= SEV_ORDER[minSev] &&
    (catFilter === "All" || f.category === catFilter) &&
    (!onlyOpen || f.decision === "open" || f.decision === "clarify");

  const tracks = ["All", ...[...new Set(papers.map(p => p.track || "(no track)"))].sort()];
  const shown = papers
    .filter(p => trackFilter === "All" || (p.track || "(no track)") === trackFilter)
    .filter(p => !search || `${p.paper_id} ${p.title} ${p.filename}`.toLowerCase().includes(search.toLowerCase()))
    .map(p => ({ ...p, vis: p.findings.filter(visibleFinding) }))
    .sort((a, b) => {
      const s = p => p.vis.reduce((m, f) => Math.min(m, SEV_ORDER[f.severity] + (f.outcome === "possible" ? 0.5 : 0)), 9);
      return s(a) - s(b) || b.vis.length - a.vis.length || String(a.paper_id).localeCompare(String(b.paper_id), undefined, { numeric: true });
    });

  const allF = papers.flatMap(p => p.findings);
  const stats = {
    papers: papers.length,
    flagged: papers.filter(p => p.findings.some(f => f.outcome === "issue" && f.severity !== "info")).length,
    open: allF.filter(f => f.decision === "open" && f.severity !== "info").length,
    confirmed: allF.filter(f => f.decision === "confirmed").length,
    clarify: allF.filter(f => f.decision === "clarify").length,
  };
  const catCounts = Object.fromEntries(Object.keys(cats).map(c => [c, papers.filter(p => p.findings.some(f => f.category === c && f.outcome === "issue")).length]));

  const exportFindings = () => {
    const rows = [];
    for (const p of papers) for (const f of p.findings) rows.push({
      paper_id: p.paper_id, track: p.track, title: p.title, category: cats[f.category] || f.category,
      kind: f.kind, check: f.check_id, finding: f.title, outcome: f.outcome, severity: f.severity,
      detail: f.detail, evidence: (f.evidence || []).map(e => `${e.page ? "p" + e.page + ": " : ""}${e.excerpt}`).join(" | "),
      confidence: f.confidence, limitations: f.limitations, suggested_action: f.suggested_action,
      decision: f.decision, note: f.decision_note || "",
    });
    exportCSV(rows, `prereview_${conference}.csv`);
  };

  const exportReport = paper => {
    const esc = s => String(s ?? "").replace(/[&<>"]/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
    const items = paper.findings.map(f => `
      <div class="f ${esc(f.severity)}"><div class="h"><b>${esc(f.title)}</b> <span>${esc(SEV_LABEL[f.severity])} · ${esc(OUTCOME_LABEL[f.outcome])} · ${esc(cats[f.category] || f.category)}</span>
      <span class="d">${esc(DECISION_LABEL[f.decision] || f.decision)}</span></div>
      <p>${esc(f.detail)}</p>
      ${(f.evidence || []).map(e => `<blockquote>${e.page ? `<i>p. ${esc(e.page)}</i> ` : ""}${esc(e.excerpt)}</blockquote>`).join("")}
      ${f.limitations ? `<p class="m">Limitations: ${esc(f.limitations)}</p>` : ""}
      ${f.decision_note ? `<p class="m">Note: ${esc(f.decision_note)}</p>` : ""}</div>`).join("");
    const html = `<!doctype html><html><head><meta charset="utf-8"><title>Pre-review screening – paper ${esc(paper.paper_id)}</title>
      <style>body{font-family:system-ui,sans-serif;max-width:820px;margin:24px auto;color:#111;padding:0 16px}h1{font-size:20px}
      .f{border:1px solid #ddd;border-left:4px solid #999;border-radius:6px;padding:10px 14px;margin:10px 0}.high{border-left-color:#dc2626}
      .medium{border-left-color:#d97706}.low{border-left-color:#2563eb}.h span{color:#666;font-size:12px;margin-left:8px}.d{float:right}
      blockquote{background:#f6f6f4;margin:6px 0;padding:6px 10px;font-size:13px;border-radius:4px}.m{color:#666;font-size:12px}</style></head>
      <body><h1>Pre-review screening — paper ${esc(paper.paper_id)}</h1><p><b>${esc(paper.title)}</b><br>${esc(paper.track)} · ${esc(paper.filename)} · ${esc(paper.n_pages)} pages</p>
      <p class="m">Findings are evidence for the chairs, not decisions. ${paper.findings.length} finding(s).</p>${items || "<p>No findings.</p>"}</body></html>`;
    const blob = new Blob([html], { type: "text/html" });
    const a = document.createElement("a"); a.href = URL.createObjectURL(blob); a.download = `prereview_paper_${paper.paper_id}.html`;
    a.click(); setTimeout(() => URL.revokeObjectURL(a.href), 1000);
  };

  const clearAll = async () => {
    if (!window.confirm("Delete all stored screening results for this conference? Chair decisions are kept.")) return;
    await postJSON("/api/prereview/clear", { conference });
    setPapers([]); setSelected(null);
  };

  const sel = papers.find(p => p.paper_id === selected);

  // ── Render ──────────────────────────────────────────────────────────────
  if (loadErr) return <InfoBanner type="error">Could not load the screening module: {loadErr}</InfoBanner>;

  return (
    <div>
      <InfoBanner>
        Checks every PDF for problems the chairs should know about before review: file integrity, formatting, anonymity,
        references, hidden text, implausible numbers, figures. Each finding comes with evidence; <b>nothing is decided
        automatically</b>. Results and your decisions are saved locally{dbPath ? <> in <code style={{ fontSize: 10 }}>{dbPath}</code></> : ""}.
      </InfoBanner>

      {/* Controls */}
      <div style={{ display: "flex", gap: 10, alignItems: "center", flexWrap: "wrap", margin: "14px 0" }}>
        {!running
          ? <PrimaryButton onClick={run} disabled={!filesToRun.length}>
              Screen {filesToRun.length} PDF{filesToRun.length === 1 ? "" : "s"}{trackFilter !== "All" ? ` (${trackFilter})` : ""}
            </PrimaryButton>
          : <GhostButton onClick={guard.stop}>Stop</GhostButton>}
        <label style={{ fontSize: 12, color: C.textSoft, display: "flex", gap: 6, alignItems: "center" }}>
          <input type="checkbox" checked={force} onChange={e => setForce(e.target.checked)} /> Re-run unchanged papers
        </label>
        <label style={{ fontSize: 12, color: C.textSoft, display: "flex", gap: 6, alignItems: "center" }}>
          <input type="checkbox" checked={!!profile.allow_network}
                 onChange={e => { const p = { ...profile, allow_network: e.target.checked }; setProfile(p); saveProfile(p); }} />
          Online reference checks (doi.org, Crossref)
        </label>
        <GhostButton small onClick={() => setShowSettings(s => !s)}>{showSettings ? "Hide" : "Show"} check settings</GhostButton>
        <div style={{ flex: 1 }} />
        {papers.length > 0 && <GhostButton small onClick={exportFindings}>Export CSV</GhostButton>}
        {papers.length > 0 && <GhostButton small onClick={clearAll}>Clear results</GhostButton>}
      </div>
      {!pdfFiles.length && <InfoBanner type="warning">Load the submission PDFs on the Data import tab to screen them. Stored results are shown below.</InfoBanner>}
      {running && <ProgressBar done={prog.done} total={prog.total} label={prog.cur} />}
      {runErrors.length > 0 && <InfoBanner type="error">{runErrors.length} file(s) failed: {runErrors.slice(0, 3).join("; ")}</InfoBanner>}

      {showSettings && catalogue && (
        <div style={{ background: C.panel, border: `1px solid ${C.border}`, borderRadius: 8, padding: 14, marginBottom: 14 }}>
          <SectionTitle>Conference settings used by the checks</SectionTitle>
          <div style={{ display: "flex", gap: 18, flexWrap: "wrap", fontSize: 12, color: C.textSoft, marginBottom: 12 }}>
            <span>Page limit: <b style={{ color: C.text }}>{conf.maxPages || 6}</b>{conf.refsExcluded ? " + references" : " incl. references"}</span>
            <span>Double-blind: <b style={{ color: C.text }}>{conf.doubleBlind !== false ? "yes" : "no"}</b></span>
            <span style={{ color: C.muted }}>(change these on the Conference tab)</span>
            <label>Paper size{" "}
              <select style={selStyle()} value={screenConf.paper_size} onChange={e => setSC("paper_size", e.target.value)}>
                <option value="any">any</option><option value="letter">US Letter</option><option value="a4">A4</option>
              </select></label>
            <label>Template{" "}
              <select style={selStyle()} value={screenConf.template} onChange={e => setSC("template", e.target.value)}>
                <option value="any">any</option><option value="ieee">IEEE</option><option value="acm">ACM</option><option value="lncs">LNCS</option>
              </select></label>
          </div>
          {Object.entries(cats).map(([cid, clabel]) => (
            <div key={cid} style={{ marginBottom: 10 }}>
              <div style={{ fontSize: 11, fontWeight: 700, color: C.accentText, marginBottom: 4 }}>{clabel}</div>
              <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(320px, 1fr))", gap: "0 16px" }}>
                {catalogue.checks.filter(c => c.category === cid).map(c => (
                  <Toggle key={c.id} checked={isEnabled(c)} onChange={v => setEnabled(c.id, v)}
                    label={<>{c.title}{c.exec_kind === "network" && <span style={{ color: C.amber }}> · online</span>}
                      {c.needs_double_blind && <span style={{ color: C.muted }}> · double-blind only</span>}</>}
                    hint={c.description} />
                ))}
              </div>
            </div>
          ))}
        </div>
      )}

      {papers.length === 0 ? (
        <EmptyState icon="🛡" title="No screening results yet"
          body="Load the PDFs (and ideally the submissions and author lists) on the Data import tab, then click Screen." />
      ) : (<>
        <div style={{ display: "flex", gap: 10, marginBottom: 14, flexWrap: "wrap" }}>
          <StatCard label="Papers screened" value={stats.papers} />
          <StatCard label="With at least one issue" value={stats.flagged} color={stats.flagged ? C.red : C.green} />
          <StatCard label="Open findings" value={stats.open} color={C.amber} />
          <StatCard label="Confirmed" value={stats.confirmed} color={C.red} />
          <StatCard label="Ask authors" value={stats.clarify} color={C.amber} />
        </div>

        {/* Category overview: papers with a clear issue per category */}
        <div style={{ display: "flex", gap: 6, flexWrap: "wrap", marginBottom: 12 }}>
          {["All", ...Object.keys(cats)].map(c => (
            <button key={c} onClick={() => setCatFilter(c)} style={{
              fontSize: 11, padding: "4px 10px", borderRadius: 14, cursor: "pointer", fontFamily: C.sans,
              border: `1px solid ${catFilter === c ? C.accent : C.border}`, background: catFilter === c ? C.accentDim : C.panel,
              color: catFilter === c ? C.accentText : C.textSoft }}>
              {c === "All" ? "All categories" : cats[c]}{c !== "All" && <b style={{ marginLeft: 6, color: catCounts[c] ? C.red : C.muted }}>{catCounts[c]}</b>}
            </button>
          ))}
        </div>

        <div style={{ display: "flex", gap: 10, alignItems: "center", flexWrap: "wrap", marginBottom: 10, fontSize: 12, color: C.textSoft }}>
          <select style={selStyle()} value={trackFilter} onChange={e => setTrackFilter(e.target.value)}>
            {tracks.map(t => <option key={t} value={t}>{t === "All" ? "All tracks" : t}</option>)}
          </select>
          <select style={selStyle()} value={minSev} onChange={e => setMinSev(e.target.value)}>
            <option value="high">High only</option><option value="medium">Medium and up</option>
            <option value="low">Low and up</option><option value="info">Everything</option>
          </select>
          <label style={{ display: "flex", gap: 5, alignItems: "center" }}>
            <input type="checkbox" checked={onlyOpen} onChange={e => setOnlyOpen(e.target.checked)} /> Undecided only
          </label>
          <input placeholder="Search ID or title" value={search} onChange={e => setSearch(e.target.value)}
                 style={{ ...selStyle(), width: 180 }} />
          <span style={{ color: C.muted }}>{shown.filter(p => p.vis.length).length} of {shown.length} papers with findings</span>
        </div>

        <div style={{ display: "grid", gridTemplateColumns: sel ? "minmax(260px, 38%) 1fr" : "1fr", gap: 14, alignItems: "start" }}>
          {/* Paper list */}
          <div style={{ background: C.panel, border: `1px solid ${C.border}`, borderRadius: 8, maxHeight: "70vh", overflowY: "auto" }}>
            {shown.map(p => {
              const bySev = { high: 0, medium: 0, low: 0 };
              p.vis.forEach(f => { if (f.outcome === "issue" && bySev[f.severity] !== undefined) bySev[f.severity]++; });
              const poss = p.vis.filter(f => f.outcome === "possible").length;
              const open = p.vis.filter(f => f.decision === "open").length;
              return (
                <div key={p.paper_id} onClick={() => setSelected(p.paper_id === selected ? null : p.paper_id)}
                  style={{ padding: "8px 12px", borderBottom: `1px solid ${C.border}`, cursor: "pointer",
                    background: p.paper_id === selected ? C.accentDim : "transparent" }}>
                  <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
                    <b style={{ fontFamily: C.mono, fontSize: 12, color: C.accentText, minWidth: 34 }}>#{p.paper_id}</b>
                    <span style={{ fontSize: 12, color: C.text, flex: 1, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                      {p.title || p.filename}</span>
                    {bySev.high > 0 && <span style={{ fontSize: 11, color: C.red, fontWeight: 700 }}>{bySev.high}●</span>}
                    {bySev.medium > 0 && <span style={{ fontSize: 11, color: C.amber, fontWeight: 700 }}>{bySev.medium}●</span>}
                    {bySev.low > 0 && <span style={{ fontSize: 11, color: C.blue, fontWeight: 700 }}>{bySev.low}●</span>}
                    {poss > 0 && <span style={{ fontSize: 11, color: C.muted }}>{poss}○</span>}
                    {!p.vis.length && <span style={{ fontSize: 11, color: C.green }}>✓</span>}
                  </div>
                  <div style={{ fontSize: 10, color: C.muted, marginTop: 2, paddingLeft: 42 }}>
                    {p.track || "no track"} · {p.n_pages} p.{p.extraction_error ? ` · ${p.extraction_error}` : ""}{open ? ` · ${open} open` : ""}
                  </div>
                </div>
              );
            })}
          </div>

          {/* Paper report */}
          {sel && (
            <div style={{ background: C.panel, border: `1px solid ${C.border}`, borderRadius: 8, padding: 14, maxHeight: "70vh", overflowY: "auto" }}>
              <div style={{ display: "flex", gap: 8, alignItems: "flex-start" }}>
                <div style={{ flex: 1 }}>
                  <div style={{ fontSize: 14, fontWeight: 700, color: C.text }}>#{sel.paper_id} {sel.title}</div>
                  <div style={{ fontSize: 11, color: C.muted, marginTop: 2 }}>
                    {sel.track} · {sel.filename} · {sel.n_pages} pages
                    {sel.versions?.length > 1 ? ` · ${sel.versions.length} file versions seen` : ""}
                  </div>
                </div>
                <GhostButton small onClick={() => openPdf(sel)}>Open PDF</GhostButton>
                <GhostButton small onClick={() => exportReport(sel)}>Report</GhostButton>
              </div>
              {["technical", "scientific"].map(kind => {
                const fs = sel.findings.filter(f => f.kind === kind).filter(visibleFinding)
                  .sort((a, b) => SEV_ORDER[a.severity] - SEV_ORDER[b.severity] || (a.outcome === "possible") - (b.outcome === "possible"));
                if (!fs.length) return null;
                return (
                  <div key={kind} style={{ marginTop: 14 }}>
                    <SectionTitle>{kind === "technical" ? "Technical compliance" : "Scientific concerns (for the reviewers / chairs)"}</SectionTitle>
                    {fs.map(f => (
                      <div key={f.key} style={{ border: `1px solid ${C.border}`, borderLeft: `3px solid ${sevColor(f.severity)}`,
                        borderRadius: 6, padding: "8px 10px", marginBottom: 8, opacity: f.decision === "dismissed" ? 0.55 : 1 }}>
                        <div style={{ display: "flex", gap: 8, alignItems: "center", flexWrap: "wrap" }}>
                          <b style={{ fontSize: 12, color: C.text }}>{f.title}</b>
                          <SevPill sev={f.severity} outcome={f.outcome} />
                          <span style={{ fontSize: 10, color: C.muted }}>{cats[f.category]}</span>
                          <div style={{ flex: 1 }} />
                          <span style={{ fontSize: 10, fontWeight: 700, color: decColor(f.decision) }}>{DECISION_LABEL[f.decision]}</span>
                        </div>
                        {f.detail && <div style={{ fontSize: 12, color: C.textSoft, marginTop: 4 }}>{f.detail}</div>}
                        {(f.evidence || []).filter(e => e.excerpt || e.page).map((e, i) => (
                          <div key={i} style={{ fontSize: 11, color: C.text, background: C.panelAlt, borderRadius: 4, padding: "4px 8px", marginTop: 4,
                            fontFamily: C.mono, wordBreak: "break-word" }}>
                            {e.page && <a onClick={ev => { ev.preventDefault(); openPdf(sel, e.page); }} href="#"
                              style={{ color: C.accentText, marginRight: 6, fontFamily: C.sans }}>p. {e.page}</a>}
                            {e.excerpt}
                          </div>
                        ))}
                        {f.limitations && <div style={{ fontSize: 10, color: C.muted, marginTop: 4 }}>Limitations: {f.limitations}</div>}
                        {f.suggested_action && <div style={{ fontSize: 10, color: C.tealText, marginTop: 2 }}>Suggested: {f.suggested_action}</div>}
                        <div style={{ display: "flex", gap: 6, marginTop: 6, flexWrap: "wrap", alignItems: "center" }}>
                          {["confirmed", "dismissed", "clarify"].map(d => (
                            <button key={d} onClick={() => decide(sel, f, f.decision === d ? "open" : d)} style={{
                              fontSize: 10, padding: "2px 8px", borderRadius: 4, cursor: "pointer", fontFamily: C.sans,
                              border: `1px solid ${f.decision === d ? decColor(d) : C.border}`,
                              background: f.decision === d ? decColor(d) + "22" : "transparent", color: f.decision === d ? decColor(d) : C.textSoft }}>
                              {d === "confirmed" ? "Confirm" : d === "dismissed" ? "Dismiss" : "Ask authors"}
                            </button>
                          ))}
                          <input placeholder="Note (saved with the decision)" value={f.decision_note || ""}
                            onChange={e => setNote(sel, f, e.target.value)} onBlur={() => f.decision_note && saveNote(sel, f)}
                            style={{ ...selStyle(), flex: 1, minWidth: 140, fontSize: 11, padding: "2px 6px" }} />
                        </div>
                      </div>
                    ))}
                  </div>
                );
              })}
              {!sel.findings.filter(visibleFinding).length && <div style={{ fontSize: 12, color: C.green, marginTop: 14 }}>No findings with the current filters.</div>}
              <ChecksRun sel={sel} />
            </div>
          )}
        </div>
      </>)}
    </div>
  );
}

function ChecksRun({ sel }) {
  const [open, setOpen] = useState(false);
  const entries = Object.entries(sel.checks || {});
  const errs = entries.filter(([, v]) => v.status === "error");
  return (
    <div style={{ marginTop: 14, fontSize: 11, color: C.muted }}>
      <a href="#" onClick={e => { e.preventDefault(); setOpen(o => !o); }} style={{ color: C.muted }}>
        {entries.length} checks ran{errs.length ? `, ${errs.length} failed` : ""} {open ? "▴" : "▾"}</a>
      {open && <div style={{ marginTop: 6, display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(220px, 1fr))", gap: 2 }}>
        {entries.map(([id, v]) => (
          <div key={id} title={v.error || ""}>
            <span style={{ color: { pass: C.green, issue: C.red, possible: C.amber, error: C.red, skipped: C.muted }[v.status] || C.muted }}>●</span>{" "}
            {v.title} <span style={{ color: C.muted }}>({v.status})</span>
          </div>
        ))}
      </div>}
    </div>
  );
}
