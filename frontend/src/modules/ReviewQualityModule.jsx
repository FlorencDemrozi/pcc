import { useState } from "react";
import { C } from "../utils/theme.js";
import { Badge, StatCard, SectionTitle, ProgressBar, PrimaryButton, GhostButton, EmptyState } from "../components/ui.jsx";
import { callLLM } from "../utils/api.js";
import { getField, safeParseJSON, exportCSV } from "../utils/helpers.js";

async function assessPaperReviews(paperTitle, reviews, conf) {
  const MAX_TEXT = 800;
  const reviewsBlock = reviews.map((rv, i) => {
    const text = (rv.text || rv.review || rv.comments || "").slice(0, MAX_TEXT);
    return `Review ${i + 1} (${rv.reviewer || "Reviewer " + (i + 1)}):\nScore: ${rv.score || "N/A"} | Confidence: ${rv.confidence || "N/A"}\n${text}${text.length >= MAX_TEXT ? "…[truncated]" : ""}`;
  }).join("\n\n---\n\n");

  const system = `You are a Program Chair assistant assessing peer review quality for "${conf.name || "the conference"}".
Assess each review. Return ONLY a JSON array (no markdown), one object per review:
[{"reviewer":"string","completeness":{"rating":"Satisfactory|Needs improvement|Poor","issues":""},"score_text_consistency":{"rating":"Consistent|Inconsistent","explanation":""},"technical_depth":{"rating":"Good|Adequate|Superficial","explanation":""},"soa_awareness":{"rating":"Good|Adequate|Weak","explanation":""},"constructiveness":{"rating":"Good|Adequate|Poor","explanation":""},"flag_for_intervention":false,"flag_reason":"","overall_quality":"Satisfactory|Acceptable|Needs improvement","recommendation":"Accept as is|Request revision|Flag for PC discussion"}]`;

  const text   = await callLLM(system, `Paper: "${paperTitle}"\n\n${reviewsBlock}\n\nReturn only the JSON array.`, Math.min(300 + reviews.length * 400, 2000), "reviews");
  const parsed = safeParseJSON(text);
  return Array.isArray(parsed) ? parsed : [parsed];
}

export function ReviewQualityModule({ conf, metaRows, reviewRows, activeTrack = "All" }) {
  const [results,     setResults]     = useState([]);
  const [prog,        setProg]        = useState({ done: 0, total: 0, cur: "" });
  const [running,     setRunning]     = useState(false);
  const [expanded,    setExpanded]    = useState(null);
  const [filter,      setFilter]      = useState("All");
  const [scoreFilter, setScoreFilter] = useState("all");

  const groupByPaper = () => {
    const groups = {};
    reviewRows.forEach(rv => {
      const pid = getField(rv, "#", "id", "paper_id", "submission", "Paper") || "?";
      if (!groups[pid]) groups[pid] = { pid, reviews: [] };
      groups[pid].reviews.push(rv);
    });
    return Object.values(groups);
  };

  const filteredGroups = () => {
    const groups = groupByPaper();
    if (scoreFilter === "all") return groups;
    return groups.filter(g => {
      const scores = g.reviews.map(rv => parseFloat(getField(rv, "score", "Score", "overall", "Overall"))).filter(s => !isNaN(s));
      const avg    = scores.length ? scores.reduce((a, b) => a + b, 0) / scores.length : 0;
      if (scoreFilter === "negative")   return avg < 0;
      if (scoreFilter === "borderline") return avg >= -0.5 && avg <= 0.5;
      return true;
    });
  };

  const run = async (force = false) => {
    if (!reviewRows.length) return;
    if (results.length > 0 && !force) return;
    setRunning(true); setResults([]);
    const all    = [];
    const groups = filteredGroups();
    setProg({ done: 0, total: groups.length, cur: "" });
    for (let i = 0; i < groups.length; i++) {
      const { pid, reviews } = groups[i];
      const meta  = metaRows.find(m => String(getField(m, "#", "id", "paper_id")).trim() === String(pid).trim()) || {};
      const title = getField(meta, "title", "Title") || `Paper #${pid}`;
      setProg({ done: i, total: groups.length, cur: title });
      try {
        const batchResults = await assessPaperReviews(title, reviews, conf);
        reviews.forEach((rv, j) => {
          const res = batchResults[j] || batchResults[0] || {};
          all.push({ id: all.length + 1, paperId: pid, title, reviewer: getField(rv, "reviewer", "Reviewer", "email", "Email") || `Reviewer ${j + 1}`, score: getField(rv, "score", "Score", "overall", "Overall"), result: res });
        });
      } catch (e) {
        reviews.forEach((rv, j) => {
          all.push({ id: all.length + 1, paperId: pid, title, reviewer: getField(rv, "reviewer", "Reviewer") || `Reviewer ${j + 1}`, result: null, error: e.message });
        });
      }
      setResults([...all]);
    }
    setRunning(false);
  };

  const flagged  = results.filter(r => r.result?.flag_for_intervention);
  const qCounts  = results.reduce((a, r) => { if (r.result) a[r.result.overall_quality] = (a[r.result.overall_quality] || 0) + 1; return a; }, {});
  const filtered = filter === "All" ? results : filter === "Flagged" ? flagged : results.filter(r => r.result?.overall_quality === filter);
  const allGroups   = groupByPaper();
  const toProcess   = filteredGroups();

  if (!reviewRows.length) return (
    <EmptyState icon="📋" title="No review data loaded" body="Load your reviews file (EasyChair .txt or review summary .xlsx) in the Data import tab." />
  );

  return (
    <div>
      {results.length === 0 && !running && (
        <div style={{ background: C.panel, border: `1px solid ${C.border}`, borderRadius: 10, padding: "20px 24px", marginBottom: 16 }}>
          <SectionTitle>Processing scope</SectionTitle>
          <div style={{ fontSize: 12, color: C.muted, marginBottom: 12, lineHeight: 1.6 }}>
            Reviews are processed <strong style={{ color: C.text }}>per paper</strong> (1 LLM call per paper). Select scope to reduce token usage.
          </div>
          <div style={{ display: "flex", gap: 8, flexWrap: "wrap", marginBottom: 14 }}>
            {[
              ["all",        `All ${allGroups.length} papers`,   C.text],
              ["negative",   "Negative avg score only",          C.red],
              ["borderline", "Borderline only (−0.5 to +0.5)",   C.amber],
            ].map(([val, label, color]) => (
              <button key={val} onClick={() => setScoreFilter(val)} style={{
                padding: "6px 14px", borderRadius: 5, fontSize: 12, fontWeight: 600, cursor: "pointer",
                border: `1px solid ${scoreFilter === val ? color + "60" : C.border}`,
                background: scoreFilter === val ? color + "18" : "transparent",
                color: scoreFilter === val ? color : C.muted,
              }}>{label}</button>
            ))}
          </div>
          <div style={{ fontSize: 12, color: C.muted, marginBottom: 16 }}>
            Will process <strong style={{ color: C.text, fontFamily: C.mono }}>{toProcess.length}</strong> papers → <strong style={{ color: C.accent, fontFamily: C.mono }}>{toProcess.length}</strong> LLM calls
          </div>
          <PrimaryButton onClick={() => run(true)}>Assess review quality →</PrimaryButton>
        </div>
      )}

      {running && <ProgressBar done={prog.done} total={prog.total} label={prog.cur} />}

      {results.length > 0 && (
        <>
          <div style={{ display: "flex", gap: 10, marginBottom: 16, flexWrap: "wrap" }}>
            <StatCard label="Reviews"          value={results.length}                    color={C.text} />
            <StatCard label="Satisfactory"     value={qCounts["Satisfactory"] || 0}      color={C.green} />
            <StatCard label="Acceptable"       value={qCounts["Acceptable"] || 0}        color={C.amber} />
            <StatCard label="Needs improvement" value={qCounts["Needs improvement"] || 0} color={C.orange} />
            <StatCard label="Flagged"          value={flagged.length}                    color={C.red} sub="Intervention needed" />
          </div>

          <div style={{ display: "flex", gap: 8, marginBottom: 14, flexWrap: "wrap" }}>
            {["All", "Flagged", "Satisfactory", "Acceptable", "Needs improvement"].map(f => (
              <button key={f} onClick={() => setFilter(f)} style={{
                padding: "4px 12px", borderRadius: 5, fontSize: 11, fontWeight: 600, cursor: "pointer",
                border: `1px solid ${filter === f ? C.accent : C.border}`,
                background: filter === f ? C.accent + "20" : "transparent",
                color: filter === f ? C.accentText : C.muted,
              }}>{f === "Flagged" ? `⚠ Flagged (${flagged.length})` : f}</button>
            ))}
            <div style={{ flex: 1 }} />
            <GhostButton small onClick={() => run(true)}>Re-run</GhostButton>
            <GhostButton onClick={() => exportCSV(results.map(r => ({
              id: r.id, paper: r.title, reviewer: r.reviewer, score: r.score,
              quality:     r.result?.overall_quality || "Error",
              flag:        r.result?.flag_for_intervention ? "Yes" : "No",
              flag_reason: r.result?.flag_reason || "",
              action:      r.result?.recommendation || "",
            })), "review_quality.csv")}>↓ Export CSV</GhostButton>
          </div>

          {filtered.map((item, i) => {
            const r     = item.result;
            const isExp = expanded === i;
            if (!r) return (
              <div key={item.id} style={{ padding: 10, marginBottom: 6, background: C.redDim, border: `1px solid ${C.red}40`, borderRadius: 8, fontSize: 12, color: C.red }}>
                Error processing review {item.id}: {item.error}
              </div>
            );
            return (
              <div key={item.id} style={{ border: `1px solid ${r.flag_for_intervention ? C.red + "60" : C.border}`, borderRadius: 10, marginBottom: 8, overflow: "hidden" }}>
                <div onClick={() => setExpanded(isExp ? null : i)} style={{ padding: "11px 16px", cursor: "pointer", display: "flex", gap: 12, alignItems: "center", background: isExp ? C.panelAlt : C.panel }}>
                  <span style={{ fontSize: 10, color: C.muted, fontFamily: C.mono, minWidth: 24 }}>#{item.id}</span>
                  <span style={{ flex: 1, fontSize: 13, fontWeight: 500, color: C.text }}>{item.title}</span>
                  {item.reviewer && <span style={{ fontSize: 11, color: C.muted }}>{item.reviewer}</span>}
                  {item.score    && <span style={{ fontSize: 11, color: C.muted, fontFamily: C.mono }}>{item.score}</span>}
                  {r.flag_for_intervention && <span style={{ fontSize: 11, color: C.red, fontWeight: 600 }}>⚠</span>}
                  <Badge label={r.overall_quality} />
                  <span style={{ color: C.muted, fontSize: 12 }}>{isExp ? "▲" : "▼"}</span>
                </div>
                {isExp && (
                  <div style={{ padding: "14px 16px 16px", borderTop: `1px solid ${C.border}` }}>
                    <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 12, marginBottom: 12 }}>
                      {[
                        ["Completeness",    r.completeness?.rating,          r.completeness?.issues],
                        ["Score/text",      r.score_text_consistency?.rating, r.score_text_consistency?.explanation],
                        ["Technical depth", r.technical_depth?.rating,       r.technical_depth?.explanation],
                        ["SoA awareness",   r.soa_awareness?.rating,         r.soa_awareness?.explanation],
                        ["Constructiveness",r.constructiveness?.rating,      r.constructiveness?.explanation],
                      ].map(([l, rat, note]) => (
                        <div key={l} style={{ display: "flex", gap: 8, alignItems: "flex-start" }}>
                          <span style={{ width: 110, fontSize: 11, color: C.muted, flexShrink: 0 }}>{l}</span>
                          <div>
                            <Badge label={rat} />
                            {note && <div style={{ fontSize: 11, color: C.muted, marginTop: 4, lineHeight: 1.5 }}>{note}</div>}
                          </div>
                        </div>
                      ))}
                    </div>
                    {r.flag_reason && (
                      <div style={{ fontSize: 12, color: C.red, background: C.redDim, border: `1px solid ${C.red}30`, borderRadius: 6, padding: "8px 12px", marginBottom: 10 }}>
                        ⚠ {r.flag_reason}
                      </div>
                    )}
                    <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
                      <span style={{ fontSize: 11, color: C.muted }}>Recommended action:</span>
                      <Badge label={r.recommendation} />
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
