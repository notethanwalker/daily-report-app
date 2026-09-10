"use client";
import {useCallback,useEffect,useState} from "react";
import VersionHistory from "./version-history";

const API="/backend";
const DEFAULT_PROBE_TIMEOUT_MS=20000;
const HEAVY_PROBE_TIMEOUT_MS=45000;
const SLOW_RESPONSE_MS=12000;
const PROBE_CONCURRENCY=3;
type Probe={name:string;method:string;path:string;probe?:boolean;note?:string;timeoutMs?:number};
type ProbeResult={state:"checking"|"ok"|"warn"|"error";status?:number;latency?:number;message?:string};
const ENDPOINTS:Probe[]=[
 {name:"Health + providers",method:"GET",path:"/api/v1/health"},
 {name:"User watchlist",method:"GET",path:"/api/v1/user/watchlist"},
 {name:"User markets",method:"GET",path:"/api/v1/user/markets/latest",timeoutMs:HEAVY_PROBE_TIMEOUT_MS},
 {name:"Security search",method:"GET",path:"/api/v1/securities/search?q=SPY"},
 {name:"World news",method:"GET",path:"/api/v1/news/world?limit=1"},
 {name:"Currencies",method:"GET",path:"/api/v1/macro/currencies"},
 {name:"Sector rotation",method:"GET",path:"/api/v1/macro/rotation",timeoutMs:HEAVY_PROBE_TIMEOUT_MS},
 {name:"Macro history",method:"GET",path:"/api/v1/macro/history?year=2026",timeoutMs:HEAVY_PROBE_TIMEOUT_MS},
 {name:"Recent flow",method:"GET",path:"/api/v1/flow/recent?limit=1"},
 {name:"Current report",method:"GET",path:"/api/v1/report/current",timeoutMs:HEAVY_PROBE_TIMEOUT_MS},
 {name:"Data health",method:"GET",path:"/api/v1/system/data-health",timeoutMs:HEAVY_PROBE_TIMEOUT_MS},
 {name:"Market snapshot",method:"GET",path:"/api/v1/markets/{symbol}",probe:false,note:"Provider-backed route; not invoked by monitor"},
 {name:"Generate report",method:"POST",path:"/api/v1/report/generate",probe:false,note:"Write route; not invoked by monitor"},
];
async function timedFetch(path:string,timeout:number){const controller=new AbortController(),timer=setTimeout(()=>controller.abort(),timeout),started=performance.now();try{const r=await fetch(`${API}${path}`,{cache:"no-store",credentials:"include",signal:controller.signal});let body:any=null;try{body=await r.clone().json()}catch{}return{ok:r.ok,status:r.status,latency:Math.round(performance.now()-started),body}}finally{clearTimeout(timer)}}
export default function BackendStatus(){const[results,setResults]=useState<Record<string,ProbeResult>>({}),[providers,setProviders]=useState<Record<string,any>>({}),[version,setVersion]=useState("—"),[lastChecked,setLastChecked]=useState("Never"),[checking,setChecking]=useState(false),[runStarted,setRunStarted]=useState("");
 const runProbe=useCallback(async(e:Probe)=>{const timeout=e.timeoutMs??DEFAULT_PROBE_TIMEOUT_MS;try{const r=await timedFetch(e.path,timeout);const slow=r.ok&&r.latency>=SLOW_RESPONSE_MS;setResults(c=>({...c,[e.name]:r.ok?{state:"ok",status:r.status,latency:r.latency,message:slow?`Responding, but slowly (${(r.latency/1000).toFixed(1)}s)`:"Responding normally"}:{state:"error",status:r.status,latency:r.latency,message:`HTTP ${r.status}`}}));if(e.name==="Health + providers"&&r.ok&&r.body){setProviders(r.body.providers||{});setVersion(r.body.version||"—")}}catch(err:any){setResults(c=>({...c,[e.name]:{state:"error",message:err?.name==="AbortError"?`Timed out after ${timeout/1000} seconds`:err?.message||"Request failed"}}))}},[]);
 const refresh=useCallback(async()=>{if(checking)return;setChecking(true);const started=new Date();setRunStarted(started.toLocaleTimeString());const initial:Record<string,ProbeResult>={};ENDPOINTS.forEach(e=>initial[e.name]={state:e.probe===false?"warn":"checking",message:e.note});setResults(initial);const probeRows=ENDPOINTS.filter(e=>e.probe!==false);for(let i=0;i<probeRows.length;i+=PROBE_CONCURRENCY){await Promise.all(probeRows.slice(i,i+PROBE_CONCURRENCY).map(runProbe))}setLastChecked(new Date().toLocaleTimeString());setChecking(false)},[checking,runProbe]);
 useEffect(()=>{refresh()},[]);const counts=Object.values(results).reduce((a,r)=>{a[r.state]=(a[r.state]||0)+1;return a},{ok:0,warn:0,error:0,checking:0} as Record<string,number>);return <><section className="settings-status"><div className="card section-head reveal-card"><div><span className="eyebrow">System monitor</span><h2>Backend API Status</h2><p className="muted">Safe reads run in batches of {PROBE_CONCURRENCY}. Lightweight routes have a {DEFAULT_PROBE_TIMEOUT_MS/1000}s ceiling; known heavier reads may use up to {HEAVY_PROBE_TIMEOUT_MS/1000}s. Successful slow responses stay healthy and are labeled with their latency instead of being reported as outages.</p></div><button className="btn" disabled={checking} onClick={refresh}>{checking?"Checking…":"Run checks"}</button></div><div className="status-summary-grid"><article className="card stat-card"><span>API version</span><strong>{version}</strong></article><article className="card stat-card"><span>Healthy</span><strong className="positive">{counts.ok}</strong></article><article className="card stat-card"><span>Issues</span><strong className={counts.error?"negative":"positive"}>{counts.error}</strong></article><article className="card stat-card"><span>{checking?"Run started":"Last completed"}</span><strong>{checking?runStarted:lastChecked}</strong></article></div><div className="card reveal-card"><h2>Providers</h2><div className="provider-status-grid">{Object.entries(providers).map(([name,p]:any)=><div className="provider-status" key={name}><span className={`health-dot ${p?.configured!==false?"ok":"warn"}`}/><div><strong>{name.replaceAll("_"," ")}</strong><p>{p?.configured!==false?"Available/configured":"Not configured"}</p></div></div>)}</div></div><div className="card reveal-card"><h2>API routes</h2><div className="api-status-table-wrap"><table className="api-status-table"><thead><tr><th>Status</th><th>Route</th><th>Method</th><th>Latency</th><th>Detail</th></tr></thead><tbody>{ENDPOINTS.map(e=>{const r=results[e.name]||{state:e.probe===false?"warn" as const:"checking" as const,message:e.note};return <tr key={e.name}><td><span className={`health-pill ${r.state}`}>{r.state}</span></td><td><strong>{e.name}</strong><code>{e.path}</code></td><td>{e.method}</td><td>{r.latency!=null?`${r.latency} ms`:"—"}</td><td>{r.message||"Checking…"}</td></tr>})}</tbody></table></div></div></section><VersionHistory/></>}
