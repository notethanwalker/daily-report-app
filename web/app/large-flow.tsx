"use client";
import {useEffect,useMemo,useState} from "react";

const API=process.env.NEXT_PUBLIC_API_BASE_URL||"https://daily-report-api-ero2.onrender.com";
type Event={id?:number;event_type?:string;symbol:string;provider?:string;outlier_score?:number|null;source_url?:string;occurred_at?:string|null;data?:{side?:string;strike?:number|null;expiration?:string|null;premium?:number|null;contracts?:number|null;volume?:number|null;open_interest?:number|null;volume_oi_ratio?:number|null;aggression?:string|null;direction?:string|null}};
const money=(v:number|null|undefined)=>v==null?"—":v>=1_000_000?`$${(v/1_000_000).toFixed(2)}M`:v>=1_000?`$${(v/1_000).toFixed(0)}K`:`$${v.toFixed(0)}`;
const num=(v:number|null|undefined)=>v==null?"—":Math.round(v).toLocaleString();

export default function LargeFlow(){
 const[events,setEvents]=useState<Event[]>([]),[loading,setLoading]=useState(false),[error,setError]=useState(""),[provider,setProvider]=useState("SquawkFlow"),[note,setNote]=useState(""),[usage,setUsage]=useState<any>({}),[symbol,setSymbol]=useState("");
 async function load(){setLoading(true);setError("");try{const q=symbol.trim()?`?limit=60&symbol=${encodeURIComponent(symbol.trim().toUpperCase())}`:"?limit=60";const r=await fetch(`${API}/api/v1/flow/recent${q}`,{cache:"no-store"});const d=await r.json();if(!r.ok)throw new Error(d?.detail||`HTTP ${r.status}`);setEvents(d.events||[]);setProvider(d.provider||"SquawkFlow");setNote(d.live_error||d.note||"");setUsage(d.usage||{})}catch(e:any){setError(e?.message||"Flow request failed")}finally{setLoading(false)}}
 useEffect(()=>{load()},[]);
 const stats=useMemo(()=>{const calls=events.filter(e=>e.data?.side==="call").length,puts=events.filter(e=>e.data?.side==="put").length,total=events.reduce((a,e)=>a+(e.data?.premium||0),0);return {calls,puts,total}},[events]);
 return <section className="tab-panel flow-panel">
  <div className="card reveal-card section-head"><div><span className="eyebrow">Unusual options intelligence</span><h2>Large Flow</h2><p className="muted">Live public unusual-options observations. Significance and directional inference are kept separate.</p></div><button className="btn" disabled={loading} onClick={load}>{loading?"Refreshing…":"Refresh"}</button></div>
  <div className="flow-summary-grid"><article className="card reveal-card stat-card"><span>Events</span><strong>{events.length}</strong></article><article className="card reveal-card stat-card"><span>Calls</span><strong>{stats.calls}</strong></article><article className="card reveal-card stat-card"><span>Puts</span><strong>{stats.puts}</strong></article><article className="card reveal-card stat-card"><span>Observed premium</span><strong>{money(stats.total)}</strong></article></div>
  <div className="card reveal-card flow-toolbar"><div><strong>{provider}</strong><p className="muted">{usage.requests_remaining!=null?`${usage.requests_remaining} anonymous requests remaining this hour`:"Public endpoint; backend caching limits request usage."}</p></div><div className="flow-filter"><input className="search" value={symbol} onChange={e=>setSymbol(e.target.value)} placeholder="Filter ticker" onKeyDown={e=>{if(e.key==="Enter")load()}}/><button className="btn" onClick={load}>Apply</button></div></div>
  {error&&<div className="error-state reveal-card"><div><strong>Large Flow unavailable</strong><p>{error}</p></div><button className="btn" onClick={load}>Retry</button></div>}
  {note&&<div className="card reveal-card flow-note"><strong>Feed note</strong><p className="muted">{note}</p></div>}
  {!loading&&!error&&!events.length&&<div className="card reveal-card"><p className="muted">No unusual-options observations matched the current filter.</p></div>}
  <div className="flow-event-grid">{events.map((e,i)=>{const d=e.data||{};const side=(d.side||"option").toLowerCase();return <article className="card reveal-card flow-event" key={`${e.symbol}-${e.occurred_at||i}-${i}`}>
   <div className="flow-event-head"><div><span className={`flow-side ${side}`}>{side}</span><strong>{e.symbol}</strong></div><span className="flow-score">Score {e.outlier_score==null?"—":e.outlier_score.toFixed(1)}</span></div>
   <div className="flow-metrics"><span>Strike <strong>{d.strike==null?"—":`$${d.strike.toFixed(2)}`}</strong></span><span>Expiry <strong>{d.expiration||"—"}</strong></span><span>Premium <strong>{money(d.premium)}</strong></span><span>Contracts <strong>{num(d.contracts)}</strong></span><span>Vol/OI <strong>{d.volume_oi_ratio==null?"—":`${d.volume_oi_ratio.toFixed(2)}x`}</strong></span><span>Execution <strong>{d.aggression||"—"}</strong></span></div>
   <div className="flow-event-foot"><span>{e.occurred_at?new Date(e.occurred_at).toLocaleString():"Latest observation"}</span>{d.direction&&<span>Provider direction: {d.direction}</span>}{e.source_url&&<a href={e.source_url} target="_blank" rel="noreferrer">Source ↗</a>}</div>
  </article>})}</div>
  <div className="card reveal-card flow-disclaimer"><strong>Interpretation rule</strong><p className="muted">A large call is not automatically bullish and a large put is not automatically bearish. Hedging, spreads, closing trades, and execution location can change the interpretation.</p></div>
 </section>
}
