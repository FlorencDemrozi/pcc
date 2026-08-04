import { useState } from "react";
import { C, IS, LS } from "../utils/theme.js";
import { SectionTitle, ProgressBar, PrimaryButton, GhostButton } from "../components/ui.jsx";
import { exportCSV, rowsToCSV } from "../utils/helpers.js";

const LEVEL_COLOR = { Definite: "#EF4444", Probable: "#F59E0B", Possible: "#F97316" };

export function COIModule({ conf, metaRows, tpcRows, authorRows, activeTrack = "All" }) {
  const [results,      setResults]      = useState(null);
  const [running,      setRunning]      = useState(false);
  const [filter,       setFilter]       = useState("All");
  const [synonyms,     setSynonyms]     = useState("");
  const [useRor,       setUseRor]       = useState(false);
  const [useLlmExpand, setUseLlmExpand] = useState(false);

  const ready         = metaRows.length > 0 && tpcRows.length > 0;
  const hasAuthorList = authorRows && authorRows.length > 0;

  const inputStyle = IS();
  const labelStyle = LS();

  const run = async () => {
    if (!ready) return;
    setRunning(true); setResults(null);
    try {
      const fd = new FormData();
      const coiMeta = activeTrack === "All" ? metaRows : metaRows.filter(r => String(r.Track || r.track || "").trim() === activeTrack);
      fd.append("submissions_file", new Blob([rowsToCSV(coiMeta)],  { type: "text/csv" }), "submissions.csv");
      fd.append("tpc_file",         new Blob([rowsToCSV(tpcRows)],  { type: "text/csv" }), "tpc.csv");
      if (hasAuthorList)
        fd.append("author_list_file", new Blob([rowsToCSV(authorRows)], { type: "text/csv" }), "author_list.csv");

      const synDict = {};
      synonyms.split("\n").forEach(line => {
        const [key, ...vals] = line.split(":");
        if (key && vals.length) synDict[key.trim().toLowerCase()] = vals.join(":").split(",").map(v => v.trim()).filter(Boolean);
      });
      fd.append("extra_synonyms",  JSON.stringify(synDict));
      fd.append("use_ror",         String(useRor));
      fd.append("use_llm_expand",  String(useLlmExpand));

      const r = await fetch("/api/check/coi", { method: "POST", body: fd });
      if (!r.ok) {
        let msg = "Server error " + r.status;
        try { const e = await r.json(); msg = e.detail || JSON.stringify(e); } catch {}
        throw new Error(msg);
      }
      setResults(await r.json());
    } catch (e) { alert("COI error: " + (e.message || String(e))); }
    setRunning(false);
  };

  const allItems = results ? [
    ...results.definite.map(r => ({ ...r, conflict_level: "Definite" })),
    ...results.probable.map(r => ({ ...r, conflict_level: "Probable" })),
    ...results.possible.map(r => ({ ...r, conflict_level: "Possible" })),
  ] : [];
  const filtered = filter === "All" ? allItems : allItems.filter(r => r.conflict_level === filter);

  if (!ready) return (
    <div style={{ textAlign: "center", padding: "48px 0", color: C.muted }}>
      <div style={{ fontSize: 32, marginBottom: 12 }}>🔍</div>
      <div>Load submissions and TPC members files in the <strong>Data import</strong> tab first.</div>
      <div style={{ fontSize: 12, marginTop: 8 }}>Submissions: {metaRows.length} papers · TPC members: {tpcRows.length}</div>
    </div>
  );

  return (
    <div>
      <div style={{ background: C.panel, border: `1px solid ${C.border}`, borderRadius: 8, padding: "10px 14px", marginBottom: 14, display: "flex", gap: 20, flexWrap: "wrap" }}>
        <span style={{ fontSize: 12, color: C.text }}>📂 <strong>{metaRows.length}</strong> papers</span>
        <span style={{ fontSize: 12, color: C.text }}>👥 <strong>{tpcRows.length}</strong> TPC members</span>
        <span style={{ fontSize: 12, color: C.muted }}>Pairs to check: <strong>{(metaRows.length * tpcRows.length).toLocaleString()}</strong></span>
      </div>

      <div style={{ background: C.panel, border: `1px solid ${C.border}`, borderRadius: 10, padding: "14px 18px", marginBottom: 14 }}>
        <label style={labelStyle}>Additional institution synonyms (optional)</label>
        <textarea style={{ ...inputStyle, height: 52, resize: "vertical", fontFamily: "monospace", fontSize: 11 }}
          placeholder={"canonical name: variant1, variant2\ne.g. University of Example: UoE, Example University"}
          value={synonyms} onChange={e => setSynonyms(e.target.value)} />
        <div style={{ fontSize: 11, color: C.muted, marginTop: 4 }}>Common variants already built in (Politecnico di Torino / Polytechnic of Turin etc.)</div>
      </div>

      <div style={{ background: C.panel, border: `1px solid ${C.border}`, borderRadius: 8, padding: "12px 16px", marginBottom: 14 }}>
        <SectionTitle>Synonym expansion</SectionTitle>
        <div style={{ display: "flex", gap: 16, flexWrap: "wrap", marginBottom: 10 }}>
          {[
            [useRor, setUseRor, "ROR lookup", "Research Organization Registry — 100k+ institutions, free, requires internet (~3-5s)"],
            [useLlmExpand, setUseLlmExpand, "LLM expansion", "AI identifies abbreviations and informal names that ROR misses (~2-3s, uses your configured provider)"],
          ].map(([checked, setter, title, desc]) => (
            <label key={title} style={{ display: "flex", gap: 8, alignItems: "flex-start", cursor: "pointer", fontSize: 12, color: C.muted }}>
              <input type="checkbox" checked={checked} onChange={e => setter(e.target.checked)} style={{ marginTop: 2 }} />
              <div>
                <span style={{ fontWeight: 600, color: C.text }}>{title}</span>
                <div style={{ fontSize: 11, marginTop: 2 }}>{desc}</div>
              </div>
            </label>
          ))}
        </div>
        {!useRor && !useLlmExpand && <div style={{ fontSize: 11, color: C.amber }}>⚠ Only built-in synonyms will be used. Affiliation conflicts may be missed.</div>}
      </div>

      <PrimaryButton onClick={run} disabled={running}>{running ? "Checking…" : "Run COI detection →"}</PrimaryButton>
      {running && (
        <div style={{ marginTop: 8 }}>
          <ProgressBar done={0} total={1} label={useRor || useLlmExpand ? "Expanding affiliation synonyms then checking all pairs…" : "Checking all TPC × paper combinations…"} />
        </div>
      )}

      {results && (
        <>
          <div style={{ background: C.panel, border: `1px solid ${C.border}`, borderRadius: 10, padding: "16px 20px", margin: "16px 0" }}>
            <SectionTitle>COI summary — {results.total_pairs.toLocaleString()} combinations checked</SectionTitle>
            <div style={{ display: "flex", gap: 8, marginBottom: 10 }}>
              {[
                ["Definite", results.definite_count, C.red,    "Do not assign"],
                ["Probable", results.probable_count, C.amber,  "Flag for review"],
                ["Possible", results.possible_count, C.orange, "Verify manually"],
                ["Clean",    results.clean_count,    C.green,  "No conflict"],
              ].map(([label, count, color, sub]) => (
                <div key={label} style={{ flex: 1, background: color + "10", border: `1px solid ${color}30`, borderRadius: 8, padding: "10px 12px", textAlign: "center" }}>
                  <div style={{ fontSize: 24, fontWeight: 700, color, fontFamily: "monospace" }}>{count}</div>
                  <div style={{ fontSize: 11, fontWeight: 600, color, marginTop: 2 }}>{label}</div>
                  <div style={{ fontSize: 10, color: C.muted }}>{sub}</div>
                </div>
              ))}
            </div>
          </div>

          <div style={{ display: "flex", gap: 8, marginBottom: 14, flexWrap: "wrap" }}>
            {["All", "Definite", "Probable", "Possible"].map(f => (
              <button key={f} onClick={() => setFilter(f)} style={{
                padding: "4px 12px", borderRadius: 5, fontSize: 11, fontWeight: 600, cursor: "pointer",
                border: `1px solid ${filter === f ? (LEVEL_COLOR[f] || C.accent) : C.border}`,
                background: filter === f ? (LEVEL_COLOR[f] || C.accent) + "20" : "transparent",
                color: filter === f ? (LEVEL_COLOR[f] || C.accentText) : C.muted,
              }}>{f}{f === "All" ? ` (${allItems.length})` : ""}</button>
            ))}
            <div style={{ flex: 1 }} />
            <GhostButton onClick={() => exportCSV(allItems.map(r => ({
              tpc_member: r.reviewer_name, tpc_email: r.reviewer_email || "",
              paper_id: r.paper_id, paper: r.paper_title,
              level: r.conflict_level, types: r.conflict_types.join("; "),
              evidence: r.evidence.join(" | "), action: r.recommendation,
            })), "coi_report.csv")}>↓ Export CSV</GhostButton>
          </div>

          {filtered.length === 0 && <div style={{ textAlign: "center", padding: "20px", color: C.muted, fontSize: 12 }}>No conflicts at this level.</div>}
          {filtered.map((item, i) => (
            <div key={i} style={{
              padding: "10px 14px", marginBottom: 6, borderRadius: 8,
              border: `1px solid ${(LEVEL_COLOR[item.conflict_level] || C.border) + "60"}`,
              background: `${LEVEL_COLOR[item.conflict_level] || C.panel}10`,
              display: "flex", gap: 12, alignItems: "flex-start",
            }}>
              <div style={{ flex: 1 }}>
                <div style={{ display: "flex", gap: 10, marginBottom: 3, flexWrap: "wrap", alignItems: "center" }}>
                  <div>
                    <span style={{ fontSize: 12, fontWeight: 700, color: C.text }}>{item.reviewer_name}</span>
                    {item.reviewer_email && <span style={{ fontSize: 11, color: C.muted, marginLeft: 8, fontFamily: C.mono }}>{item.reviewer_email}</span>}
                  </div>
                  <span style={{ fontSize: 11, color: C.muted }}>→</span>
                  <span style={{ fontSize: 12, color: C.text }}>#{item.paper_id}: {(item.paper_title || "").slice(0, 60)}</span>
                </div>
                {item.evidence.map((ev, j) => <div key={j} style={{ fontSize: 11, color: C.muted, marginTop: 2 }}>• {ev}</div>)}
              </div>
              <div style={{ display: "flex", flexDirection: "column", gap: 3, alignItems: "flex-end", flexShrink: 0 }}>
                <span style={{ fontSize: 11, fontWeight: 700, color: LEVEL_COLOR[item.conflict_level] || C.text, padding: "1px 8px", borderRadius: 3, background: (LEVEL_COLOR[item.conflict_level] || C.muted) + "20" }}>
                  {item.conflict_level}
                </span>
                <span style={{ fontSize: 10, color: C.muted, textAlign: "right", maxWidth: 140 }}>{item.recommendation}</span>
              </div>
            </div>
          ))}
        </>
      )}
    </div>
  );
}
