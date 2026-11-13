// ── Submission overview ───────────────────────────────────────────────────────
// Descriptive statistics computed locally from the files in Data import:
// totals, per-track breakdown (papers, decisions, review coverage, PC size),
// countries, affiliations, authors per paper, keywords, submissions over time.
import { useMemo, useState } from "react";
import { C } from "../utils/theme.js";
import { StatCard, SectionTitle, GhostButton, EmptyState } from "../components/ui.jsx";
import { getField, rowId, exportCSV, classifyDecision } from "../utils/helpers.js";

const NO_TRACK = "(no track)";
const trackOf  = r => getField(r, "Track", "track") || NO_TRACK;
const fmtPct   = (n, d) => (d ? `${Math.round((100 * n) / d)}%` : "—");

function splitKeywords(s) {
  return String(s || "").split(/[\n,;]+/).map(k => k.trim().toLowerCase()).filter(k => k.length > 1);
}

const MONTHS = ["jan","feb","mar","apr","may","jun","jul","aug","sep","oct","nov","dec"];

// Returns "YYYY-MM-DD". EasyChair writes "Jan 27, 09:49" without a year: those
// get `fallbackYear` (taken from the conference config, or the current year).
function parseDay(s, fallbackYear) {
  const str = String(s || "").trim();
  let m = str.match(/(\d{4})-(\d{2})-(\d{2})/);
  if (m) return `${m[1]}-${m[2]}-${m[3]}`;
  m = str.match(/^([A-Za-z]{3})[a-z]*\.?\s+(\d{1,2})(?:,?\s+(\d{4}))?/);
  if (m && MONTHS.includes(m[1].toLowerCase())) {
    const mm = String(MONTHS.indexOf(m[1].toLowerCase()) + 1).padStart(2, "0");
    return `${m[3] || fallbackYear}-${mm}-${m[2].padStart(2, "0")}`;
  }
  m = str.match(/^(\d{1,2})\/(\d{1,2})\/(\d{4})/);   // 1/27/2026 (US, as Excel exports it)
  if (m) return `${m[3]}-${m[1].padStart(2, "0")}-${m[2].padStart(2, "0")}`;
  return null;
}

// ── Small chart pieces (single-hue magnitude bars, hover tooltip) ─────────────

function useTooltip() {
  const [tip, setTip] = useState(null);
  const bind = text => ({
    onMouseEnter: e => setTip({ x: e.clientX, y: e.clientY, text }),
    onMouseMove:  e => setTip({ x: e.clientX, y: e.clientY, text }),
    onMouseLeave: () => setTip(null),
  });
  const node = tip && (
    <div style={{
      position: "fixed", left: tip.x + 12, top: tip.y + 12, zIndex: 50, pointerEvents: "none",
      background: C.panelAlt, border: `1px solid ${C.border}`, borderRadius: 6, padding: "6px 9px",
      fontSize: 11, color: C.text, boxShadow: "0 4px 14px rgba(0,0,0,0.25)", maxWidth: 320,
    }}>{tip.text}</div>
  );
  return { bind, node };
}

function Panel({ title, children, action }) {
  return (
    <div style={{ background: C.panel, border: `1px solid ${C.border}`, borderRadius: 10, padding: "16px 20px", marginBottom: 14 }}>
      <div style={{ display: "flex", alignItems: "baseline" }}>
        <div style={{ flex: 1 }}><SectionTitle>{title}</SectionTitle></div>
        {action}
      </div>
      {children}
    </div>
  );
}

// Horizontal bar list: [{label, value, tip}] — value labels in text ink, bars in accent.
function BarList({ items, bind, unit = "", labelWidth = 170 }) {
  const max = Math.max(1, ...items.map(i => i.value));
  return (
    <div>
      {items.map(it => (
        <div key={it.label} {...bind(it.tip || `${it.label}: ${it.value}${unit}`)}
          style={{ display: "flex", alignItems: "center", gap: 10, padding: "3px 0", cursor: "default" }}>
          <span style={{ width: labelWidth, flexShrink: 0, fontSize: 11, color: C.text, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{it.label}</span>
          <div style={{ flex: 1, height: 8 }}>
            <div style={{ width: `${(100 * it.value) / max}%`, minWidth: it.value ? 3 : 0, height: 8, background: C.accent, borderRadius: "0 4px 4px 0" }} />
          </div>
          <span style={{ width: 44, textAlign: "right", fontSize: 11, color: C.muted, fontFamily: C.mono, flexShrink: 0 }}>{it.value}{unit}</span>
        </div>
      ))}
    </div>
  );
}

// Vertical column chart for a time series / distribution.
function Columns({ items, bind, height = 120 }) {
  const max = Math.max(1, ...items.map(i => i.value));
  const step = Math.ceil(items.length / 8);   // label every n-th column only
  return (
    <div>
      <div style={{ display: "flex", alignItems: "flex-end", gap: 2, height, borderBottom: `1px solid ${C.border}` }}>
        {items.map(it => (
          <div key={it.label} {...bind(it.tip || `${it.label}: ${it.value}`)}
            style={{ flex: 1, height: "100%", display: "flex", alignItems: "flex-end", cursor: "default" }}>
            <div style={{ width: "100%", height: `${(100 * it.value) / max}%`, minHeight: it.value ? 2 : 0, background: C.accent, borderRadius: "4px 4px 0 0" }} />
          </div>
        ))}
      </div>
      {/* sparse axis labels: first, ~4 in between, last (never clipped by narrow columns) */}
      <div style={{ position: "relative", height: 14, marginTop: 4 }}>
        {items.map((it, i) => {
          const show = i === 0 || i === items.length - 1 || (i % Math.max(step, Math.ceil(items.length / 5)) === 0 && i < items.length - 3);
          if (!show) return null;
          const left = ((i + 0.5) / items.length) * 100;
          const tx = i === 0 ? "0" : i === items.length - 1 ? "-100%" : "-50%";
          return (
            <span key={it.label} style={{ position: "absolute", left: `${left}%`, transform: `translateX(${tx})`, fontSize: 10, color: C.muted, whiteSpace: "nowrap" }}>
              {it.short ?? it.label}
            </span>
          );
        })}
      </div>
    </div>
  );
}

// ── Module ────────────────────────────────────────────────────────────────────

export function OverviewModule({ conf = {}, metaRows = [], authorRows = [], tpcRows = [], reviewRows = [], pdfFiles = [], activeTrack = "All" }) {
  const { bind, node: tooltip } = useTooltip();
  const [sortKey, setSortKey] = useState("papers");
  const [minReviews, setMinReviews] = useState(3);

  const s = useMemo(() => {
    const inTrack = r => activeTrack === "All" || trackOf(r) === activeTrack;
    const papers = metaRows.filter(inTrack);
    const ids = new Set(papers.map(rowId));
    const allTrackOf = Object.fromEntries(metaRows.map(r => [rowId(r), trackOf(r)]));

    // reviews per paper
    const revCount = {};
    for (const r of reviewRows) {
      const pid = String(getField(r, "paper_id", "#", "Paper", "paper") || "").trim();
      if (pid) revCount[pid] = (revCount[pid] || 0) + 1;
    }

    // authors per paper / countries / affiliations
    const authorsByPaper = {};
    for (const a of authorRows) {
      const pid = rowId(a);
      if (!ids.has(pid)) continue;
      (authorsByPaper[pid] ||= []).push(a);
    }
    const uniqAuthors = new Set();
    const countryPapers = {}, countryAuthors = {}, affPapers = {};
    for (const [pid, list] of Object.entries(authorsByPaper)) {
      const cs = new Set(), afs = new Set();
      for (const a of list) {
        const name = getField(a, "Author", "Name", "name").toLowerCase();
        const email = getField(a, "Email", "email").toLowerCase();
        uniqAuthors.add(email || name);
        const c = getField(a, "Country", "country");
        if (c) { cs.add(c); countryAuthors[c] = (countryAuthors[c] || 0) + 1; }
        const af = getField(a, "Affiliation", "affiliation");
        if (af) afs.add(af);
      }
      cs.forEach(c => (countryPapers[c] = (countryPapers[c] || 0) + 1));
      afs.forEach(f => (affPapers[f] = (affPapers[f] || 0) + 1));
    }
    // papers whose authors come from more than one country
    const intl = Object.values(authorsByPaper).filter(l => new Set(l.map(a => getField(a, "Country", "country")).filter(Boolean)).size > 1).length;

    // authors-per-paper distribution
    const app = {};
    for (const p of papers) {
      const n = (authorsByPaper[rowId(p)] || []).length
        || String(getField(p, "Authors", "authors")).split(/,| and /).filter(x => x.trim()).length;
      const k = n >= 8 ? "8+" : String(n);
      app[k] = (app[k] || 0) + 1;
    }

    // per track
    const tracks = {};
    for (const p of papers) {
      const t = trackOf(p);
      const tr = (tracks[t] ||= { track: t, papers: 0, accept: 0, reject: 0, tentative: 0, none: 0,
                                  reviews: 0, underReviewed: 0, pc: new Set() });
      tr.papers++;
      tr[classifyDecision(getField(p, "Decision", "decision", "Status", "status"))]++;
      const rc = revCount[rowId(p)] || 0;
      tr.reviews += rc;
      if (rc < minReviews) tr.underReviewed++;
    }
    for (const m of tpcRows) {
      const t = trackOf(m);
      const key = getField(m, "Email", "email").toLowerCase() || `${getField(m, "First name")} ${getField(m, "Last name")}`;
      if (tracks[t]) tracks[t].pc.add(key);
    }
    const pcAll = new Set(tpcRows.filter(inTrack).map(m => getField(m, "Email", "email").toLowerCase() || `${getField(m, "First name")} ${getField(m, "Last name")}`));
    const trackRows = Object.values(tracks).map(t => ({
      ...t, pc: t.pc.size,
      decided: t.accept + t.reject,
      rate: t.accept + t.reject ? (100 * t.accept) / (t.accept + t.reject) : null,
      revPerPaper: t.papers ? t.reviews / t.papers : 0,
      load: t.pc.size ? t.papers / t.pc.size : null,
    }));

    // keywords
    const kw = {};
    for (const p of papers) for (const k of new Set(splitKeywords(getField(p, "Keywords", "keywords")))) kw[k] = (kw[k] || 0) + 1;

    // submissions over time
    const days = {};
    const yr = /^\d{4}$/.test(String(conf.year || "")) ? String(conf.year) : String(new Date().getFullYear());
    for (const p of papers) { const d = parseDay(getField(p, "Time", "time", "Submitted", "submitted", "Date"), yr); if (d) days[d] = (days[d] || 0) + 1; }
    let timeline = [];
    const dk = Object.keys(days).sort();
    if (dk.length) {
      const start = new Date(dk[0]), end = new Date(dk[dk.length - 1]);
      for (let d = new Date(start); d <= end; d.setUTCDate(d.getUTCDate() + 1)) {
        const k = d.toISOString().slice(0, 10);
        const nice = `${MONTHS[+k.slice(5, 7) - 1][0].toUpperCase()}${MONTHS[+k.slice(5, 7) - 1].slice(1)} ${+k.slice(8)}`;
        timeline.push({ label: nice, short: nice, value: days[k] || 0, tip: `${nice}: ${days[k] || 0} submission(s)` });
      }
      if (timeline.length > 90) {
        // long submission window: group by week so no period is dropped
        const weeks = [];
        for (let i = 0; i < timeline.length; i += 7) {
          const chunk = timeline.slice(i, i + 7);
          const v = chunk.reduce((a, c) => a + c.value, 0);
          const lbl = `${chunk[0].label}–${chunk[chunk.length - 1].label}`;
          weeks.push({ label: lbl, short: chunk[0].label, value: v, tip: `Week ${lbl}: ${v} submission(s)` });
        }
        timeline = weeks;
        timeline.byWeek = true;
      }
    }
    const totals = trackRows.reduce((a, t) => ({
      accept: a.accept + t.accept, reject: a.reject + t.reject, tentative: a.tentative + t.tentative, none: a.none + t.none,
      reviews: a.reviews + t.reviews, underReviewed: a.underReviewed + t.underReviewed,
    }), { accept: 0, reject: 0, tentative: 0, none: 0, reviews: 0, underReviewed: 0 });
    const hasDecisions = totals.accept + totals.reject + totals.tentative > 0;

    return { papers, trackRows, uniqAuthors: uniqAuthors.size, countryPapers, countryAuthors, affPapers, intl,
             app, kw, timeline, totals, hasDecisions, pcCount: pcAll.size, hasAuthors: authorRows.length > 0,
             withAuthors: Object.keys(authorsByPaper).length, allTrackOf,
             authorSlots: Object.values(authorsByPaper).reduce((x, l) => x + l.length, 0) };
  }, [metaRows, authorRows, tpcRows, reviewRows, activeTrack, minReviews, conf.year]);

  if (!metaRows.length) return <EmptyState icon="📈" title="No submissions loaded" body="Upload the submissions file (and optionally authors, PC and reviews) in the Data import tab." />;

  const sorted = [...s.trackRows].sort((a, b) =>
    sortKey === "track" ? a.track.localeCompare(b.track, undefined, { numeric: true })
    : (b[sortKey] ?? -1) - (a[sortKey] ?? -1));
  const top = (obj, n) => {
    const e = Object.entries(obj).sort((a, b) => b[1] - a[1]);
    const head = e.slice(0, n).map(([label, value]) => ({ label, value }));
    const rest = e.slice(n).reduce((x, [, v]) => x + v, 0);
    return rest ? [...head, { label: `Other (${e.length - n})`, value: rest }] : head;
  };
  const th = (key, label, align = "right") => (
    <th onClick={() => setSortKey(key)} title="Sort"
      style={{ textAlign: align, padding: "6px 8px", fontSize: 10, fontWeight: 700, textTransform: "uppercase", letterSpacing: "0.05em",
               color: sortKey === key ? C.accentText : C.muted, cursor: "pointer", borderBottom: `1px solid ${C.border}`, whiteSpace: "nowrap" }}>
      {label}{sortKey === key ? " ↓" : ""}
    </th>
  );
  const td = (v, align = "right", extra = {}) => (
    <td style={{ textAlign: align, padding: "6px 8px", fontSize: 12, color: C.text, fontFamily: align === "right" ? C.mono : C.sans, borderBottom: `1px solid ${C.border}`, ...extra }}>{v}</td>
  );
  const maxPapers = Math.max(1, ...s.trackRows.map(t => t.papers));
  const T = s.totals;

  return (
    <div>
      {tooltip}
      {activeTrack !== "All" && (
        <div style={{ fontSize: 12, color: C.muted, marginBottom: 10 }}>Showing track <strong style={{ color: C.text }}>{activeTrack}</strong> — choose “All” in the track selector for the full conference.</div>
      )}

      {/* KPI tiles */}
      <div style={{ display: "flex", gap: 8, flexWrap: "wrap", marginBottom: 14 }}>
        <StatCard label="Submissions" value={s.papers.length} sub={pdfFiles.length ? `${pdfFiles.length} PDFs loaded` : undefined} />
        <StatCard label="Tracks" value={s.trackRows.length} />
        {s.hasAuthors && <StatCard label="Distinct authors" value={s.uniqAuthors} sub={`${(s.authorSlots / Math.max(1, s.withAuthors)).toFixed(1)} authors per paper`} />}
        {s.hasAuthors && <StatCard label="Countries" value={Object.keys(s.countryPapers).length} sub={`${fmtPct(s.intl, s.withAuthors)} multi-country papers`} />}
        {tpcRows.length > 0 && <StatCard label="PC members" value={s.pcCount} sub={s.pcCount ? `${(s.papers.length / s.pcCount).toFixed(1)} papers per member` : undefined} />}
        {reviewRows.length > 0 && <StatCard label="Reviews" value={T.reviews} sub={`${(T.reviews / Math.max(1, s.papers.length)).toFixed(2)} per paper`} />}
        {s.hasDecisions && <StatCard label="Acceptance rate" value={fmtPct(T.accept, T.accept + T.reject)} color={C.green} sub={`${T.accept} accepted · ${T.reject} rejected`} />}
      </div>

      {/* Per-track table */}
      <Panel title="Per track" action={
        <GhostButton small onClick={() => exportCSV(sorted.map(t => ({
          track: t.track, papers: t.papers, share_pct: Math.round((100 * t.papers) / Math.max(1, s.papers.length)),
          accepted: t.accept, rejected: t.reject, tentative: t.tentative, no_decision: t.none,
          acceptance_rate_pct: t.rate == null ? "" : Math.round(t.rate),
          reviews: t.reviews, reviews_per_paper: t.revPerPaper.toFixed(2), [`papers_below_${minReviews}_reviews`]: t.underReviewed,
          pc_members: t.pc, papers_per_pc_member: t.load == null ? "" : t.load.toFixed(2),
        })), "submissions_per_track.csv")}>↓ CSV</GhostButton>}>
        <div style={{ overflowX: "auto" }}>
          <table style={{ width: "100%", borderCollapse: "collapse" }}>
            <thead><tr>
              {th("track", "Track", "left")}
              {th("papers", "Papers")}
              <th style={{ borderBottom: `1px solid ${C.border}`, width: "18%" }} />
              {s.hasDecisions && th("accept", "Acc.")}
              {s.hasDecisions && th("reject", "Rej.")}
              {s.hasDecisions && th("tentative", "Tent.")}
              {s.hasDecisions && th("rate", "Acc. rate")}
              {s.hasDecisions && <th style={{ borderBottom: `1px solid ${C.border}`, width: "14%" }} />}
              {reviewRows.length > 0 && th("revPerPaper", "Rev./paper")}
              {reviewRows.length > 0 && th("underReviewed", `< ${minReviews} rev.`)}
              {tpcRows.length > 0 && th("pc", "PC")}
              {tpcRows.length > 0 && th("load", "Papers/PC")}
            </tr></thead>
            <tbody>
              {sorted.map(t => {
                const tot = t.accept + t.reject + t.tentative + t.none;
                const seg = (n, color) => n > 0 && <div style={{ width: `${(100 * n) / tot}%`, background: color, height: 8 }} />;
                return (
                  <tr key={t.track}>
                    {td(t.track, "left")}
                    {td(t.papers)}
                    <td style={{ padding: "6px 8px", borderBottom: `1px solid ${C.border}` }} {...bind(`${t.track}: ${t.papers} papers (${fmtPct(t.papers, s.papers.length)} of all)`)}>
                      <div style={{ width: `${(100 * t.papers) / maxPapers}%`, minWidth: 3, height: 8, background: C.accent, borderRadius: "0 4px 4px 0" }} />
                    </td>
                    {s.hasDecisions && td(t.accept, "right", { color: C.text })}
                    {s.hasDecisions && td(t.reject)}
                    {s.hasDecisions && td(t.tentative || "")}
                    {s.hasDecisions && td(t.rate == null ? "—" : `${Math.round(t.rate)}%`)}
                    {s.hasDecisions && (
                      <td style={{ padding: "6px 8px", borderBottom: `1px solid ${C.border}` }}
                        {...bind(`${t.track}: ${t.accept} accepted, ${t.reject} rejected, ${t.tentative} tentative, ${t.none} no decision`)}>
                        <div style={{ display: "flex", gap: 2, borderRadius: 4, overflow: "hidden" }}>
                          {seg(t.accept, C.green)}{seg(t.tentative, C.amber)}{seg(t.reject, C.red + "99")}{seg(t.none, C.border)}
                        </div>
                      </td>
                    )}
                    {reviewRows.length > 0 && td(t.revPerPaper.toFixed(1))}
                    {reviewRows.length > 0 && td(t.underReviewed || "", "right", { color: t.underReviewed ? C.amber : C.text })}
                    {tpcRows.length > 0 && td(t.pc || "—")}
                    {tpcRows.length > 0 && td(t.load == null ? "—" : t.load.toFixed(1))}
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
        <div style={{ display: "flex", gap: 14, flexWrap: "wrap", marginTop: 10, fontSize: 11, color: C.muted, alignItems: "center" }}>
          {s.hasDecisions && <>
            {[["Accepted", C.green], ["Tentative (accept?/reject?)", C.amber], ["Rejected", C.red + "99"], ["No decision", C.border]].map(([l, c]) => (
              <span key={l} style={{ display: "inline-flex", gap: 5, alignItems: "center" }}><span style={{ width: 10, height: 10, borderRadius: 2, background: c }} />{l}</span>
            ))}
          </>}
          {reviewRows.length > 0 && (
            <label style={{ marginLeft: "auto" }}>Flag papers with fewer than{" "}
              <input type="number" min={1} max={10} value={minReviews} onChange={e => setMinReviews(Math.max(1, Number(e.target.value) || 1))}
                style={{ width: 40, background: C.bg, color: C.text, border: `1px solid ${C.border}`, borderRadius: 4, padding: "1px 4px" }} /> reviews
            </label>
          )}
        </div>
        <div style={{ fontSize: 10, color: C.muted, marginTop: 6 }}>Acceptance rate = accepted / (accepted + rejected); POSTER, ORAL etc. count as accepted. Click a column header to sort.</div>
      </Panel>

      <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(380px, 1fr))", gap: 14 }}>
        {s.timeline.length > 1 && (
          <Panel title={s.timeline.byWeek ? "Submissions per week" : "Submissions per day"}>
            <Columns items={s.timeline} bind={bind} />
            <div style={{ fontSize: 10, color: C.muted, marginTop: 6 }}>
              {s.timeline.byWeek ? "Busiest week" : "Busiest day"}: {(() => { const b = [...s.timeline].sort((a, b) => b.value - a.value)[0]; return `${b.label} (${b.value})`; })()}
            </div>
          </Panel>
        )}
        {s.hasAuthors && (
          <Panel title="Papers by author country" action={
            <GhostButton small onClick={() => exportCSV(Object.entries(s.countryPapers).sort((a, b) => b[1] - a[1]).map(([country, papers]) => ({ country, papers, authors: s.countryAuthors[country] || 0 })), "countries.csv")}>↓ CSV</GhostButton>}>
            <BarList bind={bind} items={top(s.countryPapers, 12).map(i => ({ ...i, tip: `${i.label}: ${i.value} paper(s)${s.countryAuthors[i.label] ? `, ${s.countryAuthors[i.label]} author(s)` : ""}` }))} />
            <div style={{ fontSize: 10, color: C.muted, marginTop: 6 }}>A paper counts once for each country among its authors.</div>
          </Panel>
        )}
        {s.hasAuthors && (
          <Panel title="Top affiliations (papers)">
            <BarList bind={bind} labelWidth={210} items={top(s.affPapers, 12).filter(i => !i.label.startsWith("Other"))} />
          </Panel>
        )}
        <Panel title="Authors per paper">
          <BarList bind={bind} labelWidth={60}
            items={["1", "2", "3", "4", "5", "6", "7", "8+"].filter(k => s.app[k]).map(k => ({ label: k, value: s.app[k], tip: `${s.app[k]} paper(s) with ${k} author(s)` }))} />
        </Panel>
        {Object.keys(s.kw).length > 0 && (
          <Panel title="Most frequent keywords">
            <BarList bind={bind} labelWidth={210} items={top(s.kw, 15).filter(i => !i.label.startsWith("Other"))} />
          </Panel>
        )}
      </div>
    </div>
  );
}
