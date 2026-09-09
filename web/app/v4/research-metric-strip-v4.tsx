"use client";
import {useState} from "react";
const n=(v:any,d=1)=>v==null?"—":Number(v).toFixed(d);
type Key="7d"|"30d"|"ma100"|"williams";
const META:Record<Key,{label:string;explain:string}>={
 "7d":{label:"7D",explain:"Price change across the stored seven-day comparison window."},
 "30d":{label:"30D",explain:"Price change across the stored thirty-day comparison window."},
 ma100:{label:"100MA",explain:"Current price distance from the 100-day moving average; values near zero indicate proximity."},
 williams:{label:"Williams %R",explain:"14-period Williams %R timing signal. More negative values indicate a more oversold position within the recent range."},
};
export default function ResearchMetricStripV4({research}:{research:any}){
 const[selected,setSelected]=useState<Key|null>(null);
 const values:Record<Key,string>={
  "7d":research?.market?.seven_day_percent==null?"—":`${n(research.market.seven_day_percent)}%`,
  "30d":research?.market?.thirty_day_percent==null?"—":`${n(research.market.thirty_day_percent)}%`,
  ma100:research?.market?.price_vs_ma100_percent==null?"—":`${n(research.market.price_vs_ma100_percent)}%`,
  williams:n(research?.latest_features?.williams_r,1),
 };
 return <div className="metric-explainer"><div className="mini-stats metric-buttons" role="group" aria-label="Research statistics; select one for details">{(Object.keys(META) as Key[]).map(key=><button type="button" key={key} className={selected===key?"active":""} aria-pressed={selected===key} onClick={()=>setSelected(x=>x===key?null:key)}>{META[key].label} <b>{values[key]}</b></button>)}</div>{selected&&<div className="metric-detail" role="status"><strong>{META[selected].label}</strong><span>{values[selected]}</span><p>{META[selected].explain}</p><small>{research?.market?.provider||research?.market?.technical_source||"Stored market cache"} · {research?.market?.retrieved_at?new Date(research.market.retrieved_at).toLocaleString():"timestamp unavailable"}</small></div>}</div>;
}
