"use client";

import Link from "next/link";
import {useEffect,useState} from "react";
import {useParams} from "next/navigation";
import {AuthGate} from "../../../auth-shell";
import "../../v4.css";

const API="/backend";
const n=(v:any,d=1)=>v==null?"—":Number(v).toFixed(d);
async function getJson(url:string){const r=await fetch(url,{cache:"no-store",credentials:"include"});const d=await r.json().catch(()=>({}));if(!r.ok)throw new Error(d?.detail||`HTTP ${r.status}`);return d}

export default function ThemePage(){return <AuthGate>{()=> <ThemeWorkspace/>}</AuthGate>}
function ThemeWorkspace(){
 const params=useParams<{name:string}>();const name=decodeURIComponent(String(params?.name||""));const[data,setData]=useState<any>(null),[error,setError]=useState(""),[loading,setLoading]=useState(true);
 useEffect(()=>{if(!name)return;setLoading(true);getJson(`${API}/api/v1/stack/research/theme/${encodeURIComponent(name)}`).then(setData).catch(e=>setError(e?.message||String(e))).finally(()=>setLoading(false))},[name]);
 if(loading)return <main className="v4-shell"><div className="v4-loading">Loading {name} workspace…</div></main>;
 return <main className="v4-shell"><header className="v4-header"><div><span className="v4-kicker">RESEARCH · SECTOR / THEME</span><h1>{data?.theme||name}</h1><p>Rotation state → constituents → opportunity context</p></div><Link href="/v4">Back to Decision Stack</Link></header>{error&&<div className="v4-error">{error}</div>}
 <section className="v4-grid"><article className="v4-card hero"><span className="label">Rotation state</span><strong className="small-strong">{String(data?.rotation?.state||"unmapped").replaceAll("_"," ")}</strong><p>{n(data?.rotation?.rotation_pressure,2)} pressure · {n(data?.rotation?.conviction,0)} conviction</p></article><article className="v4-card"><span className="label">Mapped constituents</span><strong>{data?.constituent_count??0}</strong><p>Weighted theme/sector exposure mappings.</p></article>
 <article className="v4-card wide"><h2>Constituent opportunity context</h2><div className="v4-table opportunities funnel-table">{(data?.constituents||[]).map((x:any)=><div key={x.symbol}><strong>{x.symbol}</strong><span>{x.name||"—"}</span><span>{Math.round(Number(x.exposure_weight||0)*100)}% exposure</span><span>7D {n(x.return_7d)}%</span><span>W%R {n(x.williams_r)}</span><span>100MA {n(x.ma100_distance)}%</span><b>{n(x.buy_score)}</b></div>)}</div><p className="muted">{data?.methodology}</p></article></section></main>
}
