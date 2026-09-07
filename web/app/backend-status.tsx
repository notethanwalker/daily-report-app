"use client";
import {useCallback,useEffect,useState} from "react";
import VersionHistory from "./version-history";

const API="/backend";
type Probe={name:string;method:string;path:string;probe?:boolean;note?:string};
type ProbeResult={state:"checking"|"ok"|"warn"|"error";status?:number;latency?:number;message?:string};
const ENDPOINTS:Probe[]=[
 {name:"Health + providers",method:"GET",path:"/api/v1/health"},
 {name:"User watchlist",method:"GET",path:"/api/v1/user/watchlist"},
 {name:"User markets",method:"GET",path:"/api/v1/user/markets/latest"},
 {name:"Security search",method:"GET",path:"/api/v1/securities/search?q=SPY"},
 {name:"World news",method:"GET",path:"/api/v1/news/world?limit=1"},
 {name:"Currencies",method:"GET",path:"/api/v1/macro/currencies"},
 {name:"Sector rotation",method:"GET",path:"/api/v1/macro/rotation"},
 {name:"Macro history",method:"GET",path:"/api/v1/macro/history?year=2026"},
 {name:"Recent flow",method:"GET",path:"/api/v1/flow/recent?limit=1"},
 {name:"Current report",method:"GET",path:"/api/v1/report/current"},
 {name:"Data health",method:"GET",path:"/api/v1/system/data-health"},
 {name:"Market snapshot",method:"GET",path:"/api/v1/markets/{symbol}",probe:false,note:"Provider-backed route; not invoked by monitor"},
 {name:"Generate report",method:"POST",path:"/api/v1/report/generate",probe:false,note:"Write route; not invoked by monitor"},
];
async function timedFetch(path:string){const controller=new AbortController(),timer=setTimeout(()=>controller.abort(),12000),started=performance.now();try{const r=await fetch(`${API}${path}`,{cache:"no-store",credentials:"include",signal:controller.signal});return{ok:r.ok,status:r.status,latency:Math.round(performance.now()-started)}}finally{clearTimeout(timer)}}
export default function BackendStatus(){
 const[results,setResults]=useState<Record<string,ProbeResult>>({}),[providers,setProviders]=useState<Record<string,any>>({}),[version,setVersion]=useState("—"),[lastChecked,setLastChecked]=useState("Never"),[checking,setChecking]=useState(false);
 const refresh=useCallback(async()=>{setChecking(true);const initial:Record<string,ProbeResult>={};ENDPOINTS.forEach(e=>initial[e.name]={state:e.probe===false?"warn":"checking",message:e.note});setResults(initial);await Promise.all(ENDPOINTS.filter(e=>e.probe!==false).map(async e=>{try{const r=await timedFetch(e.path);setResults(c=>({...c,[e.name]:r.ok?{state:"ok",status:r.status,latency:r.latency,message:"Responding normally"}:{state:"error",status:r.status,latency:r.latency,message:`HTTP ${r.status}`}}))}catch(err:any){setResults(c=>({...c,[e.name]:{state:"error",message:err?.name==="AbortError"?"Timed out after 12 seconds":err?.message||"Request failed"}}))}}));try{const r=await fetch(`${API}/api/v1/health`,{cache:"no-store",credentials:"include"});if(r.ok){const d=await r.json();setProviders(d.providers||{});setVersion(d.version||"—")}}catch{}setLastChecked(new Date().toLocaleTimeString());setChecking(false)},[]);
 useEffect(()=>{refresh()},[refresh]);const counts=Object.values(results).reduce((a,r)=>{a[r.state]=(a[r.state]||0)+1;return a},{ok:0,warn:0,error:0,checking:0} as Record<string,number>);
 return <><section className="settings-status"><div className="card section-head reveal-card"><div><span className="eyebrow">System monitor</span><h2>Backend API Status</h2><p className="muted">Safe read checks run through the authenticated same-origin session proxy.</p></div><button className="btn" disabled={checking} onClick={refresh}>{checking?"Checking…":"Run checks"}</button></div><div className="status-summary-grid"><article className="card stat-card"><span>API version</span><strong>{version}</strong></article><article className="card stat-card"><span>Healthy</span><strong className="positive">{counts.ok}</strong></article><article className="card stat-card"><span>Issues</span><strong className={counts.error?"negative":"positive"}>{counts.error}</strong></article><article className="card stat-card"><span>Last check</span><strong>{lastChecked}</strong></article></div><div className="card reveal-card"><h2>Providers</h2><div className="provider-status-grid">{Object.entries(providers).map(([name,p]:any)=><div className="provider-status" key={name}><span className={`health-dot ${p?.configured!==false?"ok":"warn"}`}/><div><strong>{name.replaceAll("_"," ")}</strong><p>{p?.configured!==false?"Available/configured":"Not configured"}</p></div></div>)}</div></div><div className="card reveal-card"><h2>API routes</h2><div className="api-status-table-wrap"><table className="api-status-table"><thead><tr><th>Status</th><th>Route</th><th>Method</th><th>Latency</th><th>Detail</th></tr></thead><tbody>{ENDPOINTS.map(e=>{const r=results[e.name]||{state:"checking" as const};return <tr key={e.name}><td><span className={`health-pill ${r.state}`}>{r.state}</span></td><td><strong>{e.name}</strong><code>{e.path}</code></td><td>{e.method}</td><td>{r.latency!=null?`${r.latency} ms`:"—"}</td><td>{r.message||"Checking…"}</td></tr>})}</tbody></table></div></div></section><VersionHistory/></>;
}
