"use client";

import {useEffect,useState} from "react";

const API="/backend";
const READY=new Set(["ma100_distance","ma200_distance","relative_volume"]);
async function api(path:string,options:RequestInit={}){const r=await fetch(`${API}${path}`,{cache:"no-store",credentials:"include",...options,headers:{...(options.headers||{})}});const d=await r.json().catch(()=>({}));if(!r.ok)throw new Error(d?.detail||`HTTP ${r.status}`);return d}

export default function FutureAlertTemplates(){
 const[data,setData]=useState<any>(null),[symbol,setSymbol]=useState(""),[creating,setCreating]=useState<string|null>(null),[notice,setNotice]=useState("");
 useEffect(()=>{api("/api/v1/future/alert-templates").then(setData).catch(e=>setNotice(e.message))},[]);
 async function createTemplate(t:any){
  if(!READY.has(t.kind)){setNotice(`${t.name} is designed, but its evaluator is not enabled yet. No placeholder rule was created.`);return}
  if(!symbol.trim()){setNotice("Enter a ticker before creating this template.");return}
  setCreating(t.id);setNotice("");
  try{const s=symbol.trim().toUpperCase();await api("/api/v1/alerts/v2",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({symbols:[s],kind:t.kind,operator:t.operator,threshold:t.threshold,label:t.name,channels:{in_app:true,push:false},cooldown_minutes:360})});setNotice(`${t.name} alert created for ${s}.`);window.dispatchEvent(new Event("daily-report-alerts-changed"))}catch(e:any){setNotice(`Could not create template: ${e.message}`)}finally{setCreating(null)}
 }
 return <div className="card reveal-card future-alert-templates"><div className="section-head"><div><span className="eyebrow">Reusable rules</span><h2>Alert templates</h2><p className="muted">Templates are capability-aware: only rule types the current evaluator actually supports can be created.</p></div><label>Ticker<input className="search" value={symbol} onChange={e=>setSymbol(e.target.value.toUpperCase())} placeholder="AAOI"/></label></div><div className="future-template-grid">{(data?.templates||[]).map((t:any)=>{const ready=READY.has(t.kind);return <article key={t.id}><div className="section-head"><strong>{t.name}</strong><span className={`data-badge ${ready?"live":"cached"}`}>{ready?"READY":"PLANNED"}</span></div><span>{t.kind} {t.operator} {t.threshold??"state change"} {t.unit}</span><p>{t.description}</p><button className="btn" disabled={creating===t.id||!ready} onClick={()=>createTemplate(t)}>{creating===t.id?"Creating…":ready?"Create from template":"Evaluator extension required"}</button></article>})}</div>{notice&&<p role="status" className={notice.startsWith("Could not")?"negative":""}>{notice}</p>}<p className="muted">{data?.methodology}</p></div>
}
