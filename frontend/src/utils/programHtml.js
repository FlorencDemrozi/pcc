// ── Program Builder: schedule hydration + standalone HTML export ──────────────
// Pure functions (no React / DOM) so they can be unit-tested in node.
//
// Security model for the exported HTML: every value that comes from submissions
// metadata, the conference config or the LLM is untrusted.
//  * Static markup: all interpolations go through escapeHtml().
//  * Embedded data: serialised with safeJSONForScript() so "</script>", "<!--",
//    U+2028/2029 etc. can never terminate or break the <script> block.
//  * Runtime JS builds the modal / search results with DOM APIs (textContent),
//    never innerHTML, and uses data-* attributes + addEventListener instead of
//    inline onclick handlers.
//  * The theme colour is validated as a hex colour before it reaches CSS.

const ID_KEYS = ["#", "id", "paper_id", "submission_id", "Id", "ID"];

function field(row, ...keys) {
  for (const k of keys) {
    const v = row[k] ?? row[k.toLowerCase()] ?? row[k.toUpperCase()];
    if (v !== undefined && v !== null && String(v).trim() !== "") return String(v).trim();
  }
  return "";
}

export function escapeHtml(v) {
  return String(v ?? "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#39;");
}

export function safeJSONForScript(data) {
  return JSON.stringify(data)
    .replace(/</g, "\\u003c")
    .replace(/>/g, "\\u003e")
    .replace(/&/g, "\\u0026")
    .replace(/\u2028/g, "\\u2028")
    .replace(/\u2029/g, "\\u2029");
}

export function safeColor(c, fallback = "#0a1f44") {
  return /^#[0-9a-fA-F]{3,8}$/.test(String(c || "")) ? c : fallback;
}

// ── Paper metadata ────────────────────────────────────────────────────────────

export function paperInfo(r) {
  const id = field(r, ...ID_KEYS);
  return {
    id,
    title:   field(r, "title", "Title"),
    authors: field(r, "authors", "Authors"),
    dec:     field(r, "decision", "Decision", "status", "Status").toUpperCase().includes("SHORT") ? "Short" : "Regular",
    fmt:     field(r, "format", "Format", "presentation") || "In-Person",
    track:   field(r, "track", "Track"),
    ss:      field(r, "special_session", "Special Session", "ss"),
    bpc:     field(r, "bpc", "BPC").toLowerCase() === "true",
  };
}

function surnames(authors, max = 6) {
  const parts = String(authors || "").split(/\s*(?:,|;|\band\b)\s*/i).map(a => a.trim()).filter(Boolean);
  const names = parts.slice(0, max).map(a => a.split(/\s+/).pop());
  return names.join(", ") + (parts.length > max ? ", …" : "");
}

// One compact line per accepted paper for the LLM prompt
export function compactPaperLine(p) {
  const tags = [p.dec === "Short" ? "S" : "R"];
  if (p.track) tags.push("T:" + p.track.slice(0, 40));
  if (p.ss)    tags.push("SS:" + p.ss.slice(0, 40));
  if (p.bpc)   tags.push("BPC");
  if (p.fmt && !/in.?person/i.test(p.fmt)) tags.push(p.fmt.slice(0, 20));
  return `${p.id}|${tags.join("|")}|${p.title.slice(0, 70)}|${surnames(p.authors)}`;
}

// ── Hydrate + validate an LLM schedule ───────────────────────────────────────
// The LLM returns sessions with paper IDs only; details are filled client-side.
// Every accepted paper must appear exactly once: duplicates keep the first
// occurrence, unknown IDs are dropped, and missing papers are returned so the UI
// can list them as "Unscheduled".
export function hydrateSchedule(raw, acceptedRows) {
  const byId = new Map();
  for (const r of acceptedRows) {
    const p = paperInfo(r);
    if (p.id && !byId.has(p.id)) byId.set(p.id, p);
  }
  const seen = new Map();
  const duplicates = [];
  const unknown = [];

  const schedule = (Array.isArray(raw) ? raw : [])
    .filter(b => b && typeof b === "object")
    .map(b => {
      if (b.type !== "session_block") return b;
      const sessions = (Array.isArray(b.sessions) ? b.sessions : [])
        .filter(s => s && typeof s === "object")
        .map(s => {
          const papers = [];
          for (const p of Array.isArray(s.papers) ? s.papers : []) {
            const id = String(p && typeof p === "object" ? (p.id ?? "") : (p ?? "")).replace(/^#/, "").trim();
            if (!id) continue;
            if (!byId.has(id)) { unknown.push(id); continue; }
            if (seen.has(id)) { duplicates.push({ id, session: String(s.id ?? ""), first: seen.get(id) }); continue; }
            seen.set(id, String(s.id ?? ""));
            papers.push({ ...byId.get(id) });
          }
          return { ...s, papers };
        });
      return { ...b, sessions };
    });

  const missing = [...byId.values()].filter(p => !seen.has(p.id));
  return { schedule, missing, duplicates, unknown };
}

// ── CSS ───────────────────────────────────────────────────────────────────────

const PROG_CSS = pc => `<style>
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
.pp-sr{margin-top:8px;display:none;}
.pp-unsched{margin-top:24px;}
.pp-unsched h3{font-size:15px;color:#9f1239;margin:0 0 8px;}
.pp-mbg{display:none;position:fixed;top:0;left:0;width:100%;height:100%;background:rgba(0,0,0,.5);z-index:9999;align-items:center;justify-content:center;}
.pp-mbg.open{display:flex;}
.pp-m{background:#fff;border-radius:8px;max-width:700px;width:90%;max-height:85vh;overflow-y:auto;}
.pp-mh{background:${pc};color:#fff;padding:16px 20px;border-radius:8px 8px 0 0;display:flex;justify-content:space-between;align-items:flex-start;}
.pp-mh h3{font-size:15px;font-weight:700;margin:0;flex:1;}
.pp-mc{background:none;border:none;color:#fff;font-size:22px;cursor:pointer;line-height:1;}
.pp-mb{padding:16px 20px;}
@media(max-width:650px){.pp-r3,.pp-r4,.pp-r5,.pp-r6{grid-template-columns:70px 1fr;}.pp-hdr:not(:first-child){display:none;}.pp-paper,.pp-ss,.pp-tutorial,.pp-panel{grid-column:2/-1 !important;}}
</style>`;

// ── Runtime JS (static text; data enters only via safeJSONForScript) ─────────

const PROG_RUNTIME = `(function(){
var D=PP_DATA.sessions,PC=PP_DATA.pc;
function $(id){return document.getElementById(id);}
function el(tag,css,text){var e=document.createElement(tag);if(css)e.style.cssText=css;if(text!=null)e.textContent=String(text);return e;}
function badge(text,css){return el('span','padding:2px 8px;border-radius:8px;font-size:10px;font-weight:700;'+css,text);}
function paperCard(p,sub,idx){
  var c=el('div','padding:10px 12px;margin-bottom:8px;border-radius:6px;border-left:4px solid '+PC+';background:#f8f9fc'+(idx!=null?';cursor:pointer':''));
  if(idx!=null)c.setAttribute('data-pp-s',String(idx));
  c.appendChild(el('div','font-size:10px;color:#888;font-family:monospace','#'+p.id+(sub?' \\u00b7 '+sub:'')));
  c.appendChild(el('div','font-size:13px;font-weight:700;color:'+PC+';margin:3px 0',p.title||''));
  c.appendChild(el('div','font-size:11px;color:#555;font-style:italic',p.authors||''));
  return c;
}
function show(i){
  var s=D[i];if(!s)return;
  $('pp-mt').textContent=s.title||'';
  var b=$('pp-mb');b.textContent='';
  b.appendChild(el('div','font-size:12px;color:#666;margin-bottom:14px',(s.time||'')+(s.room?' \\u00b7 '+s.room:'')));
  (s.papers||[]).forEach(function(p){
    var c=paperCard(p,'',null);
    var row=el('div','margin-top:5px;display:flex;gap:5px;flex-wrap:wrap');
    if(p.dec==='Short')row.appendChild(badge('Short','background:#fef3c7;color:#92400e'));
    else row.appendChild(badge('Regular','background:#dcfce7;color:#166534'));
    if(p.fmt)row.appendChild(badge(p.fmt,'background:#dbeafe;color:#1e40af'));
    if(p.bpc)row.appendChild(badge('\\u2605 BPC','background:#fef3c7;color:#92400e;border:1px solid #d97706'));
    c.appendChild(row);b.appendChild(c);
  });
  $('pp-mbg').classList.add('open');
}
function closeModal(){$('pp-mbg').classList.remove('open');}
function day(i,btn){
  var ds=document.querySelectorAll('.pp-day'),ts=document.querySelectorAll('.pp-tab'),k;
  for(k=0;k<ds.length;k++)ds[k].classList.remove('active');
  for(k=0;k<ts.length;k++)ts[k].classList.remove('active');
  var d=$('pp-d'+i);if(d)d.classList.add('active');btn.classList.add('active');
}
function search(q){
  var res=$('pp-sr'),list=$('pp-sl');list.textContent='';
  if(!q||q.length<2){res.style.display='none';return;}
  var ql=q.toLowerCase(),found=[];
  D.forEach(function(s,i){(s.papers||[]).forEach(function(p){
    if(String(p.title||'').toLowerCase().indexOf(ql)>=0||String(p.authors||'').toLowerCase().indexOf(ql)>=0||String(p.id).indexOf(ql)>=0)found.push({i:i,s:s,p:p});
  });});
  if(!found.length)list.appendChild(el('div','font-size:13px;color:#888;padding:8px 0','No results'));
  else found.slice(0,20).forEach(function(f){list.appendChild(paperCard(f.p,f.s.title||'',f.i));});
  res.style.display='block';
}
document.addEventListener('click',function(e){
  var t=e.target;if(!t||!t.closest)return;
  var s=t.closest('[data-pp-s]');if(s){show(parseInt(s.getAttribute('data-pp-s'),10));return;}
  var d=t.closest('[data-pp-day]');if(d){day(d.getAttribute('data-pp-day'),d);return;}
  if(t.id==='pp-mbg'||t.closest('.pp-mc'))closeModal();
});
document.addEventListener('keydown',function(e){if(e.key==='Escape')closeModal();});
var sb=$('pp-s');if(sb)sb.addEventListener('input',function(){search(this.value);});
})();`;

// ── HTML generator ────────────────────────────────────────────────────────────
// Schedule JSON (after hydrateSchedule):
//   Plenary/break: { day, start, end, type, label }
//   Parallel block: { day, start, end, type:"session_block",
//                     sessions:[{ id, room, title, bpc, kind, papers:[{id,title,authors,dec,fmt,bpc}] }] }

export function generateHTML(schedule, cfg, unscheduled = []) {
  const pc  = safeColor(cfg.color);
  const esc = escapeHtml;
  const sched = Array.isArray(schedule) ? schedule : [];

  const numDays = Math.max(1, ...sched.map(b => parseInt(b.day, 10) || 1));
  const days    = (Array.isArray(cfg.days) && cfg.days.length ? cfg.days : Array.from({ length: numDays }, (_, i) => `Day ${i + 1}`));

  const byDay = {};
  for (let d = 1; d <= Math.max(numDays, days.length); d++) byDay[d] = [];
  sched.forEach(b => { const d = parseInt(b.day, 10) || 1; (byDay[d] ||= []).push(b); });
  Object.values(byDay).forEach(arr => arr.sort((a, b) => String(a.start || "").localeCompare(String(b.start || ""))));

  // Modal data — an array, referenced by numeric index from data-pp-s attributes
  const sessions = [];
  const indexOf  = new Map();
  sched.forEach(block => {
    if (block.type !== "session_block") return;
    (block.sessions || []).forEach(s => {
      indexOf.set(s, sessions.length);
      sessions.push({
        title: String(s.title ?? ""), time: `${block.start ?? ""}–${block.end ?? ""}`, room: String(s.room ?? ""),
        papers: (s.papers || []).map(p => ({ id: String(p.id ?? ""), title: String(p.title ?? ""), authors: String(p.authors ?? ""), dec: p.dec === "Short" ? "Short" : "Regular", fmt: String(p.fmt ?? ""), bpc: !!p.bpc })),
      });
    });
  });
  let unschedIdx = -1;
  if (unscheduled.length) {
    unschedIdx = sessions.length;
    sessions.push({
      title: "Unscheduled papers", time: "", room: "",
      papers: unscheduled.map(p => ({ id: String(p.id ?? ""), title: String(p.title ?? ""), authors: String(p.authors ?? ""), dec: p.dec === "Short" ? "Short" : "Regular", fmt: String(p.fmt ?? ""), bpc: !!p.bpc })),
    });
  }

  const typeClass = {
    keynote: "pp-keynote", ikeynote: "pp-ikeynote", panel: "pp-panel",
    tutorial: "pp-tutorial", award: "pp-award", social: "pp-social",
  };
  const breakTypes = new Set(["break", "registration", "lunch"]);
  const kindClass  = { special: "pp-ss", tutorial: "pp-tutorial", panel: "pp-panel" };

  const renderBlock = b => {
    if (b.type === "session_block") {
      const ss  = b.sessions || [];
      const gc  = `pp-r${Math.min(ss.length + 1, 6)}`;
      const hdrs = ss.map(s => `<div class="pp-cell pp-hdr">${esc(s.room)}</div>`).join("");
      const cells = ss.map(s => {
        const bpcFlag = s.bpc ? ` <span style="color:#d97706;font-size:9px">&#9733;</span>` : "";
        const np = (s.papers || []).length;
        const kind = String(s.kind || "paper");
        const kindCls = kindClass[kind] || "pp-paper";
        const clickable = (kind === "paper" || kind === "special") && np > 0;
        const meta = kind === "tutorial" ? "Tutorial" : kind === "panel" ? "Panel" : `${np} paper${np !== 1 ? "s" : ""}`;
        return `<div class="pp-cell ${kindCls}"${clickable ? ` data-pp-s="${indexOf.get(s)}" style="cursor:pointer"` : ""}>
        <div class="pp-slot-lbl">${esc(s.id)}${bpcFlag}</div>
        <div class="pp-slot-ttl">${esc(s.title)}</div>
        <div class="pp-slot-meta">${esc(meta)}</div>
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
    <div class="pp-cell pp-break pp-full">${esc(b.label || b.type)}</div>
  </div>`;
    }
    const cls = typeClass[b.type] || "pp-keynote";
    return `<div class="pp-row pp-r2">
    <div class="pp-cell pp-time">${esc(b.start)}–${esc(b.end)}</div>
    <div class="pp-cell ${cls} pp-full">
      <div class="pp-ev-name">${esc(b.label || "")}</div>
    </div>
  </div>`;
  };

  const tabs = days.map((d, i) =>
    `<button class="pp-tab${i === 0 ? " active" : ""}" data-pp-day="${i}">${esc(d)}</button>`).join("\n    ");
  const panels = days.map((d, di) =>
    `<div id="pp-d${di}" class="pp-day${di === 0 ? " active" : ""}">
  ${(byDay[di + 1] || []).map(renderBlock).join("\n  ")}
</div>`).join("\n\n");

  const unschedHtml = unschedIdx >= 0 ? `
  <div class="pp-unsched">
    <h3>Unscheduled papers (${unscheduled.length})</h3>
    <div class="pp-cell pp-paper" data-pp-s="${unschedIdx}">
      <div class="pp-slot-ttl">${unscheduled.map(p => `#${esc(p.id)} ${esc(p.title)}`).join("<br>")}</div>
    </div>
  </div>` : "";

  const sub = [cfg.location, `Regular: ${cfg.regularMins || 25}′`, `Short: ${cfg.shortMins || 15}′`].filter(Boolean).join(" · ");

  return `<meta charset="utf-8">
${PROG_CSS(pc)}
<div class="pp">
  <h2>${esc(cfg.name || "Conference")} — Technical Programme</h2>
  <p style="font-size:13px;color:#666;margin-bottom:20px">${esc(sub)}</p>
  <div class="pp-sw">
    <input class="pp-sb" id="pp-s" type="text" placeholder="Search by title, author, or paper ID…" autocomplete="off">
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
  ${unschedHtml}
</div>
<div id="pp-mbg" class="pp-mbg">
  <div class="pp-m">
    <div class="pp-mh"><h3 id="pp-mt"></h3><button class="pp-mc" type="button" aria-label="Close">&#215;</button></div>
    <div class="pp-mb" id="pp-mb"></div>
  </div>
</div>
<script>
var PP_DATA=${safeJSONForScript({ pc, sessions })};
${PROG_RUNTIME}
</script>`;
}
