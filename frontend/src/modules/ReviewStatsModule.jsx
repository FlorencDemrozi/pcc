import { useState } from "react";
import { C } from "../utils/theme.js";
import { SectionTitle, StatCard, ProgressBar, PrimaryButton, GhostButton, EmptyState, InfoBanner } from "../components/ui.jsx";
import { exportCSV, rowsToCSV } from "../utils/helpers.js";

export function ReviewStatsModule({ reviewRows, metaRows, activeTrack = "All" }) {
  const [stats,      setStats]      = useState(null);
  const [running,    setRunning]    = useState(false);
  const [activeTab,  setActiveTab]  = useState("overview");
  const [recFilter,  setRecFilter]  = useState("All");
  const [tierFilter, setTierFilter] = useState("All");
  const [tooltip,    setTooltip]    = useState(null);

  const TIER_COLOR = { "Very Good": C.green, Good: C.teal, Average: C.amber, Poor: C.orange, Unacceptable: C.red };
  const REC_COLOR  = { "Strong Accept": C.green, Accept: C.teal, "Weak Accept": "#4ade80", Borderline: C.amber, "Weak Reject": C.orange, Reject: C.red, "Strong Reject": "#7f1d1d", "Insufficient data": C.muted };

  const ready = reviewRows.length > 0;

  const filteredReviewRows = activeTrack === "All" ? reviewRows : (() => {
    const trackPids = new Set(metaRows.filter(r => String(r.Track || r.track || "").trim() === activeTrack).map(r => String(r["#"] || r.paper_id || r.id || "").trim()));
    return reviewRows.filter(r => trackPids.has(String(r["#"] || r.paper_id || r.submission || r["paper id"] || "").trim()));
  })();
  const filteredMetaRows = activeTrack === "All" ? metaRows : metaRows.filter(r => String(r.Track || r.track || "").trim() === activeTrack);

  const run = async () => {
    if (!ready) return;
    setRunning(true);
    try {
      const fd = new FormData();
      fd.append("reviews_file", new Blob([rowsToCSV(filteredReviewRows)], { type: "text/csv" }), "reviews.csv");
      if (filteredMetaRows.length > 0)
        fd.append("submissions_file", new Blob([rowsToCSV(filteredMetaRows)], { type: "text/csv" }), "submissions.csv");
      const r = await fetch("/api/stats/reviews", { method: "POST", body: fd });
      if (!r.ok) { let msg = "Error"; try { msg = (await r.json()).detail || msg; } catch {} throw new Error(msg); }
      setStats(await r.json());
    } catch (e) { alert("Stats error: " + (e.message || String(e))); }
    setRunning(false);
  };

  const Tooltip = () => !tooltip ? null : (
    <div style={{ position: "fixed", left: tooltip.x + 12, top: tooltip.y - 8, zIndex: 9999, background: C.panel, border: `1px solid ${C.border}`, borderRadius: 6, padding: "5px 10px", fontSize: 11, color: C.text, pointerEvents: "none", whiteSpace: "nowrap", boxShadow: "0 4px 12px #00000040" }}>
      {tooltip.text}
    </div>
  );

  // ── SVG Charts ───────────────────────────────────────────────────────────────
  const SVGHistogram = ({ data, width = 340, height = 130 }) => {
    if (!data || Object.keys(data).length === 0) return null;
    const entries = Object.entries(data).sort((a, b) => Number(a[0]) - Number(b[0]));
    const maxVal  = Math.max(...entries.map(([, v]) => v), 1);
    const barW    = Math.floor((width - 40) / entries.length) - 2;
    const chartH  = height - 30;
    const total   = entries.reduce((s, [, v]) => s + v, 0);
    const mean    = entries.reduce((s, [k, v]) => s + Number(k) * v, 0) / total;
    const meanX   = 40 + ((mean - Number(entries[0][0])) / (Number(entries[entries.length - 1][0]) - Number(entries[0][0]) || 1)) * (width - 40);
    const LABELS  = { "-3": "Strong Reject", "-2": "Reject", "-1": "Weak Reject", "0": "Borderline", "1": "Weak Accept", "2": "Accept", "3": "Strong Accept" };
    return (
      <svg width={width} height={height} style={{ overflow: "visible" }}>
        {entries.map(([score, count], i) => {
          const bh = Math.max((count / maxVal) * chartH, count > 0 ? 2 : 0);
          const x  = 40 + i * (barW + 2);
          const y  = chartH - bh;
          return (
            <g key={score} onMouseEnter={e => setTooltip({ x: e.clientX, y: e.clientY, text: `Score ${score} (${LABELS[score] || ""}): ${count} review${count !== 1 ? "s" : ""}` })} onMouseLeave={() => setTooltip(null)} style={{ cursor: "pointer" }}>
              <rect x={x} y={y} width={barW} height={bh} fill={Number(score) >= 1 ? C.green : Number(score) >= -1 ? C.amber : C.red} rx={2} opacity={0.85} />
              {count > 0 && <text x={x + barW / 2} y={y - 3} textAnchor="middle" fill={C.muted} fontSize={9}>{count}</text>}
              <text x={x + barW / 2} y={height - 4} textAnchor="middle" fill={C.muted} fontSize={10}>{score}</text>
            </g>
          );
        })}
        <line x1={meanX} y1={0} x2={meanX} y2={chartH} stroke={C.amber} strokeWidth={1.5} strokeDasharray="3,3" />
        <text x={meanX + 3} y={10} fill={C.amber} fontSize={9}>mean={mean.toFixed(2)}</text>
      </svg>
    );
  };

  const SVGBarChart = ({ items, labelKey, valueKey, color, width = 340, height = 140, unitLabel = "" }) => {
    if (!items || items.length === 0) return null;
    const maxVal = Math.max(...items.map(d => Number(d[valueKey]) || 0), 1);
    const rowH   = Math.floor(height / items.length) - 2;
    return (
      <svg width={width} height={height} style={{ overflow: "visible" }}>
        {items.map((item, i) => {
          const val  = Number(item[valueKey]) || 0;
          const bw   = Math.round((val / maxVal) * (width - 120));
          const y    = i * (rowH + 2);
          const label = String(item[labelKey] || "").slice(0, 18);
          return (
            <g key={i} onMouseEnter={e => setTooltip({ x: e.clientX, y: e.clientY, text: `${item[labelKey]}: ${val}${unitLabel}` })} onMouseLeave={() => setTooltip(null)} style={{ cursor: "pointer" }}>
              <text x={0} y={y + rowH / 2 + 4} fill={C.muted} fontSize={10}>{label}</text>
              <rect x={120} y={y} width={Math.max(bw, 2)} height={rowH} fill={color || C.accent} rx={2} opacity={0.85} />
              <text x={120 + bw + 4} y={y + rowH / 2 + 4} fill={C.muted} fontSize={10}>{val}{unitLabel}</text>
            </g>
          );
        })}
      </svg>
    );
  };

  const SVGDonut = ({ segments, size = 120 }) => {
    const total = segments.reduce((s, sg) => s + sg.value, 0);
    if (!total) return null;
    const cx = size / 2, cy = size / 2, r = size / 2 - 10, innerR = r * 0.55;
    let angle = -Math.PI / 2;
    const paths = segments.map(sg => {
      const sweep = (sg.value / total) * 2 * Math.PI;
      const x1 = cx + r * Math.cos(angle), y1 = cy + r * Math.sin(angle);
      angle += sweep;
      const x2 = cx + r * Math.cos(angle), y2 = cy + r * Math.sin(angle);
      const ix1 = cx + innerR * Math.cos(angle - sweep), iy1 = cy + innerR * Math.sin(angle - sweep);
      const ix2 = cx + innerR * Math.cos(angle), iy2 = cy + innerR * Math.sin(angle);
      const large = sweep > Math.PI ? 1 : 0;
      return { ...sg, d: `M ${x1} ${y1} A ${r} ${r} 0 ${large} 1 ${x2} ${y2} L ${ix2} ${iy2} A ${innerR} ${innerR} 0 ${large} 0 ${ix1} ${iy1} Z` };
    });
    return (
      <svg width={size} height={size}>
        {paths.map((p, i) => (
          <path key={i} d={p.d} fill={p.color} opacity={0.9}
            onMouseEnter={e => setTooltip({ x: e.clientX, y: e.clientY, text: `${p.label}: ${p.value} (${Math.round(p.value / total * 100)}%)` })}
            onMouseLeave={() => setTooltip(null)} style={{ cursor: "pointer" }} />
        ))}
        <text x={cx} y={cy + 4} textAnchor="middle" fill={C.text} fontSize={13} fontWeight="700">{total}</text>
      </svg>
    );
  };

  const ChartDesc = ({ text }) => <div style={{ fontSize: 11, color: C.muted, marginBottom: 10, lineHeight: 1.5, fontStyle: "italic" }}>{text}</div>;

  const TABS = ["decisions", "overview", "charts", "papers", "reviewers", "flags"];

  return (
    <div>
      <Tooltip />
      {!ready ? (
        <EmptyState icon="📊" title="No review data loaded" body="Load your reviews file (XLSX, CSV, or TXT) and submissions file in the Data import tab first." />
      ) : (
        <>
          <div style={{ background: C.panel, border: `1px solid ${C.border}`, borderRadius: 8, padding: "12px 16px", marginBottom: 14, display: "flex", gap: 20, flexWrap: "wrap", alignItems: "center" }}>
            <span style={{ fontSize: 12, color: C.text }}>📋 <strong style={{ fontFamily: C.mono }}>{reviewRows.length}</strong> reviews</span>
            {metaRows.length > 0
              ? <span style={{ fontSize: 12, color: C.text }}>📄 <strong style={{ fontFamily: C.mono }}>{metaRows.length}</strong> submissions</span>
              : <span style={{ fontSize: 12, color: C.amber }}>⚠ No submissions file — track breakdown unavailable</span>}
            <div style={{ flex: 1 }} />
            <PrimaryButton onClick={run} disabled={running}>{running ? "Computing…" : "Compute stats →"}</PrimaryButton>
          </div>
          {running && <ProgressBar done={0} total={1} label="Computing calibrated statistics…" />}

          {stats && (
            <>
              <div style={{ display: "flex", gap: 10, marginBottom: 16, flexWrap: "wrap" }}>
                <StatCard label="Reviews"    value={stats.total_reviews}                                              color={C.text} />
                <StatCard label="Papers"     value={stats.total_papers}                                               color={C.text} />
                <StatCard label="Reviewers"  value={stats.total_reviewers}                                            color={C.text} />
                <StatCard label="Completion" value={`${Math.min(stats.completion_rate, 100)}%`}                       color={stats.completion_rate >= 80 ? C.green : C.amber} />
                <StatCard label="Mean score" value={stats.score_mean ?? "-"}                                          color={C.accent} sub="EasyChair −3 to +3" />
                <StatCard label="Std dev"    value={stats.score_stdev ?? "-"}                                         color={C.muted} sub="Score spread" />
              </div>

              {/* Tab bar */}
              <div style={{ display: "flex", gap: 0, marginBottom: 20, borderBottom: `2px solid ${C.border}` }}>
                {TABS.map(t => (
                  <div key={t} onClick={() => setActiveTab(t)} style={{ padding: "8px 16px", cursor: "pointer", fontSize: 12, fontWeight: 600, textTransform: "capitalize", color: activeTab === t ? C.accentText : C.muted, borderBottom: `2px solid ${activeTab === t ? C.accent : "transparent"}`, marginBottom: -2 }}>
                    {t}{t === "flags" && stats.quality_flags?.filter(f => f.tier === "Poor" || f.tier === "Unacceptable").length > 0 ? ` (${stats.quality_flags.filter(f => f.tier === "Poor" || f.tier === "Unacceptable").length})` : ""}
                  </div>
                ))}
              </div>

              {/* Decisions tab */}
              {activeTab === "decisions" && (
                <>
                  {stats.total_submissions > 0 ? (
                    <>
                      <div style={{ display: "flex", gap: 10, marginBottom: 20, flexWrap: "wrap" }}>
                        <StatCard label="Submissions"    value={stats.total_submissions}                                        color={C.text} />
                        <StatCard label="Accepted"       value={stats.accepted}                                                 color={C.green} />
                        <StatCard label="Rejected"       value={stats.rejected}                                                 color={C.red} />
                        <StatCard label="Borderline"     value={stats.borderline}                                               color={C.amber} />
                        <StatCard label="Acceptance rate" value={stats.acceptance_rate != null ? `${stats.acceptance_rate}%` : "—"} color={C.teal} />
                      </div>
                      {(stats.decisions_by_track || []).length > 0 && (
                        <div style={{ background: C.panel, border: `1px solid ${C.border}`, borderRadius: 10, padding: "16px 20px", marginBottom: 14 }}>
                          <SectionTitle>Acceptance rate by track</SectionTitle>
                          {(stats.decisions_by_track || []).filter(t => t.acceptance_rate != null).map((t, i) => (
                            <div key={i} style={{ display: "flex", gap: 10, alignItems: "center", marginBottom: 8 }}
                              onMouseEnter={e => setTooltip({ x: e.clientX, y: e.clientY, text: `${t.track}: ${t.accepted} accepted / ${t.total} total = ${t.acceptance_rate}%` })}
                              onMouseLeave={() => setTooltip(null)}>
                              <span style={{ fontSize: 11, color: C.text, width: 120, flexShrink: 0, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{t.track}</span>
                              <div style={{ flex: 1, height: 8, background: C.border, borderRadius: 4, overflow: "hidden", display: "flex", cursor: "pointer" }}>
                                <div style={{ width: `${t.acceptance_rate}%`, background: C.green, borderRadius: "4px 0 0 4px" }} />
                                <div style={{ width: `${100 - t.acceptance_rate}%`, background: C.red + "60", borderRadius: "0 4px 4px 0" }} />
                              </div>
                              <span style={{ fontSize: 11, color: C.green, width: 36, textAlign: "right", flexShrink: 0, fontFamily: C.mono }}>{t.acceptance_rate}%</span>
                            </div>
                          ))}
                        </div>
                      )}
                      <GhostButton onClick={() => exportCSV(stats.decisions_by_track || [], "decisions_by_track.csv")}>↓ Export track decisions CSV</GhostButton>
                    </>
                  ) : (
                    <EmptyState icon="⚖" title="No decision data" body="Load a submissions file with a Decision column in the Data import tab." />
                  )}
                </>
              )}

              {/* Overview tab */}
              {activeTab === "overview" && (
                <>
                  {(stats.missing_reviews?.length > 0 || stats.high_variance_papers?.length > 0 || stats.overloaded_reviewers?.length > 0) && (
                    <div style={{ background: C.panel, border: `1px solid ${C.amber}40`, borderRadius: 10, padding: "16px 20px", marginBottom: 14 }}>
                      <SectionTitle>⚠ Flags requiring attention</SectionTitle>
                      {stats.missing_reviews?.map((p, i) => <div key={i} style={{ fontSize: 12, color: C.amber, marginBottom: 4 }}>Paper #{p.id} "{(p.title || "").slice(0, 50)}" — {p.review_count} review(s), needs {p.needed} more</div>)}
                      {stats.high_variance_papers?.map((p, i) => <div key={i} style={{ fontSize: 12, color: C.orange, marginBottom: 4 }}>Paper #{p.id} — reviewers strongly disagree (scores range {p.score_min} to {p.score_max}, σ={p.score_stdev})</div>)}
                      {stats.overloaded_reviewers?.map((r, i) => <div key={i} style={{ fontSize: 12, color: C.red, marginBottom: 4 }}>Reviewer {r.id} — {r.count} assignments (consider redistributing)</div>)}
                    </div>
                  )}
                  {stats.tracks?.length > 0 && (
                    <div style={{ background: C.panel, border: `1px solid ${C.border}`, borderRadius: 10, padding: "16px 20px", marginBottom: 14 }}>
                      <SectionTitle>Per-track summary</SectionTitle>
                      <ChartDesc text="Completion = percentage of expected reviews received (3 per paper). Hover for details." />
                      {stats.tracks.map((t, i) => {
                        const pct = Math.min(t.completion_rate, 100);
                        return (
                          <div key={i} style={{ display: "grid", gridTemplateColumns: "2fr 60px 1fr 60px 80px", gap: 0, alignItems: "center" }}
                            onMouseEnter={e => setTooltip({ x: e.clientX, y: e.clientY, text: `${t.track}: ${t.review_count} reviews for ${t.paper_count} papers` })}
                            onMouseLeave={() => setTooltip(null)}>
                            <div style={{ fontSize: 12, color: C.text, padding: "7px 6px", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{t.track}</div>
                            <div style={{ fontSize: 12, color: C.muted, padding: "7px 6px", textAlign: "right", fontFamily: C.mono }}>{t.paper_count}</div>
                            <div style={{ padding: "7px 6px" }}>
                              <div style={{ height: 8, background: C.border, borderRadius: 4, overflow: "hidden" }}>
                                <div style={{ height: "100%", background: pct >= 80 ? C.green : C.amber, width: `${pct}%`, borderRadius: 4 }} />
                              </div>
                            </div>
                            <div style={{ fontSize: 12, color: pct >= 80 ? C.green : C.amber, padding: "7px 6px", textAlign: "right", fontFamily: C.mono, fontWeight: 600 }}>{pct}%</div>
                            <div style={{ fontSize: 12, color: C.accent, padding: "7px 6px", textAlign: "right", fontFamily: C.mono }}>{t.mean_score ?? "-"}</div>
                          </div>
                        );
                      })}
                    </div>
                  )}
                </>
              )}

              {/* Charts tab */}
              {activeTab === "charts" && (
                <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 14 }}>
                  {stats.score_distribution && Object.keys(stats.score_distribution).length > 0 && (
                    <div style={{ background: C.panel, border: `1px solid ${C.border}`, borderRadius: 10, padding: "16px 20px" }}>
                      <SectionTitle>Score distribution</SectionTitle>
                      <ChartDesc text="How many reviews gave each score. EasyChair scale: −3 = Strong Reject to +3 = Strong Accept. Dashed line = mean." />
                      <SVGHistogram data={stats.score_distribution} width={300} height={130} />
                    </div>
                  )}
                  {stats.tracks?.length > 0 && (
                    <div style={{ background: C.panel, border: `1px solid ${C.border}`, borderRadius: 10, padding: "16px 20px" }}>
                      <SectionTitle>Papers per track</SectionTitle>
                      <ChartDesc text="Total submitted papers per track. Hover for exact count." />
                      <SVGBarChart items={stats.tracks} labelKey="track" valueKey="paper_count" color={C.accent} width={300} height={Math.max(60, stats.tracks.length * 22)} unitLabel=" papers" />
                    </div>
                  )}
                  {stats.reviewers?.length > 0 && (
                    <div style={{ background: C.panel, border: `1px solid ${C.border}`, borderRadius: 10, padding: "16px 20px" }}>
                      <SectionTitle>Reviewer load (top 10)</SectionTitle>
                      <ChartDesc text="Reviews assigned per reviewer. High counts may indicate overload." />
                      <SVGBarChart items={[...stats.reviewers].sort((a, b) => b.review_count - a.review_count).slice(0, 10)} labelKey="id" valueKey="review_count" color={C.teal} width={300} height={Math.min(220, stats.reviewers.length * 22)} unitLabel=" reviews" />
                    </div>
                  )}
                </div>
              )}

              {/* Papers tab */}
              {activeTab === "papers" && (
                <>
                  <InfoBanner type="info">
                    <strong>Raw mean</strong> = average score (−3 to +3). <strong>Calibrated</strong> = adjusted for reviewer strictness. <strong>Percentile</strong> = rank within track.
                  </InfoBanner>
                  <div style={{ display: "flex", gap: 8, marginBottom: 12, flexWrap: "wrap" }}>
                    {["All", "Strong Accept", "Accept", "Borderline", "Reject", "Strong Reject"].map(f => (
                      <button key={f} onClick={() => setRecFilter(f)} style={{ padding: "3px 10px", borderRadius: 5, fontSize: 11, fontWeight: 600, cursor: "pointer", border: `1px solid ${recFilter === f ? (REC_COLOR[f] || C.accent) : C.border}`, background: recFilter === f ? (REC_COLOR[f] || C.accent) + "20" : "transparent", color: recFilter === f ? (REC_COLOR[f] || C.accentText) : C.muted }}>{f}</button>
                    ))}
                    <div style={{ flex: 1 }} />
                    <GhostButton onClick={() => exportCSV((stats.papers || []).map(p => ({ id: p.id, title: p.title, track: p.track, raw_mean: p.raw_mean, calibrated_mean: p.calibrated_mean, percentile_in_track: p.track_percentile, review_count: p.review_count, recommendation: p.recommendation })), "stats_papers.csv")}>↓ Export CSV</GhostButton>
                  </div>
                  {(stats.papers || []).filter(p => recFilter === "All" || p.recommendation === recFilter).map((p, i) => (
                    <div key={i} style={{ display: "grid", gridTemplateColumns: "60px 1fr 120px 90px 90px 80px 50px 120px", gap: 0, alignItems: "center", background: i % 2 ? C.panelAlt + "40" : "transparent", borderRadius: 4, border: `1px solid ${(REC_COLOR[p.recommendation] || C.border) + "30"}` }}
                      onMouseEnter={e => setTooltip({ x: e.clientX, y: e.clientY, text: `${p.title || `Paper #${p.id}`} — ${p.review_count} reviews` })}
                      onMouseLeave={() => setTooltip(null)}>
                      <div style={{ fontSize: 11, color: C.muted, padding: "7px 6px", fontFamily: C.mono }}>#{p.id}</div>
                      <div style={{ fontSize: 12, color: C.text, padding: "7px 6px", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{p.title || `Paper #${p.id}`}</div>
                      <div style={{ fontSize: 11, color: C.muted, padding: "7px 6px", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{p.track || "—"}</div>
                      <div style={{ fontSize: 12, color: C.text, padding: "7px 6px", textAlign: "right", fontFamily: C.mono }}>{p.raw_mean ?? "-"}</div>
                      <div style={{ fontSize: 12, padding: "7px 6px", textAlign: "right", fontFamily: C.mono, color: p.calibrated_mean == null ? C.muted : p.calibrated_mean > 0 ? C.green : p.calibrated_mean < 0 ? C.red : C.muted }}>
                        {p.calibrated_mean != null ? (p.calibrated_mean > 0 ? "+" : "") + p.calibrated_mean : "—"}
                      </div>
                      <div style={{ fontSize: 12, color: C.muted, padding: "7px 6px", textAlign: "right", fontFamily: C.mono }}>{p.track_percentile != null ? `${p.track_percentile}th` : "—"}</div>
                      <div style={{ fontSize: 12, color: C.muted, padding: "7px 6px", textAlign: "center", fontFamily: C.mono }}>{p.review_count}</div>
                      <div style={{ fontSize: 11, fontWeight: 600, padding: "7px 6px", color: REC_COLOR[p.recommendation] || C.text }}>{p.recommendation}</div>
                    </div>
                  ))}
                </>
              )}

              {/* Reviewers tab */}
              {activeTab === "reviewers" && (
                <>
                  <InfoBanner type="info">
                    <strong>Avg score given</strong> = mean score assigned by this reviewer. Compare to the conference average ({stats.score_mean}) to detect strict or lenient reviewers.
                  </InfoBanner>
                  {(stats.reviewers || []).map((r, i) => {
                    const tiers      = r.quality_tier_counts || {};
                    const scoreColor = r.mean_score_given == null ? C.muted : r.mean_score_given > stats.score_mean + 0.5 ? C.green : r.mean_score_given < stats.score_mean - 0.5 ? C.red : C.muted;
                    return (
                      <div key={i} style={{ display: "grid", gridTemplateColumns: "1fr 80px 120px 1fr", gap: 0, alignItems: "center", background: i % 2 ? C.panelAlt + "40" : "transparent", borderRadius: 4, border: `1px solid ${C.border}20`, marginBottom: 2 }}
                        onMouseEnter={e => setTooltip({ x: e.clientX, y: e.clientY, text: `${r.id}: ${r.review_count} reviews, avg score ${r.mean_score_given ?? "-"}` })}
                        onMouseLeave={() => setTooltip(null)}>
                        <div style={{ fontSize: 12, color: C.text, padding: "8px 8px", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{r.id}</div>
                        <div style={{ fontSize: 12, color: C.muted, padding: "8px 8px", textAlign: "right", fontFamily: C.mono }}>{r.review_count}</div>
                        <div style={{ fontSize: 12, padding: "8px 8px", textAlign: "right", fontFamily: C.mono, color: scoreColor, fontWeight: 600 }}>{r.mean_score_given ?? "—"}</div>
                        <div style={{ display: "flex", gap: 4, padding: "8px 8px", flexWrap: "wrap" }}>
                          {Object.entries(TIER_COLOR).map(([tier, color]) => tiers[tier] > 0 && (
                            <span key={tier} style={{ fontSize: 10, padding: "1px 7px", borderRadius: 3, background: color + "20", color, fontWeight: 600, whiteSpace: "nowrap" }}>{tier}: {tiers[tier]}</span>
                          ))}
                        </div>
                      </div>
                    );
                  })}
                  <div style={{ marginTop: 10 }}>
                    <GhostButton onClick={() => exportCSV((stats.reviewers || []).map(r => ({ reviewer: r.id, reviews: r.review_count, avg_score_given: r.mean_score_given, ...Object.fromEntries(Object.entries(r.quality_tier_counts || {}).map(([k, v]) => [`quality_${k.replace(" ", "_")}`, v])) })), "stats_reviewers.csv")}>↓ Export reviewer stats CSV</GhostButton>
                  </div>
                </>
              )}

              {/* Flags tab */}
              {activeTab === "flags" && (
                <>
                  <InfoBanner type="info">Reviews flagged for quality issues based on text length, score/text inconsistency, confidence level, or suspicious patterns. <strong>Poor</strong> and <strong>Unacceptable</strong> reviews should be followed up.</InfoBanner>
                  <div style={{ display: "flex", gap: 8, marginBottom: 12, flexWrap: "wrap" }}>
                    {["All", ...Object.keys(TIER_COLOR)].map(f => (
                      <button key={f} onClick={() => setTierFilter(f)} style={{ padding: "3px 10px", borderRadius: 5, fontSize: 11, fontWeight: 600, cursor: "pointer", border: `1px solid ${tierFilter === f ? (TIER_COLOR[f] || C.accent) : C.border}`, background: tierFilter === f ? (TIER_COLOR[f] || C.accent) + "20" : "transparent", color: tierFilter === f ? (TIER_COLOR[f] || C.accentText) : C.muted }}>{f}</button>
                    ))}
                  </div>
                  {(stats.quality_flags || []).filter(f => tierFilter === "All" || f.tier === tierFilter).map((f, i) => (
                    <div key={i} style={{ padding: "10px 16px", marginBottom: 6, borderRadius: 8, border: `1px solid ${(TIER_COLOR[f.tier] || C.border) + "50"}`, background: C.panel, display: "flex", gap: 12, alignItems: "flex-start" }}>
                      <div style={{ flex: 1 }}>
                        <div style={{ fontSize: 12, color: C.text }}>Paper #{f.paper_id} · Reviewer: <strong>{f.reviewer_id}</strong></div>
                        <div style={{ fontSize: 11, color: C.muted, marginTop: 3 }}>Score: <strong style={{ color: C.text }}>{f.score ?? "-"}</strong> · Confidence: <strong style={{ color: C.text }}>{f.confidence ?? "-"}/5</strong> · Length: <strong style={{ color: C.text }}>{f.text_length} chars</strong></div>
                        {f.signals.map((s, j) => <div key={j} style={{ fontSize: 11, color: TIER_COLOR[f.tier] || C.muted, marginTop: 2 }}>• {s}</div>)}
                      </div>
                      <span style={{ fontSize: 11, fontWeight: 700, color: TIER_COLOR[f.tier] || C.text, flexShrink: 0 }}>{f.tier}</span>
                    </div>
                  ))}
                </>
              )}

              <div style={{ marginTop: 12 }}>
                <GhostButton onClick={() => exportCSV(stats.papers || [], "review_stats.csv")}>↓ Export paper stats CSV</GhostButton>
              </div>
            </>
          )}
        </>
      )}
    </div>
  );
}
