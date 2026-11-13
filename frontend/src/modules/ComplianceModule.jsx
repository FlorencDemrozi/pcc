import { useState, useEffect } from "react";
import { C } from "../utils/theme.js";
import { Badge, StatCard, SectionTitle, ProgressBar, PrimaryButton, GhostButton, EmptyState } from "../components/ui.jsx";
import { backendPost } from "../utils/api.js";
import { exportCSV, trackForFile, knownIdSet } from "../utils/helpers.js";
import { useRunGuard } from "../utils/useRunGuard.js";

export function ComplianceModule({ conf, pdfFiles, metaRows, authorRows, activeTrack = "All" }) {
  const [results,      setResults]      = useState([]);
  const [running,      setRunning]      = useState(false);
  const [prog,         setProg]         = useState({ done: 0, total: 0, cur: "" });
  const [useLlmBlind,  setUseLlmBlind]  = useState(false);
  const [skipBlind,    setSkipBlind]    = useState(false);
  const [skipFonts,    setSkipFonts]    = useState(false);
  const [selectedIdx,  setSelectedIdx]  = useState(null);
  const [pdfUrl,       setPdfUrl]       = useState(null);
  const [overrides,    setOverrides]    = useState({});
  const [trackFilter,  setTrackFilter]  = useState(activeTrack);
  const [issueFilter,  setIssueFilter]  = useState("All");
  // Online reference verification (opt-in): { [itemId]: {loading, error, data} }
  const [refCheck,     setRefCheck]     = useState({});
  const [verifyAll,    setVerifyAll]    = useState({ running: false, done: 0, total: 0 });
  const verifyGuard = useRunGuard();

  useEffect(() => setTrackFilter(activeTrack), [activeTrack]);
  useEffect(() => () => { if (pdfUrl) URL.revokeObjectURL(pdfUrl); }, []);

  const knownIds = knownIdSet(metaRows);
  const getTrack = filename => trackForFile(filename, metaRows, knownIds);

  const openPdf = item => {
    if (pdfUrl) URL.revokeObjectURL(pdfUrl);
    const file = pdfFiles.find(f => f.name === item.filename);
    if (!file) return;
    setPdfUrl(URL.createObjectURL(file));
    setSelectedIdx(item.id);
  };

  const run = async (force = false) => {
    if (!pdfFiles.length) return;
    if (results.length > 0 && !force) return;
    setRunning(true); setResults([]);
    if (pdfUrl) { URL.revokeObjectURL(pdfUrl); setPdfUrl(null); setSelectedIdx(null); }
    const all = [];
    setProg({ done: 0, total: pdfFiles.length, cur: "" });
    for (let i = 0; i < pdfFiles.length; i++) {
      const f = pdfFiles[i];
      setProg({ done: i, total: pdfFiles.length, cur: f.name });
      try {
        const fd = new FormData();
        fd.append("file",             f, f.name);
        fd.append("max_pages",         String(conf.maxPages || 6));
        fd.append("double_blind",      String(!skipBlind && conf.doubleBlind !== false));
        fd.append("copyright_notices", JSON.stringify(conf.copyrightNotices || []));
        fd.append("camera_ready",      "false");
        fd.append("expected_layout",   conf.expectedLayout || "any");
        fd.append("validation_stamp",  conf.validationStamp || "");
        fd.append("use_llm_blind",     String(!skipBlind && useLlmBlind));
        fd.append("refs_excluded",     String(!!conf.refsExcluded));
        // Real author names make the double-blind check precise (no guessing).
        if (!skipBlind && authorRows && authorRows.length > 0)
          fd.append("author_list_json", JSON.stringify(authorRows));
        const result = await backendPost("/api/check/pdf", fd);
        const track  = getTrack(f.name);
        const failedChecks = [];
        if (!result.page_count?.passed)                                                  failedChecks.push("Pages");
        if (!skipFonts && !result.font_embedding?.passed)                                failedChecks.push("Fonts");
        if (!skipBlind && !result.blind_compliance?.passed)                              failedChecks.push("Blind");
        if (conf.expectedLayout && conf.expectedLayout !== "any" && !result.column_layout?.passed) failedChecks.push("Layout");
        if (!result.references?.passed)                                                  failedChecks.push("Refs");
        if (!result.text_extraction?.passed)                                             failedChecks.push("Text");
        if (result.citations && result.citations.passed === false)                       failedChecks.push("Cites");
        all.push({ id: i + 1, filename: f.name, track, result, passed: failedChecks.length === 0, failedChecks });
      } catch (e) {
        all.push({ id: i + 1, filename: f.name, track: getTrack(f.name), result: null, error: e.message, passed: false, failedChecks: ["Error"] });
      }
      setResults([...all]);
    }
    setRunning(false);
  };

  const effectivePassed = item => overrides[item.id] ? overrides[item.id] === "Pass" : item.passed;

  const allTracks = ["All", ...([...new Set(results.map(r => r.track || "(no track)"))].sort((a, b) => a === "(no track)" ? 1 : b === "(no track)" ? -1 : a.localeCompare(b)))];
  const ISSUE_TYPES = ["All", "Pages", "Fonts", "Blind", "Layout", "Refs", "Cites", "Text", "Error"];

  // ── Reference verification (Crossref / OpenAlex) ─────────────────────
  const verifyRefs = async (item, signal) => {
    const file = pdfFiles.find(f => f.name === item.filename);
    if (!file) return;
    setRefCheck(p => ({ ...p, [item.id]: { loading: true } }));
    try {
      const fd = new FormData();
      fd.append("file", file, file.name);
      fd.append("verify", "true");
      const data = await backendPost("/api/check/references", fd, { signal });
      setRefCheck(p => ({ ...p, [item.id]: { data } }));
    } catch (e) {
      setRefCheck(p => ({ ...p, [item.id]: { error: e.message } }));
    }
  };
  const runVerifyAll = async () => {
    const signal = verifyGuard.start();
    const todo = results.filter(r => r.result && !refCheck[r.id]?.data);
    setVerifyAll({ running: true, done: 0, total: todo.length });
    for (let i = 0; i < todo.length; i++) {
      if (verifyGuard.isCancelled()) break;
      await verifyRefs(todo[i], signal);
      setVerifyAll({ running: true, done: i + 1, total: todo.length });
    }
    setVerifyAll(v => ({ ...v, running: false }));
  };
  const unverifiedCount = id => {
    const s = refCheck[id]?.data?.verification_summary;
    return s ? (s.not_found || 0) : null;
  };
  const STATUS_LABEL = { verified: "Found", likely: "Probably found", not_found: "Not found \u2014 check manually",
                         not_checkable: "Not indexed (web/datasheet/standard)", error: "Lookup failed" };
  const STATUS_COLOR = { verified: C.green, likely: C.amber, not_found: C.red, not_checkable: C.muted, error: C.muted };

  const RefVerifyPanel = ({ item }) => {
    const st = refCheck[item.id];
    if (!st) return (
      <div style={{ marginTop: 6 }}>
        <GhostButton small onClick={() => verifyRefs(item)}>Verify references online</GhostButton>
        <div style={{ fontSize: 10, color: C.muted, marginTop: 3 }}>Sends only the reference list entries to Crossref (and OpenAlex if you added its free key in Settings).</div>
      </div>
    );
    if (st.loading) return <div style={{ fontSize: 11, color: C.muted, marginTop: 6 }}>Looking up references...</div>;
    if (st.error)   return <div style={{ fontSize: 11, color: C.red, marginTop: 6 }}>Verification failed: {st.error}</div>;
    const d = st.data, sm = d.verification_summary || {};
    const rows = (d.verification || []).filter(v => v.status !== "verified");
    return (
      <div style={{ marginTop: 6 }}>
        <div style={{ fontSize: 11, color: C.text, marginBottom: 4 }}>
          References: <strong style={{ color: C.green }}>{sm.verified || 0} found</strong>
          {sm.likely ? <> · <span style={{ color: C.amber }}>{sm.likely} probable</span></> : null}
          {sm.not_found ? <> · <span style={{ color: C.red }}>{sm.not_found} not found</span></> : null}
          {sm.not_checkable ? <> · <span style={{ color: C.muted }}>{sm.not_checkable} not indexed</span></> : null}
          {sm.error ? <> · <span style={{ color: C.muted }}>{sm.error} failed</span></> : null}
        </div>
        {rows.map(v => (
          <div key={v.n} style={{ fontSize: 10, marginBottom: 3, lineHeight: 1.4 }}>
            <span style={{ color: STATUS_COLOR[v.status], fontWeight: 600 }}>[{v.n}] {STATUS_LABEL[v.status] || v.status}</span>
            <span style={{ color: C.muted }}> {"\u2014"} {v.text.slice(0, 160)}{v.text.length > 160 ? "..." : ""}</span>
            {v.note && v.status !== "not_checkable" && <div style={{ color: C.muted, marginLeft: 10 }}>{v.note}</div>}
            {v.match && <div style={{ color: C.muted, marginLeft: 10 }}>closest: "{v.match.title}" ({v.match.source}{v.match.year ? ", " + v.match.year : ""})</div>}
          </div>
        ))}
        {sm.not_found > 0 && <div style={{ fontSize: 10, color: C.muted, marginTop: 4 }}>"Not found" does not prove a reference is fake: preprints, theses and books are often missing from these databases.</div>}
      </div>
    );
  };
  const fullPass    = results.filter(r => effectivePassed(r)).length;

  const filtered = results.filter(item => {
    const tOk = trackFilter === "All" || (item.track || "(no track)") === trackFilter;
    const iOk = issueFilter === "All" || item.failedChecks.includes(issueFilter);
    return tOk && iOk;
  });

  const trackStats = {};
  results.forEach(item => {
    const t = item.track || "(no track)";
    if (!trackStats[t]) trackStats[t] = { total: 0, pass: 0 };
    trackStats[t].total++;
    if (effectivePassed(item)) trackStats[t].pass++;
  });

  const CheckRow = ({ label, check, skipped = false }) => {
    if (skipped) return (
      <div style={{ display: "flex", gap: 8, alignItems: "center", marginBottom: 5 }}>
        <span style={{ width: 130, fontSize: 11, color: C.muted, flexShrink: 0 }}>{label}</span>
        <Badge label="N/A" /><span style={{ fontSize: 11, color: C.muted }}>Skipped</span>
      </div>
    );
    if (!check) return null;
    return (
      <div style={{ display: "flex", gap: 8, alignItems: "flex-start", marginBottom: 5 }}>
        <span style={{ width: 130, fontSize: 11, color: C.muted, flexShrink: 0 }}>{label}</span>
        <Badge label={check.passed ? "Pass" : "Fail"} />
        {check.value && <span style={{ fontSize: 11, color: C.muted }}>{check.value}</span>}
        {(check.issues || []).map((iss, j) => <span key={j} style={{ fontSize: 11, color: C.red, marginLeft: 4 }}>{iss}</span>)}
      </div>
    );
  };

  if (!pdfFiles.length) return <EmptyState icon="✅" title="No PDFs loaded" body="Upload the papers ZIP in the Data import tab." />;

  // ── Setup screen ──────────────────────────────────────────────────────────
  if (!running && results.length === 0) return (
    <div style={{ maxWidth: 560 }}>
      <div style={{ fontSize: 13, color: C.muted, marginBottom: 16, fontFamily: C.sans }}>
        {pdfFiles.length} papers ready
        {metaRows.length > 0 && ` · ${[...new Set(metaRows.map(r => r.Track || r.track || "").filter(Boolean))].length} tracks from submissions file`}
      </div>
      <div style={{ background: C.panel, border: `1px solid ${C.border}`, borderRadius: 10, padding: "14px 18px", marginBottom: 12 }}>
        <SectionTitle>Font embedding</SectionTitle>
        <div style={{ display: "flex", gap: 16 }}>
          {[["Check fonts (IEEE required)", false], ["Skip font check", true]].map(([label, val]) => (
            <label key={label} style={{ display: "flex", gap: 8, alignItems: "center", cursor: "pointer", fontSize: 12, color: C.muted }}>
              <input type="radio" checked={skipFonts === val} onChange={() => setSkipFonts(val)} />
              <span>{label}</span>
            </label>
          ))}
        </div>
      </div>
      <div style={{ background: C.panel, border: `1px solid ${C.border}`, borderRadius: 10, padding: "14px 18px", marginBottom: 16 }}>
        <SectionTitle>Blind compliance check</SectionTitle>
        <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
          {[
            [true,  false, "Skip — not applicable",            "For camera-ready or accepted papers where author identity is expected."],
            [false, false, "Deterministic — fast, no API call","Regex-based: emails, ORCIDs, affiliations, name patterns. May produce false positives on technical terms."],
            [false, true,  "AI-assisted — 1 API call per paper","LLM reads first page text — context-aware, avoids false positives."],
          ].map(([sb, llm, title, desc]) => (
            <label key={title} style={{ display: "flex", gap: 10, alignItems: "flex-start", cursor: "pointer" }}>
              <input type="radio" checked={skipBlind === sb && useLlmBlind === llm}
                onChange={() => { setSkipBlind(sb); setUseLlmBlind(llm); }} style={{ marginTop: 3, flexShrink: 0 }} />
              <div>
                <div style={{ fontSize: 12, fontWeight: 600, color: C.text }}>{title}</div>
                <div style={{ fontSize: 11, color: C.muted, marginTop: 2, lineHeight: 1.5 }}>{desc}</div>
              </div>
            </label>
          ))}
        </div>
      </div>
      <PrimaryButton onClick={() => run(true)}>Run compliance checks →</PrimaryButton>
    </div>
  );

  if (running) return <ProgressBar done={prog.done} total={prog.total} label={prog.cur} />;

  // ── Results ───────────────────────────────────────────────────────────────
  return (
    <div style={{ display: "flex", flexDirection: "column", height: "calc(100vh - 140px)", minHeight: 500 }}>
      {/* KPI row */}
      <div style={{ display: "flex", gap: 8, marginBottom: 10, flexWrap: "wrap", alignItems: "center", flexShrink: 0 }}>
        <StatCard label="Total"      value={results.length}               color={C.text} />
        <StatCard label="Pass"       value={fullPass}                     color={C.green} />
        <StatCard label="Issues"     value={results.length - fullPass}    color={C.red} />
        <StatCard label="Overridden" value={Object.keys(overrides).length} color={C.amber} />
        <div style={{ flex: 1 }} />
        {verifyAll.running
          ? <GhostButton small onClick={verifyGuard.stop}>Stop verifying ({verifyAll.done}/{verifyAll.total})</GhostButton>
          : <GhostButton small onClick={runVerifyAll} title="Looks up every reference list entry in Crossref (and OpenAlex if a key is set). Only reference entries are sent.">Verify all references (online)</GhostButton>}
        <GhostButton small onClick={() => run(true)}>Re-run</GhostButton>
        <GhostButton onClick={() => exportCSV(results.map(r => ({
          filename:      r.filename,
          track:         r.track || "",
          verdict:       overrides[r.id] || (effectivePassed(r) ? "Pass" : "Fail"),
          overridden:    overrides[r.id] ? "Yes" : "No",
          pages:         r.result?.page_count?.value || "",
          page_check:    r.result?.page_count?.passed ? "Pass" : "Fail",
          fonts:         skipFonts ? "N/A" : (r.result?.font_embedding?.passed ? "Pass" : "Fail"),
          blind:         skipBlind ? "N/A" : (r.result?.blind_compliance?.passed ? "Pass" : "Fail"),
          layout:        r.result?.column_layout?.value || "N/A",
          references:    r.result?.references?.value || "N/A",
          citations:     r.result?.citations?.value || "N/A",
          citation_issues: (r.result?.citations?.issues || []).join(" | "),
          refs_not_found: unverifiedCount(r.id) ?? "not checked",
          failed_checks: r.failedChecks.join(", "),
        })), "compliance.csv")}>↓ Export CSV</GhostButton>
      </div>

      {/* Track filter */}
      {metaRows.length === 0 ? (
        <div style={{ padding: "6px 10px", marginBottom: 8, background: C.amberDim, border: `1px solid ${C.amber}40`, borderRadius: 6, fontSize: 11, color: C.amber, flexShrink: 0 }}>
          ⚠ No submissions file loaded — track grouping unavailable.
        </div>
      ) : allTracks.length > 1 && (
        <div style={{ display: "flex", gap: 4, marginBottom: 8, flexWrap: "wrap", flexShrink: 0 }}>
          {allTracks.map(t => {
            const ts = t === "All" ? null : trackStats[t];
            return (
              <button key={t} onClick={() => setTrackFilter(t)} style={{
                padding: "4px 11px", borderRadius: 5, fontSize: 11, fontWeight: 600, cursor: "pointer",
                border: `1px solid ${trackFilter === t ? C.accent : C.border}`,
                background: trackFilter === t ? C.accentDim : "transparent",
                color: trackFilter === t ? C.accentText : C.muted,
              }}>
                {t} <span style={{ fontSize: 10, opacity: 0.8 }}>{ts ? `${ts.pass}/${ts.total}` : `${fullPass}/${results.length}`}</span>
              </button>
            );
          })}
        </div>
      )}

      {/* Issue type filter */}
      <div style={{ display: "flex", gap: 4, marginBottom: 10, flexWrap: "wrap", flexShrink: 0, alignItems: "center" }}>
        <span style={{ fontSize: 10, color: C.muted, fontWeight: 700, textTransform: "uppercase", letterSpacing: "0.06em", marginRight: 4 }}>Issues:</span>
        {ISSUE_TYPES.map(f => {
          const count = f === "All"
            ? results.filter(r => !effectivePassed(r)).length
            : results.filter(r => r.failedChecks.includes(f)).length;
          if (f !== "All" && count === 0) return null;
          return (
            <button key={f} onClick={() => setIssueFilter(f)} style={{
              padding: "3px 10px", borderRadius: 5, fontSize: 11, fontWeight: 600, cursor: "pointer",
              border: `1px solid ${issueFilter === f ? C.red + "80" : C.border}`,
              background: issueFilter === f ? C.redDim : "transparent",
              color: issueFilter === f ? C.redText : C.muted,
            }}>{f}{f !== "All" && count > 0 ? ` (${count})` : ""}</button>
          );
        })}
      </div>

      {/* Split pane */}
      <div style={{ display: "flex", gap: 10, flex: 1, overflow: "hidden" }}>
        {/* Left list */}
        <div style={{ width: 350, flexShrink: 0, overflowY: "auto", display: "flex", flexDirection: "column", gap: 2 }}>
          {filtered.map(item => {
            const r          = item.result;
            const ok         = effectivePassed(item);
            const isSelected = selectedIdx === item.id;
            const isOverride = !!overrides[item.id];
            const leftColor  = isSelected ? C.accent : isOverride ? C.amber : ok ? C.green : C.red;
            return (
              <div key={item.id} onClick={() => openPdf(item)} style={{
                borderTop: `1px solid ${C.border}`, borderRight: `1px solid ${C.border}`,
                borderBottom: `1px solid ${C.border}`, borderLeft: `3px solid ${leftColor}`,
                borderRadius: "0 6px 6px 0", cursor: "pointer",
                background: isSelected ? C.panelAlt : C.panel,
              }}>
                <div style={{ padding: "7px 10px", display: "flex", gap: 6, alignItems: "center", minHeight: 34 }}>
                  <span style={{ fontSize: 9, color: C.muted, fontFamily: C.mono, flexShrink: 0, width: 22 }}>#{item.id}</span>
                  <div style={{ flex: 1, minWidth: 0 }}>
                    <div style={{ fontSize: 11, color: C.text, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                      {item.filename.replace(/\.pdf$/i, "")}
                    </div>
                    {item.failedChecks.length > 0 && (
                      <div style={{ display: "flex", gap: 3, marginTop: 3, flexWrap: "wrap" }}>
                        {item.failedChecks.map(c => (
                          <span key={c} style={{ fontSize: 9, padding: "1px 6px", borderRadius: 3, background: C.red + "20", color: C.redText, fontWeight: 600 }}>{c}</span>
                        ))}
                      </div>
                    )}
                    {unverifiedCount(item.id) > 0 && (
                      <span style={{ display: "inline-block", marginTop: 3, fontSize: 9, padding: "1px 6px", borderRadius: 3, background: C.amber + "20", color: C.amber, fontWeight: 600 }}>
                        {unverifiedCount(item.id)} ref(s) not found
                      </span>
                    )}
                  </div>
                  {r && <span style={{ fontSize: 9, color: C.muted, flexShrink: 0, fontFamily: C.mono }}>{r.raw_pages}p</span>}
                  <span style={{ fontSize: 10, fontWeight: 700, flexShrink: 0, color: isOverride ? C.amber : ok ? C.green : C.red }}>
                    {isOverride ? `${overrides[item.id]}*` : ok ? "Pass" : "Fail"}
                  </span>
                  <div style={{ display: "flex", gap: 2, flexShrink: 0 }} onClick={e => e.stopPropagation()}>
                    <button onClick={() => setOverrides(p => ({ ...p, [item.id]: "Pass" }))} title="Mark Pass"
                      style={{ border: `1px solid ${overrides[item.id] === "Pass" ? C.green : C.border}`, background: overrides[item.id] === "Pass" ? C.greenDim : "transparent", borderRadius: 3, width: 20, height: 20, fontSize: 11, cursor: "pointer", padding: 0 }}>👍</button>
                    <button onClick={() => setOverrides(p => ({ ...p, [item.id]: "Fail" }))} title="Mark Fail"
                      style={{ border: `1px solid ${overrides[item.id] === "Fail" ? C.red : C.border}`, background: overrides[item.id] === "Fail" ? C.redDim : "transparent", borderRadius: 3, width: 20, height: 20, fontSize: 11, cursor: "pointer", padding: 0 }}>👎</button>
                    {overrides[item.id] && (
                      <button onClick={() => setOverrides(p => { const n = { ...p }; delete n[item.id]; return n; })}
                        style={{ border: `1px solid ${C.border}`, background: "transparent", borderRadius: 3, width: 16, height: 20, fontSize: 9, cursor: "pointer", padding: 0, color: C.muted }}>✕</button>
                    )}
                  </div>
                </div>
                {isSelected && r && (
                  <div style={{ padding: "8px 10px 10px", borderTop: `1px solid ${C.border}`, background: C.bg }}>
                    <CheckRow label="Pages"  check={r.page_count} />
                    <CheckRow label="Fonts"  check={r.font_embedding}   skipped={skipFonts} />
                    <CheckRow label="Blind"  check={r.blind_compliance} skipped={skipBlind} />
                    <CheckRow label="Layout" check={r.column_layout} />
                    <CheckRow label="Refs"   check={r.references} />
                    <CheckRow label="Citations" check={r.citations} />
                    <CheckRow label="Text"   check={r.text_extraction} />
                    <RefVerifyPanel item={item} />
                    {isOverride && (
                      <div style={{ marginTop: 5, padding: "4px 8px", borderRadius: 4, background: C.amberDim, border: `1px solid ${C.amber}40`, fontSize: 10, color: C.amber }}>
                        ⚠ Override: marked as <strong>{overrides[item.id]}</strong>
                      </div>
                    )}
                  </div>
                )}
                {isSelected && !r && (
                  <div style={{ padding: "6px 10px", borderTop: `1px solid ${C.border}`, background: C.bg, fontSize: 10, color: C.red }}>Error: {item.error}</div>
                )}
              </div>
            );
          })}
        </div>

        {/* Right — PDF viewer */}
        <div style={{ flex: 1, display: "flex", flexDirection: "column", overflow: "hidden", border: `1px solid ${C.border}`, borderRadius: 8, background: C.panelAlt }}>
          {pdfUrl ? (
            <>
              <div style={{ padding: "7px 12px", borderBottom: `1px solid ${C.border}`, display: "flex", gap: 10, alignItems: "center", flexShrink: 0, background: C.panel }}>
                <span style={{ fontSize: 12, color: C.text, fontWeight: 600, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap", flex: 1 }}>
                  {filtered.find(r => r.id === selectedIdx)?.filename || ""}
                </span>
                <span style={{ fontSize: 10, color: C.muted, flexShrink: 0 }}>👍 👎 to override</span>
              </div>
              <iframe src={pdfUrl} style={{ flex: 1, border: "none", width: "100%", display: "block" }} title="PDF" />
            </>
          ) : (
            <div style={{ flex: 1, display: "flex", alignItems: "center", justifyContent: "center", flexDirection: "column", gap: 10, color: C.muted }}>
              <div style={{ fontSize: 28 }}>📄</div>
              <div style={{ fontSize: 13 }}>Click a paper to preview it here</div>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
