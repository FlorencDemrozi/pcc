import { useState } from "react";
import { C } from "../utils/theme.js";
import { Badge, StatCard, SectionTitle, ProgressBar, PrimaryButton, GhostButton, EmptyState } from "../components/ui.jsx";
import { callLLM, countPagesBackend } from "../utils/api.js";
import { readFileAsBase64 } from "../utils/fileParser.js";
import { getField, matchMeta, safeParseJSON, exportCSV } from "../utils/helpers.js";

async function runScreeningAPI(pdfBase64, meta, conf, pageCount, strictness) {
  const pageInfo   = pageCount ? `The PDF has exactly ${pageCount} pages (pre-counted — treat as ground truth).` : "";
  const pageStatus = pageCount
    ? (pageCount <= (conf.maxPages || 6) ? `Page limit: PASS (${pageCount} pages, limit ${conf.maxPages || 6})` : `Page limit: FAIL (${pageCount} pages exceeds limit of ${conf.maxPages || 6})`)
    : "Page count: unknown";

  const strict = strictness || {};
  const strictnessNote = [
    strict.novelty === "strict"  ? "NOVELTY: Apply strict standards — only clear, demonstrable novelty scores Strong. Incremental improvements score Weak." :
    strict.novelty === "lenient" ? "NOVELTY: Apply lenient standards — acknowledge novelty in applied fields even if incremental." : "",
    strict.soa === "strict"      ? "SOA: Apply strict standards — require comprehensive recent citations. Missing key works score Superficial." :
    strict.soa === "lenient"     ? "SOA: Apply lenient standards — accept reasonable coverage even if not exhaustive." : "",
    strict.writing === "strict"  ? "WRITING: Apply strict standards — minor clarity issues lower the rating." :
    strict.writing === "lenient" ? "WRITING: Apply lenient standards — overlook minor language issues if technical content is clear." : "",
    strict.llm === "strict"      ? "LLM DETECTION: Flag even moderate signals of AI-generated text." :
    strict.llm === "lenient"     ? "LLM DETECTION: Only flag strong, unambiguous signals." : "",
  ].filter(Boolean).join("\n");

  const system = `You are an AI assistant helping a Program Chair perform quality screening of conference paper submissions.

Conference: ${conf.name || "N/A"}
Template: ${conf.template || "N/A"}
Scope: ${conf.scope || "N/A"}
${pageInfo}
${pageStatus}
${strictnessNote ? "\nSTRICTNESS SETTINGS:\n" + strictnessNote : ""}

IMPORTANT INSTRUCTIONS:
- Page count and blind compliance have already been checked deterministically. Do NOT assess them — focus on content quality only.
- Do NOT flag anonymisation placeholders (Author, Anonymous, [Author], Author One, etc.) as identity leaks. Only flag real names (e.g. Mario Rossi, John Smith) that appear to be genuine leaks.
- Assess novelty, SoA coverage, writing quality, figures, and LLM-writing signals based on the paper content.

Return ONLY a JSON object (no markdown, no preamble):
{"scope_fit":{"rating":"Strong","explanation":""},"novelty_signal":{"rating":"Strong","explanation":""},"soa_coverage":{"rating":"Adequate","explanation":""},"writing_quality":{"rating":"Good","issues":""},"figure_quality":{"rating":"Good","issues":""},"llm_signal":{"flag":false,"confidence":"Low","explanation":""},"recommendation":"Accept for review","recommendation_rationale":"2-3 sentences","key_strengths":["",""],"key_concerns":["",""]}

Valid values:
- scope_fit.rating: "Strong" | "Moderate" | "Weak" | "Out of scope"
- novelty_signal.rating: "Strong" | "Moderate" | "Weak" | "Cannot assess"
- soa_coverage.rating: "Adequate" | "Superficial" | "Missing" | "Cannot assess"
- writing_quality.rating: "Good" | "Acceptable" | "Poor"
- figure_quality.rating: "Good" | "Acceptable" | "Poor" | "N/A"
- llm_signal.confidence: "High" | "Medium" | "Low"
- recommendation: "Accept for review" | "Accept for review with concerns" | "Borderline" | "Desk reject"`;

  const text = await callLLM(system, [
    { type: "document", source: { type: "base64", media_type: "application/pdf", data: pdfBase64 } },
    { type: "text", text: `Title: ${meta.title || "N/A"}\nTrack: ${meta.track || "N/A"}\nAbstract: ${meta.abstract || "N/A"}\n\nAssess the paper quality and return only the JSON.` },
  ], 1800, "screening");

  return safeParseJSON(text);
}

export function ScreeningModule({ conf, pdfFiles, metaRows, activeTrack = "All" }) {
  const [papers,     setPapers]     = useState([]);
  const [prog,       setProg]       = useState({ done: 0, total: 0, cur: "" });
  const [running,    setRunning]    = useState(false);
  const [expanded,   setExpanded]   = useState(null);
  const [filter,     setFilter]     = useState("All");
  const [strictness, setStrictness] = useState({ novelty: "standard", soa: "standard", writing: "standard", llm: "standard" });

  const getFileTrack = filename => {
    if (!metaRows.length) return "";
    const matches = filename.match(/[_\-](\d{4,})/g);
    if (!matches) return "";
    const pid = matches[matches.length - 1].replace(/^[_\-]/, "");
    const row = metaRows.find(r => String(r["#"] || r.paper_id || r.id || "").trim() === pid);
    return row ? String(row.Track || row.track || "").trim() : "";
  };

  const filteredFiles = activeTrack === "All" ? pdfFiles : pdfFiles.filter(f => getFileTrack(f.name) === activeTrack);

  const run = async (force = false) => {
    if (papers.length > 0 && !force) return;
    setRunning(true); setPapers([]);
    const results = [];
    setProg({ done: 0, total: filteredFiles.length, cur: "" });
    for (let i = 0; i < filteredFiles.length; i++) {
      const f    = filteredFiles[i];
      const meta = matchMeta(f.name, metaRows);
      setProg({ done: i, total: filteredFiles.length, cur: f.name });
      try {
        const b64       = await readFileAsBase64(f);
        const pageCount = await countPagesBackend(f, f.name);
        const pagePass  = pageCount !== null ? pageCount <= (conf.maxPages || 6) : null;
        const result    = await runScreeningAPI(b64, {
          title:    getField(meta, "title", "Title"),
          track:    getField(meta, "track", "Track"),
          abstract: getField(meta, "abstract", "Abstract"),
        }, conf, pageCount, strictness);
        result._pageCount = pageCount;
        result._pagePass  = pagePass;
        results.push({ id: i + 1, filename: f.name, meta, result });
      } catch (e) {
        results.push({ id: i + 1, filename: f.name, meta, result: null, error: e.message });
      }
      setPapers([...results]);
    }
    setRunning(false);
  };

  const recCounts = papers.reduce((a, p) => { if (p.result) a[p.result.recommendation] = (a[p.result.recommendation] || 0) + 1; return a; }, {});
  const filtered  = filter === "All" ? papers : papers.filter(p => p.result?.recommendation === filter);

  if (!pdfFiles.length) return <EmptyState icon="🔬" title="No PDFs loaded" body="Upload the papers ZIP in the Data import tab." />;

  const StrictnessSelector = ({ label, dim }) => (
    <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
      <span style={{ fontSize: 11, fontWeight: 700, color: C.muted, textTransform: "uppercase", letterSpacing: "0.06em" }}>{label}</span>
      <div style={{ display: "flex", gap: 3 }}>
        {["lenient", "standard", "strict"].map(level => (
          <button key={level} onClick={() => setStrictness(p => ({ ...p, [dim]: level }))} style={{
            padding: "3px 10px", borderRadius: 4, fontSize: 11, fontWeight: 600, cursor: "pointer",
            border: `1px solid ${strictness[dim] === level ? C.accent : C.border}`,
            background: strictness[dim] === level ? C.accentDim : "transparent",
            color: strictness[dim] === level ? C.accentText : C.muted, textTransform: "capitalize",
          }}>{level}</button>
        ))}
      </div>
    </div>
  );

  return (
    <div>
      {!running && papers.length === 0 && (
        <div style={{ maxWidth: 560 }}>
          <div style={{ fontSize: 13, color: C.muted, marginBottom: 14 }}>
            {filteredFiles.length}{activeTrack !== "All" ? ` in "${activeTrack}"` : ""} of {pdfFiles.length} papers · {metaRows.length} metadata rows
          </div>
          <div style={{ background: C.panel, border: `1px solid ${C.border}`, borderRadius: 10, padding: "16px 20px", marginBottom: 16 }}>
            <SectionTitle>Evaluation strictness</SectionTitle>
            <div style={{ fontSize: 12, color: C.muted, marginBottom: 12, lineHeight: 1.5 }}>
              Set how strictly each dimension is evaluated. <strong style={{ color: C.text }}>Standard</strong> applies balanced academic conference criteria.
            </div>
            <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 14 }}>
              <StrictnessSelector label="Novelty"           dim="novelty" />
              <StrictnessSelector label="State of the art"  dim="soa" />
              <StrictnessSelector label="Writing quality"   dim="writing" />
              <StrictnessSelector label="LLM detection"     dim="llm" />
            </div>
          </div>
          <PrimaryButton onClick={() => run(true)}>Run AI screening →</PrimaryButton>
        </div>
      )}

      {running && <ProgressBar done={prog.done} total={prog.total} label={prog.cur} />}

      {papers.length > 0 && (
        <>
          <div style={{ display: "flex", gap: 10, marginBottom: 20, flexWrap: "wrap" }}>
            <StatCard label="Total"       value={papers.length}                                   color={C.text} />
            <StatCard label="Accept"      value={recCounts["Accept for review"] || 0}             color={C.green} />
            <StatCard label="Concerns"    value={recCounts["Accept for review with concerns"] || 0} color={C.amber} />
            <StatCard label="Borderline"  value={recCounts["Borderline"] || 0}                   color={C.orange} />
            <StatCard label="Desk reject" value={recCounts["Desk reject"] || 0}                  color={C.red} />
          </div>

          <div style={{ display: "flex", gap: 8, marginBottom: 16, flexWrap: "wrap" }}>
            {["All", "Accept for review", "Accept for review with concerns", "Borderline", "Desk reject"].map(f => (
              <button key={f} onClick={() => setFilter(f)} style={{
                padding: "4px 12px", borderRadius: 5, fontSize: 11, fontWeight: 600, cursor: "pointer",
                border: `1px solid ${filter === f ? C.accent : C.border}`,
                background: filter === f ? C.accent + "20" : "transparent",
                color: filter === f ? C.accentText : C.muted,
              }}>{f === "All" ? `All (${papers.length})` : f}</button>
            ))}
            <div style={{ flex: 1 }} />
            <GhostButton onClick={() => exportCSV(papers.map(p => ({
              id: p.id, filename: p.filename,
              title:          getField(p.meta, "title", "Title"),
              recommendation: p.result?.recommendation || "Error",
              pages:          p.result?._pageCount ?? "-",
              page_limit:     p.result?._pagePass === true ? "Pass" : p.result?._pagePass === false ? "Fail" : "N/A",
              scope:          p.result?.scope_fit?.rating || "",
              novelty:        p.result?.novelty_signal?.rating || "",
              soa:            p.result?.soa_coverage?.rating || "",
              writing:        p.result?.writing_quality?.rating || "",
              llm:            p.result?.llm_signal?.flag ? "Yes" : "No",
            })), "screening.csv")}>↓ Export CSV</GhostButton>
            {!running && <PrimaryButton onClick={run}>Re-run</PrimaryButton>}
          </div>

          {filtered.map((p, i) => {
            const r     = p.result;
            const isExp = expanded === i;
            if (!r) return (
              <div key={p.id} style={{ padding: 12, marginBottom: 8, background: C.redDim, border: `1px solid ${C.red}40`, borderRadius: 8, fontSize: 12, color: C.red }}>
                #{p.id} {p.filename} — {p.error}
              </div>
            );
            return (
              <div key={p.id} style={{ border: `1px solid ${C.border}`, borderRadius: 10, marginBottom: 8, overflow: "hidden" }}>
                <div onClick={() => setExpanded(isExp ? null : i)} style={{ padding: "12px 16px", cursor: "pointer", display: "flex", alignItems: "center", gap: 12, background: isExp ? C.panelAlt : C.panel }}>
                  <span style={{ fontSize: 10, color: C.muted, minWidth: 28, fontFamily: "monospace" }}>#{p.id}</span>
                  <span style={{ flex: 1, fontSize: 13, fontWeight: 500, color: C.text }}>{getField(p.meta, "title", "Title") || p.filename}</span>
                  {getField(p.meta, "track", "Track") && <span style={{ fontSize: 11, color: C.muted }}>{getField(p.meta, "track", "Track")}</span>}
                  <Badge label={r.recommendation} />
                  <span style={{ color: C.muted, fontSize: 12 }}>{isExp ? "▲" : "▼"}</span>
                </div>
                {isExp && (
                  <div style={{ padding: "14px 16px 16px", borderTop: `1px solid ${C.border}` }}>
                    <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 16, marginBottom: 14 }}>
                      <div>
                        <SectionTitle>Page count (deterministic)</SectionTitle>
                        <div style={{ display: "flex", gap: 8, alignItems: "center", marginBottom: 6 }}>
                          <span style={{ width: 60, fontSize: 11, color: C.muted, flexShrink: 0 }}>Pages</span>
                          <Badge label={r._pagePass === true ? "Pass" : r._pagePass === false ? "Fail" : "N/A"} />
                          <span style={{ fontSize: 11, color: C.muted }}>{r._pageCount != null ? `${r._pageCount} page${r._pageCount !== 1 ? "s" : ""}` : ""}</span>
                        </div>
                      </div>
                      <div>
                        <SectionTitle>Quality signals (AI)</SectionTitle>
                        {[
                          ["Scope",   r.scope_fit?.rating,        r.scope_fit?.explanation],
                          ["Novelty", r.novelty_signal?.rating,   r.novelty_signal?.explanation],
                          ["SoA",     r.soa_coverage?.rating,     r.soa_coverage?.explanation],
                          ["Writing", r.writing_quality?.rating,  r.writing_quality?.issues],
                          ["LLM",     r.llm_signal?.flag ? "Flagged" : "Clean", r.llm_signal?.explanation],
                        ].map(([l, rat, note]) => (
                          <div key={l} style={{ display: "flex", gap: 8, alignItems: "flex-start", marginBottom: 5 }}>
                            <span style={{ width: 60, fontSize: 11, color: C.muted, flexShrink: 0 }}>{l}</span>
                            <Badge label={rat} />
                            {note && <span style={{ fontSize: 11, color: C.muted, flex: 1, lineHeight: 1.4 }}>{note}</span>}
                          </div>
                        ))}
                      </div>
                    </div>
                    <SectionTitle>Rationale</SectionTitle>
                    <p style={{ fontSize: 12, color: C.muted, lineHeight: 1.7, margin: "0 0 12px" }}>{r.recommendation_rationale}</p>
                    <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 12 }}>
                      <div>
                        <SectionTitle>Strengths</SectionTitle>
                        {(r.key_strengths || []).map((s, j) => <div key={j} style={{ fontSize: 11, color: C.green, marginBottom: 4 }}>✓ {s}</div>)}
                      </div>
                      <div>
                        <SectionTitle>Concerns</SectionTitle>
                        {(r.key_concerns || []).map((s, j) => <div key={j} style={{ fontSize: 11, color: C.red, marginBottom: 4 }}>⚠ {s}</div>)}
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
