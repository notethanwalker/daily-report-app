"use client";

import {useEffect,useMemo,useState} from "react";
import {OpportunityChangePanel,PortfolioIntelligencePanel} from "./future-release-panels";

const API="/backend";
async function api(path:string,timeout=12000){const c=new AbortController(),t=setTimeout(()=>c.abort(),timeout);try{const r=await fetch(`${API}${path}`,{cache:"no-store",credentials:"include",signal:c.signal});const d=await r.json().catch(()=>({}));if(!r.ok)throw new Error(d?.detail||`HTTP ${r.status}`);return d}finally{clearTimeout(t)}}

export function PortfolioIntelligenceAutoPanel(){
 const[id,setId]=useState<number|null>(null),[error,setError]=useState("");
 useEffect(()=>{let live=true;(async()=>{try{const d=await api("/api/v1/portfolios");if(!live)return;const rows=d.portfolios||[];let chosen=Number(localStorage.getItem("dailyReportPortfolioId")||0)||rows.find((x:any)=>x.is_default)?.id||rows[0]?.id||null;if(chosen&&!rows.some((x:any)=>x.id===chosen))chosen=rows[0]?.id||null;setId(chosen)}catch(e:any){if(live)setError(e.message)}})();return()=>{live=false}},[]);
 return <section className="future-panel future-workspace-extension"><div className="card section-head"><div><span className="eyebrow">Future portfolio intelligence</span><h3>Exposure, scenarios & benchmark</h3></div></div>{error?<div className="suite-error"><span>{error}</span></div>:<PortfolioIntelligencePanel portfolioId={id}/>}</section>
}

export function OpportunityChangeDigest(){
 const[rows,setRows]=useState<any[]>([]),[selected,setSelected]=useState(""),[error,setError]=useState("");
 useEffect(()=>{let live=true;(async()=>{try{const d=await api("/api/v1/opportunities/enhanced");if(!live)return;const r=(d.opportunities||[]).slice(0,20);setRows(r);setSelected(r[0]?.symbol||"")}catch(e:any){if(live)setError(e.message)}})();return()=>{live=false}},[]);
 const selectedRow=useMemo(()=>rows.find(x=>x.symbol===selected),[rows,selected]);
 return <section className="future-panel future-workspace-extension"><div className="card section-head"><div><span className="eyebrow">Opportunity history</span><h3>Why did the score change?</h3><p className="muted">Compare the two latest stored feature snapshots, including component deltas and threshold flags.</p></div>{rows.length>0&&<label>Ticker<select className="search" value={selected} onChange={e=>setSelected(e.target.value)}>{rows.map(x=><option key={x.symbol}>{x.symbol}</option>)}</select></label>}</div>{error&&<div className="suite-error"><span>{error}</span></div>}{selectedRow&&<div className="card"><div className="metric-tile-grid"><span><i>Current buy score</i><strong>{selectedRow.buy_score}</strong></span><span><i>Current sell score</i><strong>{selectedRow.sell_score}</strong></span></div><OpportunityChangePanel symbol={selected}/></div>}</section>
}
