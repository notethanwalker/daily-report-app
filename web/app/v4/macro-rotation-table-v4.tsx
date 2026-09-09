"use client";
import {useMemo,useState} from "react";

const n=(v:any,d=1)=>v==null?"—":Number(v).toFixed(d);
const words=(v:any)=>String(v||"").replaceAll("_"," ");
type Metric="pressure"|"conviction"|"delta1"|"delta3"|"symbol";
const LABELS:Record<Metric,string>={pressure:"Rotation pressure",conviction:"Conviction",delta1:"1-observation change",delta3:"3-observation change",symbol:"Ticker"};

export default function MacroRotationTableV4({rotation,onOpen}:{rotation:any;onOpen:(symbol:string)=>void}){
 const[metric,setMetric]=useState<Metric>("pressure"),[direction,setDirection]=useState<"desc"|"asc">("desc"),[group,setGroup]=useState("all");
 function chooseMetric(next:Metric){if(next===metric){setDirection(x=>x==="asc"?"desc":"asc");return}setMetric(next);setDirection(next==="symbol"?"asc":"desc")}
 function selectMetric(next:Metric){if(next===metric)return;setMetric(next);setDirection(next==="symbol"?"asc":"desc")}
 const rows=useMemo(()=>{
  const source=[...(rotation?.rows||[])];
  const filtered=source.filter((x:any)=>group==="all"||group==="early"&&["early_rotation_candidate","watch_for_rotation"].includes(x.forward_bias)||group==="outflow"&&["rotation_out_risk","avoidance_bias"].includes(x.forward_bias)||group==="leaders"&&Number(x.rotation_score??0)>=0);
  const value=(x:any)=>metric==="pressure"?Number(x.rotation_pressure??-Infinity):metric==="conviction"?Number(x.conviction??-Infinity):metric==="delta1"?Number(x.delta_1_observation??-Infinity):metric==="delta3"?Number(x.delta_3_observations??-Infinity):String(x.symbol||"");
  filtered.sort((a:any,b:any)=>{const av=value(a),bv=value(b);const cmp=typeof av==="string"?av.localeCompare(String(bv)):Number(av)-Number(bv);return direction==="asc"?cmp:-cmp});return filtered.slice(0,16);
 },[rotation,metric,direction,group]);
 return <>
  <div className="metric-sort-bar" role="group" aria-label="Click a metric to sort macro rotation groups">{(Object.keys(LABELS) as Metric[]).map(key=><button key={key} type="button" className={metric===key?"active":""} aria-pressed={metric===key} onClick={()=>chooseMetric(key)}>{LABELS[key]}{metric===key?<span aria-hidden="true"> {direction==="asc"?"↑":"↓"}</span>:null}</button>)}</div>
  <div className="table-controls" role="group" aria-label="Macro rotation table controls"><label>View<select value={group} onChange={e=>setGroup(e.target.value)}><option value="all">All groups</option><option value="leaders">Current leaders</option><option value="early">Early rotation</option><option value="outflow">Outflow risk</option></select></label><label>Rank metric<select value={metric} onChange={e=>selectMetric(e.target.value as Metric)}>{(Object.keys(LABELS) as Metric[]).map(key=><option key={key} value={key}>{LABELS[key]}</option>)}</select></label><button type="button" onClick={()=>setDirection(x=>x==="asc"?"desc":"asc")} aria-label={`Sort ${direction==="asc"?"descending":"ascending"}`}>{direction==="asc"?"↑ Asc":"↓ Desc"}</button><span>{rows.length} shown</span></div>
  <div className="v4-table rotation-table">{rows.map((x:any)=><button className="table-row-button" key={x.symbol} onClick={()=>onOpen(x.symbol)} title={`Open ${x.symbol} research`}><strong>{x.symbol}</strong><span>{x.name}</span><span>{words(x.state)}</span><span>{metric==="delta1"?`${n(x.delta_1_observation,2)} Δ1`:metric==="delta3"?`${n(x.delta_3_observations,2)} Δ3`:x.stale_input?"stale":`${n(x.conviction,0)} conf`}</span><b>{metric==="conviction"?n(x.conviction,0):metric==="delta1"?n(x.delta_1_observation,2):metric==="delta3"?n(x.delta_3_observations,2):metric==="symbol"?n(x.rotation_pressure,2):n(x.rotation_pressure??x.rotation_score,2)}</b></button>)}</div>
 </>;
}
