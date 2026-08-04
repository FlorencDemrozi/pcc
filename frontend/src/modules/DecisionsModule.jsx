import { useState } from "react";
import { C, IS, LS } from "../utils/theme.js";
import { SectionTitle, StatCard, GhostButton, PrimaryButton, EmptyState } from "../components/ui.jsx";
import { getField } from "../utils/helpers.js";
import { rowsToCSV } from "../utils/helpers.js";

const DEC_COLOR = {
  "Strong Accept": C.green, "Accept": "#0D9488", "Weak Accept": "#4ade80",
  "Borderline": "#F59E0B", "Weak Reject": "#F97316",
  "Reject": "#EF4444", "Strong Reject": "#7f1d1d", "Error": "#64748B",
};

export function DecisionsModule({ conf, metaRows, reviewRows, activeTrack = "All" }) {
  const [customPrompt, setCustomPrompt] = useState("");
  const [running,      setRunning]      = useState(false);
  const [decisions,    setDecisions]    = useState([]);
  const [filter,       setFilter]       = useState("All");
  const [expanded,     setExpanded]     = useState(null);

  const ready = reviewRows.length > 0;

  const filteredMeta = activeTrack === "All" ? metaRows
    : metaRows.filter(r => String(r.Track || r.track || "").trim() === activeTrack);
  const trackPids = activeTrack === "All" ? null
    : new Set(filteredMeta.map(r => String(r["#"] || r.paper_id || r.id || "").trim()));
  const filteredReviews = activeTrack === "All" ? reviewRows
    : reviewRows.filter(r => {
        const pid = String(r["#"] || r.paper_id || r.submission || r["paper id"] || "").trim();
        return !trackPids || trackPids.has(pid);
      });

  const run = async () => {
    if (!ready) return;
    setRunning(true); setDecisions([]);
    try {
      const fd = new FormData();
      fd.append("reviews_file",    new Blob([rowsToCSV(filteredReviews)],  { type: "text/csv" }), "reviews.csv");
      if (filteredMeta.length > 0)
        fd.append("submissions_file", new Blob([rowsToCSV(filteredMeta)], { type: "text/csv" }), "submissions.csv");
      fd.append("custom_prompt", customPrompt);
      const r = await fetch("/api/decisions/run", { method: "POST", body: fd });
      if (!r.ok) { const e = await r.json(); throw new Error(e.detail || "Error"); }
      const d = await r.json();
      setDecisions(d.decisions || []);
    } catch (e) { alert("Error: " + e.message); }
    setRunning(false);
  };

  const exportFile = async fmt => {
    const r = await fetch(`/api/decisions/export/${fmt}`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ decisions }),
    });
    if (!r.ok) return;
    const blob = await r.blob();
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = `decisions.${fmt}`;
    a.click();
  };

  const decCounts       = decisions.reduce((a, d) => { a[d.decision] = (a[d.decision] || 0) + 1; return a; }, {});
  const needsDiscussion = decisions.filter(d => d.requires_discussion).length;
  const filtered        = filter === "All" ? decisions : decisions.filter(d => d.decision === filter);

  const inputStyle = IS();
  const labelStyle = LS();

  if (!ready) return (
    <EmptyState icon="⚖" title="No review data loaded"
      body="Load your reviews file in the Data import tab first. Optionally also load the submissions file for paper titles and tracks." />
  );

  return (
    <div>
      <div style={{ background: C.panel, border: `1px solid ${C.border}`, borderRadius: 10, padding: "16px 20px", marginBottom: 14 }}>
        <div style={{ display: "flex", gap: 16, flexWrap: "wrap", alignItems: "center", marginBottom: 12 }}>
          <span style={{ fontSize: 12, color: C.text }}>📋 <strong style={{ fontFamily: C.mono }}>{reviewRows.length}</strong> reviews loaded</span>
          {metaRows.length > 0
            ? <span style={{ fontSize: 12, color: C.text }}>📄 <strong style={{ fontFamily: C.mono }}>{metaRows.length}</strong> submissions loaded</span>
            : <span style={{ fontSize: 12, color: C.amber }}>⚠ No submissions file — paper titles will not be shown</span>}
        </div>
        <div style={{ marginBottom: 12 }}>
          <label style={labelStyle}>Custom decision criteria (optional)</label>
          <textarea style={{ ...inputStyle, height: 72, resize: "vertical" }}
            placeholder={"Leave empty for standard criteria, or describe your requirements:\ne.g. Accept only papers where all reviewers gave a positive score."}
            value={customPrompt} onChange={e => setCustomPrompt(e.target.value)} />
        </div>
        <PrimaryButton onClick={run} disabled={running}>{running ? "Processing…" : "Run decisions →"}</PrimaryButton>
        {running && <div style={{ fontSize: 12, color: C.muted, marginTop: 8 }}>Processing papers — this may take a moment…</div>}
      </div>

      {decisions.length > 0 && (
        <>
          {/* Summary bar chart */}
          <div style={{ background: C.panel, border: `1px solid ${C.border}`, borderRadius: 10, padding: "16px 20px", marginBottom: 14 }}>
            <SectionTitle>Decision summary — {decisions.length} papers</SectionTitle>
            <div style={{ display: "flex", gap: 6, alignItems: "flex-end", height: 80, marginBottom: 8 }}>
              {["Strong Accept", "Accept", "Weak Accept", "Borderline", "Weak Reject", "Reject", "Strong Reject"].map(dec => {
                const count    = decCounts[dec] || 0;
                const maxCount = Math.max(...Object.values(decCounts), 1);
                return (
                  <div key={dec} style={{ flex: 1, display: "flex", flexDirection: "column", alignItems: "center", gap: 3, cursor: "pointer" }}
                    onClick={() => setFilter(filter === dec ? "All" : dec)}>
                    <div style={{ fontSize: 9, color: count > 0 ? DEC_COLOR[dec] : C.muted }}>{count > 0 ? count : ""}</div>
                    <div style={{ width: "100%", background: count > 0 ? DEC_COLOR[dec] : C.border, height: `${(count / maxCount) * 56}px`, borderRadius: "3px 3px 0 0", minHeight: count > 0 ? 4 : 2, opacity: filter !== "All" && filter !== dec ? 0.3 : 1, transition: "all 0.2s" }} />
                    <div style={{ fontSize: 9, color: C.muted, textAlign: "center", lineHeight: 1.2 }}>{dec.split(" ").map(w => w[0]).join("")}</div>
                  </div>
                );
              })}
            </div>
            <div style={{ display: "flex", gap: 16, flexWrap: "wrap" }}>
              {[
                ["Accept (all)",    (decCounts["Strong Accept"] || 0) + (decCounts["Accept"] || 0) + (decCounts["Weak Accept"] || 0), C.green],
                ["Borderline",      decCounts["Borderline"] || 0, C.amber],
                ["Reject (all)",    (decCounts["Weak Reject"] || 0) + (decCounts["Reject"] || 0) + (decCounts["Strong Reject"] || 0), C.red],
                ["Needs discussion",needsDiscussion, C.orange],
              ].map(([label, count, color]) => (
                <div key={label} style={{ fontSize: 12 }}>
                  <span style={{ color, fontWeight: 700 }}>{count}</span>
                  <span style={{ color: C.muted }}> {label}</span>
                </div>
              ))}
            </div>
          </div>

          {/* Filter + export row */}
          <div style={{ display: "flex", gap: 8, marginBottom: 14, flexWrap: "wrap", alignItems: "center" }}>
            <button onClick={() => setFilter("All")} style={{ padding: "4px 12px", borderRadius: 5, fontSize: 11, fontWeight: 600, cursor: "pointer", border: `1px solid ${filter === "All" ? C.accent : C.border}`, background: filter === "All" ? C.accent + "20" : "transparent", color: filter === "All" ? C.accentText : C.muted }}>
              All ({decisions.length})
            </button>
            {Object.entries(decCounts).map(([dec, count]) => (
              <button key={dec} onClick={() => setFilter(filter === dec ? "All" : dec)} style={{ padding: "4px 10px", borderRadius: 5, fontSize: 11, fontWeight: 600, cursor: "pointer", border: `1px solid ${filter === dec ? (DEC_COLOR[dec] || C.accent) : C.border}`, background: filter === dec ? (DEC_COLOR[dec] || C.accent) + "20" : "transparent", color: filter === dec ? (DEC_COLOR[dec] || C.accentText) : C.muted }}>
                {dec} ({count})
              </button>
            ))}
            <div style={{ flex: 1 }} />
            <GhostButton onClick={() => exportFile("csv")}>↓ CSV</GhostButton>
            <PrimaryButton onClick={() => exportFile("xlsx")}>↓ Excel</PrimaryButton>
          </div>

          {/* Decision rows */}
          {filtered.map((d, i) => {
            const isExp = expanded === i;
            const dc    = DEC_COLOR[d.decision] || C.muted;
            return (
              <div key={i} style={{ border: `1px solid ${dc}40`, borderRadius: 10, marginBottom: 8, overflow: "hidden" }}>
                <div onClick={() => setExpanded(isExp ? null : i)} style={{ padding: "11px 16px", cursor: "pointer", display: "flex", gap: 12, alignItems: "center", background: isExp ? C.panelAlt : C.panel }}>
                  <span style={{ fontSize: 10, color: C.muted, fontFamily: "monospace", minWidth: 28 }}>#{d.paper_id}</span>
                  <span style={{ flex: 1, fontSize: 13, fontWeight: 500, color: C.text }}>{d.title}</span>
                  {d.track && <span style={{ fontSize: 11, color: C.muted }}>{d.track}</span>}
                  <span style={{ fontSize: 11, color: C.muted }}>{d.review_count} reviews</span>
                  {d.requires_discussion && <span style={{ fontSize: 10, color: C.amber }}>⚠ Discuss</span>}
                  <span style={{ fontSize: 12, fontWeight: 700, color: dc }}>{d.decision}</span>
                  <span style={{ color: C.muted, fontSize: 12 }}>{isExp ? "▲" : "▼"}</span>
                </div>
                {isExp && (
                  <div style={{ padding: "12px 16px 14px", borderTop: `1px solid ${C.border}` }}>
                    {d.authors && <div style={{ fontSize: 12, color: C.muted, marginBottom: 8 }}>Authors: {d.authors}</div>}
                    <div style={{ display: "flex", gap: 8, marginBottom: 10, flexWrap: "wrap" }}>
                      <span style={{ fontSize: 12, fontWeight: 700, color: dc, padding: "2px 10px", borderRadius: 4, background: dc + "20", border: `1px solid ${dc}40` }}>{d.decision}</span>
                      <span style={{ fontSize: 12, color: C.muted, padding: "2px 10px", borderRadius: 4, background: C.border }}>{d.confidence} confidence</span>
                    </div>
                    <p style={{ fontSize: 12, color: C.muted, lineHeight: 1.7, margin: "0 0 10px" }}>{d.rationale}</p>
                    {d.requires_discussion && d.discussion_reason && (
                      <div style={{ fontSize: 12, color: C.amber, background: C.amber + "10", border: `1px solid ${C.amber}30`, borderRadius: 6, padding: "8px 12px", marginBottom: 10 }}>
                        ⚠ {d.discussion_reason}
                      </div>
                    )}
                    <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 12 }}>
                      <div>
                        <SectionTitle>Strengths</SectionTitle>
                        {(d.key_strengths || []).map((s, j) => <div key={j} style={{ fontSize: 11, color: C.green, marginBottom: 3 }}>✓ {s}</div>)}
                      </div>
                      <div>
                        <SectionTitle>Weaknesses</SectionTitle>
                        {(d.key_weaknesses || []).map((s, j) => <div key={j} style={{ fontSize: 11, color: C.red, marginBottom: 3 }}>✗ {s}</div>)}
                      </div>
                    </div>
                  </div>
                )}
              </div>
            );
          })}
        </>
      )}
    </div>
  );
}
