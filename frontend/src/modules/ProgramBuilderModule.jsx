import { useState, useRef, useEffect } from "react";
import { C } from "../utils/theme.js";
import { PrimaryButton, GhostButton, EmptyState } from "../components/ui.jsx";
import { callLLM } from "../utils/api.js";
import { exportCSV } from "../utils/helpers.js";
import { IS } from "../utils/theme.js";

const TYPE_COLOR = {
  keynote: "#E8A020", panel: "#0D9488", tutorial: "#0D9488",
  session: "#10B981", special: "#F97316", break: "#64748B",
};

function extractSchedule(text) {
  // Try ```schedule fence first
  let m = text.match(/```schedule\s*\n?([\s\S]*?)```/);
  if (m) { try { return JSON.parse(m[1].trim()); } catch {} }

  // Try ```json fence
  m = text.match(/```json\s*\n?([\s\S]*?)```/);
  if (m) { try { const p = JSON.parse(m[1].trim()); if (Array.isArray(p)) return p; } catch {} }

  // Bare JSON array anywhere
  const arrayMatch = text.match(/(\[\s*\{[\s\S]*\}\s*\])/);
  if (arrayMatch) { try { return JSON.parse(arrayMatch[1]); } catch {} }

  // Array starting near slot_id / start_time keyword
  const idx = text.search(/"slot_id"|"start_time"|"end_time"/);
  if (idx > 0) {
    const before = text.lastIndexOf("[", idx);
    if (before >= 0) {
      try { return JSON.parse(text.slice(before)); } catch {}
      const after = text.indexOf("]", text.lastIndexOf("}"));
      if (after > before) { try { return JSON.parse(text.slice(before, after + 1)); } catch {} }
    }
  }
  return null;
}

export function ProgramBuilderModule({ conf, metaRows, ssRows, activeTrack = "All" }) {
  const allAccepted = metaRows.filter(r => {
    const d = (r.decision || r.Decision || r.Status || r.status || "").toString().toUpperCase();
    return d.includes("ACCEPT");
  });
  const accepted = activeTrack === "All" ? allAccepted
    : allAccepted.filter(r => String(r.Track || r.track || "").trim() === activeTrack);
  const regular  = accepted.filter(r => !((r.decision || r.Decision || "").toUpperCase().includes("SHORT")));
  const short    = accepted.filter(r =>  (r.decision || r.Decision || "").toUpperCase().includes("SHORT"));
  const special  = ssRows || [];
  const tracks   = [...new Set(accepted.map(r => r.track || r.Track || "").filter(Boolean))];

  const [messages, setMessages] = useState([]);
  const [input,    setInput]    = useState("");
  const [sending,  setSending]  = useState(false);
  const [schedule, setSchedule] = useState(null);
  const chatEndRef = useRef();

  useEffect(() => { chatEndRef.current?.scrollIntoView({ behavior: "smooth" }); }, [messages]);

  const buildSystem = () => {
    const confLines = [];
    if (conf.name)  confLines.push(`Conference: ${conf.name}${conf.acronym ? " (" + conf.acronym + ")" : ""}`);
    if (conf.dates) confLines.push(`Dates: ${conf.dates}`);
    if (conf.venue || conf.city) confLines.push(`Venue: ${[conf.venue, conf.city, conf.country].filter(Boolean).join(", ")}`);
    confLines.push(`Accepted: ${regular.length} regular, ${short.length} short${special.length > 0 ? ", " + special.length + " special" : ""}`);
    if (tracks.length) confLines.push(`Tracks: ${tracks.join(", ")}`);
    if (conf.conferenceDays?.length)
      conf.conferenceDays.forEach((d, i) => confLines.push(`Day ${i + 1}: ${d.date || "TBD"} ${d.start || "09:00"}–${d.end || "18:00"}`));

    const paperLines = accepted.slice(0, 150).map(r =>
      `#${r["#"] || r.id || "?"} [${(r.decision || r.Decision || "").toUpperCase().includes("SHORT") ? "S" : "R"}] ${r.track || r.Track || "?"} | ${(r.title || r.Title || "").slice(0, 60)}`
    ).concat(special.slice(0, 20).map(r => `#${r["#"] || r.id || "?"} [SP] ${(r.title || r.Title || "").slice(0, 60)}`));

    return `You are a conference program building assistant.

CONFERENCE:
${confLines.join("\n")}

PAPERS (${accepted.length + special.length} total):
${paperLines.join("\n")}

ROLE:
- Help the chair build a complete schedule through conversation.
- Ask clarifying questions (parallel tracks, session duration, keynote timing, etc.).
- When ready, generate the schedule as a JSON array. Output ONLY the raw JSON array with no other text before or after it, starting with [ and ending with ]. Each element must have: slot_id, day, start_time, end_time, type, label, track, papers (array), notes.
- Example slot: {"slot_id":"D1-K1","day":1,"start_time":"09:00","end_time":"09:45","type":"keynote","label":"Opening Keynote","track":"Plenary","papers":[],"notes":""}
- Schedule ALL papers. Group by topic/track similarity. You may draft and ask for feedback.`;
  };

  const send = async userMsg => {
    if (!userMsg.trim()) return;
    const newMessages = [...messages, { role: "user", content: userMsg }];
    setMessages(newMessages);
    setInput("");
    setSending(true);
    try {
      const historyText = newMessages.slice(-10).map(m => `${m.role === "user" ? "Chair" : "Assistant"}: ${m.content}`).join("\n\n");
      const text = await callLLM(buildSystem(), historyText, 3000, "program");
      const reply = { role: "assistant", content: text };
      setMessages(p => [...p, reply]);
      const sched = extractSchedule(text);
      if (sched && sched.length > 0) setSchedule(sched);
    } catch (e) {
      setMessages(p => [...p, { role: "assistant", content: `Error: ${e.message}. Please try again.` }]);
    }
    setSending(false);
  };

  if (!metaRows.length) return <EmptyState icon="📅" title="No submissions data" body="Load your submissions file in the Data import tab first." />;
  if (!accepted.length) return <EmptyState icon="📅" title="No accepted papers" body="The submissions file needs a Decision column with Accept/Reject values." />;

  const byDay = {};
  (schedule || []).forEach(slot => { const d = slot.day || 1; if (!byDay[d]) byDay[d] = []; byDay[d].push(slot); });

  return (
    <div style={{ display: "flex", gap: 14, height: "calc(100vh - 140px)", minHeight: 500 }}>
      {/* Chat panel */}
      <div style={{ width: 420, flexShrink: 0, display: "flex", flexDirection: "column", border: `1px solid ${C.border}`, borderRadius: 10, overflow: "hidden", background: C.panel }}>
        <div style={{ padding: "12px 16px", borderBottom: `1px solid ${C.border}`, flexShrink: 0 }}>
          <div style={{ fontSize: 13, fontWeight: 600, color: C.text }}>Program Builder</div>
          <div style={{ fontSize: 11, color: C.muted, marginTop: 2 }}>
            {regular.length} regular · {short.length} short{special.length > 0 ? ` · ${special.length} special` : ""}
            {tracks.length > 0 ? ` · ${tracks.length} tracks` : ""}
            {activeTrack !== "All" && <span style={{ color: C.accentText, marginLeft: 6 }}>• {activeTrack}</span>}
          </div>
        </div>

        <div style={{ flex: 1, overflowY: "auto", padding: "12px 14px", display: "flex", flexDirection: "column", gap: 10 }}>
          {messages.length === 0 && (
            <div style={{ textAlign: "center", paddingTop: 40 }}>
              <div style={{ fontSize: 24, marginBottom: 12 }}>💬</div>
              <div style={{ fontSize: 13, color: C.text, marginBottom: 8 }}>Interactive Program Builder</div>
              <div style={{ fontSize: 12, color: C.muted, lineHeight: 1.6, marginBottom: 20 }}>
                Describe your requirements and the AI will build the schedule. It will ask if it needs more info.
              </div>
              <PrimaryButton onClick={() => send("Hello! Please review the conference info and papers, then ask what you need to build the schedule.")}>
                Start →
              </PrimaryButton>
            </div>
          )}

          {messages.map((msg, i) => {
            const extracted = extractSchedule(msg.content);
            const displayText = extracted && extracted.length > 0
              ? msg.content.replace(/```schedule[\s\S]*?```/g, "").replace(/```json[\s\S]*?```/g, "").replace(/```[\s\S]*?```/g, "").replace(/\[\s*\{[\s\S]*\}\s*\]/, "").trim() + "\n\n✓ Schedule generated — see right panel →"
              : msg.content;

            return (
              <div key={i} style={{ alignSelf: msg.role === "user" ? "flex-end" : "flex-start", maxWidth: "88%" }}>
                <div style={{
                  padding: "9px 13px",
                  borderRadius: msg.role === "user" ? "10px 10px 2px 10px" : "10px 10px 10px 2px",
                  background: msg.role === "user" ? C.accentDim : C.panelAlt,
                  border: `1px solid ${msg.role === "user" ? C.accent + "50" : C.border}`,
                  fontSize: 12, color: C.text, lineHeight: 1.6, whiteSpace: "pre-wrap",
                }}>{displayText}</div>
                {msg.role === "assistant" && extracted && (
                  <div style={{ fontSize: 10, color: C.green, marginTop: 3 }}>✓ {extracted.length} time slots extracted</div>
                )}
              </div>
            );
          })}

          {sending && (
            <div style={{ alignSelf: "flex-start", fontSize: 12, color: C.muted, padding: "8px 12px", background: C.panelAlt, borderRadius: 8, border: `1px solid ${C.border}` }}>Thinking…</div>
          )}
          <div ref={chatEndRef} />
        </div>

        {messages.length > 0 && (
          <div style={{ padding: "10px 12px", borderTop: `1px solid ${C.border}`, display: "flex", gap: 8, flexShrink: 0 }}>
            <textarea value={input} onChange={e => setInput(e.target.value)}
              onKeyDown={e => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); if (input.trim()) send(input); } }}
              placeholder="Type a message… (Enter to send, Shift+Enter for newline)"
              style={{ ...IS(), flex: 1, height: 60, resize: "none", fontSize: 12, lineHeight: 1.5 }}
              disabled={sending} />
            <PrimaryButton onClick={() => send(input)} disabled={sending || !input.trim()}>
              {sending ? "…" : "Send"}
            </PrimaryButton>
          </div>
        )}
      </div>

      {/* Schedule panel */}
      <div style={{ flex: 1, overflowY: "auto" }}>
        {!schedule ? (
          <div style={{ display: "flex", alignItems: "center", justifyContent: "center", height: "100%", flexDirection: "column", gap: 10, color: C.muted }}>
            <div style={{ fontSize: 28 }}>📅</div>
            <div style={{ fontSize: 13 }}>Schedule will appear here once generated</div>
          </div>
        ) : (
          <>
            <div style={{ display: "flex", gap: 8, marginBottom: 14, justifyContent: "flex-end", alignItems: "center" }}>
              <span style={{ fontSize: 11, color: C.green }}>✓ {schedule.length} slots · {schedule.flatMap(s => s.papers || []).length} papers scheduled</span>
              <GhostButton small onClick={() => setSchedule(null)}>Clear</GhostButton>
              <GhostButton onClick={() => exportCSV(
                schedule.flatMap(slot => slot.papers?.length
                  ? slot.papers.map(p => ({ day: slot.day, start: slot.start_time, end: slot.end_time, session: slot.label, track: slot.track, paper_id: p.id, paper_title: p.title, type: p.type, duration_min: p.duration_min }))
                  : [{ day: slot.day, start: slot.start_time, end: slot.end_time, session: slot.label, track: slot.track, paper_id: "", paper_title: "", type: slot.type, duration_min: "" }]
                ), "program.csv")}>↓ Export CSV</GhostButton>
            </div>

            {Object.entries(byDay).sort((a, b) => Number(a[0]) - Number(b[0])).map(([day, slots]) => (
              <div key={day} style={{ marginBottom: 20 }}>
                <div style={{ fontSize: 14, fontWeight: 700, color: C.text, marginBottom: 10, paddingBottom: 6, borderBottom: `2px solid ${C.border}` }}>
                  Day {day}
                  {conf.conferenceDays?.[Number(day) - 1]?.date && (
                    <span style={{ fontSize: 12, color: C.muted, fontWeight: 400, marginLeft: 8 }}>{conf.conferenceDays[Number(day) - 1].date}</span>
                  )}
                </div>

                {[...slots].sort((a, b) => (a.start_time || "").localeCompare(b.start_time || "")).map((slot, i) => (
                  <div key={i} style={{ display: "flex", gap: 12, marginBottom: 6, alignItems: "flex-start" }}>
                    <div style={{ width: 80, flexShrink: 0, textAlign: "right" }}>
                      <div style={{ fontSize: 12, color: C.text, fontFamily: C.mono }}>{slot.start_time}</div>
                      <div style={{ fontSize: 10, color: C.muted, fontFamily: C.mono }}>{slot.end_time}</div>
                    </div>
                    <div style={{ flex: 1, background: C.panel, border: `1px solid ${(TYPE_COLOR[slot.type] || C.border) + "60"}`, borderLeft: `3px solid ${TYPE_COLOR[slot.type] || C.border}`, borderRadius: "0 8px 8px 0", padding: "10px 14px" }}>
                      <div style={{ display: "flex", gap: 8, alignItems: "center", marginBottom: slot.papers?.length ? 6 : 0 }}>
                        <span style={{ fontSize: 12, fontWeight: 600, color: C.text }}>{slot.label}</span>
                        {slot.track && slot.type !== "break" && (
                          <span style={{ fontSize: 10, color: TYPE_COLOR[slot.type] || C.muted, padding: "1px 7px", borderRadius: 3, background: (TYPE_COLOR[slot.type] || C.muted) + "20" }}>{slot.track}</span>
                        )}
                      </div>
                      {slot.papers?.length > 0 && (
                        <div style={{ display: "flex", flexDirection: "column", gap: 3 }}>
                          {slot.papers.map((p, j) => (
                            <div key={j} style={{ fontSize: 11, color: C.muted, display: "flex", gap: 8 }}>
                              <span style={{ color: C.muted, fontFamily: C.mono, flexShrink: 0 }}>#{p.id}</span>
                              <span style={{ flex: 1 }}>{p.title || "Untitled"}</span>
                              {p.duration_min && <span style={{ color: C.muted, flexShrink: 0, fontFamily: C.mono }}>{p.duration_min}min</span>}
                            </div>
                          ))}
                        </div>
                      )}
                      {slot.notes && <div style={{ fontSize: 11, color: C.muted, marginTop: 4, fontStyle: "italic" }}>{slot.notes}</div>}
                    </div>
                  </div>
                ))}
              </div>
            ))}
          </>
        )}
      </div>
    </div>
  );
}
