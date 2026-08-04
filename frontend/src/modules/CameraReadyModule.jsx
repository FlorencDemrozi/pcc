import { useState } from "react";
import { C, IS, LS } from "../utils/theme.js";
import { Badge, StatCard, SectionTitle, ProgressBar, PrimaryButton, GhostButton, EmptyState } from "../components/ui.jsx";
import { backendPost } from "../utils/api.js";
import { exportCSV } from "../utils/helpers.js";

export function CameraReadyModule({ conf, pdfFiles, authorRows }) {
  const [results,   setResults]   = useState([]);
  const [running,   setRunning]   = useState(false);
  const [prog,      setProg]      = useState({ done: 0, total: 0, cur: "" });
  const [expanded,  setExpanded]  = useState(null);
  const [overrides, setOverrides] = useState({});
  const [notices,   setNotices]   = useState((conf.copyrightNotices || []).join("\n"));

  const effectivePassed = item =>
    overrides[item.id] ? overrides[item.id] === "Pass" : item.passed === item.total;

  const run = async (force = false) => {
    if (!pdfFiles.length) return;
    if (results.length > 0 && !force) return;
    const noticeList = notices.split("\n").map(s => s.trim()).filter(Boolean);
    setRunning(true); setResults([]);
    const all = [];
    setProg({ done: 0, total: pdfFiles.length, cur: "" });
    for (let i = 0; i < pdfFiles.length; i++) {
      const f = pdfFiles[i];
      setProg({ done: i, total: pdfFiles.length, cur: f.name });
      try {
        const fd = new FormData();
        fd.append("file",             f, f.name);
        fd.append("max_pages",         String(conf.maxPages || 6));
        fd.append("double_blind",      "false");
        fd.append("copyright_notices", JSON.stringify(noticeList));
        fd.append("camera_ready",      "true");
        fd.append("expected_layout",   conf.expectedLayout || "any");
        fd.append("validation_stamp",  conf.validationStamp || "");
        fd.append("use_llm_blind",     "false");
        if (authorRows && authorRows.length > 0)
          fd.append("author_list_json", JSON.stringify(authorRows));
        const result = await backendPost("/api/check/pdf", fd);
        const checks = [
          result.page_count?.passed,
          result.author_info_present?.passed,
          result.copyright_notice?.passed,
          result.pdf_express?.passed,
          result.font_embedding?.passed,
        ];
        const passed = checks.filter(Boolean).length;
        all.push({ id: i + 1, filename: f.name, result, passed, total: checks.length });
      } catch (e) {
        all.push({ id: i + 1, filename: f.name, result: null, error: e.message, passed: 0, total: 5 });
      }
      setResults([...all]);
    }
    setRunning(false);
  };

  const fullPass = results.filter(r => effectivePassed(r)).length;

  const CheckRow = ({ label, check }) => {
    if (!check) return null;
    return (
      <div style={{ display: "flex", gap: 8, alignItems: "flex-start", marginBottom: 6 }}>
        <span style={{ width: 160, fontSize: 11, color: C.muted, flexShrink: 0 }}>{label}</span>
        <Badge label={check.passed ? "Pass" : "Fail"} />
        {check.value && <span style={{ fontSize: 11, color: C.muted }}>{check.value}</span>}
        {(check.issues || []).map((iss, idx) => (
          <span key={idx} style={{ fontSize: 11, color: C.red }}>{iss}</span>
        ))}
      </div>
    );
  };

  if (!pdfFiles.length) return (
    <EmptyState icon="📸" title="No PDFs loaded" body="Upload the camera-ready PDFs ZIP in the Data import tab." />
  );

  const inputStyle = IS();
  const labelStyle = LS();

  return (
    <div>
      {/* Copyright notice configuration */}
      <div style={{ background: C.panel, border: `1px solid ${C.border}`, borderRadius: 10, padding: "16px 20px", marginBottom: 14 }}>
        <SectionTitle>Copyright notices</SectionTitle>
        <div style={{ fontSize: 11, color: C.muted, marginBottom: 8, lineHeight: 1.6 }}>
          Enter one copyright notice per line. The checker looks for each in the <strong style={{ color: C.text }}>bottom-left footer of page 1</strong>.
        </div>
        <textarea style={{ ...inputStyle, height: 96, resize: "vertical", fontFamily: C.mono, fontSize: 12 }}
          placeholder={"© 2026 IEEE\n979-8-XXXX-XXXX-X/26/$31.00 ©2026 IEEE"}
          value={notices} onChange={e => setNotices(e.target.value)} />
        {authorRows && authorRows.length > 0
          ? <div style={{ fontSize: 11, color: C.green, marginTop: 8 }}>✓ Author list loaded ({authorRows.length} authors) — will cross-check names against each paper</div>
          : <div style={{ fontSize: 11, color: C.amber, marginTop: 8 }}>⚠ No author list loaded — author name check uses generic detection. Load in Data Import for precise checking.</div>
        }
      </div>

      {/* Run / progress */}
      {!running && results.length === 0 && (
        <div style={{ marginBottom: 16 }}>
          <div style={{ fontSize: 13, color: C.muted, marginBottom: 10 }}>
            {pdfFiles.length} PDFs ready · Checks: page count · author names · copyright notice · PDF eXpress stamp · font embedding
          </div>
          <PrimaryButton onClick={() => run(true)}>Run camera-ready checks →</PrimaryButton>
        </div>
      )}
      {running && <ProgressBar done={prog.done} total={prog.total} label={prog.cur} />}

      {/* Results */}
      {results.length > 0 && (
        <>
          <div style={{ display: "flex", gap: 10, marginBottom: 14, flexWrap: "wrap" }}>
            <StatCard label="Total"      value={results.length}               color={C.text} />
            <StatCard label="Ready"      value={fullPass}                     color={C.green} />
            <StatCard label="Issues"     value={results.length - fullPass}    color={C.red} />
            <StatCard label="Overridden" value={Object.keys(overrides).length} color={C.amber} />
          </div>
          <div style={{ display: "flex", gap: 8, marginBottom: 14, alignItems: "center" }}>
            <div style={{ flex: 1 }} />
            <GhostButton small onClick={() => run(true)}>Re-run</GhostButton>
            <GhostButton onClick={() => exportCSV(results.map(r => ({
              filename:    r.filename,
              verdict:     overrides[r.id] || (effectivePassed(r) ? "Ready" : "Issues"),
              overridden:  overrides[r.id] ? "Yes" : "No",
              pages:       r.result?.page_count?.value || "",
              authors:     r.result?.author_info_present?.value || "",
              copyright:   r.result?.copyright_notice?.value || "",
              pdf_express: r.result?.pdf_express?.value || "",
              fonts:       r.result?.font_embedding?.passed ? "Pass" : "Fail",
              issues:      r.error || (r.result ? [r.result.author_info_present, r.result.copyright_notice, r.result.pdf_express, r.result.font_embedding].flatMap(c => c?.issues || []).join("; ") : ""),
            })), "camera_ready.csv")}>↓ Export CSV</GhostButton>
          </div>

          {results.map((item, i) => {
            const r         = item.result;
            const isExp     = expanded === i;
            const ok        = effectivePassed(item);
            const isOverride = !!overrides[item.id];
            return (
              <div key={item.id} style={{ border: `1px solid ${ok ? C.border : C.red + "60"}`, borderRadius: 10, marginBottom: 8, overflow: "hidden" }}>
                <div onClick={() => setExpanded(isExp ? null : i)} style={{ padding: "11px 16px", cursor: "pointer", display: "flex", gap: 12, alignItems: "center", background: isExp ? C.panelAlt : C.panel }}>
                  <span style={{ fontSize: 10, color: C.muted, fontFamily: C.mono, minWidth: 24 }}>#{item.id}</span>
                  <span style={{ flex: 1, fontSize: 12, color: C.text, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{item.filename}</span>
                  {r && <span style={{ fontSize: 11, color: C.muted, fontFamily: C.mono }}>{r.raw_pages}p</span>}
                  {r && !ok && (() => {
                    const firstFail = [r.author_info_present, r.copyright_notice, r.pdf_express, r.font_embedding].find(c => c && !c.passed);
                    const msg = firstFail?.issues?.[0] || firstFail?.value || "";
                    return msg ? <span style={{ fontSize: 10, color: C.red, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap", maxWidth: 200 }}>{msg}</span> : null;
                  })()}
                  <span style={{ fontSize: 11, fontWeight: 600, color: isOverride ? C.amber : ok ? C.green : C.red, flexShrink: 0 }}>
                    {isOverride ? `${overrides[item.id]}*` : ok ? "✓ Ready" : `${item.total - item.passed} issue(s)`}
                  </span>
                  <div style={{ display: "flex", gap: 2, flexShrink: 0 }} onClick={e => e.stopPropagation()}>
                    <button onClick={() => setOverrides(p => ({ ...p, [item.id]: "Pass" }))} title="Mark as Ready"
                      style={{ border: `1px solid ${overrides[item.id] === "Pass" ? C.green : C.border}`, background: overrides[item.id] === "Pass" ? C.greenDim : "transparent", borderRadius: 3, width: 20, height: 20, fontSize: 11, cursor: "pointer", padding: 0 }}>👍</button>
                    <button onClick={() => setOverrides(p => ({ ...p, [item.id]: "Fail" }))} title="Mark as Issues"
                      style={{ border: `1px solid ${overrides[item.id] === "Fail" ? C.red : C.border}`, background: overrides[item.id] === "Fail" ? C.redDim : "transparent", borderRadius: 3, width: 20, height: 20, fontSize: 11, cursor: "pointer", padding: 0 }}>👎</button>
                    {overrides[item.id] && (
                      <button onClick={() => setOverrides(p => { const n = { ...p }; delete n[item.id]; return n; })}
                        style={{ border: `1px solid ${C.border}`, background: "transparent", borderRadius: 3, width: 16, height: 20, fontSize: 9, cursor: "pointer", padding: 0, color: C.muted }}>✕</button>
                    )}
                  </div>
                  <span style={{ color: C.muted, fontSize: 12, flexShrink: 0 }}>{isExp ? "▲" : "▼"}</span>
                </div>
                {isExp && r && (
                  <div style={{ padding: "12px 16px 14px", borderTop: `1px solid ${C.border}`, background: C.bg }}>
                    <CheckRow label="Page count"        check={r.page_count} />
                    <CheckRow label="Author names"      check={r.author_info_present} />
                    <CheckRow label="Copyright notice"  check={r.copyright_notice} />
                    <CheckRow label="PDF eXpress stamp" check={r.pdf_express} />
                    <CheckRow label="Font embedding"    check={r.font_embedding} />
                    <CheckRow label="Column layout"     check={r.column_layout} />
                    <CheckRow label="References"        check={r.references} />
                    {isOverride && (
                      <div style={{ marginTop: 8, padding: "5px 8px", borderRadius: 4, background: C.amberDim, border: `1px solid ${C.amber}40`, fontSize: 10, color: C.amber }}>
                        ⚠ Override: marked as <strong>{overrides[item.id]}</strong>
                      </div>
                    )}
                  </div>
                )}
                {isExp && !r && (
                  <div style={{ padding: "8px 16px", borderTop: `1px solid ${C.border}`, fontSize: 11, color: C.red }}>Error: {item.error}</div>
                )}
              </div>
            );
          })}
        </>
      )}
    </div>
  );
}
