import { useState, useEffect } from "react";
import { C, applyTheme, IS } from "./utils/theme.js";
import { DataSourceBadge, LockedModule } from "./components/ui.jsx";

import { DataTab }             from "./modules/DataTab.jsx";
import { SettingsModule }      from "./modules/SettingsModule.jsx";
import { ConfigTab }           from "./modules/ConfigTab.jsx";
import { AboutModule }         from "./modules/AboutModule.jsx";
import { ComplianceModule }    from "./modules/ComplianceModule.jsx";
import { ReviewStatsModule }   from "./modules/ReviewStatsModule.jsx";
import { ScreeningModule }     from "./modules/ScreeningModule.jsx";
import { ReviewQualityModule } from "./modules/ReviewQualityModule.jsx";
import { DecisionsModule }     from "./modules/DecisionsModule.jsx";
import { COIModule }           from "./modules/COIModule.jsx";
import { ProgramBuilderModule }from "./modules/ProgramBuilderModule.jsx";
import { CameraReadyModule }   from "./modules/CameraReadyModule.jsx";
import { EmailModule }         from "./modules/EmailModule.jsx";

const PHASES = [
  { label:"Setup", icon:"⚙", modules:[
    { id:"settings",  label:"Settings",     icon:"🔑", desc:"LLM provider and API keys" },
    { id:"config",    label:"Conference",    icon:"🏛", desc:"Details, deadlines, tracks. Upload CFP PDF for auto-fill." },
    { id:"data",      label:"Data import",   icon:"📂", desc:"Upload all files once. All modules read from here." },
    { id:"about",     label:"About",         icon:"ℹ",  desc:"About Program Chair Copilot and licensing information" },
  ]},
  { label:"Review", icon:"📋", modules:[
    { id:"compliance",label:"Compliance",    icon:"✅", desc:"Instant PDF checks: pages, fonts, blind compliance, references." },
    { id:"stats",     label:"Review stats",  icon:"📊", desc:"Score distributions, reviewer calibration, accept/reject rates." },
    { id:"screening", label:"AI screening",  icon:"🔬", desc:"AI quality assessment per paper: novelty, SoA, writing, LLM detection." },
    { id:"reviews",   label:"Review quality",icon:"📋", desc:"AI assessment of each reviewer's text quality and completeness." },
  ]},
  { label:"Decision", icon:"⚖", modules:[
    { id:"decisions", label:"Decisions",     icon:"⚖", desc:"AI accept/reject per paper based on all its reviews. Exports CSV/Excel." },
    { id:"coi",       label:"Conflicts (COI)",icon:"🔍",desc:"Checks every TPC member vs every paper for conflicts." },
  ]},
  { label:"Output", icon:"📅", modules:[
    { id:"program",   label:"Program",       icon:"📅", desc:"Full schedule from accepted papers: sessions, keynotes, breaks." },
    { id:"camera",    label:"Camera-ready",  icon:"📸", desc:"Checks final PDFs: author info, copyright notice, validation stamp." },
    { id:"emails",    label:"Emails",        icon:"✉",  desc:"Generates all conference emails and a timeline." },
  ]},
];

const ALL_MODULES   = PHASES.flatMap(p => p.modules);
const PREMIUM_IDS   = new Set(["screening","reviews","decisions","program","emails"]);
const TRACK_MODULES = new Set(["compliance","stats","screening","reviews","decisions","coi","program"]);

const BLANK_CONF = {
  name:"",acronym:"",edition:"",year:"",
  dates:"",venue:"",city:"",country:"",website:"",
  submissionSystem:"EasyChair",maxPages:6,doubleBlind:true,
  template:"Two-column conference template",
  scope:"",keywords:[],deadlines:[],tracks:[],organizers:[],
  sponsors:[],indexing:[],notes:"",
  expectedLayout:"two-column",copyrightNotices:[],
  validationStamp:"",institutionSynonyms:{},
  conferenceDays:[{date:"",start:"09:00",end:"18:00"}],
};

function QuitButton() {
  const [confirming,setConfirming] = useState(false);
  const [quitting,  setQuitting]   = useState(false);
  const handle = () => {
    if (!confirming) { setConfirming(true); setTimeout(()=>setConfirming(false),3000); return; }
    setQuitting(true);
    fetch("/api/quit",{method:"POST"}).finally(()=>{
      setTimeout(()=>{
        try{window.close();}catch{}
        setTimeout(()=>{
          document.open();
          document.write(`<html><head><title>PCC</title><style>body{background:#0A0F1E;color:#9CA3AF;font-family:system-ui,sans-serif;display:flex;align-items:center;justify-content:center;height:100vh;margin:0;flex-direction:column;gap:12px}h2{color:#E8A020;margin:0}p{margin:0;font-size:14px}</style></head><body><h2>Program Chair Copilot</h2><p>The application has been shut down.</p><p style="font-size:12px;margin-top:8px;opacity:0.6">You can close this tab.</p></body></html>`);
          document.close();
        },300);
      },400);
    });
  };
  return (
    <button onClick={handle} disabled={quitting} style={{padding:"5px 12px",borderRadius:5,fontSize:11,fontWeight:600,cursor:quitting?"not-allowed":"pointer",border:`1px solid ${confirming?C.red+"60":C.border}`,background:confirming?C.redDim:"transparent",color:confirming?C.redText:C.muted,transition:"all 0.15s"}}>
      {quitting?"Shutting down…":confirming?"Confirm quit":"✕ Quit"}
    </button>
  );
}

function ThemeBtn({id,icon,label,cur,onChange}){
  return(
    <button onClick={()=>onChange(id)} title={label} style={{width:28,height:28,borderRadius:4,fontSize:13,cursor:"pointer",display:"flex",alignItems:"center",justifyContent:"center",border:`1px solid ${cur===id?C.accent+"60":C.border}`,background:cur===id?C.accentDim:"transparent",color:cur===id?C.accentText:C.muted,transition:"all 0.15s"}}>
      {icon}
    </button>
  );
}

export default function App(){
  const [activeModule,setActiveModule] = useState("settings");
  const [theme,setTheme] = useState(()=>{try{return localStorage.getItem("pcc-theme")||"dark";}catch{return"dark";}});

  const [conf,       setConf]       = useState(BLANK_CONF);
  const [pdfFiles,   setPdfFiles]   = useState([]);
  const [metaRows,   setMetaRows]   = useState([]);
  const [reviewRows, setReviewRows] = useState([]);
  const [tpcRows,    setTpcRows]    = useState([]);
  const [ssRows,     setSsRows]     = useState([]);
  const [authorRows, setAuthorRows] = useState([]);
  const [trialStatus,setTrialStatus]= useState(null);
  const [activeTrack,setActiveTrack]= useState("All");

  applyTheme(theme);
  const setAndSaveTheme = t => { setTheme(t); try{localStorage.setItem("pcc-theme",t);}catch{} };

  useEffect(()=>{
    fetch("/api/config/conference",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify(BLANK_CONF)}).catch(()=>{});
    fetch("/api/trial").then(r=>r.json()).then(setTrialStatus).catch(()=>{});
  },[]);

  const isFreemium = trialStatus && !trialStatus.full_access;
  const daysLeft   = trialStatus?.days_remaining ?? null;
  const isLocked   = id => isFreemium && PREMIUM_IDS.has(id);

  const availableTracks = metaRows.length
    ? ["All",...[...new Set(metaRows.map(r=>String(r.Track||r.track||"").trim()).filter(Boolean))].sort()]
    : ["All"];

  const activePhase = PHASES.find(p=>p.modules.some(m=>m.id===activeModule));
  const activeMod   = ALL_MODULES.find(m=>m.id===activeModule);

  const dataSources = [
    {loaded:pdfFiles.length>0,  count:pdfFiles.length,   label:"PDFs"},
    {loaded:metaRows.length>0,  count:metaRows.length,   label:"papers"},
    {loaded:reviewRows.length>0,count:reviewRows.length, label:"reviews"},
    {loaded:tpcRows.length>0,   count:tpcRows.length,    label:"TPC"},
  ];

  const resetSession = () => {
    if(!window.confirm("Clear all loaded data and conference info? This cannot be undone.")) return;
    setPdfFiles([]); setMetaRows([]); setReviewRows([]); setTpcRows([]);
    setAuthorRows([]); setSsRows([]); setConf(BLANK_CONF);
  };

  const renderModule = () => {
    if(isLocked(activeModule)) return <LockedModule name={activeMod?.label||activeModule}/>;
    switch(activeModule){
      case "about":      return <AboutModule trialStatus={trialStatus}/>;
      case "settings":   return <SettingsModule/>;
      case "config":     return <ConfigTab conf={conf} setConf={setConf}/>;
      case "data":       return <DataTab pdfFiles={pdfFiles} setPdfFiles={setPdfFiles} metaRows={metaRows} setMetaRows={setMetaRows} reviewRows={reviewRows} setReviewRows={setReviewRows} tpcRows={tpcRows} setTpcRows={setTpcRows} authorRows={authorRows} setAuthorRows={setAuthorRows} ssRows={ssRows} setSsRows={setSsRows}/>;
      case "compliance": return <ComplianceModule conf={conf} pdfFiles={pdfFiles} metaRows={metaRows} activeTrack={activeTrack}/>;
      case "stats":      return <ReviewStatsModule reviewRows={reviewRows} metaRows={metaRows} activeTrack={activeTrack}/>;
      case "screening":  return <ScreeningModule conf={conf} pdfFiles={pdfFiles} metaRows={metaRows} activeTrack={activeTrack}/>;
      case "reviews":    return <ReviewQualityModule conf={conf} metaRows={metaRows} reviewRows={reviewRows} activeTrack={activeTrack}/>;
      case "decisions":  return <DecisionsModule conf={conf} metaRows={metaRows} reviewRows={reviewRows} activeTrack={activeTrack}/>;
      case "coi":        return <COIModule conf={conf} metaRows={metaRows} tpcRows={tpcRows} authorRows={authorRows} activeTrack={activeTrack}/>;
      case "program":    return <ProgramBuilderModule conf={conf} metaRows={metaRows} ssRows={ssRows} activeTrack={activeTrack}/>;
      case "camera":     return <CameraReadyModule conf={conf} pdfFiles={pdfFiles} authorRows={authorRows}/>;
      case "emails":     return <EmailModule conf={conf}/>;
      default:           return null;
    }
  };

  return(
    <div style={{fontFamily:C.sans,background:C.bg,minHeight:"100vh",color:C.text,display:"flex",flexDirection:"column"}}>

      {/* Header */}
      <div style={{height:52,borderBottom:`1px solid ${C.border}`,padding:"0 24px",display:"flex",alignItems:"center",gap:16,background:C.panel,flexShrink:0}}>
        <div style={{display:"flex",flexDirection:"column",gap:1}}>
          <div style={{fontSize:9,fontWeight:700,color:C.accent,letterSpacing:"0.14em",textTransform:"uppercase"}}>Program Chair Copilot</div>
          <div style={{fontSize:14,fontWeight:700,color:C.text,lineHeight:1}}>{conf.acronym||conf.name||"No conference configured"}</div>
        </div>
        <div style={{width:1,height:28,background:C.border,flexShrink:0}}/>
        <div style={{display:"flex",gap:6,flexWrap:"wrap"}}>
          {dataSources.map((ds,i)=><DataSourceBadge key={i} loaded={ds.loaded} count={ds.count} label={ds.label}/>)}
        </div>
        <div style={{flex:1}}/>
        <div style={{display:"flex",gap:2,padding:"3px",background:C.bg,borderRadius:5,border:`1px solid ${C.border}`}}>
          <ThemeBtn id="light"  icon="☀" label="Light"  cur={theme} onChange={setAndSaveTheme}/>
          <ThemeBtn id="dark"   icon="🌙" label="Dark"   cur={theme} onChange={setAndSaveTheme}/>
          <ThemeBtn id="system" icon="⊙" label="System" cur={theme} onChange={setAndSaveTheme}/>
        </div>
        <QuitButton/>
        <button onClick={resetSession} style={{padding:"5px 12px",borderRadius:5,fontSize:11,fontWeight:600,cursor:"pointer",border:`1px solid ${C.border}`,background:"transparent",color:C.muted,transition:"all 0.15s"}} title="Clear all data">↺ New session</button>
      </div>

      {/* Trial banners */}
      {trialStatus?.mode==="trial" && daysLeft<=7 && daysLeft>0 && (
        <div style={{background:`linear-gradient(90deg,${C.amber}18,${C.amber}08)`,borderBottom:`1px solid ${C.amber}40`,padding:"7px 24px",display:"flex",alignItems:"center",gap:12,fontSize:12}}>
          <span style={{fontSize:14}}>⏳</span>
          <span style={{color:C.amber,fontWeight:600}}>{daysLeft} day{daysLeft!==1?"s":""} remaining in your trial.</span>
          <span style={{color:C.muted}}>Re-download for a new 30-day trial.</span>
          <a href="mailto:florenc1991@gmail.com" style={{marginLeft:"auto",color:C.accentText,fontWeight:600,textDecoration:"none",fontSize:11}}>Get a license →</a>
        </div>
      )}
      {trialStatus?.mode==="freemium" && (
        <div style={{background:`linear-gradient(90deg,${C.red}18,${C.red}08)`,borderBottom:`1px solid ${C.red}40`,padding:"7px 24px",display:"flex",alignItems:"center",gap:12,fontSize:12}}>
          <span style={{fontSize:14}}>🔒</span>
          <span style={{color:C.redText,fontWeight:600}}>Trial expired.</span>
          <span style={{color:C.muted}}>Compliance, statistics, and COI are still free. AI features require a full license.</span>
          <a href="mailto:florenc1991@gmail.com" style={{marginLeft:"auto",color:C.accentText,fontWeight:600,textDecoration:"none",fontSize:11}}>Get a license →</a>
        </div>
      )}

      {/* Body */}
      <div style={{display:"flex",flex:1,overflow:"hidden",minHeight:0}}>

        {/* Sidebar */}
        <div style={{width:210,borderRight:`1px solid ${C.border}`,background:C.panel,flexShrink:0,display:"flex",flexDirection:"column",overflowY:"auto"}}>
          {PHASES.map((phase,pi)=>(
            <div key={pi}>
              <div style={{padding:"14px 18px 4px",fontSize:9,fontWeight:700,color:C.muted,letterSpacing:"0.12em",textTransform:"uppercase",display:"flex",alignItems:"center",gap:6}}>
                <span style={{color:activePhase?.label===phase.label?C.accent:C.muted}}>{phase.icon}</span>
                {phase.label}
              </div>
              {phase.modules.map(m=>{
                const isActive = activeModule===m.id;
                return(
                  <div key={m.id} onClick={()=>setActiveModule(m.id)} style={{padding:"7px 18px 7px 22px",cursor:"pointer",display:"flex",gap:9,alignItems:"center",background:isActive?C.accentDim:"transparent",borderLeft:`2px solid ${isActive?C.accent:"transparent"}`,transition:"all 0.12s"}}>
                    <span style={{fontSize:13,opacity:isActive?1:0.7}}>{m.icon}</span>
                    <span style={{fontSize:12,color:isActive?C.accentText:isLocked(m.id)?C.muted:C.textSoft,fontWeight:isActive?600:400}}>{m.label}</span>
                    {isLocked(m.id)&&<span style={{fontSize:10,marginLeft:"auto",color:C.muted}}>🔒</span>}
                  </div>
                );
              })}
              {pi<PHASES.length-1&&<div style={{height:1,background:C.border,margin:"8px 18px"}}/>}
            </div>
          ))}
          <div style={{flex:1}}/>
          <div style={{padding:"12px 18px",borderTop:`1px solid ${C.border}`,fontSize:10,color:C.muted}}>v1.0</div>
        </div>

        {/* Content */}
        <div style={{flex:1,overflowY:"auto",background:C.bg}}>
          {/* Module header */}
          <div style={{padding:"20px 32px 0",borderBottom:`1px solid ${C.border}`,background:C.panel}}>
            <div style={{display:"flex",alignItems:"flex-start",gap:12,paddingBottom:16}}>
              <div style={{width:40,height:40,borderRadius:8,background:C.accentDim,display:"flex",alignItems:"center",justifyContent:"center",fontSize:18,flexShrink:0}}>{activeMod?.icon||"📄"}</div>
              <div>
                <div style={{fontSize:18,fontWeight:700,color:C.text,lineHeight:1.2}}>{activeMod?.label||activeModule}</div>
                {activeMod?.desc&&<div style={{fontSize:12,color:C.muted,marginTop:4,lineHeight:1.5}}>{activeMod.desc}</div>}
              </div>
              {activePhase&&(
                <div style={{marginLeft:"auto",flexShrink:0,fontSize:10,color:C.muted,fontWeight:700,letterSpacing:"0.08em",textTransform:"uppercase",padding:"4px 10px",borderRadius:4,background:C.panelAlt,border:`1px solid ${C.border}`}}>
                  {activePhase.icon} {activePhase.label}
                </div>
              )}
              {TRACK_MODULES.has(activeModule)&&availableTracks.length>1&&(
                <div style={{display:"flex",alignItems:"center",gap:6,flexShrink:0}}>
                  <span style={{fontSize:10,color:C.muted,fontWeight:700,textTransform:"uppercase",letterSpacing:"0.06em"}}>Track:</span>
                  <select value={activeTrack} onChange={e=>setActiveTrack(e.target.value)}
                    style={{...IS(),padding:"4px 8px",fontSize:11,height:28,cursor:"pointer",minWidth:120,maxWidth:180}}>
                    {availableTracks.map(t=><option key={t} value={t}>{t}</option>)}
                  </select>
                </div>
              )}
            </div>
          </div>
          <div style={{padding:"24px 32px"}}>{renderModule()}</div>
        </div>
      </div>
    </div>
  );
}
