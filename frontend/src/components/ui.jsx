import { useState } from "react";
import { C, REC_COLORS, RATING_COLORS, IS, LS } from "../utils/theme.js";

// ── Badge ─────────────────────────────────────────────────────────────────────
export function Badge({ label, size = "sm" }) {
  const fn = REC_COLORS[label] || RATING_COLORS[label] || RATING_COLORS.default;
  const st = fn();
  return (
    <span style={{
      display: "inline-flex", alignItems: "center",
      padding: size === "lg" ? "3px 10px" : "2px 7px",
      borderRadius: 4,
      fontSize: size === "lg" ? 12 : 11,
      fontWeight: 700, fontFamily: C.sans,
      background: st.bg, color: st.color,
      border: `1px solid ${st.border || st.color + "35"}`,
      whiteSpace: "nowrap", letterSpacing: "0.03em",
    }}>{label}</span>
  );
}

// ── StatCard ──────────────────────────────────────────────────────────────────
export function StatCard({ label, value, color, sub }) {
  return (
    <div style={{
      background: C.panel, border: `1px solid ${C.border}`,
      borderRadius: 8, padding: "14px 18px", flex: 1, minWidth: 90,
    }}>
      <div style={{ fontSize: 26, fontWeight: 700, color: color || C.text, fontFamily: C.mono, letterSpacing: "-0.02em", lineHeight: 1 }}>{value}</div>
      <div style={{ fontSize: 11, color: C.muted, marginTop: 5, fontFamily: C.sans, fontWeight: 500 }}>{label}</div>
      {sub && <div style={{ fontSize: 10, color: C.accent, marginTop: 3, fontFamily: C.sans }}>{sub}</div>}
    </div>
  );
}

// ── SectionTitle ──────────────────────────────────────────────────────────────
export function SectionTitle({ children }) {
  return (
    <div style={{
      fontSize: 10, fontWeight: 700, color: C.muted,
      letterSpacing: "0.1em", textTransform: "uppercase",
      marginBottom: 10, marginTop: 2, fontFamily: C.sans,
      paddingBottom: 6, borderBottom: `1px solid ${C.border}`,
    }}>{children}</div>
  );
}

// ── Pill ──────────────────────────────────────────────────────────────────────
export function Pill({ children, color }) {
  return (
    <span style={{
      fontSize: 10, fontWeight: 700, padding: "1px 7px", borderRadius: 3,
      background: (color || C.accent) + "18", color: color || C.accentText,
      border: `1px solid ${(color || C.accent) + "30"}`,
      letterSpacing: "0.04em", textTransform: "uppercase", fontFamily: C.sans,
    }}>{children}</span>
  );
}

// ── FileUploadBox ─────────────────────────────────────────────────────────────
export function FileUploadBox({ label, hint, accept, onFile, loaded, loadedLabel, refObj }) {
  const [hover, setHover] = useState(false);
  return (
    <div style={{
      border: `1px solid ${loaded ? C.green + "50" : hover ? C.borderLight : C.border}`,
      borderRadius: 8, padding: "14px 18px", marginBottom: 10,
      background: loaded ? C.greenDim : hover ? C.panelAlt : C.panel,
      transition: "all 0.15s", display: "flex", alignItems: "center", gap: 16,
    }}
      onMouseEnter={() => setHover(true)} onMouseLeave={() => setHover(false)}>
      <div style={{
        width: 36, height: 36, borderRadius: 6, flexShrink: 0,
        background: loaded ? C.green + "20" : C.accent + "15",
        display: "flex", alignItems: "center", justifyContent: "center", fontSize: 16,
      }}>{loaded ? "✓" : "↑"}</div>
      <div style={{ flex: 1, minWidth: 0 }}>
        <div style={{ fontSize: 13, fontWeight: 600, color: C.text, fontFamily: C.sans }}>{label}</div>
        <div style={{ fontSize: 11, color: C.muted, marginTop: 2, fontFamily: C.sans }}>{loaded ? loadedLabel : hint}</div>
      </div>
      <input ref={refObj} type="file" accept={accept}
        onChange={e => { if (e.target.files[0]) onFile(e.target.files[0]); }}
        style={{ display: "none" }} />
      <button onClick={() => refObj.current?.click()} style={{
        border: `1px solid ${loaded ? C.green + "60" : C.border}`,
        background: "transparent", borderRadius: 5, padding: "5px 14px",
        fontSize: 12, cursor: "pointer", fontWeight: 600, fontFamily: C.sans,
        color: loaded ? C.greenText : C.textSoft,
        whiteSpace: "nowrap", transition: "all 0.15s",
      }}>{loaded ? "Replace" : "Choose file"}</button>
    </div>
  );
}

// ── ProgressBar ───────────────────────────────────────────────────────────────
export function ProgressBar({ done, total, label }) {
  const pct = total ? Math.round((done / total) * 100) : 0;
  return (
    <div style={{
      background: C.panelAlt, border: `1px solid ${C.border}`,
      borderRadius: 8, padding: "20px 24px", marginBottom: 16,
    }}>
      <div style={{ display: "flex", gap: 12, alignItems: "center", marginBottom: 12 }}>
        <div style={{
          width: 32, height: 32, borderRadius: 6, background: C.accentDim,
          display: "flex", alignItems: "center", justifyContent: "center",
          fontSize: 16, flexShrink: 0,
        }}>⚙</div>
        <div>
          <div style={{ fontSize: 13, fontWeight: 600, color: C.text, fontFamily: C.sans }}>Processing</div>
          <div style={{ fontSize: 11, color: C.muted, marginTop: 2, fontFamily: C.sans }}>{label}</div>
        </div>
        {total > 0 && <div style={{ marginLeft: "auto", fontSize: 12, color: C.muted, fontFamily: C.mono }}>{done}/{total}</div>}
      </div>
      <div style={{ height: 3, background: C.border, borderRadius: 2, overflow: "hidden" }}>
        <div style={{
          height: "100%", background: C.accent, borderRadius: 2,
          width: `${total > 0 ? pct : 100}%`,
          transition: "width 0.4s ease",
          animation: total === 0 ? "progress-indeterminate 1.5s ease infinite" : undefined,
        }} />
      </div>
    </div>
  );
}

// ── PrimaryButton ─────────────────────────────────────────────────────────────
export function PrimaryButton({ children, onClick, disabled }) {
  const [hover, setHover] = useState(false);
  return (
    <button onClick={onClick} disabled={disabled}
      onMouseEnter={() => setHover(true)} onMouseLeave={() => setHover(false)}
      style={{
        background: disabled ? C.border : hover ? C.accentHover : C.accent,
        color: disabled ? C.muted : C.bg,
        border: "none", borderRadius: 6,
        padding: "9px 22px", fontSize: 13, fontWeight: 700,
        cursor: disabled ? "not-allowed" : "pointer",
        fontFamily: C.sans, letterSpacing: "0.01em",
        transition: "background 0.15s",
      }}>{children}</button>
  );
}

// ── GhostButton ───────────────────────────────────────────────────────────────
export function GhostButton({ children, onClick, small = false }) {
  const [hover, setHover] = useState(false);
  return (
    <button onClick={onClick}
      onMouseEnter={() => setHover(true)} onMouseLeave={() => setHover(false)}
      style={{
        border: `1px solid ${hover ? C.borderLight : C.border}`,
        background: hover ? C.panelAlt : "transparent",
        borderRadius: 6, padding: small ? "5px 12px" : "8px 18px",
        fontSize: small ? 11 : 13, cursor: "pointer", color: C.textSoft,
        fontFamily: C.sans, fontWeight: 500, transition: "all 0.15s",
      }}>{children}</button>
  );
}

// ── EmptyState ────────────────────────────────────────────────────────────────
export function EmptyState({ icon, title, body, action }) {
  return (
    <div style={{
      textAlign: "center", padding: "64px 32px",
      display: "flex", flexDirection: "column", alignItems: "center", gap: 12,
    }}>
      <div style={{
        width: 56, height: 56, borderRadius: 12, background: C.panelAlt,
        border: `1px solid ${C.border}`, display: "flex", alignItems: "center",
        justifyContent: "center", fontSize: 24, marginBottom: 4,
      }}>{icon || "📂"}</div>
      <div style={{ fontSize: 15, fontWeight: 600, color: C.text, fontFamily: C.sans }}>{title}</div>
      {body && <div style={{ fontSize: 13, color: C.muted, maxWidth: 400, lineHeight: 1.6, fontFamily: C.sans }}>{body}</div>}
      {action && <div style={{ marginTop: 8 }}>{action}</div>}
    </div>
  );
}

// ── InfoBanner ────────────────────────────────────────────────────────────────
export function InfoBanner({ children, type = "info" }) {
  const colors = {
    info:    { bg: C.accentDim, border: C.accent + "40", icon: "ℹ", color: C.accentText },
    warning: { bg: C.amberDim,  border: C.amber + "40",  icon: "⚠", color: C.amber },
    success: { bg: C.greenDim,  border: C.green + "40",  icon: "✓", color: C.greenText },
    error:   { bg: C.redDim,    border: C.red + "40",    icon: "✕", color: C.redText },
  };
  const s = colors[type] || colors.info;
  return (
    <div style={{
      display: "flex", gap: 12, alignItems: "flex-start",
      padding: "10px 14px", borderRadius: 7,
      background: s.bg, border: `1px solid ${s.border}`,
      marginBottom: 12, fontFamily: C.sans,
    }}>
      <span style={{ fontSize: 13, color: s.color, flexShrink: 0, marginTop: 1 }}>{s.icon}</span>
      <span style={{ fontSize: 12, color: C.textSoft, lineHeight: 1.6 }}>{children}</span>
    </div>
  );
}

// ── DataSourceBadge ───────────────────────────────────────────────────────────
export function DataSourceBadge({ loaded, count, label }) {
  return (
    <div style={{
      display: "flex", alignItems: "center", gap: 6,
      padding: "4px 10px", borderRadius: 5,
      background: loaded ? C.greenDim : C.panelAlt,
      border: `1px solid ${loaded ? C.green + "40" : C.border}`,
      fontSize: 11, fontFamily: C.sans,
    }}>
      <span style={{ width: 6, height: 6, borderRadius: "50%", background: loaded ? C.green : C.muted, flexShrink: 0 }} />
      <span style={{ color: loaded ? C.greenText : C.muted, fontWeight: 600 }}>{loaded ? count : "—"}</span>
      <span style={{ color: C.muted }}>{label}</span>
    </div>
  );
}

// ── LockedModule ──────────────────────────────────────────────────────────────
export function LockedModule({ name }) {
  return (
    <div style={{
      display: "flex", flexDirection: "column", alignItems: "center",
      justifyContent: "center", padding: "80px 32px", textAlign: "center",
      maxWidth: 520, margin: "0 auto",
    }}>
      <div style={{
        width: 72, height: 72, borderRadius: 16,
        background: C.redDim, border: `1px solid ${C.red}30`,
        display: "flex", alignItems: "center", justifyContent: "center",
        fontSize: 32, marginBottom: 20,
      }}>🔒</div>
      <div style={{ fontSize: 20, fontWeight: 700, color: C.text, fontFamily: C.sans, marginBottom: 8 }}>
        {name} — Trial Expired
      </div>
      <div style={{ fontSize: 14, color: C.muted, fontFamily: C.sans, lineHeight: 1.7, marginBottom: 24 }}>
        Your 30-day free trial has ended. This feature requires a full license.
        Compliance checks, review statistics, and COI detection remain available at no cost.
      </div>
      <div style={{
        background: C.panelAlt, border: `1px solid ${C.border}`,
        borderRadius: 10, padding: "20px 24px", width: "100%", marginBottom: 16,
      }}>
        <div style={{ fontSize: 12, fontWeight: 700, color: C.muted, textTransform: "uppercase", letterSpacing: "0.08em", fontFamily: C.sans, marginBottom: 12 }}>Your options</div>
        {[
          ["↓ Re-download", "Get a fresh 30-day trial from the website", C.teal],
          ["📧 Get a license", "Contact the author for full or institutional access", C.accent],
        ].map(([title, desc, color]) => (
          <div key={title} style={{ display: "flex", gap: 12, padding: "10px 0", borderTop: `1px solid ${C.border}20` }}>
            <span style={{ fontSize: 13, fontWeight: 700, color, minWidth: 120, fontFamily: C.sans }}>{title}</span>
            <span style={{ fontSize: 12, color: C.muted, fontFamily: C.sans }}>{desc}</span>
          </div>
        ))}
      </div>
      <a href="mailto:florenc1991@gmail.com" style={{
        display: "inline-block", background: C.accent, color: C.bg,
        padding: "9px 24px", borderRadius: 6,
        fontSize: 13, fontWeight: 700, fontFamily: C.sans, textDecoration: "none",
      }}>Contact for full license →</a>
      <div style={{ fontSize: 11, color: C.muted, marginTop: 12, fontFamily: C.sans }}>florenc1991@gmail.com</div>
    </div>
  );
}
