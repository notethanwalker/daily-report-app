"use client";
import {useCallback,useEffect,useState} from "react";
import VersionHistory from "./version-history";

const API=process.env.NEXT_PUBLIC_API_BASE_URL||"https://daily-report-api-ero2.onrender.com";

type Probe={name:string;method:string;path:string;probe?:boolean;note?:string};
type ProbeResult={state:"checking"|"ok"|"warn"|"error";status?:number;latency?:number;message?:string};

const ENDPOINTS:Probe[]=[
 {name:"Service root",method:"GET",path:"/"},
 {name:"Health + providers",method:"GET",path:"/api/v1/health"},
 {name:"Watchlist read",method:"GET",path:"/api/v1/watchlist"},
 {name:"Watchlist add",method:"POST",path:"/api/v1/watchlist",probe:false,note:"Write route; not invoked by monitor"},
 {name:"Watchlist remove",method:"DELETE",path:"/api/v1/watchlist/{symbol}",probe:false,note:"Write route; not invoked by monitor"},
 {name:"Security search",method:"GET",path:"/api/v1/securities/search?q=SPY"},
 {name:"Latest markets",method:"GET",path:"/api/v1/markets/latest"},
 {name:"Market snapshot",method:"GET",path:"/api/v1/markets/{symbol}",probe:false,note:"Live/provider-backed route; monitored through provider health to avoid quota use"},
 {name:"Fundamentals",method:"GET",path:"/api/v1/markets/{symbol}/fundamentals",probe:false,note:"Provider-budgeted route; monitored through Alpha Vantage health"},
 {name:"Williams %R",method:"GET",path:"/api/v1/markets/{symbol}/williams-r",probe:false,note:"Provider-backed all-history indicator; loaded only when a ticker row is expanded"},
 {name:"Market history",method:"GET",path:"/api/v1/markets/SPY/history?limit=1"},
 {name:"World news",method:"GET",path:"/api/v1/news/world?limit=1"},
 {name:"Market news",method:"GET",path:"/api/v1/news/market?limit=1"},
 {name:"Currencies",method:"GET",path:"/api/v1/macro/currencies"},
 {name:"Sector rotation",method:"GET",path:"/api/v1/macro/rotation"},
 {name:"Macro history",method:"GET",path:"/api/v1/macro/history?year=2026"},
 {name:"Recent flow",method:"GET",path:"/api/v1/flow/recent?limit=1"},
 {name:"Current report",method:"GET",path:"/api/v1/report/current"},
 {name:"Generate report",method:"POST",path:"/api/v1/report/generate",probe:false,note:"Write route; not invoked by monitor"},
 {name:"Report history",method:"GET",path:"/api/v1/report/history?limit=1"},
 {name:"Report config",method:"GET",path:"/api/v1/report/config"},
];

async function timedFetch(path:string){
 const controller=new AbortController();
 const timer=setTimeout(()=>controller.abort(),12000);
 const started=performance.now();
 try{
  const r=await fetch(`${API}${path}`,{cache:"no-store",signal:controller.signal});
  return {ok:r.ok,status:r.status,latency:Math.round(performance.now()-started),text:r.ok?"":await r.text()};
 }finally{
  clearTimeout(timer);
 }
}

export default function BackendStatus(){
 const[results,setResults]=useState<Record<string,ProbeResult>>({});
 const[providers,setProviders]=useState<Record<string,any>>({});
 const[version,setVersion]=useState<string>("—");
 const[lastChecked,setLastChecked]=useState<string>("Never");
 const[checking,setChecking]=useState(false);

 const refresh=useCallback(async()=>{
  setChecking(true);
  const initial:Record<string,ProbeResult>={};
  ENDPOINTS.forEach(e=>{initial[e.name]={state:e.probe===false?"warn":"checking",message:e.note}});
  setResults(initial);
  const probes=ENDPOINTS.filter(e=>e.probe!==false);
  await Promise.all(probes.map(async e=>{
   try{
    const r=await timedFetch(e.path);
    setResults(current=>({...current,[e.name]:r.ok?{state:"ok",status:r.status,latency:r.latency,message:"Responding normally"}:{state:"error",status:r.status,latency:r.latency,message:`HTTP ${r.status}`}}));
   }catch(err:any){
    setResults(current=>({...current,[e.name]:{state:"error",message:err?.name==="AbortError"?"Timed out after 12 seconds":err?.message||"Request failed"}}));
   }
  }));
  try{const r=await fetch(`${API}/api/v1/health`,{cache:"no-store"});if(r.ok){const d=await r.json();setProviders(d.providers||{});setVersion(d.version||"—")}}catch{}
  setLastChecked(new Date().toLocaleTimeString());setChecking(false);
 },[]);

 useEffect(()=>{refresh()},[refresh]);
 const counts=Object.values(results).reduce((a,r)=>{a[r.state]=(a[r.state]||0)+1;return a},{ok:0,warn:0,error:0,checking:0} as Record<string,number>);

 return <><section className="settings-status">
  <div className="card section-head reveal-card"><div><span className="eyebrow">System monitor</span><h2>Backend API Status</h2><p className="muted">Checks safe read endpoints directly. Provider-budgeted and destructive routes are monitored without consuming quota or changing data.</p></div><button className="btn" disabled={checking} onClick={refresh}>{checking?"Checking…":"Run checks"}</button></div>
  <div className="status-summary-grid"><article className="card stat-card reveal-card"><span>API version</span><strong>{version}</strong></article><article className="card stat-card reveal-card"><span>Healthy</span><strong className="positive">{counts.ok}</strong></article><article className="card stat-card reveal-card"><span>Issues</span><strong className={counts.error?"negative":"positive"}>{counts.error}</strong></article><article className="card stat-card reveal-card"><span>Last check</span><strong className="status-time">{lastChecked}</strong></article></div>
  <div className="card reveal-card"><h2>Providers</h2><div className="provider-status-grid">{Object.entries(providers).map(([name,p]:any)=>{const configured=p?.configured!==false;const remaining=p?.remaining_today;return <div className="provider-status" key={name}><span className={`health-dot ${configured?"ok":"warn"}`}/><div><strong>{name.replaceAll("_"," ")}</strong><p>{configured?"Available/configured":"Not configured"}{remaining!=null?` · ${remaining} requests remaining today`:""}</p></div></div>})}{!Object.keys(providers).length&&<p className="muted">Provider health has not loaded yet.</p>}</div></div>
  <div className="card reveal-card"><h2>API routes</h2><div className="api-status-table-wrap"><table className="api-status-table"><thead><tr><th>Status</th><th>Route</th><th>Method</th><th>Latency</th><th>Detail</th></tr></thead><tbody>{ENDPOINTS.map(e=>{const r=results[e.name]||{state:"checking"};return <tr key={e.name}><td><span className={`health-pill ${r.state}`}>{r.state==="ok"?"OK":r.state==="error"?"Issue":r.state==="warn"?"Passive":"Checking"}</span></td><td><strong>{e.name}</strong><code>{e.path}</code></td><td>{e.method}</td><td>{r.latency!=null?`${r.latency} ms`:"—"}</td><td className={r.state==="error"?"negative":"muted"}>{r.message||"Checking…"}</td></tr>})}</tbody></table></div></div>
 </section><VersionHistory/></>;
}
