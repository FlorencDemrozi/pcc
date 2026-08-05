import { useState, useRef, useEffect } from "react";
import { C, IS } from "../utils/theme.js";
import { PrimaryButton, GhostButton, EmptyState } from "../components/ui.jsx";
import { callLLM } from "../utils/api.js";

// ── CSS / JS templates (identical to proven COINS structure) ──────────────────

const PROG_CSS = (pc) => `<style>
.pp *{box-sizing:border-box;}
.pp{font-family:Arial,sans-serif;font-size:14px;color:#222;max-width:1200px;margin:0 auto;padding:10px 0;}
.pp h2{font-size:22px;font-weight:700;color:${pc};margin:0 0 6px;}
.pp-tabs{display:flex;gap:6px;margin-bottom:16px;flex-wrap:wrap;}
.pp-tab{padding:8px 20px;border-radius:4px;cursor:pointer;background:#e8edf5;color:${pc};font-size:13px;font-weight:700;border:2px solid transparent;transition:.2s;}
.pp-tab.active{background:${pc};color:#fff;}
.pp-day{display:none;}.pp-day.active{display:block;}
.pp-row{display:grid;gap:4px;margin-bottom:3px;align-items:stretch;}
.pp-r2{grid-template-columns:90px 1fr;}
.pp-r3{grid-template-columns:90px 1fr 1fr;}
.pp-r4{grid-template-columns:90px 1fr 1fr 1fr;}
.pp-r5{grid-template-columns:90px 1fr 1fr 1fr 1fr;}
.pp-r6{grid-template-columns:90px 1fr 1fr 1fr 1fr 1fr;}
.pp-cell{padding:7px 10px;border-radius:4px;font-size:12px;min-height:36px;display:flex;flex-direction:column;justify-content:center;}
.pp-full{grid-column:2/-1;}
.pp-time{background:#f0f2f6;color:#555;font-weight:700;font-size:10px;text-align:center;border:1px solid #dde;}
.pp-hdr{background:${pc};color:#fff;font-weight:700;font-size:11px;text-align:center;}
.pp-break{background:#f5f5f5;color:#888;text-align:center;font-style:italic;}
.pp-keynote{background:#e8f0fc;border-left:4px solid ${pc};}
.pp-ikeynote{background:#ede9f8;border-left:4px solid #5521b5;}
.pp-panel{background:#fce8f3;border-left:4px solid #9f1239;}
.pp-tutorial{background:#fef3c7;border-left:4px solid #d97706;}
.pp-ss{background:#fce4ec;border-left:3px solid #c2185b;}
.pp-award{background:#fefce8;border-left:4px solid #ca8a04;text-align:center;font-weight:700;}
.pp-social{background:#e0f2fe;border-left:4px solid #0e7490;}
.pp-paper{background:#fff;border:1px solid #dde;border-left:4px solid ${pc};cursor:pointer;transition:.15s;}
.pp-paper:hover{background:#f0f4ff;}
.pp-ev-name{font-weight:700;font-size:12px;line-height:1.3;}
.pp-ev-sub{font-size:10px;color:#666;margin-top:2px;}
.pp-slot-lbl{font-size:9px;font-weight:800;text-transform:uppercase;letter-spacing:.5px;color:${pc};margin-bottom:2px;}
.pp-slot-ttl{font-size:12px;font-weight:700;color:${pc};line-height:1.3;}
.pp-slot-meta{font-size:10px;color:#777;margin-top:2px;}
.pp-legend{display:flex;flex-wrap:wrap;gap:6px;margin-bottom:14px;}
.pp-legend-item{display:flex;align-items:center;gap:4px;font-size:11px;color:#444;background:#f5f7fa;border-radius:4px;padding:3px 8px;}
.pp-legend-dot{width:10px;height:10px;border-radius:2px;flex-shrink:0;}
.pp-sw{margin-bottom:16px;}
.pp-sb{width:100%;max-width:500px;padding:9px 14px;border:2px solid #dde;border-radius:6px;font-size:13px;outline:none;}
.pp-sr{margin-top:8px;}
.pp-mbg{display:none;position:fixed;top:0;left:0;width:100%;height:100%;background:rgba(0,0,0,.5);z-index:9999;align-items:center;justify-content:center;}
.pp-mbg.open{display:flex;}
.pp-m{background:#fff;border-radius:8px;max-width:700px;width:90%;max-height:85vh;overflow-y:auto;}
.pp-mh{background:${pc};color:#fff;padding:16px 20px;border-radius:8px 8px 0 0;display:flex;justify-content:space-between;align-items:flex-start;}
.pp-mh h3{font-size:15px;font-weight:700;margin:0;flex:1;}
.pp-mc{background:none;border:none;color:#fff;font-size:22px;cursor:pointer;line-height:1;}
.pp-mb{padding:16px 20px;}
@media(max-width:650px){.pp-r3,.pp-r4,.pp-r5,.pp-r6{grid-template-columns:70px 1fr;}.pp-hdr:not(:first-child){display:none;}.pp-paper,.pp-ss,.pp-tutorial,.pp-panel{grid-column:2/-1 !important;}}
</style>`;

const PROG_JS = (pc, data) => `<script>
var D=${JSON.stringify(data)};
function ppDay(id,btn){document.querySelectorAll('.pp-day').forEach(d=>d.classList.remove('active'));document.querySelectorAll('.pp-tab').forEach(b=>b.classList.remove('active'));document.getElementById('pp-'+id).classList.add('active');btn.classList.add('active');}
function ppShow(sid){var s=D[sid];if(!s)return;document.getElementById('pp-mt').textContent=s.title;var b='<div style="font-size:12px;color:#666;margin-bottom:14px">'+s.time+(s.room?' &middot; '+s.room:'')+'</div>';(s.papers||[]).forEach(function(p){b+='<div style="padding:10px 12px;margin-bottom:8px;border-radius:6px;border-left:4px solid ${pc};background:#f8f9fc"><div style="font-size:10px;color:#888;font-family:monospace">#'+p.id+'</div><div style="font-size:13px;font-weight:700;color:${pc};margin:3px 0">'+p.title+'</div><div style="font-size:11px;color:#555;font-style:italic">'+p.authors+'</div><div style="margin-top:5px;display:flex;gap:5px;flex-wrap:wrap">';if(p.dec==='Short')b+='<span style="background:#fef3c7;color:#92400e;padding:2px 8px;border-radius:8px;font-size:10px;font-weight:700">Short</span>';else b+='<span style="background:#dcfce7;color:#166534;padding:2px 8px;border-radius:8px;font-size:10px;font-weight:700">Regular</span>';if(p.fmt)b+='<span style="background:#dbeafe;color:#1e40af;padding:2px 8px;border-radius:8px;font-size:10px;font-weight:700">'+p.fmt+'</span>';if(p.bpc)b+='<span style="background:#fef3c7;color:#92400e;padding:2px 8px;border-radius:8px;font-size:10px;font-weight:700;border:1px solid #d97706">&#9733; BPC</span>';b+='</div></div>';});document.getElementById('pp-mb').innerHTML=b;document.getElementById('pp-mbg').classList.add('open');}
function ppClose(e){if(!e||e.target===document.getElementById('pp-mbg'))document.getElementById('pp-mbg').classList.remove('open');}
function ppSearch(q){var res=document.getElementById('pp-sr');var list=document.getElementById('pp-sl');if(!q||q.length<2){res.style.display='none';return;}var ql=q.toLowerCase();var found=[];Object.entries(D).forEach(function(e){var sid=e[0],s=e[1];(s.papers||[]).forEach(function(p){if((p.title||'').toLowerCase().includes(ql)||(p.authors||'').toLowerCase().includes(ql)||String(p.id).includes(ql))found.push({sid:sid,session:s.title,p:p});});});if(!found.length){list.innerHTML='<div style="font-size:13px;color:#888;padding:8px 0">No results</div>';}else{list.innerHTML=found.slice(0,20).map(function(f){return '<div onclick="ppShow(\''+f.sid+'\')" style="padding:10px 12px;margin-bottom:6px;border-radius:6px;border-left:4px solid ${pc};background:#f8f9fc;cursor:pointer"><div style="font-size:10px;color:#888;font-family:monospace">#'+f.p.id+' &middot; '+f.session+'</div><div style="font-size:13px;font-weight:700;color:${pc}">'+f.p.title+'</div><div style="font-size:11px;color:#555;font-style:italic">'+f.p.authors+'</div></div>';}).join('');}res.style.display='block';}
<\/script>`;

// ── HTML generator ────────────────────────────────────────────────────────────
// Schedule JSON schema — what the LLM must produce:
//
// Plenary/break block:
//   { day:1, start:"09:00", end:"10:00",
//     type: "keynote"|"ikeynote"|"panel"|"tutorial"|"award"|"social"|"break"|"registration"|"lunch",
//     label:"Keynote 1: Speaker — Title" }
//
// Parallel session block:
//   { day:1, start:"10:20", end:"12:00", type:"session_block",
//     sessions:[
//       { id:"S1.A", room:"Room A", title:"AI Hardware", bpc:false,
//         papers:[{ id:42, title:"...", authors:"...", dec:"Regular", fmt:"In-Person", bpc:false }] }
//     ] }

function generateHTML(schedule, cfg) {
  const pc  = cfg.color  || "#0a1f44";
  const esc = s => String(s||"").replace(/&/g,"&amp;").replace(/</g,"&lt;").replace(/>/g,"&gt;").replace(/"/g,"&quot;");

  const numDays = Math.max(...schedule.map(b => b.day || 1));
  const days    = cfg.days || Array.from({length:numDays}, (_,i) => `Day ${i+1}`);

  // Sort each day by start time
  const byDay = {};
  for (let d=1; d<=numDays; d++) byDay[d] = [];
  schedule.forEach(b => { const d=b.day||1; if(!byDay[d]) byDay[d]=[]; byDay[d].push(b); });
  Object.values(byDay).forEach(arr => arr.sort((a,b) => (a.start||"").localeCompare(b.start||"")));

  // Modal data — all session blocks
  const modalData = {};
  schedule.forEach(block => {
    if (block.type !== "session_block") return;
    (block.sessions||[]).forEach(s => {
      modalData[s.id] = { title:s.title, time:`${block.start}–${block.end}`, room:s.room, papers:s.papers||[] };
    });
  });

  const typeClass = {
    keynote:"pp-keynote", ikeynote:"pp-ikeynote", panel:"pp-panel",
    tutorial:"pp-tutorial", award:"pp-award", social:"pp-social",
  };
  const breakTypes = new Set(["break","registration","lunch"]);

  const renderBlock = b => {
    if (b.type === "session_block") {
      const n   = (b.sessions||[]).length;
      const gc  = `pp-r${Math.min(n+1, 6)}`;
      const hdrs = (b.sessions||[]).map(s =>
        `<div class="pp-cell pp-hdr">${esc(s.room)}</div>`).join("");
      const cells = (b.sessions||[]).map(s => {
        const bpcFlag = s.bpc ? ` <span style="color:#d97706;font-size:9px">&#9733;</span>` : "";
        const np = (s.papers||[]).length;
        const kindCls = s.kind==="special"?"pp-ss":s.kind==="tutorial"?"pp-tutorial":s.kind==="panel"?"pp-panel":"pp-paper";
        const clickable = (s.kind==="paper"||s.kind==="special") && np > 0;
        return `<div class="pp-cell ${kindCls}"${clickable?` onclick="ppShow('${esc(s.id)}')" style="cursor:pointer"`:""}>
        <div class="pp-slot-lbl">${esc(s.id)}${bpcFlag}</div>
        <div class="pp-slot-ttl">${esc(s.title)}</div>
        <div class="pp-slot-meta">${s.kind==="tutorial"||s.kind==="panel"?s.kind.charAt(0).toUpperCase()+s.kind.slice(1):`${np} paper${np!==1?"s":""}`}</div>
      </div>`;
      }).join("");
      return `<div class="pp-row ${gc}">
    <div class="pp-cell pp-time">${esc(b.start)}–${esc(b.end)}</div>${hdrs}
  </div>
  <div class="pp-row ${gc}">
    <div class="pp-cell pp-time"></div>${cells}
  </div>`;
    }
    if (breakTypes.has(b.type)) {
      return `<div class="pp-row pp-r2">
    <div class="pp-cell pp-time">${esc(b.start)}–${esc(b.end)}</div>
    <div class="pp-cell pp-break pp-full">${esc(b.label||b.type)}</div>
  </div>`;
    }
    const cls = typeClass[b.type] || "pp-keynote";
    return `<div class="pp-row pp-r2">
    <div class="pp-cell pp-time">${esc(b.start)}–${esc(b.end)}</div>
    <div class="pp-cell ${cls} pp-full">
      <div class="pp-ev-name">${esc(b.label||"")}</div>
    </div>
  </div>`;
  };

  const tabs   = days.map((d,i) =>
    `<button class="pp-tab${i===0?" active":""}" onclick="ppDay('d${i}',this)">${esc(d)}</button>`).join("\n    ");
  const panels = days.map((d,di) =>
    `<div id="pp-d${di}" class="pp-day${di===0?" active":""}">
  ${(byDay[di+1]||[]).map(renderBlock).join("\n  ")}
</div>`).join("\n\n");

  const sub = [cfg.location, `Regular: ${cfg.regularMins||25}′`, `Short: ${cfg.shortMins||15}′`].filter(Boolean).join(" · ");

  return `${PROG_CSS(pc)}
<div class="pp">
  <h2>${esc(cfg.name||"Conference")} — Technical Programme</h2>
  <p style="font-size:13px;color:#666;margin-bottom:20px">${esc(sub)}</p>
  <div class="pp-sw">
    <input class="pp-sb" id="pp-s" type="text" placeholder="Search by title, author, or paper ID…" oninput="ppSearch(this.value)" autocomplete="off">
    <div class="pp-sr" id="pp-sr"><div id="pp-sl"></div></div>
  </div>
  <div class="pp-legend">
    <div class="pp-legend-item"><div class="pp-legend-dot" style="background:${pc}"></div>Keynote</div>
    <div class="pp-legend-item"><div class="pp-legend-dot" style="background:#5521b5"></div>Ind. Keynote</div>
    <div class="pp-legend-item"><div class="pp-legend-dot" style="background:${pc}"></div>Paper Session</div>
    <div class="pp-legend-item"><div class="pp-legend-dot" style="background:#c2185b"></div>Special Session</div>
    <div class="pp-legend-item"><div class="pp-legend-dot" style="background:#d97706"></div>Tutorial</div>
    <div class="pp-legend-item"><div class="pp-legend-dot" style="background:#9f1239"></div>Panel</div>
  </div>
  <div class="pp-tabs">${tabs}</div>
  ${panels}
</div>
<div id="pp-mbg" class="pp-mbg" onclick="ppClose(event)">
  <div class="pp-m">
    <div class="pp-mh"><h3 id="pp-mt"></h3><button class="pp-mc" onclick="ppClose()">&#215;</button></div>
    <div class="pp-mb" id="pp-mb"></div>
  </div>
</div>
${PROG_JS(pc, modalData)}`;
}

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
  const paperLines = accepted.slice(0, 250).map(r => {
    const id      = r["#"] || r.id || r.paper_id || "?";
    const title   = (r.title  || r.Title   || "").slice(0, 90);
    const authors = (r.authors|| r.Authors || "").slice(0, 60);
    const dec     = (r.decision||r.Decision||"").toUpperCase().includes("SHORT") ? "Short" : "Regular";
    const track   = r.track || r.Track || "";
    const fmt     = r.format || r.Format || r.presentation || "In-Person";
    const bpc     = (r.bpc || r.BPC || "").toString().toLowerCase() === "true";
    const ss      = r.special_session || r["Special Session"] || r.ss || "";
    return `#${id} [${dec}${track?" T:"+track:""}${ss?" SS:"+ss:""}${bpc?" BPC":""}] ${title} / ${authors} / ${fmt}`;
  }).join("\n");

  return `You are an experienced IEEE conference program chair assistant helping build a complete, publication-ready conference schedule.

CONFERENCE:
${conf.name ? `- Name: ${conf.name}` : ""}
${conf.location ? `- Location: ${conf.location}` : ""}
${conf.dates ? `- Dates: ${conf.dates}` : ""}
${conf.numDays ? `- Days: ${conf.numDays} (${(conf.days||[]).join(", ")})` : ""}
${conf.maxRooms ? `- Parallel rooms: ${conf.maxRooms} (${(conf.roomNames||[]).join(", ")})` : ""}
- Regular paper: ${conf.regularMins||25} min | Short paper: ${conf.shortMins||15} min
- Standard session block: 100 min (up to 4 regular papers, or mixed regular+short filling 100 min)

ACCEPTED PAPERS (${accepted.length} total):
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

For PARALLEL SESSION BLOCKS (multiple rooms running simultaneously):
{"day":1,"start":"10:20","end":"12:00","type":"session_block","sessions":[
  {"id":"S1.A","room":"Room A","title":"AI Hardware & EDA","bpc":false,"kind":"paper",
   "papers":[{"id":42,"title":"Full paper title","authors":"A. Smith, B. Jones","dec":"Regular","fmt":"In-Person","bpc":false}]},
  {"id":"S1.B","room":"Room B","title":"Edge Computing","bpc":false,"kind":"paper",
   "papers":[{"id":55,"title":"...","authors":"...","dec":"Short","fmt":"Online","bpc":false}]},
  {"id":"SS1","room":"Room C","title":"Special Session: Emerging IoT Security","bpc":false,"kind":"special",
   "papers":[{"id":71,"title":"...","authors":"...","dec":"Regular","fmt":"In-Person","bpc":false}]},
  {"id":"T1","room":"Room D","title":"Tutorial 1: Topic Name","bpc":false,"kind":"tutorial","papers":[]}
]}

KIND VALUES: "paper" | "special" | "tutorial" | "panel"

═══════════════════════════════════════════
SCHEDULING RULES
═══════════════════════════════════════════
1. ALL ${accepted.length} accepted papers must appear in exactly one session.
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

function Bubble({ msg }) {
  const isUser = msg.role === "user";
  // Strip JSON array from assistant messages for display
  let display = msg.content;
  if (!isUser) {
    display = display.replace(/\[\s*\{[\s\S]*?\}\s*\]/g, "").trim();
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
    const d = (r.decision||r.Decision||r.Status||r.status||"").toString().toUpperCase();
    return d.includes("ACCEPT");
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
    const history = newMessages.slice(-12)
      .map(m => `${m.role==="user"?"Chair":"Assistant"}: ${m.content}`).join("\n\n");

    try {
      const text = await callLLM(system, history, 4000, "program");
      const sched = extractSchedule(text);
      if (sched?.length) {
        setSchedule(sched);
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
      setMessages(p => [...p, {role:"assistant", content:`Something went wrong: ${e.message}. Try again.`}]);
    }
    setSending(false);
  };

  const downloadHTML = () => {
    const html = generateHTML(schedule, cfg);
    const blob = new Blob([html], {type:"text/html"});
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = `${(cfg.name||"program").replace(/\s+/g,"-").toLowerCase()}.html`;
    a.click();
  };

  const previewHTML = () => setGenerated(generateHTML(schedule, cfg));

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
          Full search and popups work after download
        </span>
      </div>
      <div style={{border:`1px solid ${C.border}`,borderRadius:8,overflow:"hidden",background:"#fff"}}>
        <iframe srcDoc={generated} style={{width:"100%",height:580,border:"none"}} title="Program preview"/>
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
          <SchedulePreview schedule={schedule} conf={cfg}/>
        )}
      </div>

    </div>
  );
}
