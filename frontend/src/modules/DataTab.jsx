import { useRef, useState } from "react";
import { C } from "../utils/theme.js";
import { FileUploadBox, InfoBanner, SectionTitle } from "../components/ui.jsx";
import { extractZipPDFs, parseCSV, parseXLSX, sanitiseRows, readFileAsText, parseReviewFile } from "../utils/fileParser.js";

export function DataTab({
  pdfFiles, setPdfFiles,
  metaRows,  setMetaRows,
  reviewRows, setReviewRows,
  tpcRows,   setTpcRows,
  authorRows, setAuthorRows,
  ssRows,    setSsRows,
}) {
  const zipRef  = useRef();
  const subRef  = useRef();
  const authRef = useRef();
  const tpcRef  = useRef();
  const rvRef   = useRef();
  const ssRef   = useRef();
  const [pdfLimit, setPdfLimit] = useState(0);

  const handleZip = async f => {
    try {
      const all     = await extractZipPDFs(f);
      const limited = pdfLimit > 0 ? all.slice(0, pdfLimit) : all;
      setPdfFiles(limited);
    } catch (e) { alert("ZIP error: " + e.message); }
  };

  const handleFile = async (f, setter) => {
    try {
      const rows = f.name.toLowerCase().endsWith(".csv")
        ? parseCSV(await readFileAsText(f))
        : await parseXLSX(f);
      setter(sanitiseRows(rows));
    } catch (e) { alert("File error: " + e.message); }
  };

  const handleReviews = async f => {
    try {
      setReviewRows(await parseReviewFile(f));
    } catch (e) { alert("Reviews file error: " + e.message); }
  };

  const FILE_GROUPS = [
    {
      title: "Submission data",
      items: [
        { label: "Submissions XLSX/CSV",     hint: "Paper ID, title, authors, track, decision — from EasyChair", accept: ".xlsx,.csv", ref: subRef,  loaded: metaRows.length > 0,   loadedLabel: `${metaRows.length} submissions`,   onFile: f => handleFile(f, setMetaRows) },
        { label: "Author list XLSX/CSV",     hint: "One row per author: paper ID, name, email, affiliation, country", accept: ".xlsx,.csv", ref: authRef, loaded: authorRows.length > 0, loadedLabel: `${authorRows.length} authors`,     onFile: f => handleFile(f, setAuthorRows) },
        { label: "TPC / PC members XLSX/CSV", hint: "Name, surname, email, affiliation, role, track", accept: ".xlsx,.csv", ref: tpcRef,  loaded: tpcRows.length > 0,    loadedLabel: `${tpcRows.length} members`,      onFile: f => handleFile(f, setTpcRows) },
      ],
    },
    {
      title: "Review data",
      items: [
        { label: "Reviews TXT or XLSX/CSV",          hint: "EasyChair review export (.txt) or review summary (.xlsx)", accept: ".xlsx,.csv,.txt", ref: rvRef, loaded: reviewRows.length > 0, loadedLabel: `${reviewRows.length} reviews`, onFile: handleReviews },
        { label: "Special session papers XLSX/CSV", hint: "Papers from special sessions (optional)", accept: ".xlsx,.csv", ref: ssRef, loaded: ssRows.length > 0, loadedLabel: `${ssRows.length} papers`, onFile: f => handleFile(f, setSsRows) },
      ],
    },
  ];

  const loadedCount = [pdfFiles.length, metaRows.length, authorRows.length, tpcRows.length, reviewRows.length, ssRows.length].filter(Boolean).length;

  return (
    <div>
      <InfoBanner type="info">
        Upload your files here once. Every module reads from this data — you will not be asked to upload files again.
        {loadedCount > 0 && ` Currently ${loadedCount}/6 file slots loaded.`}
      </InfoBanner>

      {/* Paper PDFs */}
      <div style={{ marginBottom: 20 }}>
        <div style={{ fontSize: 10, fontWeight: 700, color: C.muted, textTransform: "uppercase", letterSpacing: "0.1em", marginBottom: 10, fontFamily: C.sans }}>Paper PDFs</div>
        <FileUploadBox
          label="Papers ZIP" hint="EasyChair → Submissions → Download all PDFs as ZIP"
          accept=".zip" refObj={zipRef} loaded={pdfFiles.length > 0}
          loadedLabel={`${pdfFiles.length} PDFs`} onFile={handleZip} />
        <div style={{ display: "flex", gap: 12, alignItems: "center", marginTop: 6, padding: "8px 12px", background: C.panelAlt, border: `1px solid ${C.border}`, borderRadius: 6 }}>
          <span style={{ fontSize: 12, color: C.muted, fontFamily: C.sans }}>Load limit (for testing):</span>
          <div style={{ display: "flex", gap: 6, alignItems: "center" }}>
            {[0, 5, 10, 20, 50].map(n => (
              <button key={n} onClick={() => setPdfLimit(n)} style={{
                padding: "3px 10px", borderRadius: 4, fontSize: 11, fontWeight: 600, cursor: "pointer",
                border: `1px solid ${pdfLimit === n ? C.accent : C.border}`,
                background: pdfLimit === n ? C.accentDim : "transparent",
                color: pdfLimit === n ? C.accentText : C.muted, fontFamily: C.sans,
              }}>{n === 0 ? "All" : n}</button>
            ))}
          </div>
          <span style={{ fontSize: 11, color: C.muted, fontFamily: C.sans }}>
            {pdfLimit === 0 ? "All PDFs will be loaded" : `Only the first ${pdfLimit} PDFs — re-upload ZIP to apply`}
          </span>
        </div>
      </div>

      {/* Other file groups */}
      {FILE_GROUPS.map(group => (
        <div key={group.title} style={{ marginBottom: 20 }}>
          <div style={{ fontSize: 10, fontWeight: 700, color: C.muted, textTransform: "uppercase", letterSpacing: "0.1em", marginBottom: 10, fontFamily: C.sans }}>{group.title}</div>
          {group.items.map(item => (
            <FileUploadBox key={item.label} label={item.label} hint={item.hint} accept={item.accept}
              onFile={item.onFile} refObj={item.ref} loaded={item.loaded} loadedLabel={item.loadedLabel} />
          ))}
        </div>
      ))}

      {metaRows.length > 0 && (
        <div style={{ marginTop: 8, background: C.panel, border: `1px solid ${C.border}`, borderRadius: 8, padding: 14 }}>
          <SectionTitle>Detected columns in submissions file</SectionTitle>
          <div style={{ fontSize: 11, color: C.muted, fontFamily: C.mono, lineHeight: 1.8 }}>
            {Object.keys(metaRows[0]).join("  ·  ")}
          </div>
        </div>
      )}
    </div>
  );
}
