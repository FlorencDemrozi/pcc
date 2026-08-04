import { useState } from "react";
import { C, IS, LS } from "../utils/theme.js";
import { SectionTitle, PrimaryButton, GhostButton } from "../components/ui.jsx";
import { callLLM } from "../utils/api.js";
import { safeParseJSON } from "../utils/helpers.js";

const EMAIL_TYPES = [
  { id: "cfp",            label: "Call for Papers",           icon: "📢" },
  { id: "tpc_invite",     label: "TPC Invitation",            icon: "🤝" },
  { id: "review_assign",  label: "Review Assignment",         icon: "📋" },
  { id: "review_remind",  label: "Review Reminder",           icon: "⏰" },
  { id: "review_overdue", label: "Overdue Review",            icon: "🚨" },
  { id: "acceptance",     label: "Acceptance Notification",   icon: "✅" },
  { id: "rejection",      label: "Rejection Notification",    icon: "📄" },
  { id: "camera_ready",   label: "Camera-Ready Instructions", icon: "📸" },
  { id: "program",        label: "Program Announcement",      icon: "📅" },
  { id: "track_chair",    label: "Track Chair Update",        icon: "📊" },
];

const TIMELINE_PHASES = [
  { label: "CFP Launch",                offsetDays: 0,   emails: ["cfp"] },
  { label: "TPC invitations sent",      offsetDays: 7,   emails: ["tpc_invite"] },
  { label: "Paper submission deadline", offsetDays: 60,  emails: [] },
  { label: "Review assignments sent",   offsetDays: 63,  emails: ["review_assign"] },
  { label: "Review reminder",           offsetDays: 75,  emails: ["review_remind"] },
  { label: "Notification to authors",   offsetDays: 90,  emails: ["acceptance", "rejection"] },
  { label: "Camera-ready deadline",     offsetDays: 110, emails: ["camera_ready"] },
  { label: "Early registration",        offsetDays: 115, emails: [] },
  { label: "Program announcement",      offsetDays: 120, emails: ["program"] },
  { label: "Conference",                offsetDays: 150, emails: [] },
];

function buildEmailContext(conf) {
  const chairs = (conf.organizers || [])
    .filter(o => (o.role || "").toLowerCase().includes("chair") || (o.role || "").toLowerCase().includes("pc"))
    .map(o => o.name).filter(Boolean).join(", ");
  const dl = label => (conf.deadlines || []).find(d => (d.label || "").toLowerCase().includes(label))?.date || "TBD";
  return {
    conference:  conf.name    || "[*CONFERENCE*]",
    acronym:     conf.acronym || "[*ACRONYM*]",
    dates:       conf.dates   || "TBD",
    venue:       [conf.venue, conf.city, conf.country].filter(Boolean).join(", ") || "TBD",
    website:     conf.website || "[*CONFERENCE-LINK*]",
    chairs:      chairs       || "[*CHAIRS*]",
    subDeadline: dl("submission"),
    notifDate:   dl("notif"),
    camDeadline: dl("camera"),
    maxPages:    conf.maxPages || "6",
    tracks:      (conf.tracks || []).map(t => t.name).filter(Boolean).join(", ") || "",
    scope:       conf.scope || "",
  };
}

async function generateEmail(typeId, ctx) {
  const prompts = {
    cfp:            `Write a professional Call for Papers email for ${ctx.conference} (${ctx.acronym}). Conference dates: ${ctx.dates}. Venue: ${ctx.venue}. Website: ${ctx.website}. Submission deadline: ${ctx.subDeadline}. Notification: ${ctx.notifDate}. Camera-ready: ${ctx.camDeadline}. Max pages: ${ctx.maxPages}. Tracks: ${ctx.tracks || "see website"}.${ctx.scope ? "\nScope: " + ctx.scope : ""}\nUse [*CONFERENCE*] for conference name, [*ACRONYM*] for acronym, [*CONFERENCE-LINK*] for website, [*CHAIRS*] for chairs, [*TODAY*] for today's date.`,
    tpc_invite:     `Write a professional TPC member invitation email for ${ctx.conference} (${ctx.acronym}). Conference: ${ctx.dates}, ${ctx.venue}. Use [*NAME*] for recipient, [*CONFERENCE*] for conference name, [*ACRONYM*] for acronym, [*CHAIRS-INFO*] for chairs with emails, [*CONFERENCE-LINK*] for website.`,
    review_assign:  `Write a review assignment notification email for ${ctx.conference} (${ctx.acronym}). Use [*NAME*] for reviewer name, [*CONFERENCE*] for conference, [*ASSIGNED-SUBMISSIONS*] for assigned papers list, [*CHAIRS*] for chairs.`,
    review_remind:  `Write a review reminder email for ${ctx.conference} (${ctx.acronym}). The deadline is approaching. Use [*NAME*] for reviewer name, [*CONFERENCE*] for conference, [*SUBMISSIONS-MISSING-REVIEW*] for missing reviews, [*CHAIRS*] for chairs.`,
    review_overdue: `Write an overdue review escalation for ${ctx.conference} (${ctx.acronym}). Tone: firm but professional. Use [*NAME*] for reviewer, [*CONFERENCE*] for conference, [*SUBMISSIONS-MISSING-REVIEW*] for overdue papers, [*CHAIRS-INFO*] for chairs with emails.`,
    acceptance:     `Write an acceptance notification for ${ctx.conference} (${ctx.acronym}). Camera-ready deadline: ${ctx.camDeadline}. Conference: ${ctx.dates}, ${ctx.venue}. Use [*NAME*] for author, [*TITLE*] for paper title, [*PAPER-ID*] for paper ID, [*AUTHORS*] for author list, [*CONFERENCE*] for conference, [*CHAIRS*] for chairs.`,
    rejection:      `Write a constructive rejection notification for ${ctx.conference} (${ctx.acronym}). Acknowledge effort, mention competition, encourage future submission. Use [*NAME*] for author, [*TITLE*] for paper title, [*PAPER-ID*] for paper ID, [*CONFERENCE*] for conference, [*CHAIRS*] for chairs.`,
    camera_ready:   `Write camera-ready submission instructions for ${ctx.conference} (${ctx.acronym}). Camera-ready deadline: ${ctx.camDeadline}. Include: add author info, remove blind anonymisation, add IEEE copyright notice, validate via IEEE PDF eXpress, upload to EasyChair, complete copyright form. Use [*NAME*] for author, [*TITLE*] for title, [*PAPER-ID*] for ID, [*CONFERENCE*] for conference, [*CONFERENCE-LINK*] for website, [*CHAIRS*] for chairs.`,
    program:        `Write a conference program announcement for ${ctx.conference} (${ctx.acronym}). Conference: ${ctx.dates}, ${ctx.venue}. Use [*NAME*] for recipient, [*CONFERENCE*] for conference, [*CONFERENCE-LINK*] for website, [*PROGRAM-LINK*] for program page, [*CHAIRS*] for chairs.`,
    track_chair:    `Write a track chair status update email for ${ctx.conference} (${ctx.acronym}). Update track chairs on review progress. Use [*NAME*] for track chair, [*CONFERENCE*] for conference, [*TRACK*] for track name, [*TRACK-CHAIRS*] for track chairs, [*CHAIRS*] for general chairs.`,
  };

  const system = `You are drafting professional academic conference emails.
Write in formal but approachable English. Keep it concise and actionable.
Use ONLY these EasyChair variable tags — do NOT invent tags:
[*FIRST-NAME*] [*LAST-NAME*] [*NAME*] [*ACRONYM*] [*CONFERENCE*] [*CONFERENCE-LINK*]
[*PROGRAM-LINK*] [*CFP-LINK*] [*CHAIRS*] [*CHAIRS-INFO*] [*TODAY*] [*SENDER-NAME*] [*SENDER-EMAIL*]
[*AUTHORS*] [*TITLE*] [*ABSTRACT*] [*PAPER-ID*] [*SUBMITTER*] [*SUBMITTER-INFO*]
[*ASSIGNED-SUBMISSIONS*] [*SUBMISSIONS-MISSING-REVIEW*]
[*TRACK*] [*TRACK-CHAIRS*] [*TRACK-CHAIRS-INFO*]
[*SESSION*] [*SESSION-DATE*] [*SESSION-TIME*] [*SESSION-CHAIR*] [*SESSION-TALKS*]

Return ONLY valid JSON (no markdown fences):
{"subject":"...","body":"..."}`;

  const prompt = prompts[typeId] || `Write a professional conference email for ${ctx.conference}.`;
  const raw    = await callLLM(system, prompt, 1200, "emails");
  const clean  = raw.replace(/^```[a-z]*\n?/, "").replace(/\n?```$/, "").trim();
  const parsed = safeParseJSON(clean);
  if (parsed && parsed.subject && parsed.body) return parsed;
  return { subject: `[${typeId}] ${ctx.conference}`, body: raw };
}

export function EmailModule({ conf }) {
  const [sel,        setSel]        = useState("cfp");
  const [emails,     setEmails]     = useState({});
  const [generating, setGenerating] = useState(false);
  const [startDate,  setStartDate]  = useState("");
  const [timeline,   setTimeline]   = useState([]);
  const [copied,     setCopied]     = useState(false);

  const ctx  = buildEmailContext(conf);
  const cur  = emails[sel];
  const generatedCount = Object.keys(emails).length;

  const generate = async () => {
    setGenerating(true);
    try {
      const r = await generateEmail(sel, ctx);
      setEmails(p => ({ ...p, [sel]: r }));
    } catch (e) { alert("Error: " + e.message); }
    setGenerating(false);
  };

  const generateAll = async () => {
    setGenerating(true);
    for (const t of EMAIL_TYPES) {
      try {
        const r = await generateEmail(t.id, ctx);
        setEmails(p => ({ ...p, [t.id]: r }));
      } catch {}
    }
    setGenerating(false);
  };

  const genTimeline = () => {
    if (!startDate) return;
    const base   = new Date(startDate);
    const phases = TIMELINE_PHASES.map(p => {
      const confDL = (conf.deadlines || []).find(d => d.label?.toLowerCase().includes(p.label.toLowerCase().split(" ")[0]));
      if (confDL?.date) return { ...p, date: confDL.date };
      const d = new Date(base);
      d.setDate(d.getDate() + p.offsetDays);
      return { ...p, date: d.toISOString().split("T")[0] };
    });
    setTimeline(phases);
  };

  const copy = text => {
    navigator.clipboard?.writeText(text);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  const inputStyle = IS();
  const labelStyle = LS();

  return (
    <div>
      {/* Conference context banner */}
      <div style={{ background: C.panel, border: `1px solid ${C.border}`, borderRadius: 10, padding: "14px 18px", marginBottom: 14 }}>
        <SectionTitle>Conference context (from CFP)</SectionTitle>
        <div style={{ display: "grid", gridTemplateColumns: "repeat(3,1fr)", gap: "6px 16px" }}>
          {[
            ["Conference",  ctx.conference],
            ["Acronym",     ctx.acronym],
            ["Dates",       ctx.dates],
            ["Venue",       ctx.venue],
            ["Website",     ctx.website],
            ["Chairs",      ctx.chairs],
            ["Sub deadline",ctx.subDeadline],
            ["Notification",ctx.notifDate],
            ["Camera-ready",ctx.camDeadline],
          ].map(([label, value]) => (
            <div key={label} style={{ fontSize: 11 }}>
              <span style={{ color: C.muted }}>{label}: </span>
              <span style={{ color: C.text }}>{value || "—"}</span>
            </div>
          ))}
        </div>
        <div style={{ fontSize: 11, color: C.muted, marginTop: 8 }}>
          To update these values, edit the Conference tab and re-extract your CFP.
        </div>
      </div>

      {/* Timeline generator */}
      <div style={{ background: C.panel, border: `1px solid ${C.border}`, borderRadius: 10, padding: "14px 18px", marginBottom: 14 }}>
        <SectionTitle>Conference timeline</SectionTitle>
        <div style={{ display: "flex", gap: 10, alignItems: "flex-end", marginBottom: 12 }}>
          <div style={{ flex: 1 }}>
            <label style={labelStyle}>CFP launch date (used as timeline anchor)</label>
            <input style={inputStyle} type="date" value={startDate} onChange={e => setStartDate(e.target.value)} />
          </div>
          <PrimaryButton onClick={genTimeline} disabled={!startDate}>Generate timeline</PrimaryButton>
        </div>
        {timeline.length > 0 && timeline.sort((a, b) => (a.date || "").localeCompare(b.date || "")).map((p, i) => (
          <div key={i} style={{ display: "flex", gap: 12, alignItems: "center", padding: "6px 0", borderBottom: i < timeline.length - 1 ? `1px solid ${C.border}20` : "none" }}>
            <div style={{ width: 8, height: 8, borderRadius: "50%", background: p.emails.length ? C.accent : C.border, flexShrink: 0 }} />
            <span style={{ fontSize: 12, color: C.text, flex: 1 }}>{p.label}</span>
            <span style={{ fontSize: 11, fontFamily: C.mono, color: C.muted }}>{p.date}</span>
            {p.emails.length > 0 && (
              <div style={{ display: "flex", gap: 3 }}>
                {p.emails.map(e => (
                  <span key={e} style={{ fontSize: 9, padding: "1px 6px", background: C.accent + "30", color: C.accentText, borderRadius: 3 }}>
                    {EMAIL_TYPES.find(t => t.id === e)?.label || e}
                  </span>
                ))}
              </div>
            )}
          </div>
        ))}
      </div>

      {/* Email generator */}
      <div style={{ display: "grid", gridTemplateColumns: "200px 1fr", gap: 16 }}>
        {/* Email type list */}
        <div>
          <SectionTitle>Email type</SectionTitle>
          {EMAIL_TYPES.map(t => (
            <div key={t.id} onClick={() => setSel(t.id)} style={{
              padding: "7px 12px", borderRadius: 6, marginBottom: 3, cursor: "pointer",
              background: sel === t.id ? C.accentDim : "transparent",
              border: `1px solid ${sel === t.id ? C.accent : "transparent"}`,
              fontSize: 12, color: sel === t.id ? C.accentText : C.muted,
              display: "flex", gap: 8, alignItems: "center",
            }}>
              <span>{t.icon}</span>
              <span style={{ flex: 1 }}>{t.label}</span>
              {emails[t.id] && <span style={{ fontSize: 10, color: C.green }}>✓</span>}
            </div>
          ))}
          <div style={{ marginTop: 10 }}>
            <GhostButton onClick={generateAll} small>{generating ? "Generating…" : "Generate all →"}</GhostButton>
            {generatedCount > 0 && <div style={{ fontSize: 10, color: C.green, marginTop: 6 }}>{generatedCount}/{EMAIL_TYPES.length} generated</div>}
          </div>
        </div>

        {/* Email editor */}
        <div>
          <div style={{ display: "flex", gap: 10, marginBottom: 12, alignItems: "center" }}>
            <span style={{ fontSize: 13, fontWeight: 600, color: C.text }}>
              {EMAIL_TYPES.find(t => t.id === sel)?.icon} {EMAIL_TYPES.find(t => t.id === sel)?.label}
            </span>
            <div style={{ flex: 1 }} />
            <PrimaryButton onClick={generate} disabled={generating}>
              {generating ? "Generating…" : cur ? "Regenerate" : "Generate →"}
            </PrimaryButton>
          </div>

          {/* EasyChair tag reference */}
          <details style={{ marginBottom: 12 }}>
            <summary style={{ fontSize: 11, color: C.muted, cursor: "pointer", userSelect: "none" }}>
              📋 EasyChair variable tags reference (click to expand)
            </summary>
            <div style={{ marginTop: 8, background: C.panelAlt, border: `1px solid ${C.border}`, borderRadius: 6, padding: "10px 14px" }}>
              {[
                ["General",    "[*FIRST-NAME*] [*LAST-NAME*] [*NAME*] [*ACRONYM*] [*CONFERENCE*] [*CONFERENCE-LINK*] [*PROGRAM-LINK*] [*CFP-LINK*] [*CHAIRS*] [*CHAIRS-INFO*] [*TODAY*] [*SENDER-NAME*] [*SENDER-EMAIL*]"],
                ["Paper",      "[*AUTHORS*] [*TITLE*] [*ABSTRACT*] [*PAPER-ID*] [*SUBMITTER*] [*SUBMITTER-INFO*]"],
                ["Reviewer",   "[*ASSIGNED-SUBMISSIONS*] [*SUBMISSIONS-MISSING-REVIEW*]"],
                ["Track",      "[*TRACK*] [*TRACK-CHAIRS*] [*TRACK-CHAIRS-INFO*]"],
                ["Session",    "[*SESSION*] [*SESSION-ID*] [*SESSION-DATE*] [*SESSION-TIME*] [*SESSION-CHAIR*] [*SESSION-TALKS*]"],
              ].map(([cat, tags]) => (
                <div key={cat} style={{ marginBottom: 6 }}>
                  <span style={{ fontSize: 10, fontWeight: 700, color: C.muted, textTransform: "uppercase", letterSpacing: "0.06em" }}>{cat}: </span>
                  <span style={{ fontSize: 10, color: C.textSoft, fontFamily: C.mono }}>{tags}</span>
                </div>
              ))}
            </div>
          </details>

          {cur ? (
            <div>
              <div style={{ marginBottom: 10 }}>
                <label style={labelStyle}>Subject</label>
                <input style={inputStyle} value={cur.subject}
                  onChange={e => setEmails(p => ({ ...p, [sel]: { ...p[sel], subject: e.target.value } }))} />
              </div>
              <div style={{ marginBottom: 10 }}>
                <label style={labelStyle}>Body</label>
                <textarea style={{ ...inputStyle, height: 320, resize: "vertical", lineHeight: 1.7, fontSize: 12 }}
                  value={cur.body}
                  onChange={e => setEmails(p => ({ ...p, [sel]: { ...p[sel], body: e.target.value } }))} />
              </div>
              <button onClick={() => copy(`Subject: ${cur.subject}\n\n${cur.body}`)} style={{
                border: `1px solid ${C.border}`, background: copied ? C.greenDim : "transparent",
                borderRadius: 6, padding: "7px 14px", fontSize: 12, cursor: "pointer",
                color: copied ? C.green : C.muted,
              }}>
                {copied ? "✓ Copied to clipboard" : "Copy to clipboard"}
              </button>
            </div>
          ) : (
            <div style={{ height: 260, display: "flex", alignItems: "center", justifyContent: "center", border: `1px dashed ${C.border}`, borderRadius: 8, color: C.muted, fontSize: 12, flexDirection: "column", gap: 8 }}>
              <div style={{ fontSize: 24 }}>{EMAIL_TYPES.find(t => t.id === sel)?.icon}</div>
              <div>Click "Generate" to draft this email with your conference details</div>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
