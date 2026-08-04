// ── Design system ─────────────────────────────────────────────────────────────
// Academic Precision palette — deep blue-black + warm amber gold
// Inter for UI, JetBrains Mono for data values

export const THEMES = {
  dark: {
    bg: "#0A0F1E", panel: "#0F1629", panelAlt: "#141E35",
    border: "#1E2D4A", borderLight: "#243554",
    text: "#E8ECF4", textSoft: "#B8C4D8", muted: "#64748B",
    accent: "#E8A020", accentHover: "#F0B040", accentDim: "#E8A02018", accentText: "#FFC84A",
    green: "#10B981", greenDim: "#10B98118", greenText: "#34D399",
    amber: "#F59E0B", amberDim: "#F59E0B18",
    red: "#EF4444", redDim: "#EF444418", redText: "#F87171",
    orange: "#F97316", teal: "#0D9488", tealText: "#2DD4BF", blue: "#3B82F6",
    mono: "'JetBrains Mono', 'Fira Code', monospace",
    sans: "'Inter', 'IBM Plex Sans', system-ui, sans-serif",
  },
  light: {
    bg: "#FAFAF8", panel: "#FFFFFF", panelAlt: "#F4F3F0",
    border: "#DDE1E8", borderLight: "#E8EBF0",
    text: "#111318", textSoft: "#374151", muted: "#6B7280",
    accent: "#C47D0A", accentHover: "#A86A08", accentDim: "#C47D0A12", accentText: "#92580A",
    green: "#059669", greenDim: "#05966912", greenText: "#047857",
    amber: "#D97706", amberDim: "#D9770612",
    red: "#DC2626", redDim: "#DC262612", redText: "#B91C1C",
    orange: "#EA580C", teal: "#0D9488", tealText: "#0F766E", blue: "#2563EB",
    mono: "'JetBrains Mono', 'Fira Code', monospace",
    sans: "'Inter', 'IBM Plex Sans', system-ui, sans-serif",
  },
};

// Mutable colour object — mutated by applyTheme so all components use C at render time
export const C = { ...THEMES.dark };

export function applyTheme(t) {
  const resolved =
    t === "system"
      ? typeof window !== "undefined" && window.matchMedia("(prefers-color-scheme: dark)").matches
        ? "dark"
        : "light"
      : t || "dark";
  Object.assign(C, THEMES[resolved] || THEMES.dark);
  if (typeof document !== "undefined") {
    document.documentElement.setAttribute("data-theme", resolved);
  }
}

// ── Status badge colour maps ──────────────────────────────────────────────────

export const REC_COLORS = {
  "Accept for review":               () => ({ bg: C.greenDim, color: C.greenText, border: C.green + "40" }),
  "Accept for review with concerns": () => ({ bg: C.amberDim, color: C.amber,     border: C.amber + "40" }),
  "Borderline":                      () => ({ bg: C.amberDim, color: C.amber,     border: C.amber + "40" }),
  "Desk reject":                     () => ({ bg: C.redDim,   color: C.redText,   border: C.red + "40"   }),
};

export const RATING_COLORS = {
  Strong:          () => ({ bg: C.greenDim,  color: C.greenText }),
  Adequate:        () => ({ bg: C.greenDim,  color: C.greenText }),
  Good:            () => ({ bg: C.greenDim,  color: C.greenText }),
  Pass:            () => ({ bg: C.greenDim,  color: C.greenText }),
  Clean:           () => ({ bg: C.greenDim,  color: C.greenText }),
  Satisfactory:    () => ({ bg: C.greenDim,  color: C.greenText }),
  Moderate:        () => ({ bg: C.amberDim,  color: C.amber }),
  Acceptable:      () => ({ bg: C.amberDim,  color: C.amber }),
  Superficial:     () => ({ bg: C.amberDim,  color: C.amber }),
  Weak:            () => ({ bg: C.redDim,    color: C.redText }),
  Poor:            () => ({ bg: C.redDim,    color: C.redText }),
  Fail:            () => ({ bg: C.redDim,    color: C.redText }),
  Missing:         () => ({ bg: C.redDim,    color: C.redText }),
  Flagged:         () => ({ bg: C.redDim,    color: C.redText }),
  Incomplete:      () => ({ bg: C.redDim,    color: C.redText }),
  Inappropriate:   () => ({ bg: C.redDim,    color: C.redText }),
  "Out of scope":  () => ({ bg: "#1a0a2e",   color: "#c084fc" }),
  "Cannot assess": () => ({ bg: C.panel,     color: C.muted }),
  "N/A":           () => ({ bg: C.panel,     color: C.muted }),
  default:         () => ({ bg: C.panelAlt,  color: C.muted }),
};

// ── Dynamic style helpers (evaluated at render time so theme changes work) ────

export const IS = () => ({
  width: "100%", padding: "8px 12px",
  border: `1px solid ${C.border}`, borderRadius: 5,
  fontSize: 13, fontFamily: C.sans, color: C.text,
  background: C.panelAlt, boxSizing: "border-box", outline: "none",
  transition: "border-color 0.15s",
});

export const LS = () => ({
  fontSize: 10, fontWeight: 700, color: C.muted,
  marginBottom: 5, display: "block",
  letterSpacing: "0.08em", textTransform: "uppercase",
  fontFamily: C.sans,
});
