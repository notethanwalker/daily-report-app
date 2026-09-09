"use client";
import {useMemo,useState} from "react";

const n=(v:any,d=1)=>v==null?"—":Number(v).toFixed(d);
const words=(v:any)=>String(v||"").replaceAll("_"," ");
type SortKey="score"|"williams"|"ma100"|"liquidity"|"symbol";
const LABELS:Record<SortKey,string>={score:"Opportunity score",williams:"Williams %R",ma100:"100MA distance",liquidity:"20D dollar volume",symbol:"Ticker"};

function opportunityTone(x:any){
 const score=Number(x.funnel_score??x.score??50), wr=Number(x.williams_r_14??x.williams_feature??0), ma=Number(x.price_vs_ma100_percent??x.ma100_distance??0);
 if(score>=80||((wr<=-80)&&(ma>=0&&ma<=5)))return "strength-strong";
 if(score>=68||wr<=-70)return "strength-positive";
 if(score<=38)return "strength-weak";
 if(score<=50)return "strength-negative";
 return "strength-neutral";
}

export default function OpportunityTableV4({rows,onOpen}:{rows:any[];onOpen:(symbol:string)=>void}){
 const[sort,setSort]=useState<SortKey>("score"),[direction,setDirection]=useState<"desc"|"asc">("desc"),[bucket,setBucket]=useState("all");
 const buckets=useMemo(()=>Array.from(new Set((rows||[]).map((x:any)=>String(x.bucket||"")).filter(Boolean))).sort(),[rows]);
 function chooseSort(key:SortKey){
  if(sort===key){setDirection(x=>x==="asc"?"desc":"asc");return}
  setSort(key);
  setDirection(key==="williams"||key==="ma100"||key==="symbol"?"asc":"desc");
 }
 function selectSort(key:SortKey){
  if(sort===key)return;
  setSort(key);
  setDirection(key==="williams"||key==="ma100"||key==="symbol"?"asc":"desc");
 }
 const visible=useMemo(()=>{
  const out=(rows||[]).filter(x=>bucket==="all"||x.bucket===bucket);
  const value=(x:any)=>sort==="score"?Number(x.funnel_score??x.score??-Infinity):sort==="williams"?Number(x.williams_r_14??x.williams_feature??Infinity):sort==="ma100"?Number(x.price_vs_ma100_percent??x.ma100_distance??Infinity):sort==="liquidity"?Number(x.average_dollar_volume_20d??-Infinity):String(x.symbol||"");
  out.sort((a:any,b:any)=>{const av=value(a),bv=value(b);const cmp=typeof av==="string"?av.localeCompare(String(bv)):Number(av)-Number(bv);return direction==="asc"?cmp:-cmp});return out;
 },[rows,sort,direction,bucket]);
 return <>
  <div className="metric-sort-bar" role="group" aria-label="Click a metric to sort opportunity candidates">
   {(Object.keys(LABELS) as SortKey[]).map(key=><button key={key} type="button" className={sort===key?"active":""} aria-pressed={sort===key} onClick={()=>chooseSort(key)}>{LABELS[key]}{sort===key?<span aria-hidden="true"> {direction==="asc"?"↑":"↓"}</span>:null}</button>)}
  </div>
  <div className="table-controls" role="group" aria-label="Opportunity table controls">
   <label>Setup<select value={bucket} onChange={e=>setBucket(e.target.value)}><option value="all">All</option>{buckets.map(x=><option key={x} value={x}>{words(x)}</option>)}</select></label>
   <label>Sort<select value={sort} onChange={e=>selectSort(e.target.value as SortKey)}>{(Object.keys(LABELS) as SortKey[]).map(key=><option key={key} value={key}>{LABELS[key]}</option>)}</select></label>
   <button type="button" onClick={()=>setDirection(x=>x==="asc"?"desc":"asc")} aria-label={`Sort ${direction==="asc"?"descending":"ascending"}`}>{direction==="asc"?"↑ Asc":"↓ Desc"}</button><span>{visible.length} shown</span>
  </div>
  <div className="v4-table opportunities funnel-table">{visible.map((x:any)=><button className={`table-row-button ${opportunityTone(x)}`} key={x.symbol} onClick={()=>onOpen(x.symbol)} title={`Open ${x.symbol} research`}><strong>{x.symbol}</strong><span>{x.rotation_proxy||x.sector||"Unclassified"}</span><span>{words(x.setup_type||x.bucket||x.rotation_state||"tracked")}</span><span>100MA {x.price_vs_ma100_percent==null&&x.ma100_distance==null?"—":`${n(x.price_vs_ma100_percent??x.ma100_distance,1)}%`}</span><span>W%R {n(x.williams_r_14??x.williams_feature,1)}</span><span>{words(x.verification_status||x.enrichment_status||x.rotation_state||"unknown")}</span><b>{n(x.funnel_score??x.score,1)}</b></button>)}</div>
 </>;
}
