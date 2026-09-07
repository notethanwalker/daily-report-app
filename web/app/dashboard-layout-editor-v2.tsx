"use client";

import {useEffect,useMemo,useState} from "react";

const API="/backend";
const CARDS=[
 {key:"market_dashboard",label:"Market Dashboard"},
 {key:"sentiment",label:"Market Sentiment"},
 {key:"themes",label:"Top Themes"},
 {key:"report_controls",label:"Report controls"},
 {key:"trust_summary",label:"Verification summary"},
 {key:"currencies",label:"World Currencies"},
 {key:"outliers",label:"Notable Outliers"},
 {key:"top_news",label:"Top Market News"},
];
const DEFAULT_ORDER=CARDS.map(x=>x.key);
async function api(path:string,options:RequestInit={}){const r=await fetch(`${API}${path}`,{cache:"no-store",credentials:"include",...options,headers:{...(options.headers||{})}});const d=await r.json().catch(()=>({}));if(!r.ok)throw new Error(d?.detail||`HTTP ${r.status}`);return d}

export default function DashboardLayoutEditorV2(){
 const[data,setData]=useState<any>(null),[name,setName]=useState("Default"),[cards,setCards]=useState<string[]>(DEFAULT_ORDER),[hidden,setHidden]=useState<string[]>([]),[columns,setColumns]=useState(2),[density,setDensity]=useState("comfortable"),[saving,setSaving]=useState(false),[notice,setNotice]=useState("");
 const labels=useMemo(()=>Object.fromEntries(CARDS.map(x=>[x.key,x.label])),[]);
 function normalize(order:string[]){const valid=order.filter(x=>DEFAULT_ORDER.includes(x));for(const x of DEFAULT_ORDER)if(!valid.includes(x))valid.push(x);return valid}
 function loadProfile(p:any){setName(p?.name||"Default");setCards(normalize(p?.cards||DEFAULT_ORDER));setHidden((p?.hidden||[]).filter((x:string)=>DEFAULT_ORDER.includes(x)));setColumns(p?.columns||2);setDensity(p?.density||"comfortable")}
 async function load(){try{const d=await api("/api/v1/future/dashboard-layouts");setData(d);const active=(d.layouts||[]).find((x:any)=>x.name===d.active)||d.layouts?.[0];loadProfile(active||{name:"Default",cards:DEFAULT_ORDER,hidden:[],columns:2,density:"comfortable"});setNotice("")}catch(e:any){setNotice(e.message)}}
 useEffect(()=>{load()},[]);
 function move(key:string,dir:number){setCards(prev=>{const next=[...prev],i=next.indexOf(key),j=i+dir;if(i<0||j<0||j>=next.length)return next;[next[i],next[j]]=[next[j],next[i]];return next})}
 async function saveAs(targetName=name){setSaving(true);setNotice("");try{await api("/api/v1/future/dashboard-layouts",{method:"PUT",headers:{"Content-Type":"application/json"},body:JSON.stringify({name:targetName,cards,hidden,density,columns,make_active:true})});setName(targetName);await load();window.dispatchEvent(new Event("daily-report-dashboard-layout-changed"));setNotice(`Saved ${targetName}.`)}catch(e:any){setNotice(e.message)}finally{setSaving(false)}}
 async function activate(n:string){try{await api("/api/v1/future/dashboard-layouts/active",{method:"PUT",headers:{"Content-Type":"application/json"},body:JSON.stringify({name:n})});await load();window.dispatchEvent(new Event("daily-report-dashboard-layout-changed"))}catch(e:any){setNotice(e.message)}}
 async function duplicate(){const proposed=window.prompt("Name for duplicated layout",`${name} Copy`)?.trim();if(!proposed)return;await saveAs(proposed)}
 async function reset(){setCards(DEFAULT_ORDER);setHidden([]);setColumns(2);setDensity("comfortable");setSaving(true);setNotice("");try{await api("/api/v1/future/dashboard-layouts",{method:"PUT",headers:{"Content-Type":"application/json"},body:JSON.stringify({name,cards:DEFAULT_ORDER,hidden:[],density:"comfortable",columns:2,make_active:true})});await load();window.dispatchEvent(new Event("daily-report-dashboard-layout-changed"));setNotice("Active layout reset to default.")}catch(e:any){setNotice(e.message)}finally{setSaving(false)}}
 return <div className="card reveal-card future-layout-editor"><div className="section-head"><div><span className="eyebrow">Full Report customization</span><h2>Dashboard layouts</h2><p className="muted">Reorder or hide Report modules, change density and columns, save multiple private profiles, duplicate a profile, or reset it. Verification warnings and errors remain forced-visible.</p></div></div>{(data?.layouts||[]).length>0&&<div className="chip-row">{data.layouts.map((x:any)=><button className={`chip ${data.active===x.name?"active":""}`} key={x.name} onClick={()=>activate(x.name)}>{x.name}{data.active===x.name?" · active":""}</button>)}</div>}<div className="future-layout-form"><label>Layout name<input className="search" value={name} onChange={e=>setName(e.target.value)}/></label><label>Columns<select className="search" value={columns} onChange={e=>setColumns(Number(e.target.value))}><option value={1}>1</option><option value={2}>2</option><option value={3}>3</option><option value={4}>4</option></select></label><label>Density<select className="search" value={density} onChange={e=>setDensity(e.target.value)}><option value="comfortable">Comfortable</option><option value="compact">Compact</option></select></label></div><div className="future-layout-card-list">{cards.map((key,i)=><div key={key}><label><input type="checkbox" checked={!hidden.includes(key)} onChange={e=>setHidden(prev=>e.target.checked?prev.filter(x=>x!==key):[...new Set([...prev,key])])}/><strong>{labels[key]||key}</strong></label><div><button className="text-btn" type="button" disabled={i===0} onClick={()=>move(key,-1)} aria-label={`Move ${labels[key]} up`}>↑</button><button className="text-btn" type="button" disabled={i===cards.length-1} onClick={()=>move(key,1)} aria-label={`Move ${labels[key]} down`}>↓</button></div></div>)}</div><div className="metric-links"><button className="btn" disabled={saving||!name.trim()} onClick={()=>saveAs()}>{saving?"Saving…":"Save & apply"}</button><button className="text-btn" disabled={saving} onClick={duplicate}>Duplicate</button><button className="text-btn danger" disabled={saving} onClick={reset}>Reset active</button></div>{notice&&<p role="status" className={notice.includes("HTTP")||notice.includes("failed")?"negative":""}>{notice}</p>}</div>
}
