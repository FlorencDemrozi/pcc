import { useState } from "react";
import { C } from "../utils/theme.js";
import { SectionTitle, InfoBanner } from "../components/ui.jsx";

const LICENSE_TEXT = `Program Chair Copilot
Copyright (c) 2026 Prof. Florenc Demrozi (florenc1991@gmail.com)
All rights reserved.

NON-COMMERCIAL USE LICENSE

1. GRANT OF LICENSE
   Subject to the terms below, the author grants you a worldwide, royalty-free,
   non-exclusive, non-transferable license to use, copy, and run this software
   solely for non-commercial purposes, including academic research, personal
   use, and the organisation of non-profit scientific conferences.

2. NON-COMMERCIAL USE DEFINED
   "Non-commercial use" means use that is not primarily intended for, or
   directed towards, commercial advantage or monetary compensation. Academic
   conferences, university research groups, and individual researchers are
   considered non-commercial users. Commercial entities (companies, for-profit
   organisations, consulting firms) are NOT permitted to use this software
   under this license without a separate commercial license.

3. RESTRICTIONS — YOU MAY NOT:
   a) Use the software for commercial purposes.
   b) Redistribute, sublicense, sell, rent, lease, or transfer the software or
      any modified version as part of a paid product or service, or for
      commercial gain. Sharing the original, unmodified repository link is
      permitted.
   c) Remove, alter, or obscure any copyright notice or author attribution.
   d) Claim ownership of the software or misrepresent its origin.

4. COMMERCIAL LICENSING
   Commercial use requires a separate written license agreement with the author.
   Contact: florenc1991@gmail.com

5. RESERVATION OF RIGHTS
   The author reserves the right to release future versions under different
   license terms, including commercial-only terms, at any time without notice.

6. NO WARRANTY
   This software is provided "as is", without warranty of any kind.

7. GOVERNING LAW
   Governed by the laws of the European Union.`;

export function AboutModule({ trialStatus }) {
  const [licenseOpen, setLicenseOpen] = useState(false);

  return (
    <div style={{ maxWidth: 720 }}>
      {/* Hero */}
      <div style={{ background: `linear-gradient(135deg, ${C.panelAlt} 0%, ${C.panel} 100%)`, border: `1px solid ${C.border}`, borderRadius: 12, padding: "32px 36px", marginBottom: 16, display: "flex", gap: 24, alignItems: "flex-start" }}>
        <div style={{ width: 64, height: 64, borderRadius: 14, flexShrink: 0, background: C.accentDim, border: `1px solid ${C.accent}40`, display: "flex", alignItems: "center", justifyContent: "center", fontSize: 28 }}>🏛</div>
        <div style={{ flex: 1 }}>
          <div style={{ fontSize: 22, fontWeight: 700, color: C.text, marginBottom: 4 }}>Program Chair Copilot</div>
          <div style={{ fontSize: 13, color: C.muted, lineHeight: 1.6, marginBottom: 12 }}>
            An AI-powered desktop assistant for conference program chairs. Automates compliance checking, review statistics, conflict-of-interest detection, decision support, and program building — so you can focus on the science.
          </div>
          <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
            {[["12 modules", C.accent], ["Local processing", C.green], ["Multiple LLM providers", C.teal], ["No data sent to servers", C.green]].map(([label, color]) => (
              <span key={label} style={{ fontSize: 11, fontWeight: 600, padding: "2px 10px", borderRadius: 12, background: color + "15", color, border: `1px solid ${color}30` }}>{label}</span>
            ))}
          </div>
        </div>
      </div>

      {/* Trial status */}
      {trialStatus && (
        <div style={{ background: C.panel, border: `1px solid ${C.border}`, borderRadius: 10, padding: "20px 24px", marginBottom: 14 }}>
          <SectionTitle>License status</SectionTitle>
          {trialStatus.mode === "development" && <InfoBanner type="info">Development mode — trial not active.</InfoBanner>}
          {trialStatus.mode === "trial" && (
            <div>
              <InfoBanner type={trialStatus.days_remaining <= 7 ? "warning" : "success"}>
                <strong>Trial active</strong> — {trialStatus.days_remaining} of {trialStatus.trial_days} days remaining.
                {trialStatus.days_remaining <= 7 && " Re-download soon to continue with full access."}
              </InfoBanner>
              <div style={{ height: 6, borderRadius: 3, overflow: "hidden", background: C.border, marginBottom: 12 }}>
                <div style={{ width: `${Math.round((1 - trialStatus.days_remaining / trialStatus.trial_days) * 100)}%`, height: "100%", background: trialStatus.days_remaining <= 7 ? C.amber : C.green }} />
              </div>
              <div style={{ fontSize: 11, color: C.muted }}>Build date: <span style={{ fontFamily: C.mono, color: C.textSoft }}>{trialStatus.build_date}</span></div>
            </div>
          )}
          {trialStatus.mode === "freemium" && (
            <div>
              <InfoBanner type="error"><strong>Trial expired.</strong> AI features are disabled. Re-download for a new trial, or contact the author for a full license.</InfoBanner>
              <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 8, marginTop: 8 }}>
                <div style={{ background: C.greenDim, border: `1px solid ${C.green}30`, borderRadius: 7, padding: "10px 14px" }}>
                  <div style={{ fontSize: 11, fontWeight: 700, color: C.greenText, marginBottom: 6 }}>✓ Always free</div>
                  {["Compliance check", "Review statistics", "COI detection", "Conference config", "Data import"].map(f => (
                    <div key={f} style={{ fontSize: 12, color: C.textSoft, padding: "2px 0" }}>• {f}</div>
                  ))}
                </div>
                <div style={{ background: C.redDim, border: `1px solid ${C.red}30`, borderRadius: 7, padding: "10px 14px" }}>
                  <div style={{ fontSize: 11, fontWeight: 700, color: C.redText, marginBottom: 6 }}>🔒 Full license required</div>
                  {["AI Screening", "Review quality", "Decisions", "Program builder", "Emails & timeline"].map(f => (
                    <div key={f} style={{ fontSize: 12, color: C.textSoft, padding: "2px 0" }}>• {f}</div>
                  ))}
                </div>
              </div>
            </div>
          )}
        </div>
      )}

      {/* Author */}
      <div style={{ background: C.panel, border: `1px solid ${C.border}`, borderRadius: 10, padding: "20px 24px", marginBottom: 14 }}>
        <SectionTitle>Author & Links</SectionTitle>
        {[
          ["Author",      "Prof. Florenc Demrozi"],
          ["Contributor", "Dr. Klevia Dishnica"],
          ["Email",       "florenc1991@gmail.com"],
          ["Version",     "1.0.0"],
          ["Year",        "2026"],
        ].map(([label, value]) => (
          <div key={label} style={{ display: "flex", gap: 16, padding: "7px 0", borderBottom: `1px solid ${C.border}20`, alignItems: "center" }}>
            <span style={{ fontSize: 11, fontWeight: 700, color: C.muted, width: 90, flexShrink: 0, textTransform: "uppercase", letterSpacing: "0.06em" }}>{label}</span>
            <span style={{ fontSize: 13, color: C.text, fontFamily: ["Email","Version"].includes(label) ? C.mono : C.sans }}>{value}</span>
          </div>
        ))}
        <div style={{ marginTop: 16, display: "flex", flexDirection: "column", gap: 8 }}>
          {[
            ["🔗", "GitHub repository", "https://github.com/FlorencDemrozi/pcc"],
            ["📋", "Feedback form",     "https://forms.cloud.microsoft/e/EeQg7grrF5"],
            ["🌐", "Project website",   "https://florencdemrozi.github.io/pcc/"],
          ].map(([icon, label, url]) => (
            <a key={url} href={url} target="_blank" rel="noreferrer" style={{
              display: "flex", alignItems: "center", gap: 10, padding: "8px 12px",
              borderRadius: 7, background: C.panelAlt, border: `1px solid ${C.border}`,
              textDecoration: "none",
            }}>
              <span style={{ fontSize: 15 }}>{icon}</span>
              <span style={{ fontSize: 12, fontWeight: 600, color: C.accent }}>{label}</span>
              <span style={{ fontSize: 11, color: C.muted, marginLeft: "auto", fontFamily: C.mono }}>
                {url.replace("https://", "")}
              </span>
            </a>
          ))}
        </div>
      </div>

      {/* License */}
      <div style={{ background: C.panel, border: `1px solid ${C.border}`, borderRadius: 10, padding: "20px 24px", marginBottom: 14 }}>
        <SectionTitle>License</SectionTitle>
        <div style={{ fontSize: 13, color: C.textSoft, lineHeight: 1.8, marginBottom: 16 }}>
          Program Chair Copilot is available free of charge for <strong style={{ color: C.text }}>non-commercial use</strong> — including academic research, personal use, and the organisation of non-profit scientific conferences.
        </div>
        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 10, marginBottom: 16 }}>
          {[
            { icon: "✓", label: "Academic use",          color: C.green, desc: "Free for universities and research groups" },
            { icon: "✓", label: "Personal use",           color: C.green, desc: "Free for individual researchers" },
            { icon: "✓", label: "Non-profit conferences", color: C.green, desc: "Free for non-profit scientific events" },
            { icon: "✗", label: "Commercial use",         color: C.red,   desc: "Requires a separate commercial license" },
            { icon: "✗", label: "Resale or sublicensing", color: C.red,   desc: "Not permitted without written agreement" },
            { icon: "✗", label: "Removing attribution",   color: C.red,   desc: "Author credit must be preserved" },
          ].map((item, i) => (
            <div key={i} style={{ display: "flex", gap: 10, padding: "10px 14px", borderRadius: 8, background: item.color + "08", border: `1px solid ${item.color}25`, alignItems: "flex-start" }}>
              <span style={{ fontSize: 14, color: item.color, flexShrink: 0, fontWeight: 700 }}>{item.icon}</span>
              <div>
                <div style={{ fontSize: 12, fontWeight: 600, color: item.color }}>{item.label}</div>
                <div style={{ fontSize: 11, color: C.muted, marginTop: 2 }}>{item.desc}</div>
              </div>
            </div>
          ))}
        </div>
        <div style={{ background: C.accentDim, border: `1px solid ${C.accent}40`, borderRadius: 8, padding: "12px 16px", marginBottom: 16, display: "flex", gap: 12, alignItems: "flex-start" }}>
          <span style={{ fontSize: 16, flexShrink: 0 }}>💼</span>
          <div>
            <div style={{ fontSize: 13, fontWeight: 600, color: C.accentText, marginBottom: 3 }}>Commercial licensing available</div>
            <div style={{ fontSize: 12, color: C.textSoft, lineHeight: 1.6 }}>
              Companies and for-profit organisations must obtain a separate commercial license.
            </div>
            <a href="mailto:florenc1991@gmail.com" style={{ fontSize: 12, fontWeight: 600, color: C.accent, textDecoration: "none", display: "block", marginTop: 8 }}>florenc1991@gmail.com →</a>
          </div>
        </div>
        <button onClick={() => setLicenseOpen(!licenseOpen)} style={{ background: "transparent", border: `1px solid ${C.border}`, borderRadius: 5, padding: "6px 14px", fontSize: 11, fontWeight: 600, cursor: "pointer", color: C.muted }}>
          {licenseOpen ? "▲ Hide full license text" : "▼ Read full license text"}
        </button>
        {licenseOpen && (
          <pre style={{ marginTop: 14, padding: "16px 18px", background: C.panelAlt, border: `1px solid ${C.border}`, borderRadius: 8, fontSize: 11, color: C.textSoft, fontFamily: C.mono, lineHeight: 1.8, whiteSpace: "pre-wrap", wordBreak: "break-word", maxHeight: 400, overflowY: "auto" }}>
            {LICENSE_TEXT}
          </pre>
        )}
      </div>

      {/* Privacy */}
      <div style={{ background: C.panel, border: `1px solid ${C.border}`, borderRadius: 10, padding: "20px 24px" }}>
        <SectionTitle>Privacy</SectionTitle>
        <div style={{ fontSize: 13, color: C.textSoft, lineHeight: 1.8 }}>
          Program Chair Copilot runs entirely on your local machine. Your conference data, paper PDFs, and review files never leave your computer except when you explicitly use an AI feature — in which case only the necessary content is sent directly to your chosen LLM provider using your own API key. There is no telemetry, no analytics, and no server-side storage.
        </div>
      </div>
    </div>
  );
}
