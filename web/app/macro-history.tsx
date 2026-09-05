"use client";
import {useEffect,useMemo,useState} from "react";
const API=process.env.NEXT_PUBLIC_API_BASE_URL||"https://daily-report-api-ero2.onrender.com";
const pct=(v:number|null|undefined)=>v==null?"—":`${v>=0?"+":""}${v.toFixed(2)}%`;
export default function MacroHistory(){
 const[data,setData]=useState<any>(null),[status,setStatus]=useState("Loading 2026 history...");
 async function load(){setStatus("Loading 2026 history...");try{const r=await fetch(`${API}/api/v1/macro/history?year=2026`,{cache:"no-store"});const d=await r.json();if(!r.ok)throw new Error(d?.detail||`HTTP ${r.status}`);setData(d);setStatus(`${d.data_points||0} historical daily observations`)}catch(e){setStatus(e instanceof Error?e.message:"History unavailable")}}
 useEffect(()=>{load()},[]);
 const monthly=useMemo(()=>{if(!data?.rotation_timeline)return[];const groups:Record<string,any[]>={};for(const x of data.rotation_timeline){const m=x.date.slice(0,7);(groups[m]??=[]).push(x)}return Object.entries(groups).map(([month,rows])=>{const latest=rows[rows.length-1];const counts:Record<string,number>={};for(const r of rows)for(const l of r.leaders||[])counts[l.symbol]=(counts[l.symbol]||0)+1;const leader=Object.entries(counts).sort((a,b)=>b[1]-a[1])[0];return{month,leader:leader?.[0]||"—",days:leader?.[1]||0,spread:latest?.spread}})},[data]);
 const outliers=(data?.stock_outliers||[]).slice(0,16);
 return <>
  <div className="card"><div className="row"><div><h2>2026 Rotation History</h2><p className="muted">{status}</p></div><button className="btn" onClick={load}>Refresh history</button></div><p className="muted">Tracks which groups repeatedly lead/lag and highlights watchlist stocks that diverge from their mapped sector/theme benchmark.</p></div>
  {data&&<>
   <div className="card"><h2>Rotation by Month</h2><div className="comparison-wrap"><table className="comparison-table"><thead><tr><th>Month</th><th>Most frequent leader</th><th>Leader days</th><th>Latest spread</th></tr></thead><tbody>{monthly.map((m:any)=><tr key={m.month}><td>{m.month}</td><td><strong>{m.leader}</strong></td><td>{m.days}</td><td>{m.spread?.toFixed(2)??"—"}</td></tr>)}</tbody></table></div></div>
   <div className="card"><h2>Stock / Sector Divergences</h2><p className="muted">Large 5-day deviations from the mapped sector/theme. These are candidates for stock-specific catalysts, delayed participation, or unusual relative strength/weakness.</p><div className="outlier-list">{outliers.map((o:any)=><div className="outlier-row" key={`${o.date}-${o.symbol}`}><div><strong>{o.symbol} vs {o.benchmark}</strong><p>{o.date} · stock {pct(o.stock_5d_percent)} · benchmark {pct(o.benchmark_5d_percent)} · {o.direction}</p></div><span className={o.relative_gap_points>=0?"positive":"negative"}>{o.relative_gap_points>=0?"+":""}{o.relative_gap_points.toFixed(2)} pts</span></div>)}</div></div>
   <div className="card"><h2>Methodology</h2><p className="muted">{data.methodology}</p></div>
  </>}
 </>;
}
