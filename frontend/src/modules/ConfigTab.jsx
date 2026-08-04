import { useState, useRef } from "react";
import { C, IS, LS } from "../utils/theme.js";
import { SectionTitle, PrimaryButton, InfoBanner } from "../components/ui.jsx";
import { readFileAsBase64 } from "../utils/fileParser.js";
import { extractFromCFP } from "../utils/api.js";

function DayDateInput({ value, onChange }) {
  return (
    <input type="date" value={value || ""} onChange={e => onChange(e.target.value)}
      style={{ ...IS(), flex: 1, maxWidth: 160 }} />
  );
}

function Section({ title, children }) {
  return (
    <div style={{ background: C.panel, border: `1px solid ${C.border}`, borderRadius: 10, padding: "16px 20px", marginBottom: 14 }}>
      <SectionTitle>{title}</SectionTitle>
      {children}
    </div>
  );
}

export function ConfigTab({ conf, setConf }) {
  const [extracting, setExtracting] = useState(false);
  const [extracted, setExtracted]   = useState(false);
  const [cfpName, setCfpName]       = useState("");
  const [nTrack, setNTrack]   = useState({ name: "", description: "" });
  const [nOrg, setNOrg]       = useState({ role: "", name: "", affiliation: "" });
  const [nDL, setNDL]         = useState({ label: "", date: "" });
  const [nKw, setNKw]         = useState("");
  const cfpRef = useRef();

  const inputStyle = IS();
  const labelStyle = LS();

  const u = (k, v) => setConf(p => ({ ...p, [k]: v }));

  const handleCFP = async file => {
    setCfpName(file.name); setExtracting(true); setExtracted(false);
    try {
      const b64  = await readFileAsBase64(file);
      const data = await extractFromCFP(b64, conf.website || "");
      setConf(p => ({
        ...p,
        name:             data.name             || p.name,
        acronym:          data.acronym          || p.acronym          || "",
        edition:          data.edition          || p.edition          || "",
        year:             data.year             || p.year             || "",
        dates:            data.dates            || p.dates            || "",
        venue:            data.venue            || p.venue            || "",
        city:             data.city             || p.city             || "",
        country:          data.country          || p.country          || "",
        website:          data.website          || p.website          || "",
        submissionSystem: data.submissionSystem || p.submissionSystem || "EasyChair",
        scope:            data.scope            || p.scope,
        keywords:         data.keywords?.length ? data.keywords : (p.keywords || []),
        maxPages:         data.maxPages         || p.maxPages,
        template:         data.template         || p.template,
        doubleBlind:      data.doubleBlind !== null && data.doubleBlind !== undefined ? data.doubleBlind : p.doubleBlind,
        deadlines:        data.deadlines?.length ? data.deadlines : (p.deadlines || []),
        conferenceDays:   data.conferenceDays?.length ? data.conferenceDays : (p.conferenceDays || [{ date: "", start: "09:00", end: "18:00" }]),
        tracks:           data.tracks?.length ? data.tracks.filter(t => t.name) : (p.tracks || []),
        organizers:       data.organizers?.length ? data.organizers.filter(o => o.name || o.role) : (p.organizers || []),
        sponsors:         data.sponsors?.length ? data.sponsors : (p.sponsors || []),
        indexing:         data.indexing?.length ? data.indexing : (p.indexing || []),
        notes:            data.notes            || p.notes            || "",
      }));
      setExtracted(true);
    } catch (e) { alert("Extraction error: " + e.message); }
    setExtracting(false);
  };

  const handleURL = async () => {
    if (!conf.website) return;
    setExtracting(true); setExtracted(false);
    try {
      const data = await extractFromCFP(null, conf.website);
      setConf(p => ({
        ...p,
        ...Object.fromEntries(Object.entries(data).filter(([, v]) => v !== null && !(Array.isArray(v) && v.length === 0))),
        conferenceDays: data.conferenceDays?.length ? data.conferenceDays : (p.conferenceDays || [{ date: "", start: "09:00", end: "18:00" }]),
      }));
      setExtracted(true);
    } catch (e) { alert("Error: " + e.message); }
    setExtracting(false);
  };

  return (
    <div>
      {/* CFP import */}
      <Section title="Import from CFP">
        <div style={{ display: "flex", gap: 8, marginBottom: 12 }}>
          <input style={{ ...inputStyle, flex: 1 }} placeholder="https://conf2026.example.org"
            value={conf.website || ""} onChange={e => u("website", e.target.value)} />
          <button onClick={handleURL} disabled={!conf.website || extracting} style={{ padding: "8px 14px", borderRadius: 6, fontSize: 12, fontWeight: 600, border: `1px solid ${C.accent}`, background: C.accent + "20", color: C.accentText, cursor: "pointer", whiteSpace: "nowrap" }}>
            {extracting ? "Extracting…" : "Extract from URL"}
          </button>
        </div>
        <div style={{ border: `2px dashed ${cfpName ? C.green + "60" : C.border}`, borderRadius: 8, padding: "12px 16px", background: cfpName ? C.greenDim : C.panelAlt, display: "flex", alignItems: "center", gap: 12 }}>
          <span style={{ fontSize: 20 }}>📄</span>
          <div>
            <div style={{ fontSize: 12, fontWeight: 600, color: C.text }}>{cfpName || "Upload CFP PDF"}</div>
            <div style={{ fontSize: 11, color: C.muted }}>{cfpName ? "Metadata extracted — review below" : "AI extracts all fields including every deadline date"}</div>
          </div>
          <div style={{ flex: 1 }} />
          <input ref={cfpRef} type="file" accept=".pdf" onChange={e => { if (e.target.files[0]) handleCFP(e.target.files[0]); }} style={{ display: "none" }} />
          <button onClick={() => cfpRef.current?.click()} disabled={extracting} style={{ padding: "7px 14px", borderRadius: 6, fontSize: 12, fontWeight: 600, border: `1px solid ${C.border}`, background: C.panelAlt, color: cfpName ? C.green : C.text, cursor: "pointer" }}>
            {extracting ? "Extracting…" : cfpName ? "✓ Replace" : "Choose PDF"}
          </button>
        </div>
        {extracted && <InfoBanner type="success">Fields auto-filled — deadlines and conference days populated where found. Review and edit below.</InfoBanner>}
      </Section>

      {/* Basic info */}
      <Section title="Basic information">
        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 12 }}>
          {[
            ["Conference name", "name",   "text"],
            ["Acronym",         "acronym","text"],
            ["Edition",         "edition","text"],
            ["Year",            "year",   "text"],
            ["Dates",           "dates",  "text"],
            ["Venue",           "venue",  "text"],
            ["City",            "city",   "text"],
            ["Country",         "country","text"],
            ["Submission system","submissionSystem","text"],
            ["Template",        "template","text"],
            ["Max pages",       "maxPages","number"],
          ].map(([l, k, t]) => (
            <div key={k}>
              <label style={labelStyle}>{l}</label>
              <input style={inputStyle} type={t} value={conf[k] || ""}
                onChange={e => u(k, t === "number" ? Number(e.target.value) : e.target.value)} />
            </div>
          ))}
          <div style={{ display: "flex", alignItems: "center", gap: 10, paddingTop: 20 }}>
            <input type="checkbox" id="blind" checked={!!conf.doubleBlind} onChange={e => u("doubleBlind", e.target.checked)} />
            <label htmlFor="blind" style={{ fontSize: 13, color: C.text, cursor: "pointer" }}>Double-blind review</label>
          </div>
          <div>
            <label style={labelStyle}>Expected column layout</label>
            <select style={{ ...inputStyle, cursor: "pointer" }} value={conf.expectedLayout || "any"} onChange={e => u("expectedLayout", e.target.value)}>
              <option value="any">Any / not checked</option>
              <option value="single">Single column</option>
              <option value="two-column">Two column</option>
            </select>
          </div>
          <div>
            <label style={labelStyle}>Validation stamp string (camera-ready)</label>
            <input style={inputStyle} placeholder="e.g. Certified by Publisher, or leave empty"
              value={conf.validationStamp || ""} onChange={e => u("validationStamp", e.target.value)} />
          </div>
        </div>
        <div style={{ marginTop: 12 }}>
          <label style={labelStyle}>Scope</label>
          <textarea style={{ ...inputStyle, height: 72, resize: "vertical" }} value={conf.scope || ""} onChange={e => u("scope", e.target.value)} />
        </div>
        <div style={{ marginTop: 10 }}>
          <label style={labelStyle}>Notes</label>
          <textarea style={{ ...inputStyle, height: 48, resize: "vertical" }} value={conf.notes || ""} onChange={e => u("notes", e.target.value)} />
        </div>
      </Section>

      {/* Keywords */}
      <Section title="Keywords">
        <div style={{ display: "flex", flexWrap: "wrap", gap: 6, marginBottom: 10 }}>
          {(conf.keywords || []).map((kw, i) => (
            <span key={i} style={{ padding: "3px 10px", borderRadius: 20, fontSize: 12, background: C.accent + "20", color: C.accentText, border: `1px solid ${C.accent}40`, display: "flex", alignItems: "center", gap: 6 }}>
              {kw}
              <span onClick={() => u("keywords", conf.keywords.filter((_, j) => j !== i))} style={{ cursor: "pointer", color: C.muted, fontWeight: 700, fontSize: 14 }}>×</span>
            </span>
          ))}
        </div>
        <div style={{ display: "flex", gap: 8 }}>
          <input style={{ ...inputStyle, flex: 1 }} placeholder="Add keyword…" value={nKw} onChange={e => setNKw(e.target.value)}
            onKeyDown={e => { if (e.key === "Enter" && nKw.trim()) { u("keywords", [...(conf.keywords || []), nKw.trim()]); setNKw(""); } }} />
          <button onClick={() => { if (nKw.trim()) { u("keywords", [...(conf.keywords || []), nKw.trim()]); setNKw(""); } }}
            style={{ padding: "8px 14px", borderRadius: 6, fontSize: 12, border: `1px solid ${C.border}`, background: C.panelAlt, color: C.text, cursor: "pointer" }}>Add</button>
        </div>
      </Section>

      {/* Deadlines */}
      <Section title="Deadlines">
        <div style={{ fontSize: 11, color: C.muted, marginBottom: 10 }}>Dates must be in YYYY-MM-DD format. After CFP extraction, verify each deadline label and date.</div>
        {(conf.deadlines || []).map((d, i) => (
          <div key={i} style={{ display: "flex", gap: 8, marginBottom: 8, alignItems: "center" }}>
            <input style={{ ...inputStyle, flex: 2 }} placeholder="Label (e.g. Paper submission)" value={d.label}
              onChange={e => { const dl = [...conf.deadlines]; dl[i] = { ...dl[i], label: e.target.value }; u("deadlines", dl); }} />
            <input style={{ ...inputStyle, flex: 1 }} type="date" value={d.date || ""}
              onChange={e => { const dl = [...conf.deadlines]; dl[i] = { ...dl[i], date: e.target.value }; u("deadlines", dl); }} />
            <span style={{ fontSize: 11, color: C.muted, flexShrink: 0 }}>{d.date || ""}</span>
            <span onClick={() => u("deadlines", conf.deadlines.filter((_, j) => j !== i))}
              style={{ cursor: "pointer", color: C.muted, fontSize: 18, padding: "0 4px" }}>×</span>
          </div>
        ))}
        <div style={{ display: "flex", gap: 8 }}>
          <input style={{ ...inputStyle, flex: 2 }} placeholder="Label" value={nDL.label} onChange={e => setNDL(p => ({ ...p, label: e.target.value }))} />
          <input style={{ ...inputStyle, flex: 1 }} type="date" value={nDL.date} onChange={e => setNDL(p => ({ ...p, date: e.target.value }))} />
          <button onClick={() => { if (nDL.label) { u("deadlines", [...(conf.deadlines || []), nDL]); setNDL({ label: "", date: "" }); } }}
            style={{ padding: "8px 14px", borderRadius: 6, fontSize: 12, border: `1px solid ${C.border}`, background: C.panelAlt, color: C.text, cursor: "pointer", whiteSpace: "nowrap" }}>+ Add</button>
        </div>
      </Section>

      {/* Tracks */}
      <Section title="Tracks">
        {(conf.tracks || []).map((t, i) => (
          <div key={i} style={{ display: "flex", gap: 8, marginBottom: 8, alignItems: "flex-start" }}>
            <div style={{ display: "flex", flexDirection: "column", gap: 6, flex: 1 }}>
              <input style={inputStyle} placeholder="Track name" value={t.name}
                onChange={e => { const tr = [...conf.tracks]; tr[i] = { ...tr[i], name: e.target.value }; u("tracks", tr); }} />
              <input style={inputStyle} placeholder="Description" value={t.description || ""}
                onChange={e => { const tr = [...conf.tracks]; tr[i] = { ...tr[i], description: e.target.value }; u("tracks", tr); }} />
            </div>
            <span onClick={() => u("tracks", conf.tracks.filter((_, j) => j !== i))} style={{ cursor: "pointer", color: C.muted, fontSize: 18, paddingTop: 8 }}>×</span>
          </div>
        ))}
        <div style={{ display: "flex", gap: 8 }}>
          <input style={{ ...inputStyle, flex: 1 }} placeholder="Track name" value={nTrack.name} onChange={e => setNTrack(p => ({ ...p, name: e.target.value }))} />
          <input style={{ ...inputStyle, flex: 2 }} placeholder="Description" value={nTrack.description} onChange={e => setNTrack(p => ({ ...p, description: e.target.value }))} />
          <button onClick={() => { if (nTrack.name) { u("tracks", [...(conf.tracks || []), nTrack]); setNTrack({ name: "", description: "" }); } }}
            style={{ padding: "8px 14px", borderRadius: 6, fontSize: 12, border: `1px solid ${C.border}`, background: C.panelAlt, color: C.text, cursor: "pointer", whiteSpace: "nowrap" }}>+ Add</button>
        </div>
      </Section>

      {/* Organizers */}
      <Section title="Organizers">
        {(conf.organizers || []).map((o, i) => (
          <div key={i} style={{ display: "flex", gap: 8, marginBottom: 8, alignItems: "center" }}>
            <input style={{ ...inputStyle, flex: 1 }} placeholder="Role" value={o.role} onChange={e => { const or = [...conf.organizers]; or[i] = { ...or[i], role: e.target.value }; u("organizers", or); }} />
            <input style={{ ...inputStyle, flex: 1 }} placeholder="Name" value={o.name} onChange={e => { const or = [...conf.organizers]; or[i] = { ...or[i], name: e.target.value }; u("organizers", or); }} />
            <input style={{ ...inputStyle, flex: 2 }} placeholder="Affiliation" value={o.affiliation || ""} onChange={e => { const or = [...conf.organizers]; or[i] = { ...or[i], affiliation: e.target.value }; u("organizers", or); }} />
            <span onClick={() => u("organizers", conf.organizers.filter((_, j) => j !== i))} style={{ cursor: "pointer", color: C.muted, fontSize: 18 }}>×</span>
          </div>
        ))}
        <div style={{ display: "flex", gap: 8 }}>
          <input style={{ ...inputStyle, flex: 1 }} placeholder="Role" value={nOrg.role} onChange={e => setNOrg(p => ({ ...p, role: e.target.value }))} />
          <input style={{ ...inputStyle, flex: 1 }} placeholder="Name" value={nOrg.name} onChange={e => setNOrg(p => ({ ...p, name: e.target.value }))} />
          <input style={{ ...inputStyle, flex: 2 }} placeholder="Affiliation" value={nOrg.affiliation} onChange={e => setNOrg(p => ({ ...p, affiliation: e.target.value }))} />
          <button onClick={() => { if (nOrg.role || nOrg.name) { u("organizers", [...(conf.organizers || []), nOrg]); setNOrg({ role: "", name: "", affiliation: "" }); } }}
            style={{ padding: "8px 14px", borderRadius: 6, fontSize: 12, border: `1px solid ${C.border}`, background: C.panelAlt, color: C.text, cursor: "pointer", whiteSpace: "nowrap" }}>+ Add</button>
        </div>
      </Section>

      {/* Conference days */}
      <Section title="Conference days & schedule">
        <div style={{ fontSize: 11, color: C.muted, marginBottom: 10 }}>
          Define one row per conference day. Start/end times are used by the Program Builder.
        </div>
        {(conf.conferenceDays || []).map((d, i) => (
          <div key={i} style={{ display: "flex", gap: 8, marginBottom: 8, alignItems: "center" }}>
            <span style={{ fontSize: 11, color: C.muted, minWidth: 48 }}>Day {i + 1}</span>
            <DayDateInput value={d.date || ""} onChange={v => { const days = [...(conf.conferenceDays || [])]; days[i] = { ...days[i], date: v }; u("conferenceDays", days); }} />
            <input style={{ ...inputStyle, flex: 1, maxWidth: 90 }} type="time" value={d.start || "09:00"}
              onChange={e => { const days = [...(conf.conferenceDays || [])]; days[i] = { ...days[i], start: e.target.value }; u("conferenceDays", days); }} />
            <span style={{ fontSize: 11, color: C.muted }}>→</span>
            <input style={{ ...inputStyle, flex: 1, maxWidth: 90 }} type="time" value={d.end || "18:00"}
              onChange={e => { const days = [...(conf.conferenceDays || [])]; days[i] = { ...days[i], end: e.target.value }; u("conferenceDays", days); }} />
            <span onClick={() => u("conferenceDays", (conf.conferenceDays || []).filter((_, j) => j !== i))}
              style={{ cursor: "pointer", color: C.muted, fontSize: 18, padding: "0 4px" }}>×</span>
          </div>
        ))}
        <button onClick={() => u("conferenceDays", [...(conf.conferenceDays || []), { date: "", start: "09:00", end: "18:00" }])}
          style={{ padding: "7px 14px", borderRadius: 6, fontSize: 12, border: `1px solid ${C.border}`, background: C.panelAlt, color: C.text, cursor: "pointer" }}>
          + Add day
        </button>
      </Section>
    </div>
  );
}
