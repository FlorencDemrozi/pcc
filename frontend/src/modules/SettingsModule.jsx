import { useState } from "react";
import { C, IS, LS } from "../utils/theme.js";
import { SectionTitle, PrimaryButton } from "../components/ui.jsx";

const PROVIDERS = {
  claude: { name: "Claude (Anthropic)",  pdfSupport: "Native",   keyField: "claude_key",  keyLabel: "Anthropic API key", placeholder: "sk-ant-..." },
  openai: { name: "ChatGPT (OpenAI)",    pdfSupport: "Vision",   keyField: "openai_key",  keyLabel: "OpenAI API key",    placeholder: "sk-..." },
  gemini: { name: "Gemini (Google)",     pdfSupport: "Native",   keyField: "gemini_key",  keyLabel: "Gemini API key",    placeholder: "AIza..." },
  groq:   { name: "Groq",               pdfSupport: "Text only", keyField: "groq_key",    keyLabel: "Groq API key",      placeholder: "gsk_..." },
  ollama: { name: "Ollama (local)",      pdfSupport: "Text only", keyField: null,          keyLabel: null,                placeholder: null },
};

export function SettingsModule() {
  const [llmConf, setLlmConf]     = useState({ provider: "claude", claude_key: "", openai_key: "", gemini_key: "", groq_key: "", ollama_url: "http://localhost:11434", models: {} });
  const [keyInputs, setKeyInputs] = useState({});
  const [status, setStatus]       = useState(null);
  const [testing, setTesting]     = useState(false);
  const [testResult, setTestResult] = useState(null);

  // Load LLM config on mount
  useState(() => {
    fetch("/api/config/llm").then(r => r.json()).then(d => {
      setLlmConf(p => ({ ...p, provider: d.provider || "claude", ollama_url: d.ollama_url || "http://localhost:11434", models: d.models || {} }));
    });
  }, []);

  const saveKey = async field => {
    const val = (keyInputs[field] || "").trim();
    if (!val) return;
    const updated = { ...llmConf, [field]: val };
    const r = await fetch("/api/config/llm", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(updated) });
    if (r.ok) { setStatus({ field, ok: true }); setKeyInputs(p => ({ ...p, [field]: "" })); setLlmConf(updated); }
    else setStatus({ field, ok: false });
    setTimeout(() => setStatus(null), 3000);
  };

  const saveProvider = async provider => {
    const updated = { ...llmConf, provider };
    await fetch("/api/config/llm", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(updated) });
    setLlmConf(updated);
  };

  const saveOllamaUrl = async () => {
    await fetch("/api/config/llm", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(llmConf) });
    setStatus({ field: "ollama", ok: true });
    setTimeout(() => setStatus(null), 2000);
  };

  const testConn = async () => {
    setTesting(true); setTestResult(null);
    const r = await fetch("/api/config/llm/test", { method: "POST" });
    setTestResult(await r.json());
    setTesting(false);
  };

  const inputStyle = IS();
  const labelStyle = LS();

  return (
    <div>
      {/* Provider selector */}
      <div style={{ background: C.panel, border: `1px solid ${C.border}`, borderRadius: 10, padding: "20px 24px", marginBottom: 14 }}>
        <SectionTitle>LLM Provider</SectionTitle>
        <div style={{ fontSize: 12, color: C.muted, marginBottom: 14 }}>AI modules use the selected provider. Deterministic checks never make API calls.</div>
        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 8, marginBottom: 16 }}>
          {Object.entries(PROVIDERS).map(([id, p]) => (
            <div key={id} onClick={() => saveProvider(id)} style={{
              padding: "10px 14px", borderRadius: 8, cursor: "pointer",
              border: `1px solid ${llmConf.provider === id ? C.accent : C.border}`,
              background: llmConf.provider === id ? C.accent + "18" : C.panel,
              transition: "all 0.15s",
            }}>
              <div style={{ fontSize: 13, fontWeight: 600, color: llmConf.provider === id ? C.accentText : C.text }}>{p.name}</div>
              <div style={{ fontSize: 11, color: C.muted, marginTop: 3 }}>PDF support: {p.pdfSupport}</div>
            </div>
          ))}
        </div>
        <div style={{ display: "flex", gap: 10, alignItems: "center" }}>
          <PrimaryButton onClick={testConn} disabled={testing}>{testing ? "Testing…" : `Test ${PROVIDERS[llmConf.provider]?.name || "provider"}`}</PrimaryButton>
          {testResult && <span style={{ fontSize: 12, color: testResult.ok ? C.green : C.red }}>{testResult.ok ? "✓ Connected" : `✗ ${testResult.error || "Failed"}`}</span>}
        </div>
      </div>

      {/* API key fields per provider */}
      {Object.entries(PROVIDERS).filter(([, p]) => p.keyField).map(([id, p]) => (
        <div key={id} style={{ background: C.panel, border: `1px solid ${llmConf.provider === id ? C.accent + "60" : C.border}`, borderRadius: 10, padding: "16px 20px", marginBottom: 10 }}>
          <SectionTitle>{p.name} — {p.keyLabel}</SectionTitle>
          <div style={{ display: "flex", gap: 10 }}>
            <input style={{ ...inputStyle, flex: 1, fontFamily: "monospace" }} type="password"
              placeholder={p.placeholder} value={keyInputs[p.keyField] || ""}
              onChange={e => setKeyInputs(prev => ({ ...prev, [p.keyField]: e.target.value }))}
              onKeyDown={e => e.key === "Enter" && saveKey(p.keyField)} />
            <PrimaryButton onClick={() => saveKey(p.keyField)} disabled={!keyInputs[p.keyField]?.trim()}>Save</PrimaryButton>
          </div>
          {status?.field === p.keyField && <div style={{ fontSize: 12, marginTop: 6, color: status.ok ? C.green : C.red }}>{status.ok ? "✓ Saved" : "✗ Failed"}</div>}
        </div>
      ))}

      {/* Ollama URL */}
      {llmConf.provider === "ollama" && (
        <div style={{ background: C.panel, border: `1px solid ${C.accent + "60"}`, borderRadius: 10, padding: "16px 20px", marginBottom: 10 }}>
          <SectionTitle>Ollama — endpoint URL</SectionTitle>
          <div style={{ display: "flex", gap: 10 }}>
            <input style={{ ...inputStyle, flex: 1 }} value={llmConf.ollama_url} onChange={e => setLlmConf(p => ({ ...p, ollama_url: e.target.value }))} />
            <PrimaryButton onClick={saveOllamaUrl}>Save</PrimaryButton>
          </div>
          {status?.field === "ollama" && <div style={{ fontSize: 12, marginTop: 6, color: C.green }}>✓ Saved</div>}
          <div style={{ fontSize: 11, color: C.muted, marginTop: 8 }}>
            Ollama must be running. Install from ollama.com and run:{" "}
            <code style={{ fontSize: 11, background: C.border, padding: "1px 6px", borderRadius: 3 }}>ollama pull llama3</code>
          </div>
        </div>
      )}

      {/* Model tiers per module */}
      <div style={{ background: C.panel, border: `1px solid ${C.border}`, borderRadius: 10, padding: "16px 20px", marginBottom: 10 }}>
        <SectionTitle>Model tier per module</SectionTitle>
        <div style={{ fontSize: 12, color: C.muted, marginBottom: 12, lineHeight: 1.6, fontFamily: C.sans }}>
          Each module uses either the <strong style={{ color: C.text }}>Full model</strong> (best quality, more tokens) or <strong style={{ color: C.text }}>Fast model</strong> (cheaper, lower latency). Defaults are pre-set based on task complexity.
        </div>
        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 8 }}>
          {[
            ["AI Screening",    "screening",     "full"],
            ["Decisions",       "decisions",     "full"],
            ["Review Quality",  "review_quality","fast"],
            ["Blind Compliance","blind",         "fast"],
            ["Program Builder", "program",       "full"],
            ["Email drafting",  "email",         "fast"],
          ].map(([label, taskId, defaultTier]) => (
            <div key={taskId} style={{ display: "flex", justifyContent: "space-between", alignItems: "center", padding: "8px 12px", background: C.panelAlt, borderRadius: 6 }}>
              <span style={{ fontSize: 12, color: C.text, fontFamily: C.sans }}>{label}</span>
              <div style={{ display: "flex", gap: 4 }}>
                {["fast", "full"].map(tier => {
                  const active = (llmConf.module_tiers || {})[taskId] === tier || (!(llmConf.module_tiers || {})[taskId] && tier === defaultTier);
                  return (
                    <button key={tier} onClick={async () => {
                      const updated = { ...llmConf, module_tiers: { ...(llmConf.module_tiers || {}), [taskId]: tier } };
                      await fetch("/api/config/llm", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(updated) });
                      setLlmConf(updated);
                    }} style={{
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
        <div style={{ fontSize: 11, color: C.muted, marginTop: 10, fontFamily: C.sans }}>
          Fast: Claude Haiku / GPT-4o-mini / Gemini Flash · Full: Claude Sonnet / GPT-4o / Gemini Pro
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
