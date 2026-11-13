import { useState, useEffect, useCallback } from "react";
import { C, IS } from "../utils/theme.js";
import { SectionTitle, PrimaryButton, GhostButton, InfoBanner } from "../components/ui.jsx";
import { errorFromResponse } from "../utils/api.js";

// UI metadata only (key field names / placeholders). Display names and model IDs
// come from GET /api/config/llm/providers so they never go stale here.
const PROVIDER_UI = {
  claude: { name: "Claude (Anthropic)", keyField: "claude_key", keyLabel: "Anthropic API key", placeholder: "sk-ant-..." },
  openai: { name: "ChatGPT (OpenAI)",   keyField: "openai_key", keyLabel: "OpenAI API key",    placeholder: "sk-..." },
  gemini: { name: "Gemini (Google)",    keyField: "gemini_key", keyLabel: "Gemini API key",    placeholder: "AIza..." },
  groq:   { name: "Groq",               keyField: "groq_key",   keyLabel: "Groq API key",      placeholder: "gsk_..." },
  ollama: { name: "Ollama (local)",     keyField: null,         keyLabel: null,                placeholder: null },
};

// Non-LLM keys shown as extra key cards (not selectable as a provider).
const EXTRA_KEYS = {
  openalex: { name: "OpenAlex (optional)", keyField: "openalex_key",
              keyLabel: "OpenAlex API key \u2014 free at openalex.org; improves reference verification",
              placeholder: "OpenAlex API key" },
};

const PDF_LABEL = { native: "Native", vision: "Vision", text: "Text only" };

// Module ids match the backend's task names (callLLM "task").
const MODULE_TIERS = [
  ["AI Screening",     "screening",      "full"],
  ["Decisions",        "decisions",      "full"],
  ["Review Quality",   "review_quality", "fast"],
  ["Blind Compliance", "blind",          "fast"],
  ["Program Builder",  "program",        "full"],
  ["Email drafting",   "email",          "fast"],
  ["CFP extraction",   "cfp_extract",    "fast"],
];

async function postLLMConfig(payload) {
  const r = await fetch("/api/config/llm", {
    method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload),
  });
  if (!r.ok) throw await errorFromResponse(r);
  const d = await r.json().catch(() => ({}));
  if (d && d.ok === false) throw new Error("Backend did not save the configuration");
  return d;
}

export function SettingsModule() {
  // Non-secret settings; keys are never held here — only their "set"/masked status.
  const [llmConf, setLlmConf]     = useState({ provider: "claude", ollama_url: "http://localhost:11434", module_tiers: {} });
  const [keyStatus, setKeyStatus] = useState({});   // { claude_key: { set, masked }, ... }
  const [providers, setProviders] = useState(null); // from /api/config/llm/providers
  const [keyInputs, setKeyInputs] = useState({});
  const [status, setStatus]       = useState(null); // { field, ok, msg }
  const [loadError, setLoadError] = useState("");
  const [testing, setTesting]     = useState(false);
  const [testResult, setTestResult] = useState(null);

  const flash = (field, ok, msg) => {
    setStatus({ field, ok, msg });
    setTimeout(() => setStatus(s => (s && s.field === field ? null : s)), ok ? 2500 : 6000);
  };

  const loadStatus = useCallback(async () => {
    try {
      const r = await fetch("/api/config/llm");
      if (!r.ok) throw await errorFromResponse(r);
      const d = await r.json();
      setLlmConf({
        provider:     d.provider || "claude",
        ollama_url:   d.ollama_url || "http://localhost:11434",
        module_tiers: (d.module_tiers && typeof d.module_tiers === "object") ? d.module_tiers : {},
      });
      const ks = {};
      for (const p of [...Object.values(PROVIDER_UI), ...Object.values(EXTRA_KEYS)]) {
        if (!p.keyField) continue;
        ks[p.keyField] = { set: !!d[`${p.keyField}_set`], masked: d[`${p.keyField}_masked`] || "" };
      }
      setKeyStatus(ks);
      setLoadError("");
    } catch (e) {
      setLoadError(`Could not load LLM settings: ${e.message}`);
    }
  }, []);

  useEffect(() => {
    loadStatus();
    fetch("/api/config/llm/providers")
      .then(r => (r.ok ? r.json() : null))
      .then(d => { if (d && typeof d === "object") setProviders(d); })
      .catch(() => {});
  }, [loadStatus]);

  // Only non-secret fields + whatever is explicitly given. Keys are sent only when non-empty.
  const baseSettings = () => ({ provider: llmConf.provider, ollama_url: llmConf.ollama_url, module_tiers: llmConf.module_tiers });

  const saveKey = async field => {
    const val = (keyInputs[field] || "").trim();
    if (!val) return;
    try {
      await postLLMConfig({ ...baseSettings(), [field]: val });
      setKeyInputs(p => ({ ...p, [field]: "" }));
      flash(field, true, "Saved");
      await loadStatus();
    } catch (e) { flash(field, false, e.message); }
  };

  const removeKey = async field => {
    if (!window.confirm("Remove this API key from the local configuration?")) return;
    try {
      await postLLMConfig({ ...baseSettings(), clear_keys: [field] });
      flash(field, true, "Removed");
      await loadStatus();
    } catch (e) { flash(field, false, e.message); }
  };

  const saveProvider = async provider => {
    const prev = llmConf.provider;
    setLlmConf(p => ({ ...p, provider }));
    try { await postLLMConfig({ ...baseSettings(), provider }); }
    catch (e) { setLlmConf(p => ({ ...p, provider: prev })); flash("provider", false, e.message); }
  };

  const saveOllamaUrl = async () => {
    try { await postLLMConfig(baseSettings()); flash("ollama", true, "Saved"); }
    catch (e) { flash("ollama", false, e.message); }
  };

  const saveTier = async (taskId, tier) => {
    const module_tiers = { ...(llmConf.module_tiers || {}), [taskId]: tier };
    const prev = llmConf.module_tiers;
    setLlmConf(p => ({ ...p, module_tiers }));
    try { await postLLMConfig({ ...baseSettings(), module_tiers }); }
    catch (e) { setLlmConf(p => ({ ...p, module_tiers: prev })); flash("tiers", false, e.message); }
  };

  const testConn = async () => {
    setTesting(true); setTestResult(null);
    try {
      const r = await fetch("/api/config/llm/test", { method: "POST" });
      if (!r.ok) throw await errorFromResponse(r);
      setTestResult(await r.json());
    } catch (e) {
      setTestResult({ ok: false, error: e.message || "Request failed" });
    } finally {
      setTesting(false);
    }
  };

  const inputStyle = IS();
  const providerName = id => providers?.[id]?.name || PROVIDER_UI[id]?.name || id;
  const pdfSupport   = id => PDF_LABEL[providers?.[id]?.pdf] || providers?.[id]?.pdf || "—";
  const curModels    = providers?.[llmConf.provider]?.models || null;
  const Status = ({ field }) => status?.field === field
    ? <div style={{ fontSize: 12, marginTop: 6, color: status.ok ? C.green : C.red }}>{status.ok ? "✓ " : "✗ "}{status.msg}</div>
    : null;

  return (
    <div>
      {loadError && <InfoBanner type="error">{loadError}</InfoBanner>}

      {/* Provider selector */}
      <div style={{ background: C.panel, border: `1px solid ${C.border}`, borderRadius: 10, padding: "20px 24px", marginBottom: 14 }}>
        <SectionTitle>LLM Provider</SectionTitle>
        <div style={{ fontSize: 12, color: C.muted, marginBottom: 14 }}>AI modules use the selected provider. Deterministic checks never make API calls.</div>
        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 8, marginBottom: 16 }}>
          {Object.keys(PROVIDER_UI).map(id => (
            <div key={id} onClick={() => saveProvider(id)} style={{
              padding: "10px 14px", borderRadius: 8, cursor: "pointer",
              border: `1px solid ${llmConf.provider === id ? C.accent : C.border}`,
              background: llmConf.provider === id ? C.accent + "18" : C.panel,
              transition: "all 0.15s",
            }}>
              <div style={{ fontSize: 13, fontWeight: 600, color: llmConf.provider === id ? C.accentText : C.text }}>{providerName(id)}</div>
              <div style={{ fontSize: 11, color: C.muted, marginTop: 3 }}>
                PDF support: {pdfSupport(id)}
                {PROVIDER_UI[id].keyField && keyStatus[PROVIDER_UI[id].keyField]?.set && <span style={{ color: C.green }}> · key set</span>}
              </div>
            </div>
          ))}
        </div>
        <Status field="provider" />
        <div style={{ display: "flex", gap: 10, alignItems: "center" }}>
          <PrimaryButton onClick={testConn} disabled={testing}>{testing ? "Testing…" : `Test ${providerName(llmConf.provider)}`}</PrimaryButton>
          {testResult && <span style={{ fontSize: 12, color: testResult.ok ? C.green : C.red }}>{testResult.ok ? "✓ Connected" : `✗ ${testResult.error || testResult.detail || "Failed"}`}</span>}
        </div>
      </div>

      {/* API key fields per provider */}
      {[...Object.entries(PROVIDER_UI), ...Object.entries(EXTRA_KEYS)].filter(([, p]) => p.keyField).map(([id, p]) => {
        const ks = keyStatus[p.keyField] || {};
        return (
          <div key={id} style={{ background: C.panel, border: `1px solid ${llmConf.provider === id ? C.accent + "60" : C.border}`, borderRadius: 10, padding: "16px 20px", marginBottom: 10 }}>
            <SectionTitle>{providerName(id)} — {p.keyLabel}</SectionTitle>
            <div style={{ fontSize: 12, marginBottom: 8, color: ks.set ? C.green : C.muted, display: "flex", alignItems: "center", gap: 10 }}>
              {ks.set
                ? <>✓ Key set <code style={{ fontSize: 11, background: C.border, padding: "1px 6px", borderRadius: 3, color: C.textSoft }}>{ks.masked}</code></>
                : "No key set"}
              {ks.set && <GhostButton small onClick={() => removeKey(p.keyField)}>Remove</GhostButton>}
            </div>
            <div style={{ display: "flex", gap: 10 }}>
              <input style={{ ...inputStyle, flex: 1, fontFamily: "monospace" }} type="password" autoComplete="off"
                placeholder={ks.set ? "Enter a new key to replace the current one" : p.placeholder} value={keyInputs[p.keyField] || ""}
                onChange={e => setKeyInputs(prev => ({ ...prev, [p.keyField]: e.target.value }))}
                onKeyDown={e => e.key === "Enter" && saveKey(p.keyField)} />
              <PrimaryButton onClick={() => saveKey(p.keyField)} disabled={!keyInputs[p.keyField]?.trim()}>Save</PrimaryButton>
            </div>
            <Status field={p.keyField} />
          </div>
        );
      })}

      {/* Ollama URL */}
      {llmConf.provider === "ollama" && (
        <div style={{ background: C.panel, border: `1px solid ${C.accent + "60"}`, borderRadius: 10, padding: "16px 20px", marginBottom: 10 }}>
          <SectionTitle>Ollama — endpoint URL</SectionTitle>
          <div style={{ display: "flex", gap: 10 }}>
            <input style={{ ...inputStyle, flex: 1 }} value={llmConf.ollama_url} onChange={e => setLlmConf(p => ({ ...p, ollama_url: e.target.value }))} />
            <PrimaryButton onClick={saveOllamaUrl}>Save</PrimaryButton>
          </div>
          <Status field="ollama" />
          <div style={{ fontSize: 11, color: C.muted, marginTop: 8 }}>
            Ollama must be running. Install it from ollama.com and pull a model, e.g.{" "}
            <code style={{ fontSize: 11, background: C.border, padding: "1px 6px", borderRadius: 3 }}>ollama pull {providers?.ollama?.models?.full || "<model>"}</code>
          </div>
        </div>
      )}

      {/* Model tiers per module */}
      <div style={{ background: C.panel, border: `1px solid ${C.border}`, borderRadius: 10, padding: "16px 20px", marginBottom: 10 }}>
        <SectionTitle>Model tier per module</SectionTitle>
        <div style={{ fontSize: 12, color: C.muted, marginBottom: 12, lineHeight: 1.6, fontFamily: C.sans }}>
          Each module uses either the provider's <strong style={{ color: C.text }}>full model</strong> (best quality, higher cost) or its <strong style={{ color: C.text }}>fast model</strong> (cheaper, lower latency). Defaults are pre-set based on task complexity.
        </div>
        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 8 }}>
          {MODULE_TIERS.map(([label, taskId, defaultTier]) => (
            <div key={taskId} style={{ display: "flex", justifyContent: "space-between", alignItems: "center", padding: "8px 12px", background: C.panelAlt, borderRadius: 6 }}>
              <span style={{ fontSize: 12, color: C.text, fontFamily: C.sans }}>{label}</span>
              <div style={{ display: "flex", gap: 4 }}>
                {["fast", "full"].map(tier => {
                  const cur    = (llmConf.module_tiers || {})[taskId] || defaultTier;
                  const active = cur === tier;
                  return (
                    <button key={tier} onClick={() => saveTier(taskId, tier)} style={{
                      padding: "3px 10px", borderRadius: 4, fontSize: 11, fontWeight: 600, cursor: "pointer",
                      border: `1px solid ${active ? C.accent : C.border}`,
                      background: active ? C.accentDim : "transparent",
                      color: active ? C.accentText : C.muted, fontFamily: C.sans,
                    }}>{tier}</button>
                  );
                })}
              </div>
            </div>
          ))}
        </div>
        <Status field="tiers" />
        <div style={{ fontSize: 11, color: C.muted, marginTop: 10, fontFamily: C.sans }}>
          {curModels
            ? <>Current provider ({providerName(llmConf.provider)}): fast = <code>{curModels.fast || "—"}</code> · full = <code>{curModels.full || "—"}</code></>
            : "Model IDs for each tier are configured by the backend for the selected provider."}
        </div>
      </div>

      <div style={{ background: C.panel, border: `1px solid ${C.border}`, borderRadius: 10, padding: "16px 20px" }}>
        <SectionTitle>About</SectionTitle>
        <div style={{ fontSize: 12, color: C.muted, lineHeight: 1.8 }}>
          <strong style={{ color: C.text }}>Program Chair Copilot</strong> v1.0.0
          <div style={{ marginTop: 6 }}>
            Keys stored in <code style={{ fontSize: 11, background: C.border, padding: "1px 6px", borderRadius: 3 }}>~/.pcc/config.json</code> — never transmitted except to the selected provider.
          </div>
        </div>
      </div>
    </div>
  );
}
