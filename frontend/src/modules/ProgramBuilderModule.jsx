import { useState, useRef, useEffect } from "react";
import { C, IS } from "../utils/theme.js";
import { PrimaryButton, GhostButton, EmptyState, InfoBanner } from "../components/ui.jsx";
import { callLLM, TASKS, isAbortError } from "../utils/api.js";
import { generateHTML, hydrateSchedule, paperInfo, compactPaperLine } from "../utils/programHtml.js";
import { useRunGuard } from "../utils/useRunGuard.js";

// ── Schedule extractor ────────────────────────────────────────────────────────

function extractSchedule(text) {
  // Strategy 1: json code fence
  const fence = text.match(/```(?:json)?\s*\n?([\s\S]*?)```/);
  if (fence) {
    try { const p = JSON.parse(fence[1].trim()); if (Array.isArray(p) && p.length) return p; } catch {}
  }
  // Strategy 2: find the outermost [ ... ] that parses as an array
  let depth = 0, start = -1;
  for (let i = 0; i < text.length; i++) {
    if (text[i] === '[') { if (depth === 0) start = i; depth++; }
    else if (text[i] === ']') {
      depth--;
      if (depth === 0 && start !== -1) {
        const chunk = text.slice(start, i + 1);
        try { const p = JSON.parse(chunk); if (Array.isArray(p) && p.length) return p; } catch {}
        start = -1;
      }
    }
  }
  // Strategy 3: extract each {...} block and try to build array
  const blocks = [];
  let bdepth = 0, bstart = -1;
  for (let i = 0; i < text.length; i++) {
    if (text[i] === '{') { if (bdepth === 0) bstart = i; bdepth++; }
    else if (text[i] === '}') {
      bdepth--;
      if (bdepth === 0 && bstart !== -1) {
        try { blocks.push(JSON.parse(text.slice(bstart, i + 1))); } catch {}
        bstart = -1;
      }
    }
  }
  if (blocks.length > 0) return blocks;
  return null;
}

// ── Schedule preview widget ───────────────────────────────────────────────────

function SchedulePreview({ schedule, conf }) {
  const numDays = Math.max(...schedule.map(b => b.day||1));
  const days    = conf.days || Array.from({length:numDays},(_,i)=>`Day ${i+1}`);
  const [activeDay, setActiveDay] = useState(0);

  const byDay = {};
  schedule.forEach(b => { const d=(b.day||1)-1; if(!byDay[d]) byDay[d]=[]; byDay[d].push(b); });
  Object.values(byDay).forEach(arr => arr.sort((a,b)=>(a.start||"").localeCompare(b.start||"")));

  const totalPapers   = schedule.filter(b=>b.type==="session_block").flatMap(b=>b.sessions||[]).flatMap(s=>s.papers||[]).length;
  const totalSessions = schedule.filter(b=>b.type==="session_block").flatMap(b=>b.sessions||[]).length;

  return (
    <div style={{display:"flex",flexDirection:"column",height:"100%"}}>
      <div style={{display:"flex",gap:6,marginBottom:10,flexWrap:"wrap",alignItems:"center",flexShrink:0}}>
        {days.map((d,i) => (
          <button key={i} onClick={()=>setActiveDay(i)} style={{
            padding:"4px 12px",borderRadius:4,fontSize:11,fontWeight:600,cursor:"pointer",
            background:activeDay===i?C.accent:C.panelAlt,
            color:activeDay===i?"#fff":C.textSoft,
            border:`1px solid ${activeDay===i?C.accent:C.border}`,
          }}>{d}</button>
        ))}
        <span style={{fontSize:11,color:C.green,marginLeft:"auto",fontFamily:C.mono}}>
          ✓ {totalSessions} sessions · {totalPapers} papers
        </span>
      </div>
      <div style={{flex:1,overflowY:"auto"}}>
        {(byDay[activeDay]||[]).map((block,bi) => {
          if (block.type==="session_block") {
            const sessions = block.sessions||[];
            return (
              <div key={bi} style={{marginBottom:5}}>
                <div style={{
                  display:"grid",
                  gridTemplateColumns:`68px ${"1fr ".repeat(sessions.length).trim()}`,
                  gap:3,
                }}>
                  <div style={{fontSize:10,fontWeight:700,color:C.muted,padding:"5px 4px",
                    textAlign:"center",background:C.panelAlt,borderRadius:3,lineHeight:1.4}}>
                    {block.start}<br/>{block.end}
                  </div>
                  {sessions.map(s => (
                    <div key={s.id} style={{
                      padding:"6px 8px",borderRadius:4,background:C.panel,
                      border:`1px solid ${C.border}`,borderLeft:`3px solid ${C.accent}`,
                    }}>
                      <div style={{fontSize:9,fontWeight:700,color:C.accent,
                        textTransform:"uppercase",letterSpacing:"0.05em"}}>
                        {s.id}{s.bpc?" ★":""}
                      </div>
                      <div style={{fontSize:11,fontWeight:600,color:C.text,lineHeight:1.3,marginTop:2}}>
                        {s.title}
                      </div>
                      <div style={{fontSize:10,color:C.muted,marginTop:2}}>
                        {s.room} · {s.kind==="tutorial"?"Tutorial":s.kind==="panel"?"Panel":s.kind==="special"?"Special Session":`${(s.papers||[]).length}p`}
                      </div>
                    </div>
                  ))}
                </div>
              </div>
            );
          }
          const breakTypes = new Set(["break","registration","lunch"]);
          const isBreak = breakTypes.has(block.type);
          const accent = {keynote:C.accentDim,ikeynote:"#5521b518",panel:"#9f123918",
            tutorial:"#d9770618",award:"#ca8a0418",social:"#0e749018"}[block.type];
          return (
            <div key={bi} style={{
              display:"grid",gridTemplateColumns:"68px 1fr",gap:3,marginBottom:3,
            }}>
              <div style={{fontSize:10,fontWeight:700,color:C.muted,padding:"4px",
                textAlign:"center",background:C.panelAlt,borderRadius:3}}>
                {block.start}<br/>{block.end}
              </div>
              <div style={{
                padding:"5px 10px",borderRadius:4,
                background:isBreak?C.panelAlt:(accent||C.panelAlt),
                border:`1px solid ${C.border}`,fontSize:12,
                color:isBreak?C.muted:C.textSoft,
                fontStyle:isBreak?"italic":"normal",fontWeight:isBreak?400:500,
              }}>
                {block.label||block.type}
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}

// ── System prompt for LLM ─────────────────────────────────────────────────────

function makeSystemPrompt(conf, accepted) {
  // Every accepted paper, one compact line each: ID|R(egular)/S(hort)|T:track|SS:special session|BPC|format|title|author surnames
  const paperLines = accepted.map(r => compactPaperLine(paperInfo(r))).join("\n");

  return `You are an experienced IEEE conference program chair assistant helping build a complete, publication-ready conference schedule.

CONFERENCE:
${conf.name ? `- Name: ${conf.name}` : ""}
${conf.location ? `- Location: ${conf.location}` : ""}
${conf.dates ? `- Dates: ${conf.dates}` : ""}
${conf.numDays ? `- Days: ${conf.numDays} (${(conf.days||[]).join(", ")})` : ""}
${conf.maxRooms ? `- Parallel rooms: ${conf.maxRooms} (${(conf.roomNames||[]).join(", ")})` : ""}
- Regular paper: ${conf.regularMins||25} min | Short paper: ${conf.shortMins||15} min
- Standard session block: 100 min (up to 4 regular papers, or mixed regular+short filling 100 min)

ACCEPTED PAPERS (${accepted.length} total). Format: ID|R=Regular,S=Short|T:track|SS:special session|BPC=best paper candidate|format|title|author surnames
${paperLines}

YOUR BEHAVIOUR:
- Converse naturally. Ask only what you genuinely need. When ready, output the JSON immediately.
- For refinements: apply the change and output the complete updated JSON.
- Keep text replies short (2-4 sentences). The JSON carries the schedule.
- CRITICAL: always output the JSON array on its own line, with no other text on the same line.

═══════════════════════════════════════════
OUTPUT FORMAT — copy exactly, no markdown fences
═══════════════════════════════════════════

For PLENARIES and BREAKS (full-width, single room):
{"day":1,"start":"09:00","end":"10:00","type":"keynote","label":"Keynote 1: Speaker Name — Talk Title"}
{"day":1,"start":"10:00","end":"10:20","type":"break","label":"Coffee Break + PhD Forum"}
{"day":1,"start":"12:00","end":"13:00","type":"lunch","label":"Lunch"}
{"day":2,"start":"19:00","end":"23:00","type":"social","label":"Social Dinner"}
{"day":3,"start":"12:00","end":"12:30","type":"award","label":"Award Ceremony & Closing"}

Valid types: keynote | ikeynote | panel | tutorial | award | social | break | registration | lunch | welcome

For PARALLEL SESSION BLOCKS (multiple rooms running simultaneously).
"papers" lists ONLY the paper IDs (titles/authors are filled in automatically — do not repeat them):
{"day":1,"start":"10:20","end":"12:00","type":"session_block","sessions":[
  {"id":"S1.A","room":"Room A","title":"AI Hardware & EDA","bpc":false,"kind":"paper","papers":[42,17,93,8]},
  {"id":"S1.B","room":"Room B","title":"Edge Computing","bpc":false,"kind":"paper","papers":[55,61,12]},
  {"id":"SS1","room":"Room C","title":"Special Session: Emerging IoT Security","bpc":false,"kind":"special","papers":[71,72,74]},
  {"id":"T1","room":"Room D","title":"Tutorial 1: Topic Name","bpc":false,"kind":"tutorial","papers":[]}
]}

KIND VALUES: "paper" | "special" | "tutorial" | "panel"

═══════════════════════════════════════════
SCHEDULING RULES
═══════════════════════════════════════════
1. ALL ${accepted.length} accepted paper IDs listed above must appear in exactly one session (no duplicates, no invented IDs).
2. Papers tagged SS: belong to a special session — keep them together in that special session.
3. Session IDs: S{slot}.{Room} for paper sessions (S1.A, S2.B…), SS1–SS6 for special sessions, T1/T2 for tutorials.
4. Special sessions numbered SS1–SS6 in chronological slot order.
5. Sort sessions A→B→C→D within each block.
6. Set bpc:true on a session if any paper in it is BPC. Spread BPC papers across different slots when possible.
7. Group regular papers thematically by topic/track. Give each session a concise 4-7 word title.
8. No author should present in two parallel rooms at the same time (except within one special session).
9. Authors of special session papers who also have a regular paper must not be in a parallel slot.
10. Tutorials use kind:"tutorial" and have empty papers:[].
11. Panels in a room use kind:"panel" and have empty papers:[].
12. Default day start: 08:30 registration, 09:00 first event — unless told otherwise.`;
}

// ── Typing indicator ──────────────────────────────────────────────────────────

function TypingDots() {
  return (
    <div style={{display:"flex",gap:4,alignItems:"center",padding:"2px 0"}}>
      {[0,1,2].map(i => (
        <div key={i} style={{
          width:7,height:7,borderRadius:"50%",background:C.accent,
          animation:`ppBounce 1s ease-in-out ${i*0.2}s infinite`,
        }}/>
      ))}
      <style>{`@keyframes ppBounce{0%,80%,100%{transform:scale(0.6);opacity:0.4}40%{transform:scale(1);opacity:1}}`}</style>
    </div>
  );
}

// ── Message bubble ────────────────────────────────────────────────────────────

// Remove the schedule JSON (fenced or bare array) from an assistant message
function stripScheduleJSON(text) {
  let t = text.replace(/```(?:json)?[\s\S]*?```/g, "");
  const start = t.search(/\[\s*\{/);
  if (start >= 0) {
    const end = t.lastIndexOf("]");
    t = end > start ? t.slice(0, start) + t.slice(end + 1) : t.slice(0, start);
  }
  return t.trim();
}

function Bubble({ msg }) {
  const isUser = msg.role === "user";
  // Strip JSON array from assistant messages for display
  let display = msg.content;
  if (!isUser) {
    display = stripScheduleJSON(display);
    if (msg.scheduleExtracted) display = (display || "Done.") + "\n\n✓ Schedule updated — see the preview →";
  }
  if (!display.trim()) return null;

  return (
    <div style={{
      alignSelf:isUser?"flex-end":"flex-start",
      maxWidth:"82%",
    }}>
      {!isUser && (
        <div style={{fontSize:10,fontWeight:700,color:C.accent,marginBottom:4,
          letterSpacing:"0.08em",textTransform:"uppercase"}}>
          AI Assistant
        </div>
      )}
      <div style={{
        padding:"10px 14px",
        borderRadius:isUser?"12px 12px 2px 12px":"12px 12px 12px 2px",
        background:isUser?C.accentDim:C.panelAlt,
        border:`1px solid ${isUser?C.accent+"40":C.border}`,
        fontSize:13,color:C.text,lineHeight:1.65,whiteSpace:"pre-wrap",
        fontFamily:C.sans,
      }}>
        {display}
      </div>
    </div>
  );
}

// ── Suggestion chips ──────────────────────────────────────────────────────────

function Chips({ chips, onSelect }) {
  return (
    <div style={{display:"flex",flexWrap:"wrap",gap:6,marginTop:8,marginBottom:4}}>
      {chips.map((c,i) => (
        <button key={i} onClick={()=>onSelect(c)} style={{
          padding:"6px 12px",borderRadius:16,fontSize:12,cursor:"pointer",
          background:"transparent",color:C.accentText,
          border:`1px solid ${C.accent+"60"}`,fontFamily:C.sans,
          transition:"all 0.15s",
        }}
        onMouseEnter={e=>{e.target.style.background=C.accentDim;}}
        onMouseLeave={e=>{e.target.style.background="transparent";}}>
          {c}
        </button>
      ))}
    </div>
  );
}

// ── Main module ───────────────────────────────────────────────────────────────

export function ProgramBuilderModule({ conf: globalConf, metaRows = [] }) {
  const accepted = metaRows.filter(r => {
    const d = (r.decision||r.Decision||r.Status||r.status||"").toString().trim();
    // "accept?" / "reject?" are tentative; POSTER, ORAL etc. are acceptance categories.
    if (d.endsWith("?")) return false;
    return /^(accept|accepted|poster|oral|short\s+paper|regular\s+paper|presentation)\b/i.test(d);
  });

  // Build initial conf from globalConf (already filled in Config tab)
  const [cfg, setCfg] = useState(() => ({
    name:        globalConf?.name || globalConf?.acronym || "",
    location:    [globalConf?.city, globalConf?.country].filter(Boolean).join(", "),
    dates:       globalConf?.dates || "",
    numDays:     globalConf?.conferenceDays?.length || 3,
    days:        globalConf?.conferenceDays?.length
                   ? globalConf.conferenceDays.map((d,i) => d.date || `Day ${i+1}`)
                   : ["Day 1","Day 2","Day 3"],
    maxRooms:    4,
    roomNames:   ["Room A","Room B","Room C","Room D"],
    regularMins: 25,
    shortMins:   15,
    color:       "#0a1f44",
  }));

  const [messages,  setMessages]  = useState([]);
  const [input,     setInput]     = useState("");
  const [sending,   setSending]   = useState(false);
  const [schedule,  setSchedule]  = useState(null);
  const [generated, setGenerated] = useState(null);
  const [started,   setStarted]   = useState(false);
  const [check,     setCheck]     = useState(null);   // { missing, duplicates, unknown }
  const guard      = useRunGuard();
  const chatEndRef = useRef();
  const inputRef   = useRef();

  useEffect(() => { chatEndRef.current?.scrollIntoView({behavior:"smooth"}); }, [messages, sending]);

  // Opening greeting from AI (fired once when user clicks Start)
  const startConversation = async () => {
    setStarted(true);
    setSending(true);
    const knownInfo = [];
    if (cfg.name)     knownInfo.push(`conference name is "${cfg.name}"`);
    if (cfg.location) knownInfo.push(`venue is ${cfg.location}`);
    if (cfg.dates)    knownInfo.push(`dates are ${cfg.dates}`);
    knownInfo.push(`${accepted.length} accepted papers loaded`);

    const greeting = `I can see ${knownInfo.join(", ")}. Before I build the program, I have a couple of quick questions:\n\n1. How many days and parallel rooms do you want? (e.g. "3 days, 4 rooms")\n2. Are there any keynote speakers, special sessions, or social events I should include?\n\nIf everything looks good as-is, just say "build it" and I'll get started.`;
    setMessages([{role:"assistant", content:greeting}]);
    setSending(false);
  };

  const send = async (userMsg) => {
    if (!userMsg.trim() || sending) return;
    const newMessages = [...messages, {role:"user", content:userMsg}];
    setMessages(newMessages);
    setInput("");
    setSending(true);
    inputRef.current?.focus();

    const system = makeSystemPrompt(cfg, accepted);
    // Only the most recent schedule JSON is kept in the history to save tokens
    const recent  = newMessages.slice(-12);
    const lastSch = recent.map(m => !!m.scheduleExtracted).lastIndexOf(true);
    const history = recent
      .map((m, i) => {
        const content = m.scheduleExtracted && i !== lastSch ? (stripScheduleJSON(m.content) || "Done.") + " [earlier schedule JSON omitted]" : m.content;
        return `${m.role==="user"?"Chair":"Assistant"}: ${content}`;
      }).join("\n\n");

    const signal = guard.start();
    try {
      const text = await callLLM(system, history, 16000, TASKS.program, { signal });
      if (guard.isCancelled()) { setSending(false); return; }
      const raw = extractSchedule(text);
      const hyd = raw?.length ? hydrateSchedule(raw, accepted) : null;
      const sched = hyd?.schedule;
      if (sched?.length) {
        setSchedule(sched);
        setCheck({ missing: hyd.missing, duplicates: hyd.duplicates, unknown: [...new Set(hyd.unknown)] });
        const notes = [];
        if (hyd.missing.length)    notes.push(`${hyd.missing.length} accepted paper(s) were not scheduled and are listed as "Unscheduled": ${hyd.missing.slice(0, 30).map(p => "#" + p.id).join(", ")}${hyd.missing.length > 30 ? ", …" : ""}.`);
        if (hyd.duplicates.length) notes.push(`${hyd.duplicates.length} duplicate placement(s) removed (kept first occurrence): ${hyd.duplicates.slice(0, 20).map(d => `#${d.id} (${d.first} & ${d.session})`).join(", ")}.`);
        if (hyd.unknown.length)    notes.push(`Ignored unknown paper ID(s): ${[...new Set(hyd.unknown)].slice(0, 20).join(", ")}.`);
        if (notes.length) {
          setMessages(p => [...p,
            {role:"assistant", content:text, scheduleExtracted:true},
            {role:"assistant", content:"⚠️ Schedule check: " + notes.join(" ") + " You can ask me to place the unscheduled papers."},
          ]);
          setSending(false);
          return;
        }
      } else if (text.includes("{") && text.includes("day")) {
        // LLM returned something JSON-like but we couldn't parse it
        setMessages(p => [...p,
          {role:"assistant", content:text, scheduleExtracted:false},
          {role:"assistant", content:"⚠️ I generated a schedule but couldn't parse the JSON. Please ask me to try again, or say \"output just the JSON array\" to get a clean version."},
        ]);
        setSending(false);
        return;
      }
      setMessages(p => [...p, {role:"assistant", content:text, scheduleExtracted:!!sched?.length}]);
    } catch(e) {
      if (isAbortError(e) || guard.isCancelled()) setMessages(p => [...p, {role:"assistant", content:"Stopped."}]);
      else setMessages(p => [...p, {role:"assistant", content:`Something went wrong: ${e.message}. Try again.`}]);
    }
    setSending(false);
  };

  const downloadHTML = () => {
    const html = generateHTML(schedule, cfg, check?.missing || []);
    const blob = new Blob([html], {type:"text/html;charset=utf-8"});
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = `${(cfg.name||"program").replace(/\s+/g,"-").toLowerCase()}.html`;
    a.click();
  };

  const previewHTML = () => setGenerated(generateHTML(schedule, cfg, check?.missing || []));

  // ── No papers loaded ──────────────────────────────────────────────────────
  if (!metaRows.length) return (
    <EmptyState icon="📅" title="No submissions loaded"
      body="Load your submissions file in the Data tab first." />
  );
  if (!accepted.length) return (
    <EmptyState icon="📅" title="No accepted papers"
      body="The submissions file needs a Decision column with Accept/Reject values." />
  );

  // ── HTML preview ──────────────────────────────────────────────────────────
  if (generated) return (
    <div>
      <div style={{display:"flex",alignItems:"center",gap:10,marginBottom:14}}>
        <GhostButton onClick={()=>setGenerated(null)}>← Back</GhostButton>
        <PrimaryButton onClick={downloadHTML}>↓ Download HTML</PrimaryButton>
        <span style={{fontSize:11,color:C.muted}}>
          Sandboxed preview — the downloaded file is a standalone page
        </span>
      </div>
      <div style={{border:`1px solid ${C.border}`,borderRadius:8,overflow:"hidden",background:"#fff"}}>
        <iframe srcDoc={generated} sandbox="allow-scripts" style={{width:"100%",height:580,border:"none"}} title="Program preview"/>
      </div>
    </div>
  );

  // ── Landing screen ────────────────────────────────────────────────────────
  if (!started) return (
    <div style={{
      display:"flex",flexDirection:"column",alignItems:"center",
      justifyContent:"center",height:"calc(100vh - 180px)",gap:0,
    }}>
      <div style={{fontSize:32,marginBottom:16}}>📅</div>
      <div style={{fontSize:18,fontWeight:700,color:C.text,marginBottom:8,fontFamily:C.sans}}>
        Program Builder
      </div>
      <div style={{fontSize:13,color:C.muted,marginBottom:6,textAlign:"center",maxWidth:420,lineHeight:1.6}}>
        Tell me about your conference and I'll automatically group your papers into sessions, build the full schedule, and generate a publish-ready HTML program.
      </div>
      <div style={{
        display:"flex",gap:20,marginBottom:28,padding:"12px 20px",
        background:C.panelAlt,borderRadius:8,border:`1px solid ${C.border}`,
      }}>
        <div style={{textAlign:"center"}}>
          <div style={{fontSize:20,fontWeight:700,color:C.accent,fontFamily:C.mono}}>{accepted.length}</div>
          <div style={{fontSize:11,color:C.muted}}>accepted papers</div>
        </div>
        {cfg.name && (
          <div style={{textAlign:"center"}}>
            <div style={{fontSize:13,fontWeight:700,color:C.textSoft}}>{cfg.name}</div>
            <div style={{fontSize:11,color:C.muted}}>{cfg.location||"venue TBD"}</div>
          </div>
        )}
      </div>
      <PrimaryButton onClick={startConversation}>
        Start building →
      </PrimaryButton>
    </div>
  );

  // ── Main layout: chat + preview ───────────────────────────────────────────
  return (
    <div style={{display:"flex",gap:12,height:"calc(100vh - 140px)",minHeight:500}}>

      {/* Chat panel */}
      <div style={{
        width:380,flexShrink:0,display:"flex",flexDirection:"column",
        border:`1px solid ${C.border}`,borderRadius:10,overflow:"hidden",
        background:C.panel,
      }}>
        {/* Header */}
        <div style={{
          padding:"10px 14px",borderBottom:`1px solid ${C.border}`,
          flexShrink:0,display:"flex",alignItems:"center",gap:8,
        }}>
          <div style={{
            width:8,height:8,borderRadius:"50%",
            background:sending?C.amber:C.green,
            boxShadow:`0 0 6px ${sending?C.amber:C.green}`,
            transition:"background 0.3s",
          }}/>
          <div style={{fontSize:12,fontWeight:600,color:C.text}}>
            {sending ? "Building schedule…" : "AI Program Assistant"}
          </div>
          <div style={{marginLeft:"auto",display:"flex",gap:6}}>
            {sending && <GhostButton small onClick={guard.stop}>■ Stop</GhostButton>}
            {schedule && <GhostButton small onClick={previewHTML}>Preview</GhostButton>}
            {schedule && <PrimaryButton onClick={downloadHTML}>↓ HTML</PrimaryButton>}
          </div>
        </div>

        {/* Messages */}
        <div style={{
          flex:1,overflowY:"auto",padding:"14px 14px 8px",
          display:"flex",flexDirection:"column",gap:12,
        }}>
          {messages.map((m,i) => <Bubble key={i} msg={m} />)}
          {sending && (
            <div style={{alignSelf:"flex-start"}}>
              <div style={{fontSize:10,fontWeight:700,color:C.accent,marginBottom:4,
                letterSpacing:"0.08em",textTransform:"uppercase"}}>AI Assistant</div>
              <div style={{
                padding:"10px 14px",borderRadius:"12px 12px 12px 2px",
                background:C.panelAlt,border:`1px solid ${C.border}`,
              }}>
                <TypingDots/>
              </div>
            </div>
          )}

          {/* Suggestion chips — shown after first AI message if no schedule yet */}
          {messages.length === 1 && !schedule && !sending && (
            <Chips
              chips={[
                "3 days, 4 rooms — build it",
                "2 days, 3 rooms, start at 9am",
                "Add a keynote on day 1 morning",
              ]}
              onSelect={send}
            />
          )}

          {/* Post-schedule chips */}
          {schedule && !sending && (
            <Chips
              chips={[
                "Move all Short papers to the last slot",
                "Add a coffee break at 15:30 on every day",
                "Rename session S1.A",
              ]}
              onSelect={send}
            />
          )}

          <div ref={chatEndRef}/>
        </div>

        {/* Input */}
        <div style={{
          padding:"10px 12px",borderTop:`1px solid ${C.border}`,
          flexShrink:0,display:"flex",gap:8,alignItems:"flex-end",
        }}>
          <textarea
            ref={inputRef}
            value={input}
            onChange={e => setInput(e.target.value)}
            onKeyDown={e => {
              if (e.key==="Enter" && !e.shiftKey) { e.preventDefault(); send(input); }
            }}
            placeholder={schedule
              ? "Ask for any change…"
              : "e.g. '3 days, 4 rooms, keynote each morning'"}
            style={{
              ...IS(), flex:1, height:52, resize:"none",
              fontSize:13, lineHeight:1.5, borderRadius:8,
            }}
            disabled={sending}
          />
          <PrimaryButton
            onClick={() => send(input)}
            disabled={sending || !input.trim()}
            style={{height:52,paddingLeft:18,paddingRight:18}}
          >
            {sending ? "…" : "Send"}
          </PrimaryButton>
        </div>
      </div>

      {/* Schedule preview panel */}
      <div style={{
        flex:1,display:"flex",flexDirection:"column",
        border:`1px solid ${C.border}`,borderRadius:10,
        padding:"14px 14px",overflow:"hidden",background:C.panel,
      }}>
        {!schedule ? (
          <div style={{
            flex:1,display:"flex",flexDirection:"column",
            alignItems:"center",justifyContent:"center",
            color:C.muted,gap:10,
          }}>
            <div style={{fontSize:28,opacity:0.4}}>📋</div>
            <div style={{fontSize:13}}>Schedule preview will appear here</div>
            <div style={{fontSize:11,maxWidth:260,textAlign:"center",lineHeight:1.6}}>
              Once the AI generates a program, you'll see a live preview and can keep refining it through the chat.
            </div>
          </div>
        ) : (
          <>
            {check && (check.missing.length > 0 || check.duplicates.length > 0) && (
              <InfoBanner type="warning">
                {check.missing.length > 0 && <div><strong>Unscheduled ({check.missing.length}):</strong> {check.missing.map(p => `#${p.id} ${p.title.slice(0, 40)}`).join(" · ")}</div>}
                {check.duplicates.length > 0 && <div><strong>Duplicates removed ({check.duplicates.length}):</strong> {check.duplicates.map(d => `#${d.id}`).join(", ")}</div>}
              </InfoBanner>
            )}
            <SchedulePreview schedule={schedule} conf={cfg}/>
          </>
        )}
      </div>

    </div>
  );
}
